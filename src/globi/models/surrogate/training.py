"""Models used for the surrogate training pipeline."""

import warnings
from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scythe.base import ExperimentInputSpec
from scythe.scatter_gather import RecursionMap, ScatterGatherResult
from scythe.utils.filesys import FileReference, S3Url

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client as S3ClientType
else:
    S3ClientType = object


# TODO: allow specific configuration per column.
class ConvergenceThresholds(BaseModel):
    """The thresholds for convergence."""

    mae: float = Field(default=0.5, description="The maximum MAE for convergence.")
    rmse: float = Field(default=0.5, description="The maximum RMSE for convergence.")
    mape: float = Field(default=0.15, description="The maximum MAPE for convergence.")
    r2: float = Field(default=0.95, description="The minimum R2 for convergence.")
    cvrmse: float = Field(
        default=0.05, description="The maximum CV_RMSE for convergence."
    )

    @property
    def thresholds(self) -> pd.Series:
        """The thresholds for convergence."""
        return pd.Series(self.model_dump(), name="metric")

    def check_convergence(self, metrics: pd.Series):
        """Check if the metrics have converged.

        Note that this requires the metrics data frame to have the following shape:

        """
        thresholds = pd.Series(self.model_dump(), name="metric")

        # first, we will select the appropriate threshold for each metric
        comparators = thresholds.loc[metrics.index.get_level_values("metric")]
        # we can then copy over the index safely
        comparators.index = metrics.index

        # next, we will flip the sign of the r2 metric since it is a maximization metric rather thin min
        metrics = metrics * np.where(
            metrics.index.get_level_values("metric") == "r2", -1, 1
        )
        comparators = comparators * np.where(
            comparators.index.get_level_values("metric") == "r2", -1, 1
        )

        # run the comparisons
        comparison = metrics < comparators

        # now we will groupby the stratum (e.g. features.weather.file)
        # and by the target (e.g. Electricity, Gas, etc.)
        # we are converged if any of the metrics have converged for that target
        # in that stratum
        comparison_stratum_and_target = comparison.groupby(
            level=[lev for lev in comparison.index.names if lev != "metric"]
        ).any()

        # then we will check that all targets have converged for each stratum
        comparison_strata = comparison_stratum_and_target.groupby(level="stratum").all()

        # finally, we will check that all strata have converged
        comparison_all = comparison_strata.all()

        return (
            comparison_all,
            comparison_strata,
            comparison_stratum_and_target,
            comparison,
        )


class XGBTrainerConfig(BaseModel):
    """The trainer hyperparameters for the xgboost model."""

    num_boost_round: int = Field(
        default=4000, description="The number of boosting rounds."
    )
    early_stopping_rounds: int = Field(
        default=10, description="The number of boosting rounds to early stop."
    )
    verbose_eval: bool = Field(
        default=True, description="Whether to print verbose evaluation results."
    )


class XGBModelConfig(BaseModel):
    """The model hyperparameters for the xgboost model."""

    max_depth: int = Field(default=5, description="The maximum depth of the tree.")
    eta: float = Field(default=0.1, description="The learning rate.")
    min_child_weight: int | None = Field(
        default=3, description="The minimum child weight."
    )
    subsample: float | None = Field(default=None, description="The subsample rate.")
    colsample_bytree: float | None = Field(
        default=None, description="The column sample by tree rate."
    )
    alpha: float | None = Field(default=None, description="The alpha parameter.")
    lam: float | None = Field(default=None, description="The lambda parameter.")
    gamma: float | None = Field(default=None, description="The gamma parameter.")
    seed: int = Field(
        default=42, description="The seed for the random number generator."
    )

    @property
    def param_dict(self) -> dict[str, Any]:
        """The dictionary of parameters."""
        import torch

        data = {
            "objective": "reg:squarederror",
            "eval_metric": "rmse",
            "tree_method": "auto",
            "seed": self.seed,
            # hyperparameters
            **self.model_dump(
                exclude_none=True,
            ),
        }
        if torch.cuda.is_available():
            data["device"] = "cuda"
        return data


