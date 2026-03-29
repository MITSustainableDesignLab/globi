"""Models used for the surrogate training pipeline."""

import fnmatch
import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import numpy as np
import pandas as pd
from pydantic import Field
from scythe.base import ExperimentInputSpec, ExperimentOutputSpec
from scythe.scatter_gather import ScatterGatherResult
from scythe.utils.filesys import S3Url

from globi.models.surrogate.backends import TrainedModelWithArtifacts
from globi.models.surrogate.backends.base import TrainingContext
from globi.models.surrogate.inference import ReferencedMLBackend
from globi.models.surrogate.metrics import normalized_mean_bias_error
from globi.models.surrogate.pipeline import (
    ProgressiveTrainingSpec,
    StageSpec,
    TargetsConfigColumnSpec,
)
from globi.models.surrogate.transforms import (
    DataPair,
    IdentityScaler,
    MinMaxScaler,
    PrepDataResult,
    StandardScaler,
    TrainTestPair,
    Transformers,
    XTransformer,
    YTransformer,
    encode_inputs,
)

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client as S3ClientType
else:
    S3ClientType = object

logger = logging.getLogger(__name__)


EXCLUDED_COLUMNS = frozenset({
    "experiment_id",
    "sort_index",
    "workflow_run_id",
    "root_workflow_run_id",
})


@dataclass(frozen=True)
class TrainFoldRunResult:
    """Trained artifacts and evaluation metrics for one fold."""

    artifacts: TrainedModelWithArtifacts
    global_metrics: pd.DataFrame
    stratum_metrics: pd.DataFrame


