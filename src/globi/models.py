"""A model for an SBEM composed shoebox simulation."""

import logging
import tempfile
from functools import cached_property
from pathlib import Path
from typing import Annotated, Literal, Self, cast

import numpy as np
import yaml
from epinterface.geometry import compute_shading_mask
from epinterface.sbem.components.composer import (
    construct_composer_model,
    construct_graph,
)
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.sbem.prisma.client import PrismaSettings
from pydantic import BaseModel, BeforeValidator, Field
from scythe.base import ExperimentInputSpec, ExperimentOutputSpec
from scythe.utils.filesys import FileReference, fetch_uri

from globi.type_utils import (
    BasementAtticOccupationConditioningStatus,
    ConditionedOptions,
    OccupiedOptions,
)

logger = logging.getLogger(__name__)


AvailableHourlyData = Literal[
    "Zone Mean Air Temperature",
    "Zone Air Relative Humidity",
]


class BaseConfig(BaseModel):
    """A base configuration for a Globi experiment."""

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> Self:
        """Load the base configuration from a manifest file."""
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
        return cls.model_validate(manifest)

    @classmethod
    def from_manifest_fileref(cls, manifest_fileref: FileReference) -> Self:
        """Load the base configuration from a manifest file reference."""
        if isinstance(manifest_fileref, str) and (
            not manifest_fileref.startswith("http://")
            and not manifest_fileref.startswith("https://")
            and not manifest_fileref.startswith("s3://")
        ):
            manifest_fileref = Path(manifest_fileref)
        if isinstance(manifest_fileref, Path):
            local_path = manifest_fileref
        else:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir) / "manifest.yaml"
                local_path = fetch_uri(manifest_fileref, temp_path)
        return cls.from_manifest(local_path)

    @classmethod
    def from_(cls, v: Self | FileReference) -> Self:
        """Load the base configuration from a manifest file reference or a local path."""
        if isinstance(v, BaseConfig | dict):
            return v
        return cls.from_manifest_fileref(v)