class XGBHyperparameters(BaseModel):
    """The parameters for the xgboost model."""

    hp: XGBModelConfig = Field(
        default_factory=XGBModelConfig,
        description="The hyperparameters for the model.",
    )
    trainer: XGBTrainerConfig = Field(
        default_factory=XGBTrainerConfig,
        description="The trainer hyperparameters for the model.",
    )


class LGBHyperparameters(BaseModel):
    """The parameters for the lightgbm model."""

    objective: Literal["regression", "binary", "multiclass"] = Field(
        default="regression", description="The objective function to use."
    )
    metric: Literal["rmse"] = Field(
        default="rmse", description="The metric to optimize."
    )
    # TODO: add other parameters as needed


ModelHPType = XGBHyperparameters | LGBHyperparameters


class StratificationSpec(BaseModel):
    """A spec for stratifying the data."""

    field: str = Field(
        default="feature.weather.file", description="The field to stratify by."
    )
    sampling: Literal["equal", "error-weighted", "proportional"] = Field(
        default="equal",
        description="The sampling method to use over the strata.",
    )
    aliases: list[str] = Field(
        default_factory=lambda: ["epwzip_path", "epw_path"],
        description="The alias to use for the stratum as a fallback.",
    )

    # TODO: consider allowing the stratification to be a compound with e.g. component_map_uri and semantic_fields_uri and database_uri


class CrossValidationSpec(BaseModel):
    """The cross validation spec."""

    n_folds: int = Field(
        default=5, description="The number of folds for the entire parent task."
    )


class IterationSpec(BaseModel):
    """The iteration spec."""

    n_init: int = Field(default=10000, description="The number of initial samples.")
    min_per_stratum: int = Field(
        default=100, description="The minimum number of samples per stratum."
    )
    n_per_iter: int = Field(
        default=10000,
        description="The number of samples to add per each iteration of the outer loop.",
    )
    max_iters: int = Field(
        default=100,
        description="The maximum number of outer loop iterations to perform.",
    )
    recursion: RecursionMap = Field(
        default_factory=lambda: RecursionMap(factor=100, max_depth=1),
        description="The recursion spec.",
    )
    current_iter: int = Field(
        default=0,
        description="The index of the current training iteration within the outer loop.",
    )

    @property
    def at_max_iters(self) -> bool:
        """Whether the current iteration is the maximum number of iterations."""
        return self.current_iter + 1 >= self.max_iters


class TargetsConfigSpec(BaseModel):
    """The targets config spec."""

    columns: list[str] = Field(
        default_factory=list, description="The columns to use as targets."
    )
    normalization: Literal["min-max", "standard", "none"] = Field(
        default="none", description="The normalization method to use."
    )


class FeatureConfigSpec(BaseModel):
    """The feature config spec."""

    continuous_columns: frozenset[str] = Field(
        default=frozenset(), description="The continuous columns to use as features."
    )
    categorical_columns: frozenset[str] = Field(
        default=frozenset(), description="The categorical columns to use as features."
    )
    exclude_columns: frozenset[str] = Field(
        default=frozenset(),
        description="The columns to exclude from the features.",
    )
    cont_cat_unicity_transition_threshold: int = Field(
        default=10,
        description="The threshold for the number of unique values to transition from continuous to categorical variable.",
    )


EXCLUDED_COLUMNS = frozenset({
    "experiment_id",
    "sort_index",
    "workflow_run_id",
    "root_workflow_run_id",
})


class RegressionIOConfigSpec(BaseModel):
    """The input/output spec for a regression model."""

    targets: TargetsConfigSpec = Field(
        default_factory=TargetsConfigSpec, description="The targets config spec."
    )
    features: FeatureConfigSpec = Field(
        default_factory=FeatureConfigSpec,
        description="The features config spec.",
    )


