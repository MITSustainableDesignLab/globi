"""Experiment configuration for building builder simulations."""

import logging
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import yaml
from epinterface.geometry import (
    SceneContext,
    ShoeboxGeometry,
)
from epinterface.sbem.builder import (
    AtticAssumptions,
    BasementAssumptions,
    Model,
    construct_zone_def,
)
from scythe.registry import ExperimentRegistry
from scythe.utils.filesys import FileReference
from shapely import Polygon, from_wkt

from globi.models.tasks import GloBIBuildingSpec, GloBIOutputSpec

logger = logging.getLogger(__name__)


INDEX_COLS_TO_KEEP: list[str] = [
    "feature.geometry.long_edge",
    "feature.geometry.short_edge",
    "feature.geometry.orientation",
    "feature.geometry.num_floors",
    "feature.geometry.energy_model_conditioned_area",
    "feature.geometry.energy_model_occupied_area",
    "feature.semantic.Typology",
    "feature.semantic.Age_bracket",
    "feature.semantic.Region",
    "feature.weather.file",
    "feature.geometry.wwr",
    "feature.geometry.f2f_height",
    "feature.geometry.attic_height",
]


def simulate_globi_building_pipeline(
    input_spec: GloBIBuildingSpec,
    tempdir: Path,
) -> GloBIOutputSpec:
    """Simulate a GlobiSpec building and return energy and peak results.

    Args:
        input_spec: The input specification containing building parameters and file URIs
        tempdir: Temporary directory for intermediate files
    Returns:
        Output specification containing a DataFrame with MultiIndex:
        - Top level: Measurement type (Energy, Peak)
        - Feature levels from input specification
    """
    spec = input_spec
    log = logger.info
    zone_def = construct_zone_def(
        component_map_path=spec.component_map,
        db_path=spec.db_path,
        semantic_field_context=spec.semantic_field_context,
    )
    model = Model(
        Weather=spec.epwzip_path,
        Zone=zone_def,
        Basement=BasementAssumptions(
            Conditioned=spec.basement_is_conditioned,
            UseFraction=spec.basement_use_fraction_computed
            if spec.basement_is_occupied
            else None,
        ),
        Attic=AtticAssumptions(
            Conditioned=spec.attic_is_conditioned,
            UseFraction=spec.attic_use_fraction_computed
            if spec.attic_is_occupied
            else None,
        ),
        geometry=ShoeboxGeometry(
            x=0,
            y=0,
            w=spec.long_edge,
            d=spec.short_edge,
            h=spec.f2f_height,
            wwr=spec.wwr,
            num_stories=spec.num_floors,
            basement=spec.has_basement,
            zoning=spec.use_core_perim_zoning,
            roof_height=spec.attic_height_computed,
            exposed_basement_frac=spec.exposed_basement_frac,
            scene_context=SceneContext(
                building=cast(Polygon, from_wkt(spec.rotated_rectangle)),
                neighbors=[
                    cast(Polygon, from_wkt(poly)) for poly in spec.neighbor_polys
                ],
                neighbor_heights=[
                    float(h) if h is not None else 0 for h in spec.neighbor_heights
                ],
                orientation=spec.long_edge_angle,
            ),
        ),
    )

    log("Building and running model...")
    overheating_config = (
        spec.parent_experiment_spec.overheating_config
        if spec.parent_experiment_spec
        else None
    )
    run_result = model.run(
        eplus_parent_dir=tempdir,
        overheating_config=overheating_config,
    )
    # Validate conditioned area
    if not np.allclose(
        model.total_conditioned_area, spec.energy_model_conditioned_area
    ):
        msg = (
            f"Total conditioned area mismatch: "
            f"{model.total_conditioned_area} != {spec.energy_model_conditioned_area}"
        )
        raise ValueError(msg)

    # Results Post-processing
    # TODO: consider if we actually want all t he columns we are including.
    feature_index = spec.make_multiindex(
        n_rows=1, additional_index_data=spec.feature_dict
    )
    results = run_result.energy_and_peak.to_frame().T.set_index(feature_index)

    energy = results["Energy"]
    energy_annual = (
        energy.T.groupby(
            level=[level for level in energy.columns.names if level != "Month"]
        )
        .sum()
        .T
    )
    peak = results["Peak"]
    peak_annual = (
        peak.T.groupby(
            level=[level for level in peak.columns.names if level != "Month"]
        )
        .max()
        .T
    )
    EnergyAndPeakAnnual = cast(
        pd.DataFrame,
        pd.concat(
            [energy_annual, peak_annual],
            axis=1,
            keys=["Energy", "Peak"],
            names=results.columns.names[:-1],
        ),
    )

    dfs: dict[str, pd.DataFrame] = {
        "EnergyAndPeak": results,
        "EnergyAndPeakAnnual": EnergyAndPeakAnnual,
    }
    if run_result.overheating_results is not None:
        # TODO: add feature dict to overheating df indices? Or instead of a full feature df, just add a single column with the building id?
        edh = run_result.overheating_results.edh
        old_ix = edh.index
        feature_index = spec.make_multiindex(
            n_rows=len(edh), include_sort_subindex=False
        )
        edh.index = feature_index
        edh = edh.set_index(old_ix, append=True)
        dfs["ExceedanceDegreeHours"] = edh

        basic_oh = run_result.overheating_results.basic_oh
        old_ix = basic_oh.index
        feature_index = spec.make_multiindex(
            n_rows=len(basic_oh), include_sort_subindex=False
        )
        basic_oh.index = feature_index
        basic_oh = basic_oh.set_index(old_ix, append=True)
        dfs["BasicOverheating"] = basic_oh

        heat_index_categories = run_result.overheating_results.hi
        old_ix = heat_index_categories.index
        feature_index = spec.make_multiindex(
            n_rows=len(heat_index_categories), include_sort_subindex=False
        )
        heat_index_categories.index = feature_index
        heat_index_categories = heat_index_categories.set_index(old_ix, append=True)
        dfs["HeatIndexCategories"] = heat_index_categories

        consecutive_e_zone = run_result.overheating_results.consecutive_e_zone
        # may be zero if no streaks found in any zones
        if len(consecutive_e_zone) > 0:
            old_ix = consecutive_e_zone.index
            feature_index = spec.make_multiindex(
                n_rows=len(consecutive_e_zone), include_sort_subindex=False
            )
            consecutive_e_zone.index = feature_index
            consecutive_e_zone = consecutive_e_zone.set_index(old_ix, append=True)
            dfs["ConsecutiveExceedances"] = consecutive_e_zone

    hourly_data_outpath: FileReference | None = None

    if spec.parent_experiment_spec and spec.parent_experiment_spec.hourly_data_config:
        hourly_df = run_result.sql.timeseries_by_name(
            spec.parent_experiment_spec.hourly_data_config.data,
            reporting_frequency="Hourly",
        )
        hourly_df.index.names = ["Timestep"]
        hourly_df.columns.names = ["Trash", "Group", "Meter"]
        hourly_df: pd.DataFrame = cast(
            pd.DataFrame,
            hourly_df.droplevel("Trash", axis=1)
            .stack(level="Group", future_stack=True)
            .unstack(level="Timestep"),
        )
        hourly_multiindex = spec.make_multiindex(
            n_rows=len(hourly_df), include_sort_subindex=False
        )
        old_ix = hourly_df.index
        hourly_df.index = hourly_multiindex
        hourly_df = hourly_df.set_index(old_ix, append=True)

        if spec.parent_experiment_spec.hourly_data_config.does_dataframe_output:
            for meter_name in hourly_df.columns.get_level_values("Meter").unique():
                variable_df = hourly_df.xs(meter_name, level="Meter", axis=1)
                dataframe_key = f"HourlyData.{meter_name.replace(' ', '')}"
                dfs[dataframe_key] = variable_df
        if spec.parent_experiment_spec.hourly_data_config.does_file_output:
            hourly_data_outpath = tempdir / "outputs_hourly_data.pq"
            hourly_df.to_parquet(hourly_data_outpath)

    return GloBIOutputSpec(
        dataframes=dfs,
        hourly_data=hourly_data_outpath,
    )


@ExperimentRegistry.Register(retries=2, schedule_timeout="10h", execution_timeout="30m")
def simulate_globi_building(
    input_spec: GloBIBuildingSpec, tempdir: Path
) -> GloBIOutputSpec:
    """Simulate a GlobiSpec building and return monthly energy and peak results.

    NB: this is separated from the pipeline above so the pipeline can still be used as a
    local invocation without *too* much difficulty.
    """
    return simulate_globi_building_pipeline(input_spec, tempdir)


if __name__ == "__main__":
    import tempfile

    from globi.models.tasks import MinimalBuildingSpec

    with tempfile.TemporaryDirectory() as tempdir:
        with open("inputs/building.yml") as f:
            input_spec = MinimalBuildingSpec.model_validate(yaml.safe_load(f))
        o = simulate_globi_building_pipeline(
            input_spec=input_spec.globi_spec,
            tempdir=Path(tempdir),
        )
