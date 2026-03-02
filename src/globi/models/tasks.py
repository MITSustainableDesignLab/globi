"""Task models for the GloBI project."""

import logging
from functools import cached_property
from pathlib import Path
from typing import Literal

import numpy as np
from epinterface.geometry import compute_shading_mask
from pydantic import BaseModel, Field, model_validator
from scythe.base import ExperimentInputSpec, ExperimentOutputSpec
from scythe.utils.filesys import FileReference

from globi.models.configs import GloBIExperimentSpec
from globi.type_utils import (
    BasementAtticOccupationConditioningStatus,
    ConditionedOptions,
    OccupiedOptions,
)

logger = logging.getLogger(__name__)


class MinimalBuildingSpec(BaseModel):
    """A spec for running an EnergyPlus simulation for any region."""

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
    length: float = Field(
        default=15.0,
        description="The length of the long edge of the building [m].",
        ge=3,
    )
    width: float = Field(
        default=15.0,
        description="The length of the short edge of the building [m].",
        ge=3,
    )
    num_floors: int = Field(
        default=2,
        description="The number of floors in the building.",
        ge=1,
    )
    f2f_height: float = Field(
        default=3.0,
        description="The floor-to-floor height of the building [m].",
        ge=0,
    )
    wwr: float = Field(
        default=0.2,
        description="The window-to-wall ratio of the building [unitless].",
        ge=0,
        le=1,
    )
    basement: BasementAtticOccupationConditioningStatus = Field(
        default="none",
        description="The type of basement in the building.",
    )
    attic: BasementAtticOccupationConditioningStatus = Field(
        default="none",
        description="The type of attic in the building.",
    )
    exposed_basement_frac: float = Field(
        default=0.25,
        description="The fraction of the basement that is exposed to the air.",
        ge=0,
        le=1,
    )

    @model_validator(mode="after")
    def order_length_width(self):
        """Order the length and width of the building."""
        if self.length < self.width:
            self.length, self.width = self.width, self.length
        return self

    @property
    def globi_spec(self) -> "GloBIBuildingSpec":
        """Convert the MinimalBuildingSpec to a GloBIBuildingSpec."""
        return GloBIBuildingSpec(
            building_id="placeholder",
            db_file=self.db_file,
            semantic_fields_file=self.semantic_fields_file,
            component_map_file=self.component_map_file,
            epwzip_file=self.epwzip_file,
            semantic_field_context=self.semantic_field_context,
            neighbor_polys=[],
            neighbor_heights=[],
            neighbor_floors=[],
            rotated_rectangle=f"Polygon ((0 0, {self.length} 0, {self.length} {self.width}, 0 {self.width}, 0 0))",
            long_edge_angle=0,
            long_edge=self.length,
            short_edge=self.width,
            aspect_ratio=self.length / self.width,
            wwr=self.wwr,
            num_floors=self.num_floors,
            f2f_height=self.f2f_height,
            height=self.num_floors * self.f2f_height,
            basement=self.basement,
            attic=self.attic,
            exposed_basement_frac=self.exposed_basement_frac,
            rotated_rectangle_area_ratio=1,
            experiment_id="MinimalBuildingSpec",
            sort_index=0,
        )


class GloBIBuildingSpec(ExperimentInputSpec):
    """A spec for running an EnergyPlus simulation for any region."""

    # TODO: update the nullability
    building_id: str = Field(..., description="The id of the building.")
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