# TODO: should this be a subclass of ExperimentInputSpec?
class ProgressiveTrainingSpec(ExperimentInputSpec):
    """A spec for iteratively training an SBEM regression model."""

    base_run_name: str = Field(
        ...,
        description="The base run name for the experiment.",
    )
    convergence_criteria: ConvergenceThresholds = Field(
        default_factory=ConvergenceThresholds,
        description="The convergence criteria.",
    )
    regression_io_config: RegressionIOConfigSpec = Field(
        default_factory=RegressionIOConfigSpec,
        description="The regression io config spec.",
    )
    hyperparameters: ModelHPType = Field(
        default_factory=XGBHyperparameters,
        description="The hyperparameters for the model.",
    )
    stratification: StratificationSpec = Field(
        default_factory=StratificationSpec,
        description="The stratification spec.",
    )
    cross_val: CrossValidationSpec = Field(
        default_factory=CrossValidationSpec,
        description="The cross validation spec.",
    )
    iteration: IterationSpec = Field(
        default_factory=IterationSpec,
        description="The iteration spec.",
    )
    gis_uri: FileReference = Field(
        ...,
        description="The uri of the gis data to train on.",
    )
    data_uris: ScatterGatherResult | None = Field(
        default=None,
        description="The uri of the previous simulation results to train on.",
    )

    def format_combined_output_key(self, key: str) -> str:
        """Format the output key for a combined result file."""
        return f"{self.prefix}/combined/{key}.parquet"

    def format_combined_output_uri(self, key: str) -> S3Url:
        """Format the output uri for a combined result file."""
        if self.storage_settings is None:
            msg = "Storage settings are not set, so we can't construct a combined output uri."
            raise ValueError(msg)
        return S3Url(
            f"s3://{self.storage_settings.BUCKET}/{self.format_combined_output_key(key)}"
        )

    @property
    def gis_path(self) -> Path:
        """The path to the gis data."""
        if isinstance(self.gis_uri, Path):
            return self.gis_uri
        return self.fetch_uri(self.gis_uri)

    @cached_property
    def gis_data(self) -> pd.DataFrame:
        """Load the gis data."""
        return pd.read_parquet(self.gis_path)


class StageSpec(BaseModel):
    """A spec that is common to both the sample and train stages (and possibly others)."""

    parent: ProgressiveTrainingSpec = Field(
        ...,
        description="The parent spec.",
    )

    @cached_property
    def random_generator(self) -> np.random.Generator:
        """The random generator."""
        return np.random.default_rng(self.parent.iteration.current_iter)


