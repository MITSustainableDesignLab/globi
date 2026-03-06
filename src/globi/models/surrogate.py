"""Surrogate training configuration models.

These models define the configuration for progressive surrogate training,
including convergence thresholds, hyperparameters, cross-validation specs,
and Scythe experiment input/output specs.
"""

from typing import Annotated, Any

import pandas as pd
from pydantic import BaseModel, BeforeValidator, Field
from scythe.base import ExperimentInputSpec, ExperimentOutputSpec
from scythe.utils.filesys import FileReference

from globi.models.base import BaseConfig
from globi.models.configs import ReferencedGISPreprocessorConfig


class Metrics(BaseModel):
    """Metrics for a single training run."""

    mae: float = Field(..., description="Mean absolute error.")
    rmse: float = Field(..., description="Root mean squared error.")
    mape: float = Field(..., description="Mean absolute percentage error.")
    r_squared: float = Field(..., description="R-squared.")
    cvrmse: float = Field(
        ..., description="Coefficient of variation of root mean squared error."
    )
    target: str = Field(..., description="Target column name.")
    fold: int = Field(..., description="Fold index.")

    stratum: str | None = Field(..., description="Stratum name.")


class ConvergenceThresholds(BaseConfig):
    """Thresholds for determining surrogate model convergence."""

    mae: float | None = Field(default=None, description="Max allowable MAE.")
    rmse: float | None = Field(default=None, description="Max allowable RMSE.")
    mape: float | None = Field(default=None, description="Max allowable MAPE.")
    r_squared: float | None = Field(
        default=None, description="Min allowable R-squared."
    )
    cvrmse: float | None = Field(default=None, description="Max allowable CV(RMSE).")

    def check(self, metrics: Metrics) -> bool:
        """Check if metrics meet all specified convergence thresholds.

        Args:
            metrics: Dict with keys matching threshold names and float values.

        Returns:
            True if any specified thresholds are met.
        """
        if self.mae is not None and metrics.mae <= self.mae:
            return True
        if self.rmse is not None and metrics.rmse <= self.rmse:
            return True
        if self.mape is not None and metrics.mape <= self.mape:
            return True
        if self.r_squared is not None and metrics.r_squared >= self.r_squared:
            return True
        passes_cvrmse = self.cvrmse is not None and metrics.cvrmse <= self.cvrmse
        return passes_cvrmse


class TrainingHyperparameters(BaseConfig):
    """LightGBM hyperparameters for surrogate model training."""

    num_leaves: int = Field(default=31, description="Max number of leaves per tree.")
    max_depth: int = Field(default=-1, description="Max tree depth (-1 = no limit).")
    learning_rate: float = Field(default=0.1, description="Boosting learning rate.")
    n_estimators: int = Field(default=100, description="Number of boosting rounds.")
    min_child_samples: int = Field(
        default=20, description="Min samples in a leaf node."
    )
    subsample: float = Field(
        default=1.0, description="Subsample ratio of training data.", ge=0, le=1
    )
    colsample_bytree: float = Field(
        default=1.0, description="Subsample ratio of features.", ge=0, le=1
    )
    reg_alpha: float = Field(default=0.0, description="L1 regularization.", ge=0)
    reg_lambda: float = Field(default=0.0, description="L2 regularization.", ge=0)

    def to_lgb_params(self) -> dict[str, Any]:
        """Convert to LightGBM parameter dict."""
        return {
            "num_leaves": self.num_leaves,
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
            "n_estimators": self.n_estimators,
            "min_child_samples": self.min_child_samples,
            "subsample": self.subsample,
            "colsample_bytree": self.colsample_bytree,
            "reg_alpha": self.reg_alpha,
            "reg_lambda": self.reg_lambda,
            "verbose": -1,
        }


class CrossValidationSpec(BaseConfig):
    """Cross-validation configuration."""

    n_folds: int = Field(default=5, description="Number of CV folds.", ge=2)


class IterationSpec(BaseConfig):
    """Progressive training iteration configuration."""

    n_init: int = Field(
        default=1000, description="Number of samples for the first iteration."
    )
    n_per_iter: int = Field(
        default=500, description="Number of new samples per subsequent iteration."
    )
    max_iters: int = Field(
        default=10, description="Maximum number of training iterations."
    )


ReferencedConvergenceThresholds = Annotated[
    ConvergenceThresholds, BeforeValidator(ConvergenceThresholds.from_)
]
ReferencedTrainingHyperparameters = Annotated[
    TrainingHyperparameters, BeforeValidator(TrainingHyperparameters.from_)
]
ReferencedCrossValidationSpec = Annotated[
    CrossValidationSpec, BeforeValidator(CrossValidationSpec.from_)
]
ReferencedIterationSpec = Annotated[IterationSpec, BeforeValidator(IterationSpec.from_)]


