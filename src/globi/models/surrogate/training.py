"""Models used for the surrogate training pipeline."""

import fnmatch
import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property, partial
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, Field
from scythe.base import ExperimentInputSpec, ExperimentOutputSpec
from scythe.scatter_gather import ScatterGatherResult
from scythe.utils.filesys import FileReference, S3Url

from globi.models.surrogate.configs.pipeline import (
    ProgressiveTrainingSpec,
    StageSpec,
    TargetsConfigColumnSpec,
)
from globi.models.surrogate.configs.regression import XGBHyperparameters

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
class DataPair:
    """A pair of dataframes."""

    x: pd.DataFrame
    y: pd.DataFrame


@dataclass(frozen=True)
class TrainTestPair:
    """A pair of train and test dataframes."""

    train: DataPair
    test: DataPair


class XTransformer(BaseModel, frozen=True):
    """A transformer for the x features."""

    features: list[str]
    cat_map: dict[str, list[str | float | int]]
    cat_encoding: Literal["index", "one-hot"]


class MinMaxScaler(BaseModel, arbitrary_types_allowed=True):
    """The configuration for a min-max scaler."""

    mins_: dict[str, float] = Field(default_factory=dict)
    maxs_: dict[str, float] = Field(default_factory=dict)

    @property
    def mins(self) -> pd.Series:
        """The mins."""
        return pd.Series(self.mins_, name="mins", dtype=float)

    @property
    def maxs(self) -> pd.Series:
        """The maxs."""
        return pd.Series(self.maxs_, name="maxs", dtype=float)

    def fit(self, y: pd.DataFrame) -> None:
        """Fit the min-max scaler."""
        y_min = cast(pd.Series, y.min(axis=0))
        y_max = cast(pd.Series, y.max(axis=0))
        self.mins_ = y_min.to_dict()
        self.maxs_ = y_max.to_dict()

    @property
    def scale(self) -> pd.Series:
        """The scale."""
        return self.maxs - self.mins

    def transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Transform the data."""
        return (y - self.mins) / self.scale

    def fit_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Fit and transform the data."""
        self.fit(y)
        return self.transform(y)

    def inverse_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Inverse transform the data."""
        return y * self.scale + self.mins


class StandardScaler(BaseModel, arbitrary_types_allowed=True):
    """The configuration for a min-max scaler."""

    means_: dict[str, float] = Field(default_factory=dict)
    stds_: dict[str, float] = Field(default_factory=dict)

    @property
    def means(self) -> pd.Series:
        """The means."""
        return pd.Series(self.means_, name="means", dtype=float)

    @property
    def stds(self) -> pd.Series:
        """The stds."""
        return pd.Series(self.stds_, name="stds", dtype=float)

    def fit(self, y: pd.DataFrame) -> None:
        """Fit the standard scaler."""
        y_mean = cast(pd.Series, y.mean(axis=0))
        y_std = cast(pd.Series, y.std(axis=0))
        # if any stds are zero, we will set them to 1 to avoid division by zero
        y_std = y_std.where(y_std != 0, 1)
        self.means_ = y_mean.to_dict()
        self.stds_ = y_std.to_dict()

    def transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Transform the data."""
        return (y - self.means) / self.stds

    def fit_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Fit and transform the data."""
        self.fit(y)
        return self.transform(y)

    def inverse_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Inverse transform the data."""
        return y * self.stds + self.means


