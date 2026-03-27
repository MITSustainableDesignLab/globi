"""Configs for the surrogate model pipeline."""

import fnmatch
import re
from functools import cached_property
from pathlib import Path
from typing import Literal, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scythe.base import ExperimentInputSpec
from scythe.experiments import SemVer, SerializableRunnable
from scythe.scatter_gather import RecursionMap, ScatterGatherResult
from scythe.utils.filesys import OptionalFileReference, S3Url

from globi.models.surrogate.backends import MLBackend, XGBBackend
from globi.models.surrogate.samplers import Priors


class IterationSpec(BaseModel):
    """The iteration spec."""

    n_per_iter: int | list[int] = Field(
        default=10_000,
        description="The number of samples to generate per generation. If the current iteration exceeds the length of the list, the last element will be used.",
    )
    min_per_stratum: int = Field(
        default=100, description="The minimum number of samples per stratum."
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

    @property
    def n_per_gen_for_current_iter(self) -> int:
        """The number of samples to generate for the current iteration."""
        if isinstance(self.n_per_iter, int):
            return self.n_per_iter
        return self.n_per_iter[min(self.current_iter, len(self.n_per_iter) - 1)]


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


class ConvergenceThresholds(BaseModel):
    """The thresholds for convergence."""

    mae: float | None = Field(
        default=None, description="The maximum MAE for convergence."
    )
    rmse: float | None = Field(
        default=None, description="The maximum RMSE for convergence."
    )
    mape: float | None = Field(
        default=None, description="The maximum MAPE for convergence."
    )
    r2: float | None = Field(
        default=None, description="The minimum R2 for convergence."
    )
    cvrmse: float | None = Field(
        default=None, description="The maximum CV_RMSE for convergence."
    )
    nmbe: float | None = Field(
        default=None,
        description=(
            "The maximum normalized mean bias error for convergence. "
            "This is treated as a minimization metric."
        ),
    )

    def check_convergence(self, metrics: pd.Series, target: re.Pattern | None = None):
        """Check if the metrics have converged.

        Note that this requires the metrics data frame to have the following shape:

        """
        # first, we select the data for the relevant targets:
        if target is not None:
            target_level = metrics.index.get_level_values("target")
            # Interpret target as a regex and match
            mask = cast(pd.Series, target_level.to_series().astype(str)).str.match(
                target
            )
            metrics = cast(pd.Series, metrics.loc[mask.values])

        thresholds = pd.Series(self.model_dump(), name="metric")

        # first, we will select the appropriate threshold for each metric
        comparators = thresholds.loc[metrics.index.get_level_values("metric")]

        # we can then copy over the index safely
        comparators.index = metrics.index

        # we will ignore any thresholds that are not set or are NaN
        comparators_are_na = comparators.isna()

        # next, we will flip the sign of the r2 metric since it is a maximization metric rather thin min
        metrics = metrics * np.where(
            metrics.index.get_level_values("metric") == "r2", -1, 1
        )
        comparators = comparators * np.where(
            comparators.index.get_level_values("metric") == "r2", -1, 1
        )

        # run the comparisons
        comparison = metrics < comparators
        comparison = comparison.loc[~comparators_are_na]

        return comparison


class ConvergenceThresholdsByTarget(BaseModel):
    """The thresholds for convergence by target."""

    thresholds: dict[str, ConvergenceThresholds] = Field(
        default_factory=lambda: {"*": ConvergenceThresholds()},
        description="The thresholds for convergence by target.",
    )

    def make_comparisons(self, metrics: pd.Series) -> list[pd.Series]:
        """Generate a list of all stratum/target/metric True/False comparisons."""
        return [
            self.thresholds[target].check_convergence(
                metrics, re.compile(fnmatch.translate(target))
            )
            for target in self.thresholds
        ]

    def combine_and_check_strata_and_targets(self, comparisons: list[pd.Series]):
        """Combine the comparisons and aggregate first by targets then by strata."""
        comparison = pd.concat(comparisons, axis=0)
        # now we will groupby the stratum (e.g. features.weather.file)
        # and by the target (e.g. Electricity, Gas, etc.)
        # we are converged if any of the metrics have converged for that target
        # in that stratum
        comparison_stratum_and_target = comparison.groupby(
            level=[lev for lev in comparison.index.names if lev != "metric"]
        ).any()  # TODO: make it configurable such that instead of `any`, we can specify a count, i.e. at least 2 must be converged

        # then we will check that all targets have converged for each stratum

        # only levels left in multiindex should be stratum and target

        comparison_strata = comparison_stratum_and_target.groupby(level="stratum").all()

        # finally, we will check that all strata have converged
        comparison_all = comparison_strata.all()

        return (
            comparison_all,
            comparison_strata,
            comparison_stratum_and_target,
            comparison,
        )

    def run(self, metrics: pd.Series) -> tuple[bool, pd.Series, pd.Series, pd.Series]:
        """Run the convergence criteria."""
        comparisons = self.make_comparisons(metrics)
        return self.combine_and_check_strata_and_targets(comparisons)


class TargetsConfigBaseSpec(BaseModel):
    """The base targets config spec."""

    normalization: (
        Literal[
            "min-max",
            "standard",
        ]
        | None
    ) = Field(default="min-max", description="The normalization method to use.")


class TargetsConfigColumnSpec(TargetsConfigBaseSpec):
    """The targets config spec."""

    columns: list[str] = Field(
        default_factory=list, description="The columns to use as targets."
    )


class TargetsConfigGlobSpec(TargetsConfigBaseSpec):
    """The targets config spec."""

    globs: list[str] = Field(
        default_factory=list, description="The columns to use as targets."
    )


TargetsConfigSpec = TargetsConfigColumnSpec | TargetsConfigGlobSpec


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
    cat_encoding: Literal["index", "one-hot"] = Field(
        default="index",
        description="The encoding method to use for categorical columns.",
    )
    cont_encoding: Literal["min-max", "standard"] | None = Field(
        default=None,
        description=(
            "The encoding method to use for continuous columns. "
            "Use 'standard' for standardization."
        ),
    )


class RegressionIOConfigSpec(BaseModel):
    """The input/output spec for a regression model."""

    targets: TargetsConfigSpec = Field(
        default_factory=TargetsConfigColumnSpec, description="The targets config spec."
    )
    features: FeatureConfigSpec = Field(
        default_factory=FeatureConfigSpec,
        description="The features config spec.",
    )


class ProgressiveTrainingSpec(ExperimentInputSpec, SerializableRunnable):
    """A spec for iteratively training an SBEM regression model."""

    base_run_name: str = Field(
        ...,
        description="The base run name for the experiment.",
    )
    convergence_criteria: ConvergenceThresholdsByTarget = Field(
        default_factory=ConvergenceThresholdsByTarget,
        description="The convergence criteria.",
    )
    regression_io_config: RegressionIOConfigSpec = Field(
        default_factory=RegressionIOConfigSpec,
        description="The regression io config spec.",
    )
    ml_backend: MLBackend = Field(
        default_factory=XGBBackend,
        description="The ml backend for the model.",
        discriminator="ml_backend",
    )
    stratification: StratificationSpec = Field(
        default_factory=StratificationSpec,
        description="The stratification spec.",
    )
    samplers: Priors = Field(
        ...,
        description="The sampling spec.",
    )
    cross_val: CrossValidationSpec = Field(
        default_factory=CrossValidationSpec,
        description="The cross validation spec.",
    )
    iteration: IterationSpec = Field(
        default_factory=IterationSpec,
        description="The iteration spec.",
    )
    context: OptionalFileReference = Field(
        default=None,
        description="The uri of the gis data to train on.",
    )
    data_uris: ScatterGatherResult | None = Field(
        default=None,
        description="The uri of the previous simulation results to train on.",
    )
    metrics_uris: list[ScatterGatherResult] = Field(
        default_factory=list,
        description="The uris of the iteration metrics from previous iterations.",
    )
    previous_experiment_ids: list[str] = Field(
        default_factory=list,
        description="The ids of the previous experiments.",
    )

    def format_combined_output_key(self, key: str) -> str:
        """Format the output key for a combined result file."""
        return f"{self.prefix}/combined/data/{key}.parquet"

    def format_combined_output_uri(self, key: str) -> S3Url:
        """Format the output uri for a combined result file."""
        if self.storage_settings is None:
            msg = "Storage settings are not set, so we can't construct a combined output uri."
            raise ValueError(msg)
        return S3Url(
            f"s3://{self.storage_settings.BUCKET}/{self.format_combined_output_key(key)}"
        )

    def format_metrics_output_key(self, key: str) -> str:
        """Format the output key for a metrics file."""
        return f"{self.prefix}/combined/metrics/{key}.parquet"

    def format_metrics_output_uri(self, key: str) -> S3Url:
        """Format the output uri for a metrics file."""
        if self.storage_settings is None:
            msg = "Storage settings are not set, so we can't construct a metrics output uri."
            raise ValueError(msg)
        return S3Url(
            f"s3://{self.storage_settings.BUCKET}/{self.format_metrics_output_key(key)}"
        )

    def format_summary_manifest_key(self) -> str:
        """Format the output key for a summary manifest file."""
        return f"{self.prefix}/summary.yml"

    def format_summary_manifest_uri(self) -> S3Url:
        """Format the output uri for a summary manifest file."""
        if self.storage_settings is None:
            msg = "Storage settings are not set, so we can't construct a summary manifest uri."
            raise ValueError(msg)
        return S3Url(
            f"s3://{self.storage_settings.BUCKET}/{self.format_summary_manifest_key()}"
        )

    def subrun_name(self, subrun: Literal["sample", "train"]) -> str:
        """Format the run name for a subrun."""
        return f"{self.experiment_id}/{subrun}"

    @property
    def context_path(self) -> Path | None:
        """The path to the gis data."""
        if self.context is None:
            return None
        if isinstance(self.context, Path):
            return self.context
        return self.fetch_uri(self.context)

    @cached_property
    def context_data(self) -> pd.DataFrame | None:
        """Load the gis data."""
        if self.context_path is None:
            return None
        return pd.read_parquet(self.context_path)

    @property
    def current_version(self) -> SemVer:
        """The current version."""
        vstr = [
            piece for piece in self.experiment_id.split("/") if piece.startswith("v")
        ][-1]
        return SemVer.FromString(vstr)


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