class SampleSpec(StageSpec):
    """A spec for the sampling stage of the progressive training."""

    # TODO: add the ability to receive the last set of error metrics and use them to inform the sampling

    def stratified_selection(self) -> pd.DataFrame:
        """Sample the gis data."""
        df = self.parent.gis_data

        stratification_field = self.parent.stratification.field
        stratification_aliases = self.parent.stratification.aliases

        if stratification_field not in df.columns and not any(
            alias in df.columns for alias in stratification_aliases
        ):
            msg = f"Stratification field {stratification_field} not found in gis data.  Please check the field name and/or the aliases."
            raise ValueError(msg)

        if stratification_field not in df.columns:
            stratification_field = next(
                alias for alias in stratification_aliases if alias in df.columns
            )

        strata = cast(list[str], df[stratification_field].unique().tolist())

        if self.parent.stratification.sampling == "equal":
            return self.sample_equally_by_stratum(df, strata, stratification_field)
        elif self.parent.stratification.sampling == "error-weighted":
            msg = "Error-weighted sampling is not yet implemented."
            raise NotImplementedError(msg)
        elif self.parent.stratification.sampling == "proportional":
            msg = "Proportional sampling is not yet implemented."
            raise NotImplementedError(msg)
        else:
            msg = f"Invalid sampling method: {self.parent.stratification.sampling}"
            raise ValueError(msg)

    def sample_equally_by_stratum(
        self, df: pd.DataFrame, strata: list[str], stratification_field: str
    ) -> pd.DataFrame:
        """Sample equally by stratum.

        This will break the dataframe up into n strata and ensure that each strata ends up with the same number of samples.

        Args:
            df (pd.DataFrame): The dataframe to sample from.
            strata (list[str]): The unique values of the strata.
            stratification_field (str): The field to stratify the data by.

        Returns:
            samples (pd.DataFrame): The sampled dataframe.
        """
        stratum_dfs = {
            stratum: df[df[stratification_field] == stratum] for stratum in strata
        }
        n_per_iter = (
            self.parent.iteration.n_per_iter
            if self.parent.iteration.current_iter != 0
            else self.parent.iteration.n_init
        )
        n_per_stratum = max(
            n_per_iter // len(strata),
            (
                self.parent.iteration.min_per_stratum
                if self.parent.iteration.current_iter == 0
                else 0
            ),
        )

        # TODO: consider how we want to handle potentially having the same geometry appear in both
        # the training and testing sets.
        # if any(len(stratum_df) < n_per_stratum for stratum_df in stratum_dfs.values()):
        #     msg = "There are not enough buildings in some strata to sample the desired number of buildings per stratum."
        #     # connsider making this a warning?
        #     raise ValueError(msg)

        sampled_strata = {
            stratum: stratum_df.sample(
                n=n_per_stratum, random_state=self.random_generator, replace=True
            )
            for stratum, stratum_df in stratum_dfs.items()
        }
        return cast(pd.DataFrame, pd.concat(sampled_strata.values()))

    # def sample_semantic_fields(self, df: pd.DataFrame) -> pd.DataFrame:
    #     """Sample the semantic fields."""
    #     # TODO: consider randomizing the locations?
    #     semantic_fields = self.progressive_training_spec.semantic_fields_data
    #     for field in semantic_fields.Fields:
    #         if isinstance(field, CategoricalFieldSpec):
    #             options = field.Options
    #             df[field.Name] = self.random_generator.choice(options, size=len(df))
    #         elif isinstance(field, NumericFieldSpec):
    #             df[field.Name] = self.random_generator.uniform(
    #                 field.Min, field.Max, size=len(df)
    #             )
    #         else:
    #             msg = f"Invalid field type: {type(field)}"
    #             raise TypeError(msg)
    #     return df

    # def sample_basements_and_attics(self, df: pd.DataFrame) -> pd.DataFrame:
    #     """Add basement/attics to models."""
    #     # get the options for the type literal
    #     options: list[BasementAtticOccupationConditioningStatus] = [
    #         "none",
    #         "occupied_unconditioned",
    #         "unoccupied_unconditioned",
    #         "occupied_conditioned",
    #         "unoccupied_conditioned",
    #     ]
    #     weights = [0.5, *([0.5 / 4] * 4)]
    #     # sample the type literal
    #     df["basement"] = self.random_generator.choice(options, size=len(df), p=weights)
    #     df["attic"] = self.random_generator.choice(options, size=len(df), p=weights)
    #     df["exposed_basement_frac"] = self.random_generator.uniform(
    #         0.1, 0.5, size=len(df)
    #     )
    #     return df

    # def sample_wwrs(self, df: pd.DataFrame) -> pd.DataFrame:
    #     """Sample the wwrs."""
    #     wwr_min = 0.05
    #     wwr_max = 0.35
    #     df["wwr"] = self.random_generator.uniform(wwr_min, wwr_max, size=len(df))
    #     return df

    # def sample_f2f_heights(self, df: pd.DataFrame) -> pd.DataFrame:
    #     """Sample the f2f heights."""
    #     f2f_min = 2.3
    #     f2f_max = 4.3
    #     df["f2f_height"] = self.random_generator.uniform(f2f_min, f2f_max, size=len(df))
    #     return df

    def to_sim_specs(self, df: pd.DataFrame):
        """Convert the sampled dataframe to a list of simulation specs.

        For now, we are assuming that all the other necessary fields are present and we are just
        ensuring that sort_index and experiment_id are set appropriately.
        """
        # df["semantic_field_context"] = df.apply(
        #     lambda row: {
        #         field.Name: row[field.Name]
        #         for field in self.progressive_training_spec.semantic_fields_data.Fields
        #     },
        #     axis=1,
        # )
        # df["sort_index"] = np.arange(len(df))
        # df["experiment_id"] = self.experiment_key
        # # TODO: consider allowing the component map/semantic_fields/database to be inherited from the row
        # # e.g. to allow multiple component maps and dbs per run.
        # df["component_map_uri"] = str(self.progressive_training_spec.component_map_uri)
        # df["semantic_fields_uri"] = str(
        #     self.progressive_training_spec.semantic_fields_uri
        # )
        # df["db_uri"] = str(self.progressive_training_spec.database_uri)
        return df

    # def make_payload(self, s3_client: S3ClientType):
    #     """Make the payload for the scatter gather task, including generating the simulation specs and serializing them to s3."""
    #     df = self.stratified_selection()
    #     # df = self.sample_semantic_fields(df)
    #     # df = self.sample_basements_and_attics(df)
    #     # df = self.sample_wwrs(df)
    #     # df = self.sample_f2f_heights(df)
    #     df = self.to_sim_specs(df)
    #     # serialize to a parquet file and upload to s3
    #     bucket = self.progressive_training_spec.storage_settings.BUCKET
    #     with tempfile.TemporaryDirectory() as tmpdir:
    #         tmpdir = Path(tmpdir)
    #         fpath = tmpdir / "specs.pq"
    #         df.to_parquet(fpath)
    #         key = f"hatchet/{self.experiment_key}/specs.pq"
    #         specs_uri = f"s3://{bucket}/{key}"
    #         s3_client.upload_file(fpath.as_posix(), bucket, key)

    #     payload = {
    #         "specs": specs_uri,
    #         "bucket": bucket,
    #         "workflow_name": "simulate_sbem_shoebox",
    #         "experiment_id": self.experiment_key,
    #         "recursion_map": {
    #             "factor": self.progressive_training_spec.iteration.recursion_factor,
    #             "max_depth": self.progressive_training_spec.iteration.recursion_max_depth,
    #         },
    #     }
    #     return payload


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
        dfs: dict[str, pd.DataFrame] = {
            key: pd.read_parquet(str(uri)) for key, uri in self.data_uris.items()
        }
        if not all(
            df.index.equals(next(iter(dfs.values())).index) for df in dfs.values()
        ):
            msg = "The indices of the dataframes are not all equal. "
            "This is not supported, since the features must be identical for all outputs.."
            raise ValueError(msg)

        for df in dfs.values():
            # TODO: use level names while constructing the sequential name
            _level_names = df.columns.names
            df.columns = df.columns.to_flat_index()

            df.columns = [
                "/".join(col) if isinstance(col, tuple | list) else col
                for col in df.columns
            ]

        combined_df = pd.concat(dfs, axis=1)
        combined_df.columns = combined_df.columns.to_flat_index()
        combined_df.columns = ["/".join(col) for col in combined_df.columns]
        shuffled_df = combined_df.sample(frac=1, random_state=42, replace=False)
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
        return frozenset(self.dparams.columns)

    @cached_property
    def all_target_columns(self) -> frozenset[str]:
        """The names of all columns."""
        return frozenset(self.data.columns)

    @cached_property
    def continuous_columns(self) -> frozenset[str]:
        """The continuous columns."""
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

    @cached_property
    def targets(self) -> list[str]:
        """The list of regression targets."""
        return self.parent.regression_io_config.targets.columns or sorted(
            self.all_target_columns
        )

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

    def train_xgboost(self, tempdir: Path):
        """Train an xgboost model."""
        import xgboost as xgb

        hp = (
            self.parent.hyperparameters
            if isinstance(self.parent.hyperparameters, XGBHyperparameters)
            else XGBHyperparameters()
        )

        x_train, y_train = self.train_segment
        x_test, y_test = self.test_segment

        # select the features
        x_train_selected, x_test_selected = (
            x_train.loc[:, self.continuous_columns | self.categorical_columns],
            x_test.loc[:, self.continuous_columns | self.categorical_columns],
        )
        cats = {
            col: self.dparams[col].unique().tolist() for col in self.categorical_columns
        }
        x_train_encoded = self.index_encode_categorical_columns(x_train_selected, cats)
        x_test_encoded = self.index_encode_categorical_columns(x_test_selected, cats)

        # select the targets
        y_train, y_test = y_train.loc[:, self.targets], y_test.loc[:, self.targets]

        train_dmat = xgb.DMatrix(
            x_train_encoded.reset_index(drop=True), label=y_train.reset_index(drop=True)
        )
        test_dmat = xgb.DMatrix(
            x_test_encoded.reset_index(drop=True), label=y_test.reset_index(drop=True)
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

        def predict(x: pd.DataFrame) -> pd.DataFrame:
            """Predict the targets for the given features."""
            x_selected = cast(
                pd.DataFrame,
                x.loc[:, self.continuous_columns | self.categorical_columns],
            )
            x_encoded = self.index_encode_categorical_columns(x_selected, cats)
            preds = model.predict(
                xgb.DMatrix(
                    x_encoded.reset_index(drop=True),
                )
            )
            return pd.DataFrame(
                preds, columns=pd.Index(self.targets), index=pd.MultiIndex.from_frame(x)
            )

        evaluation = self.evaluate(predict, x_train, x_test, y_train, y_test)
        model_path = tempdir / "model.ubj"
        model.save_model(model_path.as_posix())
        return model, evaluation, model_path

    def evaluate(
        self,
        fn: Callable[[pd.DataFrame], pd.DataFrame],
        x_train: pd.DataFrame,
        x_test: pd.DataFrame,
        y_train: pd.DataFrame,
        y_test: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Evaluate a model on the train and test segments."""
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
        return global_metrics, stratum_metrics

    def index_encode_categorical_columns(
        self, df: pd.DataFrame, cats: dict[str, list[str]]
    ) -> pd.DataFrame:
        """Index encode the categorical columns."""
        df = df.copy(deep=True)
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = pd.Categorical(df[col], categories=cats[col]).codes
        return df

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
            train=train_targets.reset_index(),
            validation=test_targets.reset_index(),
            seed=42,
        )
        model.save_model((tempdir / "model").as_posix())
        return model, trainer

    # @cached_property
    # def non_numeric_options(self) -> dict[str, list[str]]:
    #     """Get the non-numeric options for categorical features.

    #     We must perform this across the entire dataset not just splits for consistency
    #     and to ensure we get all options.

    #     TODO: In the future, this should be based off of transform instructions.
    #     """
    #     fparams = self.dparams[
    #         [col for col in self.dparams.columns if col.startswith("feature.")]
    #     ]
    #     non_numeric_cols = fparams.select_dtypes(include=["object"]).columns
    #     non_numeric_options = {
    #         col: sorted(cast(pd.Series, fparams[col]).unique().tolist())
    #         for col in non_numeric_cols
    #     }
    #     return non_numeric_options

    # @cached_property
    # def numeric_min_maxs(self) -> dict[str, tuple[float, float]]:
    #     """Get the min and max for numeric features.

    #     We perform this only on the training set to prevent leakage.

    #     TODO: In the future, this should be based off of transform instructions.

    #     Args:
    #         params (pd.DataFrame): The parameters to get the min and max for.

    #     Returns:
    #         norm_bounds (dict[str, tuple[float, float]]): The min and max for each numeric feature.
    #     """
    #     params, _ = self.train_segment
    #     fparams = params[[col for col in params.columns if col.startswith("feature.")]]
    #     numeric_cols = fparams.select_dtypes(include=["number"]).columns
    #     numeric_min_maxs = {
    #         col: (float(fparams[col].min()), float(fparams[col].max()))
    #         for col in numeric_cols
    #     }
    #     for col in numeric_min_maxs:
    #         low, high = numeric_min_maxs[col]
    #         # we want to floor the "low" value down to the nearest 0.001
    #         # and ceil the "high" value up to the nearest 0.001
    #         # e.g. if low is -0.799, we want to set it to -0.800
    #         # and if high is 0.799, we want to set it to 0.800
    #         numeric_min_maxs[col] = (
    #             math.floor(low * 1000) / 1000,
    #             math.ceil(high * 1000) / 1000,
    #         )
    #     return numeric_min_maxs

    # @cached_property
    # def feature_spec(self) -> RegressorInputSpec:
    #     """Get the feature spec which can be serialized and reloaded."""
    #     params, _ = self.train_segment
    #     features: list[CategoricalFeature | ContinuousFeature] = []
    #     for col in params.columns:
    #         if col in self.numeric_min_maxs:
    #             low, high = self.numeric_min_maxs[col]
    #             features.append(
    #                 ContinuousFeature(name=col, min=float(low), max=float(high))
    #             )
    #         elif col in self.non_numeric_options:
    #             opts = self.non_numeric_options[col]
    #             features.append(CategoricalFeature(name=col, values=opts))
    #     return RegressorInputSpec(features=features)

    # def normalize_params(self, params: pd.DataFrame) -> pd.DataFrame:
    #     """Normalize the params."""
    #     regressor_spec = self.feature_spec
    #     fparams = regressor_spec.transform(params, do_check=False)
    #     return fparams

    # def run(
    #     self,
    # ):
    #     """Train the model."""
    #     train_params, train_targets = self.train_segment
    #     test_params, test_targets = self.test_segment

    #     # select/transform the params as necessary
    #     train_params = self.normalize_params(train_params)
    #     test_params = self.normalize_params(test_params)

    #     # Train the model
    #     # train_preds, test_preds = self.train_xgboost(
    #     #     train_params, train_targets, test_params, test_targets
    #     # )
    #     s3_client = boto3.client("s3")
    #     train_preds, test_preds = self.train_lightgbm(
    #         train_params, train_targets, test_params, test_targets, s3_client
    #     )

    #     # compute the metrics
    #     global_train_metrics, stratum_train_metrics = self.compute_metrics(
    #         train_preds, train_targets
    #     )
    #     global_test_metrics, stratum_test_metrics = self.compute_metrics(
    #         test_preds, test_targets
    #     )

    #     global_metrics = pd.concat(
    #         [global_train_metrics, global_test_metrics],
    #         axis=1,
    #         keys=["train", "test"],
    #         names=["split_segment"],
    #     )
    #     stratum_metrics = pd.concat(
    #         [stratum_train_metrics, stratum_test_metrics],
    #         axis=1,
    #         keys=["train", "test"],
    #         names=["split_segment"],
    #     )
    #     return {
    #         "global_metrics": global_metrics,
    #         "stratum_metrics": stratum_metrics,
    #     }

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
        for stratum_name in self.stratum_names:
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
            keys=self.stratum_names,
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

    # def train_lightgbm(
    #     self,
    #     train_params: pd.DataFrame,
    #     train_targets: pd.DataFrame,
    #     test_params: pd.DataFrame,
    #     test_targets: pd.DataFrame,
    #     s3_client: S3ClientType | None = None,
    # ):
    #     """Train the lightgbm model."""
    #     import lightgbm as lgb

    #     lgb_params = {
    #         "objective": "regression",
    #         "metric": "rmse",
    #     }
    #     test_preds = {}
    #     train_preds = {}
    #     for col in train_targets.columns:
    #         lgb_train_data = lgb.Dataset(train_params, label=train_targets[col])
    #         lgb_test_data = lgb.Dataset(test_params, label=test_targets[col])
    #         model = lgb.train(
    #             lgb_params,
    #             lgb_train_data,
    #             num_boost_round=4000,
    #             valid_sets=[lgb_test_data],
    #             valid_names=["eval"],
    #             callbacks=[lgb.early_stopping(20)],
    #         )
    #         test_preds[col] = pd.Series(
    #             cast(np.ndarray, model.predict(test_params)),
    #             index=test_targets.index,
    #             name=col,
    #         )
    #         train_preds[col] = pd.Series(
    #             cast(np.ndarray, model.predict(train_params)),
    #             index=train_targets.index,
    #             name=col,
    #         )
    #         if s3_client is not None:
    #             model_name = (
    #                 f"{col}.lgb"
    #                 if not isinstance(col, tuple)
    #                 else f"{'.'.join(col)}.lgb"
    #             )
    #             model_key = self.format_model_key(model_name)
    #             model_str = model.model_to_string()
    #             s3_client.put_object(Bucket=self.bucket, Key=model_key, Body=model_str)

    #     if s3_client is not None:
    #         import yaml

    #         space_key = self.format_model_key("space.yml")
    #         space_str = yaml.dump(
    #             self.feature_spec.model_dump(mode="json"), indent=2, sort_keys=False
    #         )
    #         s3_client.put_object(Bucket=self.bucket, Key=space_key, Body=space_str)

    #     test_preds = pd.concat(test_preds, axis=1)
    #     train_preds = pd.concat(train_preds, axis=1)
    #     return train_preds, test_preds

    # @property
    # def model_dir_key(self) -> str:
    #     """Get the key for the model directory."""
    #     return f"{self.experiment_id}/{self.sort_index}/models"

    # def format_model_key(self, model_name: str) -> str:
    #     """Format the model key."""
    #     return f"hatchet/{self.model_dir_key}/{model_name}"


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
        # TODO: this should be configured/selected/etc

        for i in range(self.parent.cross_val.n_folds):
            schedule.append(
                TrainFoldSpec(
                    # TODO: this should be set in a better manner
                    experiment_id="placeholder",
                    sort_index=i,
                    data_uris=self.data_uris.uris,
                    parent=self.parent,
                )
            )
        return schedule

    # def check_convergence(self, uri: URIResponse, s3_client: S3ClientType):
    #     """Check the convergence of the training."""
    #     with tempfile.TemporaryDirectory() as tempdir:
    #         tempdir = Path(tempdir)
    #         results_path = tempdir / "results.hdf"
    #         # download the results from s3
    #         fetch_uri(uri.uri, local_path=results_path, use_cache=False, s3=s3_client)
    #         results = cast(
    #             pd.DataFrame, pd.read_hdf(results_path, key="stratum_metrics")
    #         )

    #     fold_averages = cast(
    #         pd.Series,
    #         results.xs(
    #             "test",
    #             level="split_segment",
    #             axis=1,
    #         )
    #         .groupby(level="measurement")
    #         .mean()
    #         .unstack(level="measurement"),
    #     )
    #     with tempfile.TemporaryDirectory() as tempdir:
    #         fold_averages_path = Path(tempdir) / "fold-averaged-errors.pq"
    #         fold_averages.to_frame(
    #             name=self.progressive_training_iteration_ix
    #         ).to_parquet(fold_averages_path)
    #         key = f"hatchet/{self.experiment_key}/fold-averaged-errors.pq"
    #         bucket = self.progressive_training_spec.bucket
    #         s3_client.upload_file(fold_averages_path.as_posix(), bucket, key)

    #     (
    #         convergence_all,
    #         convergence_monitor_segment,
    #         convergence_monitor_segment_and_target,
    #         convergence,
    #     ) = self.progressive_training_spec.convergence_criteria.check_convergence(
    #         fold_averages.xs("Energy", level="measurement")
    #     )

    #     return convergence_all, convergence