class HourlyDataConfig(BaseConfig):
    """Configuration for hourly data."""

    data: tuple[AvailableHourlyData, ...] = Field(
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


class GloBIBuildingSpec(ExperimentInputSpec):
    """A spec for running an EnergyPlus simulation for any region."""

    # TODO: update the nullability
    db_file: FileReference = Field(..., description="The component database file.")
    semantic_fields_file: FileReference = Field(
        ..., description="The semantic fields file."
    )
    component_map_file: FileReference = Field(
        ..., description="The component map file."
    )
    epwzip_file: FileReference = Field(..., description="The EPW weather file.")
    semantic_field_context: dict[str, float | str | int] = Field(
        ...,
        description="The semantic field values which will be used to compile the zone definition.",
    )
    neighbor_polys: list[str] = Field(
        ..., description="The polygons of the neighboring buildings."
    )
    neighbor_heights: list[float | int | None] = Field(
        ..., description="The height of the neighboring buildings  [m]."
    )
    neighbor_floors: list[float | int | None] = Field(
        ..., description="The number of floors of the neighboring buildings."
    )
    rotated_rectangle: str = Field(
        ..., description="The rotated rectangle fitted around the base of the building."
    )
    long_edge_angle: float = Field(
        ..., description="The long edge angle of the building (radians)."
    )
    long_edge: float = Field(
        ..., description="The length of the long edge of the building [m]."
    )
    short_edge: float = Field(
        ..., description="The length of the short edge of the building [m]."
    )
    aspect_ratio: float = Field(
        ..., description="The aspect ratio of the building footprint [unitless]."
    )
    rotated_rectangle_area_ratio: float = Field(
        ...,
        description="The ratio of the rotated rectangle footprint area to the building footprint area.",
    )
    wwr: float = Field(
        ...,
        description="The window-to-wall ratio of the building [unitless].",
        ge=0,
        le=1,
    )
    height: float = Field(..., description="The height of the building [m].", ge=0)
    num_floors: int = Field(
        ..., description="The number of floors in the building.", ge=0
    )
    f2f_height: float = Field(..., description="The floor to floor height [m].", ge=0)
    basement: BasementAtticOccupationConditioningStatus = Field(
        ..., description="The type of basement in the building."
    )
    attic: BasementAtticOccupationConditioningStatus = Field(
        ..., description="The type of attic in the building."
    )
    exposed_basement_frac: float = Field(
        ...,
        description="The fraction of the basement that is exposed to the air.",
        gt=0,
        lt=1,
    )

    parent_experiment_spec: GloBIExperimentSpec | None = Field(
        default=None,
        description="The parent experiment spec.",
    )

    @property
    def feature_dict(self) -> dict[str, str | int | float]:
        """Return a dictionary of features which will be available to ML algos."""
        features: dict[str, str | int | float] = {
            "feature.geometry.long_edge": self.long_edge,
            "feature.geometry.short_edge": self.short_edge,
            "feature.geometry.orientation": self.long_edge_angle,
            "feature.geometry.orientation.cos": np.cos(self.long_edge_angle),
            "feature.geometry.orientation.sin": np.sin(self.long_edge_angle),
            "feature.geometry.aspect_ratio": self.aspect_ratio,
            "feature.geometry.wwr": self.wwr,
            "feature.geometry.num_floors": self.num_floors,
            "feature.geometry.f2f_height": self.f2f_height,
            # "feature.geometry.fp_area": self.fp_area,
            "feature.geometry.zoning": self.use_core_perim_zoning,
            "feature.geometry.energy_model_conditioned_area": self.energy_model_conditioned_area,
            "feature.geometry.energy_model_occupied_area": self.energy_model_occupied_area,
            "feature.geometry.attic_height": self.attic_height or 0,
            "feature.geometry.exposed_basement_frac": self.exposed_basement_frac,
        }

        # TODO: consider passing in
        # neighbors directly to Model.geometry, letting model perform neighbor
        # insertion directly rather than via a callback,
        # and then let shading mask become a computed property of the model.geometry.
        shading_mask = compute_shading_mask(
            self.rotated_rectangle,
            neighbors=self.neighbor_polys,
            neighbor_heights=self.neighbor_heights,
            azimuthal_angle=2 * np.pi / 48,
        )
        shading_mask_values = {
            f"feature.geometry.shading_mask_{i:02d}": val
            for i, val in enumerate(shading_mask.tolist())
        }
        features.update(shading_mask_values)

        # semantic features are kept separately as one building may have
        # multiple simulations with different semantic fields.
        features.update({
            f"feature.semantic.{feature_name}": feature_value
            for feature_name, feature_value in self.semantic_field_context.items()
        })

        features["feature.weather.file"] = self.epwzip_path.stem

        # conditional features are derived from the static and semantic features,
        # and may be subject to things like conditional sampling, estimation etc.
        # e.g. rvalues, uvalues, schedule, etc.
        # additional things like basement/attic config?
        features["feature.extra_spaces.basement.exists"] = (
            "Yes" if self.has_basement else "No"
        )
        features["feature.extra_spaces.basement.occupied"] = (
            "Yes" if self.basement_is_occupied else "No"
        )
        features["feature.extra_spaces.basement.conditioned"] = (
            "Yes" if self.basement_is_conditioned else "No"
        )
        features["feature.extra_spaces.basement.use_fraction"] = (
            self.basement_use_fraction
        )
        features["feature.extra_spaces.attic.exists"] = (
            "Yes" if self.has_attic else "No"
        )
        features["feature.extra_spaces.attic.occupied"] = (
            "Yes" if self.attic_is_occupied else "No"
        )
        features["feature.extra_spaces.attic.conditioned"] = (
            "Yes" if self.attic_is_conditioned else "No"
        )
        features["feature.extra_spaces.attic.use_fraction"] = self.attic_use_fraction

        return features

    # TODO: use the scythe automatic referencing for these paths - FileReference class from scythe.utils.files
    # choose a local file and direclty use the 'Path' for this
    # self scythe - fetch uri
    # input_sepc.weather_file
    # everything gets a tempdir

    #

    @cached_property
    def db_path(self) -> Path:
        """Fetch the db file and return the local path.

        Returns:
            local_path (Path): The local path of the db file
        """
        if isinstance(self.db_file, Path):
            return self.db_file
        return self.fetch_uri(self.db_file)

    @cached_property
    def semantic_fields_path(self) -> Path:
        """Fetch the semantic fields file and return the local path.

        Returns:
            local_path (Path): The local path of the semantic fields file
        """
        if isinstance(self.semantic_fields_file, Path):
            return self.semantic_fields_file
        return self.fetch_uri(self.semantic_fields_file)

    @cached_property
    def epwzip_path(self) -> Path:
        """Fetch the epw file and return the local path.

        Returns:
            local_path (Path): The local path of the epw file
        """
        if isinstance(self.epwzip_file, Path):
            return self.epwzip_file
        return self.fetch_uri(self.epwzip_file)

    @property
    def component_map(self) -> Path:
        """Fetch the component map file and return the local path.

        Returns:
            local_path (Path): The local path of the component map file
        """
        if isinstance(self.component_map_file, Path):
            return self.component_map_file
        return self.fetch_uri(self.component_map_file)

    def construct_zone_def(self) -> ZoneComponent:
        """Construct the zone definition for the simulation.

        Returns:
            zone_def (ZoneComponent): The zone definition for the simulation
        """
        g = construct_graph(ZoneComponent)
        SelectorModel = construct_composer_model(
            g,
            ZoneComponent,
            use_children=False,
        )

        with open(self.component_map) as f:
            component_map_yaml = yaml.safe_load(f)
        selector = SelectorModel.model_validate(component_map_yaml)

        # Log the database path being used for debugging
        import os
        from datetime import datetime

        if self.db_path.exists():
            mtime = os.path.getmtime(self.db_path)
            mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(
                f"Loading database: {self.db_path} "
                f"(modified: {mtime_str}, size: {self.db_path.stat().st_size} bytes)"
            )
        else:
            logger.error(f"Database file not found: {self.db_path}")

        # Force a fresh database connection by creating a new PrismaSettings instance
        # This ensures we always reload the database, avoiding any caching issues.
        # Each call to construct_zone_def() creates a new PrismaSettings instance,
        # which should force SQLite to open a fresh connection and see any file updates.
        settings = PrismaSettings.New(
            database_path=self.db_path, if_exists="ignore", auto_register=False
        )
        db = settings.db

        # Use context manager to ensure connection is properly closed after use.
        # This ensures SQLite releases file locks and any future reads will see
        # updated database content.
        context = self.semantic_field_context
        with db:
            zone = cast(ZoneComponent, selector.get_component(context=context, db=db))
        # Connection is now closed, ensuring any future reads will see updated data
        return zone

    @property
    def use_core_perim_zoning(self) -> Literal["by_storey", "core/perim"]:
        """Whether to use the core perimeter for the simulation."""
        use_core_perim = self.long_edge > 15 and self.short_edge > 15
        return "core/perim" if use_core_perim else "by_storey"

    @property
    def basement_is_occupied(self) -> bool:
        """Whether the basement is occupied."""
        return self.basement in OccupiedOptions

    @property
    def attic_is_occupied(self) -> bool:
        """Whether the attic is occupied."""
        return self.attic in OccupiedOptions

    @property
    def basement_is_conditioned(self) -> bool:
        """Whether the basement is conditioned."""
        return self.basement in ConditionedOptions

    @property
    def attic_is_conditioned(self) -> bool:
        """Whether the attic is conditioned."""
        return self.attic in ConditionedOptions

    @cached_property
    def basement_use_fraction(self) -> float:
        """The use fraction of the basement."""
        if not self.basement_is_occupied:
            return 0
        return np.random.uniform(0.2, 0.6)

    @cached_property
    def attic_use_fraction(self) -> float:
        """The use fraction of the attic."""
        if not self.attic_is_occupied:
            return 0
        # TODO: use sampling as a fallback value when a default is not provided rather
        # than always sampling.
        return np.random.uniform(0.2, 0.6)

    @cached_property
    def has_basement(self) -> bool:
        """Whether the building has a basement."""
        return self.basement != "none"

    @cached_property
    def has_attic(self) -> bool:
        """Whether the building has an attic."""
        return self.attic != "none"

    @cached_property
    def attic_height(self) -> float | None:
        """The height of the attic."""
        if not self.has_attic:
            return None
        min_occupied_or_conditioned_rise_over_run = 6 / 12
        max_occupied_or_conditioned_rise_over_run = 9 / 12
        min_unoccupied_and_unconditioned_rise_over_run = 4 / 12
        max_unoccupied_and_unconditioned_rise_over_run = 6 / 12

        run = self.short_edge / 2
        attic_height = None
        attempts = 20
        while attic_height is None and attempts > 0:
            if self.attic_is_occupied or self.attic_is_conditioned:
                attic_height = run * np.random.uniform(
                    min_occupied_or_conditioned_rise_over_run,
                    max_occupied_or_conditioned_rise_over_run,
                )
            else:
                attic_height = run * np.random.uniform(
                    min_unoccupied_and_unconditioned_rise_over_run,
                    max_unoccupied_and_unconditioned_rise_over_run,
                )
            if attic_height > self.f2f_height * 2.5:
                attic_height = None
            attempts -= 1
        if attic_height is None:
            msg = "Failed to sample valid attic height (must be less than 2.5x f2f height)."
            raise ValueError(msg)
        return attic_height

    @property
    def n_conditioned_floors(self) -> int:
        """The number of conditioned floors in the building."""
        n_floors = self.num_floors
        if self.basement_is_conditioned:
            n_floors += 1
        if self.attic_is_conditioned:
            n_floors += 1
        return n_floors

    @property
    def n_occupied_floors(self) -> int:
        """The number of occupied floors in the building."""
        n_floors = self.num_floors
        if self.basement_is_occupied:
            n_floors += 1
        if self.attic_is_occupied:
            n_floors += 1
        return n_floors

    @property
    def energy_model_footprint_area(self) -> float:
        """The floor area of the building."""
        return self.long_edge * self.short_edge

    @property
    def energy_model_conditioned_area(self) -> float:
        """The conditioned area of the building."""
        return self.n_conditioned_floors * self.energy_model_footprint_area

    @property
    def energy_model_occupied_area(self) -> float:
        """The conditioned area of the building."""
        return self.n_occupied_floors * self.energy_model_footprint_area


class GloBIOutputSpec(ExperimentOutputSpec):
    """Output for the building builder experiment."""

    hourly_data: FileReference | None = None
