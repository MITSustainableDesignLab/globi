"""Pydantic models for the visualization system."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class DataSourceType(str, Enum):
    """Type of data source."""

    LOCAL = "local"
    S3 = "s3"


class LocalDataSourceConfig(BaseModel):
    """Configuration for local data source."""

    source_type: Literal["local"] = "local"
    base_dir: Path = Field(
        default=Path("outputs"),
        description="Base directory for local output files.",
    )
    buildings_path: Path | None = Field(
        default=None,
        description="Path to buildings.parquet for geo data. Defaults to inputs/buildings.parquet.",
    )


class S3DataSourceConfig(BaseModel):
    """Configuration for S3 data source."""

    source_type: Literal["s3"] = "s3"
    run_name: str = Field(
        ...,
        description="The experiment run name in S3.",
    )
    version: str | None = Field(
        default=None,
        description="Specific version to load. If None, uses latest.",
    )
    dataframe_key: str = Field(
        default="Results",
        description="The dataframe key to load from S3.",
    )
    cache_dir: Path = Field(
        default=Path("outputs"),
        description="Local directory to cache downloaded files.",
    )


DataSourceConfig = LocalDataSourceConfig | S3DataSourceConfig


class BuildingMetric(str, Enum):
    """Available metrics for 3D building visualization."""

    ENERGY_USAGE = "energy_usage"
    PEAK_POWER = "peak_power"
    PERCENT_CHANGE = "percent_change"
    EUI = "eui"
    CUSTOM = "custom"


class PydeckViewConfig(BaseModel):
    """Configuration for pydeck view state."""

    zoom: float = Field(default=12.0, ge=0, le=22)
    pitch: float = Field(default=50.0, ge=0, le=85)
    bearing: float = Field(default=0.0, ge=-180, le=180)


class Building3DConfig(BaseModel):
    """Configuration for 3D building visualization."""

    metric: BuildingMetric = Field(
        default=BuildingMetric.EUI,
        description="Metric to use for building height/color.",
    )
    custom_column: str | None = Field(
        default=None,
        description="Custom column name when metric is CUSTOM.",
    )
    elevation_scale: float = Field(
        default=10.0,
        ge=1,
        le=100,
        description="Scale factor for elevation.",
    )
    radius: float = Field(
        default=8.0,
        ge=1,
        le=50,
        description="Radius for column layer.",
    )
    fill_color: tuple[int, int, int, int] = Field(
        default=(32, 99, 210, 190),
        description="RGBA fill color for buildings.",
    )
    view: PydeckViewConfig = Field(
        default_factory=PydeckViewConfig,
        description="View state configuration.",
    )


class UseCaseType(str, Enum):
    """Available use case types."""

    RETROFIT = "retrofit"
    OVERHEATING = "overheating"
    SCENARIO_COMPARISON = "scenario_comparison"


class RetrofitUseCaseConfig(BaseModel):
    """Configuration for retrofit analysis use case."""

    use_case_type: Literal["retrofit"] = "retrofit"
    baseline_scenario: str = Field(..., description="Baseline scenario name.")
    retrofit_scenario: str = Field(..., description="Retrofit scenario name.")
    metrics: list[BuildingMetric] = Field(
        default=[BuildingMetric.ENERGY_USAGE, BuildingMetric.PERCENT_CHANGE],
        description="Metrics to display.",
    )


class OverheatingUseCaseConfig(BaseModel):
    """Configuration for overheating analysis use case."""

    use_case_type: Literal["overheating"] = "overheating"
    threshold_hours: int = Field(
        default=200,
        ge=0,
        description="Hours above threshold to flag overheating.",
    )
    temperature_threshold: float = Field(
        default=26.0,
        description="Temperature threshold in Celsius.",
    )


class ScenarioComparisonConfig(BaseModel):
    """Configuration for comparing two scenarios."""

    use_case_type: Literal["scenario_comparison"] = "scenario_comparison"
    baseline_run: str = Field(..., description="Baseline scenario run name.")
    comparison_run: str = Field(..., description="Comparison scenario run name.")
    metric: BuildingMetric = Field(
        default=BuildingMetric.PERCENT_CHANGE,
        description="Metric to compute for comparison.",
    )


UseCaseConfig = (
    RetrofitUseCaseConfig | OverheatingUseCaseConfig | ScenarioComparisonConfig
)