class SurrogateTrainingConfig(BaseConfig):
    """Top-level configuration for progressive surrogate training.

    Can be loaded from a YAML file, S3 URI, or provided inline.
    """

    name: str = Field(
        ...,
        description="Name for this training run. Used as Scythe run_name prefix "
        "(e.g. 'mysurrogate' -> '{name}/simulate', '{name}/train').",
    )
    priors_file: FileReference = Field(
        ..., description="YAML file containing serialized Priors graph."
    )
    gis_file: FileReference = Field(
        ...,
        description="Preprocessed GIS parquet with rotated rectangles and neighbors.",
    )
    gis_preprocessor_config: ReferencedGISPreprocessorConfig | None = Field(
        default=None,
        description="GIS preprocessor config (used if gis_file needs preprocessing).",
    )
    convergence: ReferencedConvergenceThresholds = Field(
        default_factory=ConvergenceThresholds,
        description="Convergence thresholds for training.",
    )
    hyperparameters: ReferencedTrainingHyperparameters = Field(
        default_factory=TrainingHyperparameters,
        description="LightGBM hyperparameters.",
    )
    cv: ReferencedCrossValidationSpec = Field(
        default_factory=CrossValidationSpec,
        description="Cross-validation configuration.",
    )
    iteration: ReferencedIterationSpec = Field(
        default_factory=IterationSpec,
        description="Progressive training iteration configuration.",
    )


ReferencedSurrogateTrainingConfig = Annotated[
    SurrogateTrainingConfig, BeforeValidator(SurrogateTrainingConfig.from_)
]


# --- Scythe Experiment Input/Output Specs ---


class TrainingSimInputSpec(ExperimentInputSpec):
    """Input spec for a single training simulation.

    Contains all FlatModel constructor kwargs plus GIS-derived geometry
    and neighbor information. The explicit width/depth/num_floors/rotation
    fields come from GIS and are used to override whatever the priors
    may have sampled for those FlatModel fields.
    """

    flat_model_params: dict[str, Any] = Field(
        ..., description="All FlatModel constructor kwargs (from priors sampling)."
    )
    epw_uri: FileReference = Field(..., description="EPW weather file URI.")
    width: float = Field(..., description="Building width (long edge) from GIS [m].")
    depth: float = Field(..., description="Building depth (short edge) from GIS [m].")
    num_floors: int = Field(..., description="Number of floors from GIS.")
    rotation: float = Field(..., description="Building rotation from GIS [degrees].")
    rotated_rectangle: str = Field(
        ...,
        description="WKT polygon of the building footprint from GIS "
        "(in real-world coordinates, for neighbor shading).",
    )
    long_edge_angle: float = Field(
        ..., description="Long edge angle from GIS [radians]."
    )
    neighbor_polys: list[str] = Field(
        default_factory=list, description="WKT polygons of neighboring buildings."
    )
    neighbor_heights: list[float | int | None] = Field(
        default_factory=list, description="Heights of neighboring buildings."
    )
    neighbor_floors: list[float | int | None] = Field(
        default_factory=list, description="Floor counts of neighboring buildings."
    )
    weather_file_id: str = Field(
        default="", description="Weather file identifier for stratification."
    )


class TrainingSimOutputSpec(ExperimentOutputSpec):
    """Output spec for a single training simulation.

    Scythe auto-manages the dataframes dict. Will contain:
    - "Features": DataFrame with one row of ML features
    - "EnergyAndPeak": DataFrame with energy and peak results
    """

    pass


class TrainFoldInputSpec(ExperimentInputSpec):
    """Input spec for a single CV fold training."""

    data_uri: FileReference = Field(
        ..., description="S3 URI to combined training data parquet."
    )
    fold_index: int = Field(..., description="Index of this fold.", ge=0)
    n_folds: int = Field(..., description="Total number of folds.", ge=2)
    hyperparameters: TrainingHyperparameters = Field(
        ..., description="LightGBM hyperparameters for this fold."
    )
    feature_columns: list[str] = Field(..., description="Names of feature columns.")
    target_columns: list[str] = Field(..., description="Names of target columns.")
    stratification_column: str = Field(
        default="weather_file_id",
        description="Column to stratify train/test splits by.",
    )


class TrainFoldOutputSpec(ExperimentOutputSpec):
    """Output spec for a single CV fold training.

    Dataframes will contain:
    - "GlobalMetrics": per-target global metrics
    - "StratumMetrics": per-target per-stratum metrics
    """

    pass


def compute_training_metrics(
    y_true: pd.Series,
    y_pred: pd.Series,
    target: str,
    fold: int,
    stratum: str | None = None,
) -> Metrics:
    """Compute standard regression metrics.

    Args:
        y_true: True values.
        y_pred: Predicted values.
        target: Target column name.
        fold: Fold index.
        stratum: Stratum name.

    Returns:
        Metrics object.
    """
    import numpy as np

    residuals = y_true - y_pred
    mae = float(np.mean(np.abs(residuals)))
    rmse = float(np.sqrt(np.mean(residuals**2)))
    mean_true = float(np.mean(y_true))
    mape = float(np.mean(np.abs(residuals / y_true.replace(0, np.nan)).dropna()))
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y_true - mean_true) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    cvrmse = rmse / mean_true if mean_true != 0 else float("inf")

    return Metrics(
        mae=mae,
        rmse=rmse,
        mape=mape,
        r_squared=r_squared,
        cvrmse=cvrmse,
        target=target,
        fold=fold,
        stratum=stratum,
    )