class IdentityScaler(BaseModel, frozen=True):
    """A scaler that does nothing."""

    def fit(self, y: pd.DataFrame) -> None:
        """Fit the identity scaler."""
        pass

    def transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Transform the data."""
        return y

    def fit_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Fit and transform the data."""
        self.fit(y)
        return self.transform(y)

    def inverse_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Inverse transform the data."""
        return y


class YTransformer(BaseModel, arbitrary_types_allowed=True, frozen=True):
    """A transformer for the y features."""

    scaler: MinMaxScaler | StandardScaler | IdentityScaler
    targets: list[str]
    normalization: Literal["min-max", "standard"] | None


class Transformers(BaseModel, frozen=True):
    """A pair of transformers."""

    x: XTransformer
    y: YTransformer


@dataclass(frozen=True)
class PrepDataResult:
    """The result of preparing the data."""

    # original data
    selected: TrainTestPair
    # transformed data
    transformed: TrainTestPair
    # Transformers
    transformers: Transformers


def xgb_pred(x: pd.DataFrame, *, model):
    """Predict the targets for the given features using xgboost."""
    import xgboost as xgb

    if not isinstance(model, xgb.Booster):
        msg = f"Model is not an xgboost model: {type(model)}"
        raise TypeError(msg)

    dmat = xgb.DMatrix(x.reset_index(drop=True))
    preds = model.predict(dmat)
    return preds


def predict[T: pd.DataFrame | np.ndarray](
    x: pd.DataFrame, *, conf: Transformers, pred_fn: Callable[[pd.DataFrame], T]
) -> pd.DataFrame:
    """Predict the targets for the given features."""
    x_encoded = encode_inputs(
        x,
        conf=conf.x,
    )
    preds = pred_fn(x_encoded.reset_index(drop=True))
    preds = pd.DataFrame(preds, columns=pd.Index(conf.y.targets), index=x_encoded.index)
    if conf.y.scaler:
        preds = conf.y.scaler.inverse_transform(preds)
    return preds


def index_encode_categorical_columns(
    df: pd.DataFrame, *, cats: dict[str, list[str | float | int]]
) -> pd.DataFrame:
    """Index encode the categorical columns."""
    # TODO: make sure this still works when one of the values is nan
    # TODO: drop this copy call since we have already made a copy of the dataframe
    df = df.copy(deep=True)
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = pd.Categorical(df[col], categories=cats[col]).codes
    return df


def encode_inputs(
    x: pd.DataFrame,
    *,
    conf: XTransformer,
    log: Callable[[str], None] = lambda x: logger.info(x),
) -> pd.DataFrame:
    """Encode the inputs."""
    log(f"Selecting {len(conf.features)} features out of {len(x.columns)}...")
    x_encoded = x.loc[:, conf.features]
    log("Selected features.")

    log(f"Encoding categorical inputs with {conf.cat_encoding} encoding...")
    if conf.cat_encoding == "index":
        x_encoded = index_encode_categorical_columns(x_encoded, cats=conf.cat_map)
    elif conf.cat_encoding == "one-hot":
        raise NotImplementedError("One-hot encoding is not implemented yet.")
    else:
        raise NotImplementedError(
            f"Unsupported categorical encoding: {conf.cat_encoding}"
        )
    log("Encoded inputs.")
    # TODO: add continuous encoding
    return x_encoded.set_index(pd.MultiIndex.from_frame(x))


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
        self.log("Checking for valid targets in dataframes...")
        dfs_to_use: dict[str, pd.DataFrame] = {}
        for key, df in all_dfs.items():
            self.log(f"Checking dataframe {key}...")
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
                self.log(
                    f"Including dataframe {key} with {len(viable_targets)} targets: {viable_targets}"
                )
                dfs_to_use[key] = df
            else:
                self.log(f"Excluding dataframe {key} because it has no valid targets.")

        # TODO: consider how/if we want to handle dataframes with different indices.
        if not all(
            df.index.equals(next(iter(dfs_to_use.values())).index)
            for df in dfs_to_use.values()
        ):
            msg = "The indices of the dataframes are not all equal. "
            "This is not supported, since the features must be identical for all outputs.."
            raise ValueError(msg)

        self.log("Concatenating and shuffling dataframes...")
        combined_df = pd.concat(dfs_to_use, axis=1)
        combined_df.columns = combined_df.columns.to_flat_index()
        combined_df.columns = ["/".join(col) for col in combined_df.columns]
        shuffled_df = combined_df.sample(frac=1, random_state=42, replace=False)
        self.log(f"Shuffled dataframe has {len(shuffled_df)} rows.")
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
        self.log("Determining targets...")
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
        self.log(
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
        """Train the model."""
        if isinstance(self.parent.hyperparameters, XGBHyperparameters):
            # TOOO: Consider adding an interface/protocol/base class so signatures can be consistent.
            return self.train_xgboost(tempdir)
        else:
            raise NotImplementedError(
                f"Unsupported hyperparameters type: {type(self.parent.hyperparameters)}"
            )

    def prep_data(
        self,
        *,
        x_cat_encoding: Literal["index", "one-hot"],
        y_encoding: Literal["min-max", "standard"] | None,
    ) -> PrepDataResult:
        """Prepare the data for training."""
        self.log("Preparing data for training...")
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
        )
        x_train_encoded = encode_inputs(
            x_train,
            conf=x_transformer,
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
        self.log("Selecting targets...")
        y_train, y_test = (
            cast(pd.DataFrame, y_train.loc[:, y_transformer.targets]),
            cast(pd.DataFrame, y_test.loc[:, y_transformer.targets]),
        )
        self.log("Selected targets.")

        self.log(f"Scaling targets with {type(y_transformer.scaler).__name__}...")
        y_train_scaled = y_transformer.scaler.fit_transform(y_train)
        y_test_scaled = y_transformer.scaler.transform(y_test)
        self.log("Scaled targets.")

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

    def train_xgboost(self, tempdir: Path):
        """Train an xgboost model."""
        import xgboost as xgb

        x_encoding = self.parent.regression_io_config.features.cat_encoding
        y_encoding = self.parent.regression_io_config.targets.normalization
        data = self.prep_data(x_cat_encoding=x_encoding, y_encoding=y_encoding)
        self.log("Training XGBoost model...")

        hp = (
            self.parent.hyperparameters
            if isinstance(self.parent.hyperparameters, XGBHyperparameters)
            else XGBHyperparameters()
        )
        train_dmat = xgb.DMatrix(
            data.transformed.train.x.reset_index(drop=True),
            label=data.transformed.train.y.reset_index(drop=True),
        )
        test_dmat = xgb.DMatrix(
            data.transformed.test.x.reset_index(drop=True),
            label=data.transformed.test.y.reset_index(drop=True),
        )

        evals = [(train_dmat, "train"), (test_dmat, "eval")]
        model = xgb.train(
            hp.hp.param_dict,
            train_dmat,
            num_boost_round=hp.trainer.num_boost_round,
            evals=evals,
            early_stopping_rounds=hp.trainer.early_stopping_rounds,
            verbose_eval=hp.trainer.verbose_eval,
        )
        self.log("Trained XGBoost model.")

        pred = partial(
            predict, conf=data.transformers, pred_fn=partial(xgb_pred, model=model)
        )

        evaluation = self.evaluate(
            pred,
            selected=data.selected,
        )
        self.log("Saving model...")
        model_path = tempdir / "model.ubj"
        model.save_model(model_path.as_posix())
        transforms_path = tempdir / "transforms.yml"
        with open(transforms_path, "w") as f:
            yaml.dump(
                data.transformers.model_dump(mode="json"), f, indent=2, sort_keys=False
            )
        self.log("Model saved.")
        return (model, model_path), (data.transformers, transforms_path), evaluation

    def evaluate(
        self,
        fn: Callable[[pd.DataFrame], pd.DataFrame],
        selected: TrainTestPair,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Evaluate a model on the train and test segments."""
        self.log("Evaluating model on train and test segments...")
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
        self.log("Model evaluated on train and test segments.")
        return global_metrics, stratum_metrics

    def train_pytorch_tabular(self, tempdir: Path):
        """Train a pytorch tabular model."""
        from pytorch_tabular import TabularModel
        from pytorch_tabular.config import (
            DataConfig,
            ExperimentConfig,
            OptimizerConfig,
            TrainerConfig,
        )
        from pytorch_tabular.models import GANDALFConfig
        from pytorch_tabular.models.common.heads import LinearHeadConfig

        data_config = DataConfig(
            target=self.targets,
            continuous_cols=list(self.continuous_columns),
            categorical_cols=list(self.categorical_columns),
            # validation_split=0.2,
            # continuous_feature_transform="",
            # normalize_continuous_features=True,
        )
        n_epochs = 200
        optimizer_config = OptimizerConfig(  # TODO: make this all configurable
            optimizer="AdamW",
            optimizer_params={"weight_decay": 1e-5},
            # lr_scheduler="CosineAnnealingLR",
            # lr_scheduler_params={"T_max": n_epochs, "eta_min": 1e-5},
        )
        trainer_config = TrainerConfig(
            batch_size=256,
            fast_dev_run=False,
            max_epochs=n_epochs,
            min_epochs=max(n_epochs // 20, 1),
            early_stopping=None,
            # early_stopping= "valid_loss",
            # early_stopping_min_delta=0.001,
            # early_stopping_mode="min",
            # early_stopping_patience=3,
            # gradient_clip_val=1.0,
            # auto_lr_find=False
            # max_time=60,
        )

        model_config = GANDALFConfig(
            task="regression",
            head="LinearHead",
            head_config=LinearHeadConfig(
                layers="256-128-64",
                activation="SiLU",
                use_batch_norm=True,
                # dropout=0,
            ).__dict__,
            target_range=self.target_range,
            embedding_dims=None,
            embedding_dropout=0.05,
            batch_norm_continuous_input=True,
            gflu_stages=24,
            gflu_dropout=0.0,
            gflu_feature_init_sparsity=0.3,
            learnable_sparsity=True,
        )

        experiment_config = ExperimentConfig(
            run_name=self.experiment_id,
            project_name="globi-surrogate-training",
            log_target="tensorboard",
        )

        model = TabularModel(
            data_config=data_config,
            optimizer_config=optimizer_config,
            trainer_config=trainer_config,
            experiment_config=experiment_config,
            model_config=model_config,
        )

        _, train_targets = self.train_segment
        _, test_targets = self.test_segment
        trainer = model.fit(
            train=train_targets.reset_index(drop=True),
            validation=test_targets.reset_index(drop=True),
            seed=42,
        )
        model.save_model((tempdir / "model").as_posix())
        return model, trainer

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


class FoldResult(ExperimentOutputSpec):
    """The output for a fold."""

    regressor: FileReference
    transforms: FileReference


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
