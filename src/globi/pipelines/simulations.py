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


def simulate_globi_building_pipeline(  # noqa: C901
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
            UseFraction=spec.basement_use_fraction
            if spec.basement_is_occupied
            else None,
        ),
        Attic=AtticAssumptions(
            Conditioned=spec.attic_is_conditioned,
            UseFraction=spec.attic_use_fraction if spec.attic_is_occupied else None,
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
            perim_depth=spec.perim_depth,
            zoning=spec.geometry_zoning,
            roof_height=spec.attic_height or None,
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

    single_zone_mode = spec.zoning == "one"
    if single_zone_mode:
        model = model.convert_to_onezone()

    # if single_zone_mode:
    #     model = Model(
    #         Weather=spec.epwzip_path,
    #         Zone=zone_def,
    #         Basement=BasementAssumptions(
    #             Conditioned=False,
    #             UseFraction=None,
    #         ),
    #         Attic=AtticAssumptions(
    #             Conditioned=False,
    #             UseFraction=None,
    #         ),
    #         geometry=ShoeboxGeometry(
    #             x=0,
    #             y=0,
    #             w=spec.long_edge,
    #             d=spec.short_edge,
    #             h=(
    #                 spec.f2f_height * spec.num_floors
    #                 + (spec.f2f_height if spec.basement_is_conditioned else 0)
    #                 + (spec.f2f_height / 2 if spec.attic_is_conditioned else 0)
    #             ),
    #             wwr=spec.wwr,
    #             num_stories=1,
    #             basement=False,
    #             zoning=spec.geometry_zoning,
    #             roof_height=None,
    #             exposed_basement_frac=0,
    #             scene_context=SceneContext(
    #                 building=cast(Polygon, from_wkt(spec.rotated_rectangle)),
    #                 neighbors=[
    #                     cast(Polygon, from_wkt(poly)) for poly in spec.neighbor_polys
    #                 ],
    #                 neighbor_heights=[
    #                     float(h) if h is not None else 0 for h in spec.neighbor_heights
    #                 ],
    #                 orientation=spec.long_edge_angle,
    #             ),
    #         ),
    #     )

    #     old_pd = model.Zone.Operations.SpaceUse.Occupancy.PeopleDensity
    #     old_epd = model.Zone.Operations.SpaceUse.Equipment.PowerDensity
    #     old_lpd = model.Zone.Operations.SpaceUse.Lighting.PowerDensity
    #     model.Zone.Operations.SpaceUse.Occupancy.PeopleDensity = (
    #         old_pd * spec.num_floors
    #         + old_pd
    #         * ((spec.basement_use_fraction or 0) if spec.basement_is_occupied else 0)
    #         + old_pd * ((spec.attic_use_fraction or 0) if spec.attic_is_occupied else 0)
    #     )
    #     model.Zone.Operations.SpaceUse.Equipment.PowerDensity = (
    #         old_epd * spec.num_floors
    #         + old_epd
    #         * ((spec.basement_use_fraction or 0) if spec.basement_is_occupied else 0)
    #         + old_epd
    #         * ((spec.attic_use_fraction or 0) if spec.attic_is_occupied else 0)
    #     )
    #     model.Zone.Operations.SpaceUse.Lighting.PowerDensity = (
    #         old_lpd * spec.num_floors
    #         + old_lpd
    #         * ((spec.basement_use_fraction or 0) if spec.basement_is_occupied else 0)
    #         + old_lpd
    #         * ((spec.attic_use_fraction or 0) if spec.attic_is_occupied else 0)
    #     )
    #     old_vdot = model.Zone.Operations.HVAC.Ventilation.FreshAirPerFloorArea
    #     model.Zone.Operations.HVAC.Ventilation.FreshAirPerFloorArea = (
    #         old_vdot * spec.num_floors
    #         + (old_vdot if spec.basement_is_conditioned else 0)
    #         + (old_vdot if spec.attic_is_conditioned else 0)
    #     )
    #     # infiltration is area weighted
    #     old_infil = model.Zone.Envelope.Infiltration.AirChangesPerHour
    #     old_infil_attic = model.Zone.Envelope.AtticInfiltration.AirChangesPerHour
    #     old_infil_basement = model.Zone.Envelope.BasementInfiltration.AirChangesPerHour
    #     base_weight = spec.num_floors
    #     attic_weight = 1 if spec.has_attic else 0
    #     basement_weight = 1 if spec.has_basement else 0
    #     total_weight = base_weight + attic_weight + basement_weight
    #     base_weight = base_weight / total_weight
    #     attic_weight = attic_weight / total_weight
    #     basement_weight = basement_weight / total_weight
    #     model.Zone.Envelope.Infiltration.AirChangesPerHour = (
    #         old_infil * base_weight
    #         + old_infil_attic * attic_weight
    #         + old_infil_basement * basement_weight
    #     )
    # else:
    #     model = Model(
    #         Weather=spec.epwzip_path,
    #         Zone=zone_def,
    #         Basement=BasementAssumptions(
    #             Conditioned=spec.basement_is_conditioned,
    #             UseFraction=spec.basement_use_fraction
    #             if spec.basement_is_occupied
    #             else None,
    #         ),
    #         Attic=AtticAssumptions(
    #             Conditioned=spec.attic_is_conditioned,
    #             UseFraction=spec.attic_use_fraction if spec.attic_is_occupied else None,
    #         ),
    #         geometry=ShoeboxGeometry(
    #             x=0,
    #             y=0,
    #             w=spec.long_edge,
    #             d=spec.short_edge,
    #             h=spec.f2f_height,
    #             wwr=spec.wwr,
    #             num_stories=spec.num_floors,
    #             basement=spec.has_basement,
    #             perim_depth=4.57,
    #             zoning=spec.geometry_zoning,
    #             roof_height=spec.attic_height or None,
    #             exposed_basement_frac=spec.exposed_basement_frac,
    #             scene_context=SceneContext(
    #                 building=cast(Polygon, from_wkt(spec.rotated_rectangle)),
    #                 neighbors=[
    #                     cast(Polygon, from_wkt(poly)) for poly in spec.neighbor_polys
    #                 ],
    #                 neighbor_heights=[
    #                     float(h) if h is not None else 0 for h in spec.neighbor_heights
    #                 ],
    #                 orientation=spec.long_edge_angle,
    #             ),
    #         ),
    #     )

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
    if (
        not np.allclose(
            model.total_conditioned_area, spec.energy_model_conditioned_area
        )
        and not single_zone_mode
    ):
        msg = (
            f"Total conditioned area mismatch: "
            f"{model.total_conditioned_area} != {spec.energy_model_conditioned_area}"
        )
        raise ValueError(msg)
    if (
        not np.allclose(model.total_conditioned_area, spec.energy_model_footprint_area)
        and single_zone_mode
    ):
        msg = (
            f"Total conditioned area mismatch: "
            f"{model.total_conditioned_area} != {spec.energy_model_footprint_area}"
        )
        raise ValueError(msg)

    # Results Post-processing
    # TODO: consider if we actually want all t he columns we are including.
    feature_index = spec.make_multiindex(n_rows=1)
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
    if single_zone_mode:
        results = (
            results
            * spec.energy_model_footprint_area
            / spec.energy_model_conditioned_area
        )
        EnergyAndPeakAnnual = (
            EnergyAndPeakAnnual
            * spec.energy_model_footprint_area
            / spec.energy_model_conditioned_area
        )

    dfs: dict[str, pd.DataFrame] = {
        "EnergyAndPeak": results,
        "EnergyAndPeakAnnual": EnergyAndPeakAnnual,
    }
    if run_result.overheating_results is not None:
        if single_zone_mode:
            raise NotImplementedError(
                "Overheating results not supported for single zone mode"
            )
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