class TrainFoldSpec(ExperimentInputSpec):
    """Train an sbem model for a specific fold.

    The fold is determined by the sort_index, which does mean we need to know the n_folds.

    We will need to know:
    - where the data is
    - the desired stratification (e.g. feature.weather.file)
    - how to divide the data into training and testing splits given the desired stratification

    The data uri should be assumed to have features in the index and targets in the columns.

    TODO: consider the potential for leakage when a stratum has few buildings!

    First, we will subdivide the data into its strata.

    Then for each stratum, we will create a train/test split according to the fold index.

    We wish to return validation metrics with the following hierarchy for the column index
    - train/test ["split_segment"]
    - loc1/loc2 ... ["stratum"]
    - mae/rmse/r2/... ["metric"]

    Theoretically, we also might want to pass in normalization specifications for features and/or targets.
    However, with xgb, this is less imperative.
    """

    data_uris: dict[str, S3Url] = Field(
        ..., description="The uris of the data to train on."
    )
    parent: ProgressiveTrainingSpec = Field(..., description="The parent spec.")

    @cached_property
    def combined_data(self) -> pd.DataFrame:
        """Combines the data from the data uris into a single dataframe with a flattened column index."""
        all_dfs: dict[str, pd.DataFrame] = {
            key: pd.read_parquet(str(uri)) for key, uri in self.data_uris.items()
        }

        # We wiull only include dataframes which have valid targets in the training.
        logger.info("Checking for valid targets in dataframes...")
        dfs_to_use: dict[str, pd.DataFrame] = {}
        for key, df in all_dfs.items():
            logger.info(f"Checking dataframe {key}...")
            # TODO: use level names while constructing the sequential name?
            _level_names = df.columns.names
            df.columns = df.columns.to_flat_index()

            new_columns = [
                "/".join([
                    str(c) if not isinstance(c, int) else f"{c:03d}" for c in col
                ])  # pad integers with leading zeros to make them sortable
                if isinstance(col, tuple | list)
                else col
                for col in df.columns
            ]
            # we will only temporarily include the key prefix in the columns so we can perform the filtering check;
            # it will get re-added later when concat the dataframes.
            new_columns_with_prefix = [f"{key}/{col}" for col in new_columns]
            df.columns = new_columns_with_prefix
            viable_targets = self.valid_targets_in_df(df)
            df.columns = new_columns
            if viable_targets:
                logger.info(
                    f"Including dataframe {key} with {len(viable_targets)} targets: {viable_targets}"
                )
                dfs_to_use[key] = df
            else:
                logger.info(
                    f"Excluding dataframe {key} because it has no valid targets."
                )

        # TODO: consider how/if we want to handle dataframes with different indices.
        if not all(
            df.index.equals(next(iter(dfs_to_use.values())).index)
            for df in dfs_to_use.values()
        ):
            msg = "The indices of the dataframes are not all equal. "
            "This is not supported, since the features must be identical for all outputs.."
            raise ValueError(msg)

        logger.info("Concatenating and shuffling dataframes...")
        combined_df = pd.concat(dfs_to_use, axis=1)
        combined_df.columns = combined_df.columns.to_flat_index()
        combined_df.columns = ["/".join(col) for col in combined_df.columns]
        shuffled_df = combined_df.sample(frac=1, random_state=42, replace=False)
        logger.info(f"Shuffled dataframe has {len(shuffled_df)} rows.")
        return shuffled_df

    @property
    def data(self) -> pd.DataFrame:
        """The combined data."""
        return self.combined_data

    @cached_property
    def dparams(self) -> pd.DataFrame:
        """The index of the data."""
        return self.data.index.to_frame()

    @cached_property
    def all_feature_columns(self) -> frozenset[str]:
        """The names of all columns."""
        init_cols = frozenset(self.dparams.columns)
        is_exclusively_one_val = [
            col for col in init_cols if self.dparams[col].nunique() <= 1
        ]
        all_cols = init_cols - frozenset(is_exclusively_one_val)
        return all_cols

    @cached_property
    def all_target_columns(self) -> frozenset[str]:
        """The names of all columns."""
        return frozenset(self.data.columns)

    @cached_property
    def continuous_columns(self) -> frozenset[str]:
        """The continuous columns."""
        # TODO: add some logging calls here.
        feature_conf = self.parent.regression_io_config.features
        candidates = (
            self.all_feature_columns - feature_conf.exclude_columns - EXCLUDED_COLUMNS
        )
        object_dype_columns = (
            self.dparams[candidates].select_dtypes(include=["object"]).columns.tolist()
        )
        candidates = candidates - frozenset(object_dype_columns)
        nunique_counts = cast(pd.Series, self.dparams[candidates].nunique())
        thresh = feature_conf.cont_cat_unicity_transition_threshold
        passing_candidates = cast(
            list[str],
            cast(pd.Series, nunique_counts[nunique_counts > thresh]).index.tolist(),
        )
        non_passing_candidates = cast(
            list[str],
            cast(pd.Series, nunique_counts[nunique_counts <= thresh]).index.tolist(),
        )
        prespecified = feature_conf.continuous_columns
        if prespecified:
            skipped_candidates = frozenset(passing_candidates) - (prespecified)
            possibly_not_continuous_candidats = (
                frozenset(non_passing_candidates) & prespecified
            )
            if possibly_not_continuous_candidats:
                warnings.warn(
                    f"The following columns were specified as continuous but have less than {thresh} unique values: {possibly_not_continuous_candidats}",
                    stacklevel=2,
                )
            if skipped_candidates:
                warnings.warn(
                    f"The following columns are likely continuous but are not included in the continuous columns: {skipped_candidates}",
                    stacklevel=2,
                )
            return prespecified
        return frozenset(passing_candidates)

    @cached_property
    def categorical_columns(self) -> frozenset[str]:
        """The categorical columns."""
        # TODO: add some logging calls here.
        feature_conf = self.parent.regression_io_config.features
        candidates = (
            self.all_feature_columns - feature_conf.exclude_columns - EXCLUDED_COLUMNS
        )
        object_dtype_columns = (
            self.dparams[candidates].select_dtypes(include=["object"]).columns.tolist()
        )
        non_obj_dtype_columns = candidates - frozenset(object_dtype_columns)
        nunique_counts = cast(pd.Series, self.dparams[non_obj_dtype_columns].nunique())
        thresh = feature_conf.cont_cat_unicity_transition_threshold
        passing_non_obj_dtype_candidates = cast(
            list[str],
            cast(pd.Series, nunique_counts[nunique_counts <= thresh]).index.tolist(),
        )
        non_passing_non_obj_dtype_candidates = cast(
            list[str],
            cast(pd.Series, nunique_counts[nunique_counts > thresh]).index.tolist(),
        )
        prespecified = feature_conf.categorical_columns
        if prespecified:
            skipped_candidates = frozenset(passing_non_obj_dtype_candidates) - (
                prespecified
            )
            possibly_not_categorical_candidats = (
                frozenset(non_passing_non_obj_dtype_candidates) & prespecified
            )
            if possibly_not_categorical_candidats:
                warnings.warn(
                    f"The following columns were specified as categorical but have more than {thresh} unique values: {possibly_not_categorical_candidats}",
                    stacklevel=2,
                )
            if skipped_candidates:
                warnings.warn(
                    f"The following columns are likely categorical but are not included in the categorical columns: {skipped_candidates}",
                    stacklevel=2,
                )
            return prespecified
        return frozenset(passing_non_obj_dtype_candidates) | frozenset(
            object_dtype_columns
        )

    @cached_property
    def x_features(self) -> frozenset[str]:
        """The all features."""
        return self.continuous_columns | self.categorical_columns

    @cached_property
    def stratum_names(self) -> list[str]:
        """The values of the stratification field."""
        return sorted(self.dparams[self.parent.stratification.field].unique().tolist())

    @cached_property
    def data_by_stratum(self) -> dict[str, pd.DataFrame]:
        """Subdivide the data by the stratification field.

        We want 1/n_folds data in the test segment for each stratification option,
        so we will need to compute train/test splits separately for each stratum.

        This would not be necessary if we knew that the strata always had equal representation, but
        since we might use things like adaptive sampling or generating samples proportionally to the number of buildings in that stratum,
        e.g. by population, then what *could* happen if we just did a random train/test split is that some strata might end up
        entirely in the train set.
        """
        return {
            val: cast(
                pd.DataFrame,
                self.data[self.dparams[self.parent.stratification.field] == val],
            )
            for val in self.stratum_names
        }

    @cached_property
    def train_test_split_by_fold_and_stratum(self) -> pd.DataFrame:
        """Create the folds for the data.

        To do this, we will go to each stratum and use a strided step to
        construct each fold, then assign the fold matching the sort_index
        to the test split.  We also recombine the strata since they are now
        safely stratified.
        """
        all_strata = []
        for val in self.stratum_names:
            folds = []
            for i in range(self.parent.cross_val.n_folds):
                fold = self.data_by_stratum[val].iloc[
                    i :: self.parent.cross_val.n_folds
                ]
                folds.append(fold)
            folds_df = pd.concat(
                folds,
                axis=0,
                keys=[
                    "test" if i == self.sort_index else "train"
                    for i in range(self.parent.cross_val.n_folds)
                ],
                names=["split_segment"],
            )
            all_strata.append(folds_df)
        return pd.concat(all_strata)

    @cached_property
    def train_segment(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Get the training segment."""
        train_df = cast(
            pd.DataFrame,
            self.train_test_split_by_fold_and_stratum.xs(
                "train", level="split_segment"
            ),
        )
        params = train_df.index.to_frame(index=False)
        targets = train_df
        return params, targets

    @cached_property
    def test_segment(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Get the test segment."""
        test_df = cast(
            pd.DataFrame,
            self.train_test_split_by_fold_and_stratum.xs("test", level="split_segment"),
        )
        params = test_df.index.to_frame(index=False)
        targets = test_df
        return params, targets

    def valid_targets_in_df(self, df: pd.DataFrame) -> list[str]:
        """Get the valid targets in the dataframe."""
        if isinstance(
            self.parent.regression_io_config.targets, TargetsConfigColumnSpec
        ):
            if self.parent.regression_io_config.targets.columns:
                return [
                    c
                    for c in df.columns
                    if c in self.parent.regression_io_config.targets.columns
                ]
            return sorted(df.columns.tolist())
        globs = self.parent.regression_io_config.targets.globs
        if not globs:
            return sorted(df.columns.tolist())
        viable_target_columns = []
        for col in df.columns:
            if any(fnmatch.fnmatch(col, glob) for glob in globs):
                viable_target_columns.append(col)
        return sorted(viable_target_columns)

    @cached_property
    def targets(self) -> list[str]:
        """The list of regression targets."""
        logger.info("Determining targets...")
        if isinstance(
            self.parent.regression_io_config.targets, TargetsConfigColumnSpec
        ):
            final_targets = self.parent.regression_io_config.targets.columns or sorted(
                self.all_target_columns
            )
        else:
            globs = self.parent.regression_io_config.targets.globs
            if not globs:
                final_targets = sorted(self.all_target_columns)
            viable_target_columns = []
            for col in self.all_target_columns:
                if any(fnmatch.fnmatch(col, glob) for glob in globs):
                    viable_target_columns.append(col)
            final_targets = sorted(viable_target_columns)
        logger.info(
            f"Selected {len(final_targets)} / {len(self.all_target_columns)} targets."
        )
        return final_targets

    @cached_property
    def target_range(self) -> list[tuple[float, float]]:
        """The range of the regression targets."""
        _, targets = self.train_segment
        targets = targets[self.targets]
        return [
            (float(targets[col].min() * 0.8), float(targets[col].max() * 1.2))
            for col in self.targets
        ]

    def train(self, tempdir: Path):
        """Train the model with hyperparameter-driven backend dispatch."""
        x_cat_encoding = self.parent.regression_io_config.features.cat_encoding
        x_cont_encoding = self.parent.regression_io_config.features.cont_encoding
        y_encoding = self.parent.regression_io_config.targets.normalization
        data = self.prep_data(
            x_cat_encoding=x_cat_encoding,
            x_cont_encoding=x_cont_encoding,
            y_encoding=y_encoding,
        )

        context = TrainingContext(
            prepped_data=data,
            tempdir=tempdir,
        )
        artifacts = self.parent.ml_backend.train_and_save(context)
        predict_fn = self.parent.ml_backend.build_predict_fn(
            model_object=artifacts.trained_model.model_object,
            transformers=artifacts.trained_model.transformers,
        )
        global_metrics, stratum_metrics = self.evaluate(
            fn=predict_fn,
            selected=data.selected,
        )
        return TrainFoldRunResult(
            artifacts=artifacts,
            global_metrics=global_metrics,
            stratum_metrics=stratum_metrics,
        )

    def prep_data(
        self,
        *,
        x_cat_encoding: Literal["index", "one-hot"],
        x_cont_encoding: Literal["min-max", "standard"] | None,
        y_encoding: Literal["min-max", "standard"] | None,
    ) -> PrepDataResult:
        """Prepare the data for training."""
        logger.info("Preparing data for training...")
        x_train, y_train = self.train_segment
        x_test, y_test = self.test_segment

        # Technically we are allowing some of our test-set features' categorical options
        # through, but that's okay; we are assuming we exhaustively know the categorical options
        # and this is not leakage.
        cats = {
            col: self.dparams[col].unique().tolist() for col in self.categorical_columns
        }

        x_transformer = XTransformer(
            features=sorted(self.x_features),
            cat_map=cats,
            cat_encoding=x_cat_encoding,
            continuous_features=sorted(self.continuous_columns),
            cont_encoding=x_cont_encoding,
            cont_scaler=(
                MinMaxScaler()
                if x_cont_encoding == "min-max"
                else (
                    StandardScaler()
                    if x_cont_encoding == "standard"
                    else IdentityScaler()
                )
            ),
        )
        x_train_encoded = encode_inputs(
            x_train,
            conf=x_transformer,
            fit_continuous=True,
        )

        x_test_encoded = encode_inputs(
            x_test,
            conf=x_transformer,
        )
        scaler = (
            MinMaxScaler()
            if y_encoding == "min-max"
            else StandardScaler()
            if y_encoding == "standard"
            else IdentityScaler()
        )
        y_transformer = YTransformer(
            scaler=scaler,
            targets=self.targets,
            normalization=y_encoding,
        )

        # select the targets
        logger.info("Selecting targets...")
        y_train, y_test = (
            cast(pd.DataFrame, y_train.loc[:, y_transformer.targets]),
            cast(pd.DataFrame, y_test.loc[:, y_transformer.targets]),
        )
        logger.info("Selected targets.")

        logger.info(f"Scaling targets with {type(y_transformer.scaler).__name__}...")
        y_train_scaled = y_transformer.scaler.fit_transform(y_train)
        y_test_scaled = y_transformer.scaler.transform(y_test)
        logger.info("Scaled targets.")

        transformers = Transformers(
            x=x_transformer,
            y=y_transformer,
        )
        selected = TrainTestPair(
            train=DataPair(x=x_train, y=y_train),
            test=DataPair(x=x_test, y=y_test),
        )
        transformed = TrainTestPair(
            train=DataPair(x=x_train_encoded, y=y_train_scaled),
            test=DataPair(x=x_test_encoded, y=y_test_scaled),
        )
        return PrepDataResult(
            selected=selected,
            transformed=transformed,
            transformers=transformers,
        )

    def evaluate(
        self,
        fn: Callable[[pd.DataFrame], pd.DataFrame],
        selected: TrainTestPair,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Evaluate a model on the train and test segments."""
        logger.info("Evaluating model on train and test segments...")
        x_train = selected.train.x
        x_test = selected.test.x
        y_train = selected.train.y
        y_test = selected.test.y
        y_train_preds = fn(x_train)
        y_test_preds = fn(x_test)

        # compute the metrics
        global_train_metrics, stratum_train_metrics = self.compute_metrics(
            y_train_preds, y_train
        )
        global_test_metrics, stratum_test_metrics = self.compute_metrics(
            y_test_preds, y_test
        )

        global_metrics = pd.concat(
            [global_train_metrics, global_test_metrics],
            axis=1,
            keys=["train", "test"],
            names=["split_segment"],
        )
        stratum_metrics = pd.concat(
            [stratum_train_metrics, stratum_test_metrics],
            axis=1,
            keys=["train", "test"],
            names=["split_segment"],
        )
        logger.info("Model evaluated on train and test segments.")
        return global_metrics, stratum_metrics

    def compute_frame_metrics(
        self, preds: pd.DataFrame, targets: pd.DataFrame
    ) -> pd.DataFrame:
        """Compute the metrics."""
        from sklearn.metrics import (
            mean_absolute_error,
            mean_absolute_percentage_error,
            mean_squared_error,
            r2_score,
        )

        mae = mean_absolute_error(targets, preds, multioutput="raw_values")
        mse = mean_squared_error(targets, preds, multioutput="raw_values")
        rmse = np.sqrt(mse)
        r2 = r2_score(targets, preds, multioutput="raw_values")
        cvrmse = rmse / np.abs(targets.mean(axis=0) + 1e-5)
        nmbe = normalized_mean_bias_error(preds=preds, targets=targets)
        mape = mean_absolute_percentage_error(
            targets + 1e-5,
            preds,
            multioutput="raw_values",
        )

        metrics = pd.DataFrame(
            {
                "mae": mae,
                "rmse": rmse,
                "r2": r2,
                "cvrmse": cvrmse,
                "nmbe": nmbe,
                "mape": mape,
            },
        )
        metrics.columns.names = ["metric"]
        metrics.index.names = ["target"]

        return metrics

    def compute_metrics(self, preds: pd.DataFrame, targets: pd.DataFrame):
        """Compute the metrics."""
        global_metrics = self.compute_frame_metrics(preds, targets)
        stratum_metric_dfs = {}
        names = []
        for stratum_name in self.stratum_names:
            if (
                stratum_name
                not in targets.index.get_level_values(
                    self.parent.stratification.field
                ).unique()
            ):
                continue
            names.append(stratum_name)
            stratum_targets = cast(
                pd.DataFrame,
                targets.xs(stratum_name, level=self.parent.stratification.field),
            )
            stratum_preds = cast(
                pd.DataFrame,
                preds.xs(stratum_name, level=self.parent.stratification.field),
            )
            metrics = self.compute_frame_metrics(stratum_preds, stratum_targets)
            stratum_metric_dfs[stratum_name] = metrics

        stratum_metrics = pd.concat(
            stratum_metric_dfs,
            axis=1,
            keys=names,
            names=["stratum"],
        )
        global_metrics = (
            global_metrics.set_index(
                pd.Index(
                    [self.sort_index] * len(global_metrics),
                    name="sort_index",
                ),
                append=True,
            )
            .set_index(
                pd.Index(
                    [self.parent.iteration.current_iter] * len(global_metrics),
                    name="iteration",
                ),
                append=True,
            )
            .unstack(level="target")
        )

        stratum_metrics = (
            stratum_metrics.set_index(
                pd.Index(
                    [self.sort_index] * len(stratum_metrics),
                    name="sort_index",
                ),
                append=True,
            )
            .set_index(
                pd.Index(
                    [self.parent.iteration.current_iter] * len(stratum_metrics),
                    name="iteration",
                ),
                append=True,
            )
            .unstack(level="target")
        )
        return global_metrics, stratum_metrics


class FoldResult(ReferencedMLBackend, ExperimentOutputSpec):
    """The output for a fold."""


class TrainWithCVSpec(StageSpec):
    """Train an SBEM model using a scatter gather approach for cross-fold validation."""

    data_uris: ScatterGatherResult = Field(
        ...,
        description="The uris of the data to train on.",
    )

    @property
    def schedule(self) -> list[TrainFoldSpec]:
        """Create the task schedule."""
        schedule = []

        for i in range(self.parent.cross_val.n_folds):
            schedule.append(
                TrainFoldSpec(
                    experiment_id="placeholder",
                    sort_index=i,
                    data_uris=self.data_uris.uris,
                    parent=self.parent,
                )
            )
        return schedule
