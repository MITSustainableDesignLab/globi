"""Configuration models for the GloBI project."""

from pathlib import Path
from typing import Annotated, Literal

from epinterface.sbem.builder import AvailableHourlyVariables
from pydantic import BeforeValidator, Field

from globi.models.base import BaseConfig
from globi.type_utils import BasementAtticOccupationConditioningStatus


class HourlyDataConfig(BaseConfig):
    """Configuration for hourly data."""

    data: tuple[AvailableHourlyVariables, ...] = Field(
        default=(),
        description="The hourly data to report.",
    )

    output_mode: Literal[
        "dataframes-and-filerefs", "fileref-only", "dataframes-only"
    ] = Field(
        default="dataframes-and-filerefs",
        description="The mode to output the hourly data.",
    )

    @property
    def does_file_output(self) -> bool:
        """Whether the hourly data output is a file."""
        return self.output_mode in ["dataframes-and-filerefs", "fileref-only"]

    @property
    def does_dataframe_output(self) -> bool:
        """Whether the hourly data output is a dataframe."""
        return self.output_mode in ["dataframes-and-filerefs", "dataframes-only"]


class DeterministicGISPreprocessorConfig(BaseConfig):
    """Configuration for the GIS preprocessor."""

    # TODO: design decision - Separated out this config since this would be for deterministic elements primarily

    cart_crs: str = Field(
        default="EPSG:3857",
        description="The cartesian CRS to project to.",
    )
    min_building_area: float = Field(
        default=10.0,
        ge=1,
        le=1000,
        description="The minimum area of a building to be included [m^2].",
    )
    min_edge_length: float = Field(
        default=3.0,
        ge=1,
        le=2000,
        description="The minimum edge length of a building to be included [m].",
    )
    max_edge_length: float = Field(
        default=1000.0,
        ge=1,
        le=2000,
        description="The maximum edge length of a building to be included [m].",
    )
    neighbor_threshold: float = Field(
        default=100.0,
        ge=0,
        description="The distance threshold for neighbors [m].",
    )
    f2f_height: float = Field(
        default=3.0,
        ge=2,
        le=5,
        description="The floor-to-floor height [m].",
    )
    min_building_height: float = Field(
        default=3,
        ge=1,
        le=500,
        description="The minimum building height [m].",
    )
    max_building_height: float = Field(
        default=300,
        ge=1,
        le=500,
        description="The maximum building height [m].",
    )
    min_num_floors: int = Field(
        default=1,
        ge=1,
        le=150,
        description="The minimum number of floors.",
    )
    max_num_floors: int = Field(
        default=125,
        ge=1,
        le=150,
        description="The maximum number of floors.",
    )

    default_wwr: float = Field(
        default=0.2,
        ge=0,
        le=1,
        description="The default window-to-wall ratio.",
    )
    default_num_floors: int = Field(
        default=2,
        ge=1,
        description="The default number of floors.",
    )
    default_basement: BasementAtticOccupationConditioningStatus = Field(
        default_factory=lambda: "none", description="The default basement type."
    )
    default_attic: BasementAtticOccupationConditioningStatus = Field(
        default_factory=lambda: "none", description="The default attic type."
    )
    default_exposed_basement_frac: float = Field(
        default=0.25,
        ge=0,
        le=1,
        description="The default exposed basement fraction.",
    )
    epw_query: str | None = Field(
        default_factory=lambda: "source in ['tmyx']",
        description="The EPW query filter for closest_epw.",
    )


class GISPreprocessorColumnMap(BaseConfig):
    """Output for the GIS preprocessor column names."""

    DB_File_col: str
    Semantic_Fields_File_col: str
    Component_Map_File_col: str
    EPWZip_File_col: str
    Semantic_Field_Context_col: str
    Neighbor_Polys_col: str
    Neighbor_Heights_col: str
    Neighbor_Floors_col: str
    Rotated_Rectangle_col: str
    Long_Edge_Angle_col: str
    Long_Edge_col: str
    Short_Edge_col: str
    Aspect_Ratio_col: str
    Rotated_Rectangle_Area_Ratio_col: str
    WWR_col: str
    Height_col: str
    Num_Floors_col: str
    F2F_Height_col: str
    Basement_col: str
    Attic_col: str
    Exposed_Basement_Frac_col: str


class FileConfig(BaseConfig):
    """Configuration for files."""

    gis_file: Path = Field(..., description="The path to the local GIS file.")
    db_file: Path  # these could be file refs?
    semantic_fields_file: Path  # these could be file refs?
    epwzip_file: (
        Path | str | None
    )  # TODO: our gis to model conversion should handle EPW identification; see gis job submission in epengine
    component_map_file: Path


ReferencedHourlyDataConfig = Annotated[
    HourlyDataConfig, BeforeValidator(HourlyDataConfig.from_)
]
ReferencedFileConfig = Annotated[FileConfig, BeforeValidator(FileConfig.from_)]
ReferencedGISPreprocessorConfig = Annotated[
    DeterministicGISPreprocessorConfig,
    BeforeValidator(DeterministicGISPreprocessorConfig.from_),
]


class GloBIExperimentSpec(BaseConfig):
    """Specification for a Globi experiment."""

    name: str = Field(..., description="The name of the experiment.")
    scenario: str = Field(..., description="The scenario identifier.")
    hourly_data_config: ReferencedHourlyDataConfig | None = Field(
        default=None,
        description="The configuration for the hourly data.",
    )
    file_config: ReferencedFileConfig = Field(
        ..., description="The configuration for the files."
    )
    gis_preprocessor_config: ReferencedGISPreprocessorConfig = Field(
        default_factory=DeterministicGISPreprocessorConfig,
        description="The configuration for the GIS preprocessor.",
    )
