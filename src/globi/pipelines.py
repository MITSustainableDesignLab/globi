"""Experiment configuration for building builder simulations."""

import logging
import tempfile
from pathlib import Path
from typing import cast

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from archetypal.idfclass import IDF
from epinterface.geometry import (
    ShoeboxGeometry,
    compute_shading_mask,
    match_idf_to_building_and_neighbors,
)
from epinterface.sbem.builder import AtticAssumptions, BasementAssumptions, Model
from epinterface.sbem.fields.spec import SemanticModelFields
from numpy.typing import ArrayLike
from pydantic import HttpUrl
from scythe.registry import ExperimentRegistry
from scythe.utils.filesys import FileReference
from shapely import Point, Polygon, from_wkt

from globi.gis.errors import SemanticFieldsFileHasNoBuildingIDColumnError
from globi.gis.geometry import (
    convert_neighbors,
    inject_neighbor_ixs,
    inject_rotated_rectangles,
)
from globi.gis.utils import (
    add_lat_and_lon_cols,
    check_building_ids,
    check_for_column_existence,
    drop_by_area,
    drop_by_edge_length,
    drop_non_polygons,
    handle_attic,
    handle_basement,
    handle_basement_exposed_fraction,
    handle_epwzip,
    handle_height_and_floors,
    handle_wwr,
    inject_semantic_fields,
    rename_shp_cols,
    reproject_gdf,
    validate_has_rows,
    validate_semantic_field_compatibility,
)
from globi.models import (
    DeterministicGISPreprocessorConfig,
    FileConfig,
    GISPreprocessorColumnMap,
    GloBIBuildingSpec,
    GloBIOutputSpec,
)

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
    zone_def = spec.construct_zone_def()
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
            zoning=spec.use_core_perim_zoning,
            roof_height=spec.attic_height,
            exposed_basement_frac=spec.exposed_basement_frac,
        ),
    )
    # TODO: move this into epinterface.
    azimuthal_angle = 2 * np.pi / 48
    shading_mask = compute_shading_mask(
        spec.rotated_rectangle,
        neighbors=spec.neighbor_polys,
        neighbor_heights=spec.neighbor_heights,
        azimuthal_angle=azimuthal_angle,
    )
    az, p0, p1, h, _w = shading_fence_closed_ring(
        elevations=shading_mask,
        d=100,
    )
    angles = 2 * np.pi * np.arange(len(az)) / len(az)
    p2 = p1 + 2 * np.stack([np.cos(angles), np.sin(angles)], axis=-1)
    p3 = p0 + 2 * np.stack([np.cos(angles), np.sin(angles)], axis=-1)
    rotated_rect_centroid = from_wkt(spec.rotated_rectangle).centroid
    mask_polys = [
        Polygon([
            Point(p0[i] + np.array([rotated_rect_centroid.x, rotated_rect_centroid.y])),
            Point(p1[i] + np.array([rotated_rect_centroid.x, rotated_rect_centroid.y])),
            Point(p2[i] + np.array([rotated_rect_centroid.x, rotated_rect_centroid.y])),
            Point(p3[i] + np.array([rotated_rect_centroid.x, rotated_rect_centroid.y])),
            Point(p0[i] + np.array([rotated_rect_centroid.x, rotated_rect_centroid.y])),
        ])
        for i in range(len(az))
    ]

    def post_geometry_callback(idf: IDF) -> IDF:
        log("Matching IDF to building and neighbors...")
        original_total_building_area = idf.total_building_area
        idf = match_idf_to_building_and_neighbors(
            idf,
            building=spec.rotated_rectangle,
            # neighbor_polys=spec.neighbor_polys,  # pyright: ignore [reportArgumentType]
            # neighbor_floors=spec.neighbor_floors,
            neighbor_polys=mask_polys,  # pyright: ignore [reportArgumentType]
            neighbor_floors=[h[i] // spec.f2f_height for i in range(len(h))],
            neighbor_f2f_height=spec.f2f_height,
            target_short_length=spec.short_edge,
            target_long_length=spec.long_edge,
            rotation_angle=spec.long_edge_angle,
        )
        new_total_building_area = idf.total_building_area
        if not np.isclose(original_total_building_area, new_total_building_area):
            msg = (
                f"Total building area mismatch after matching to building and neighbors: "
                f"{original_total_building_area} != {new_total_building_area}"
            )
            raise ValueError(msg)
        log("IDF matched to building and neighbors.")
        # TODO: possibly consider adding hourly data meter requests to idf here.
        return idf

    log("Building and running model...")
    _idf, results, _err_text, sql, _temp_dir = model.run(
        post_geometry_callback=post_geometry_callback, eplus_parent_dir=tempdir
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
    results = results.to_frame().T.set_index(feature_index)

    dfs: dict[str, pd.DataFrame] = {
        "Results": results,
    }

    hourly_data_outpath: FileReference | None = None

    if spec.parent_experiment_spec and spec.parent_experiment_spec.hourly_data_config:
        hourly_df = sql.timeseries_by_name(
            spec.parent_experiment_spec.hourly_data_config.data,
            reporting_frequency="Hourly",
        )
        hourly_df.index.names = ["Timestep"]
        hourly_df.columns.names = ["Trash", "Zone", "Meter"]
        hourly_df: pd.DataFrame = cast(
            pd.DataFrame,
            hourly_df.droplevel("Trash", axis=1)
            .stack(level="Zone", future_stack=True)
            .unstack(level="Timestep"),
        )
        hourly_multiindex = spec.make_multiindex(
            n_rows=len(hourly_df), include_sort_subindex=False
        )
        old_ix = hourly_df.index
        hourly_df.index = hourly_multiindex
        hourly_df = hourly_df.set_index(old_ix, append=True)

        if spec.parent_experiment_spec.hourly_data_config.does_dataframe_output:
            dfs["HourlyData"] = hourly_df
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
    from globi.models import FileConfig, GloBIExperimentSpec, HourlyDataConfig

    region = "Brazil"
    data_dir = Path(__file__).parent.parent.parent / "data"
    db_path = data_dir / region / "components-lib.db"
    semantic_fields_path = data_dir / region / "semantic-fields.yaml"
    component_map_path = data_dir / region / "component-map.yaml"
    weather_url = "https://climate.onebuilding.org/WMO_Region_3_South_America/BRA_Brazil/SP_Sao_Paulo/BRA_SP_Guaratingueta.AP.837080_TMYx.2009-2023.zip"
    epwzip_file = HttpUrl(weather_url)
    globi_spec = GloBIBuildingSpec(
        experiment_id="brazil-test-experiment",
        db_file=db_path,
        semantic_fields_file=semantic_fields_path,
        component_map_file=component_map_path,
        epwzip_file=epwzip_file,
        long_edge=20,
        short_edge=15,
        long_edge_angle=0,
        aspect_ratio=20 / 15,
        rotated_rectangle_area_ratio=1.0,
        num_floors=3,
        height=3 * 3.0,
        f2f_height=3.0,
        wwr=0.2,
        rotated_rectangle="POLYGON ((0 0, 0 15, 20 15, 20 0, 0 0))",
        neighbor_polys=[],
        neighbor_floors=[],
        neighbor_heights=[],
        semantic_field_context={
            "region": "SP",
            "typology": "Residential",
            "income": "Medium",
            "scenario": "noAC",
        },
        basement="none",
        attic="none",
        exposed_basement_frac=0.25,
        sort_index=0,
        parent_experiment_spec=GloBIExperimentSpec(
            name="placeholder",
            hourly_data_config=HourlyDataConfig(
                data=("Zone Mean Air Temperature",),
                output_mode="dataframes-only",
            ),
            file_config=FileConfig(
                gis_file=Path("placeholder"),
                db_file=db_path,
                semantic_fields_file=semantic_fields_path,
                epwzip_file=str(epwzip_file),
                component_map_file=component_map_path,
            ),
            scenario="test",
        ),
    )

    print("Test simulation...")
    with tempfile.TemporaryDirectory() as tempdir:
        r = simulate_globi_building_pipeline(globi_spec, tempdir=Path(tempdir))


def preprocess_gis_file(
    config: DeterministicGISPreprocessorConfig,
    file_config: "FileConfig",
    scenario: str | None = None,
    output_path: Path | None = None,
    load_from_output_if_present: bool = True,
) -> tuple[gpd.GeoDataFrame, GISPreprocessorColumnMap]:
    """Preprocess a GIS file.

    Args:
        config (DeterministicGISPreprocessorConfig): The configuration for the GIS preprocessor.
        file_config (FileConfig): The configuration for the files.
        scenario (str | None): The scenario identifier to add to the semantic field context.
        output_path (Path | None): Optional folder to save preprocessed files. If None, file is not saved.
        load_from_output_if_present (bool): If True, loads the preprocessed file from the output path if it exists.

    Returns:
        gdf (gpd.GeoDataFrame): The preprocessed GeoDataFrame.
    """
    if output_path is not None and output_path.is_file():
        msg = f"Expected a folder, got {output_path}"
        raise ValueError(msg)
    gis_fp = file_config.gis_file
    if load_from_output_if_present and output_path is not None:
        gdf_output_path = output_path / "globi_gdf.pq"
        column_output_map_output_path = output_path / "globi_column_output_map.yaml"
        gdf = cast(gpd.GeoDataFrame, gpd.read_parquet(gdf_output_path))
        column_output_map = GISPreprocessorColumnMap.from_manifest(
            column_output_map_output_path
        )
        return gdf, column_output_map

    # load the semantic fields
    # We will need to access this as it stores some
    # rich information about which columns in the provided GIS data will
    # contain standard provided values, like wwr, height etc etc.
    # it also stores the fields that will be used for semantic mapping,
    # so we can run a consistency check with the component map.
    with open(file_config.semantic_fields_file) as f:
        semantic_fields = SemanticModelFields.model_validate(yaml.safe_load(f))
    if semantic_fields.Building_ID_col is None:
        raise SemanticFieldsFileHasNoBuildingIDColumnError()

    gdf = cast(gpd.GeoDataFrame, gpd.read_file(gis_fp))

    validate_has_rows(gdf)

    # Check that the current CRS is WGS84 or the cart one, convert to WGS84 early and use throughout
    gdf = reproject_gdf(gdf, config.cart_crs)

    required_col_names = semantic_fields.field_names

    # We need to deal with the fact that shapefiles will trucnate the column
    # name to 10 characters, but users might not realize this when they
    # export from e.g. ArcGIS.
    gdf = rename_shp_cols(gdf, required_col_names, log_fn=logger.info)
    if scenario is not None:
        gdf["scenario"] = scenario

    # We want to run a consistency check to make sure that the requested semantic fields
    # are actually in the GDF after we have dealt with appropriate renaming.
    # We also should run a consistency check to make sure that every cell value that is listed as a
    # semantic field is actually one of the expected values.
    check_for_column_existence(gdf, required_col_names, log_fn=logger.info)
    validate_semantic_field_compatibility(
        gdf,
        semantic_fields,
        missing_ok=False,
        log_fn=logger.info,
    )

    # If the building ID column is not provided or partial, we will inject uuids
    gdf, semantic_fields.Building_ID_col = check_building_ids(
        gdf, semantic_fields.Building_ID_col, log_fn=logger.info
    )

    # We add the latitude and longitude columns to the GeoDataFrame.
    gdf = add_lat_and_lon_cols(gdf)

    # We store the initial building count since we will now start dropping rows.
    initial_count = len(gdf)

    # We deal with imputing heights/number of floors depending on what is present.
    (
        gdf,
        semantic_fields.Height_col,
        semantic_fields.Num_Floors_col,
        f2f_height_col,
        n_dropped_by_floors_heights,
    ) = handle_height_and_floors(
        gdf,
        height_col=semantic_fields.Height_col,
        nfloors_col=semantic_fields.Num_Floors_col,
        assumed_f2f_height=config.f2f_height,
        default_n_floors=config.default_num_floors,
        min_floors=config.min_num_floors,
        max_floors=config.max_num_floors,
        min_height=config.min_building_height,
        max_height=config.max_building_height,
        log_fn=logger.info,
    )
    validate_has_rows(gdf)

    # Next, we deal with imputing various rich columns.
    (
        gdf,
        semantic_fields.WWR_col,
        n_dropped_by_wwr,
    ) = handle_wwr(
        gdf,
        wwr_col=semantic_fields.WWR_col,
        assumed_wwr=config.default_wwr,
        log_fn=logger.info,
    )
    validate_has_rows(gdf)
    (
        gdf,
        semantic_fields.Basement_col,
        n_dropped_by_basement,
    ) = handle_basement(
        gdf,
        basement_col=semantic_fields.Basement_col,
        assumed_basement=config.default_basement,
        log_fn=logger.info,
    )
    validate_has_rows(gdf)
    (
        gdf,
        semantic_fields.Exposed_Basement_Frac_col,
        n_dropped_by_basement_exposed_fraction,
    ) = handle_basement_exposed_fraction(
        gdf,
        basement_exposed_fraction_col=semantic_fields.Exposed_Basement_Frac_col,
        assumed_basement_exposed_fraction=config.default_exposed_basement_frac,
        log_fn=logger.info,
    )
    validate_has_rows(gdf)
    (
        gdf,
        semantic_fields.Attic_col,
        n_dropped_by_attic,
    ) = handle_attic(
        gdf,
        attic_col=semantic_fields.Attic_col,
        assumed_attic=config.default_attic,
        log_fn=logger.info,
    )
    validate_has_rows(gdf)
    gdf, n_dropped_by_points = drop_non_polygons(gdf, log_fn=logger.info)
    validate_has_rows(gdf)
    logger.info("injecting rotated rectangles")
    gdf, injected_geometry_column_map = inject_rotated_rectangles(
        gdf, cart_crs=config.cart_crs
    )
    gdf, n_dropped_by_area = drop_by_area(
        gdf,
        area_col=injected_geometry_column_map.Footprint_Area_col,
        min_area=config.min_building_area,
        log_fn=logger.info,
    )
    validate_has_rows(gdf)
    gdf, n_dropped_by_edge = drop_by_edge_length(
        gdf,
        short_edge_col=injected_geometry_column_map.Short_Edge_col,
        long_edge_col=injected_geometry_column_map.Long_Edge_col,
        min_edge_length_m=config.min_edge_length,
        max_edge_length_m=config.max_edge_length,
        log_fn=logger.info,
    )

    n_dropped = (
        n_dropped_by_area
        + n_dropped_by_edge
        + n_dropped_by_floors_heights
        + n_dropped_by_wwr
        + n_dropped_by_basement_exposed_fraction
        + n_dropped_by_basement
        + n_dropped_by_attic
        + n_dropped_by_points
    )
    logger.info(f"Dropped {n_dropped / initial_count:.1%} of all buildings.")

    validate_has_rows(gdf)

    logger.info(
        f"Retained {len(gdf)} buildings after filtering (removed {initial_count - len(gdf)} total)"
    )

    logger.info("computing neighbor indices")
    gdf, injected_neighbor_column_map = inject_neighbor_ixs(
        cast(gpd.GeoDataFrame, gdf),
        injected_geometry_col_map=injected_geometry_column_map,
        neighbor_threshold=config.neighbor_threshold,
        log_fn=logger.info,
    )

    logger.info("extracting and converting neighbors")
    gdf = convert_neighbors(
        gdf,
        neighbor_col=injected_neighbor_column_map.Neighbor_Ixs_col,
        geometry_col=injected_geometry_column_map.Rotated_Rectangle_col,
        height_col=semantic_fields.Height_col,
        neighbor_geo_out_col=injected_neighbor_column_map.Neighbor_Polys_col,
        neighbor_heights_out_col=injected_neighbor_column_map.Neighbor_Heights_col,
        neighbor_floors_out_col=injected_neighbor_column_map.Neighbor_Floors_col,
        fill_na_val=config.default_num_floors * config.f2f_height,
        neighbor_f2f_height=config.f2f_height,
    )

    # Construct a dictionary of the semantic field values for each building.
    gdf, semantic_fields_context_col = inject_semantic_fields(gdf, semantic_fields)

    # EPW FILE HANDLING
    gdf, semantic_fields.Weather_File_col = handle_epwzip(
        gdf,
        weather_file_col=semantic_fields.Weather_File_col,
        assumed_epwzip=file_config.epwzip_file,
        epw_query=config.epw_query,
        cart_crs=config.cart_crs,
        log_fn=logger.info,
    )

    db_file_col = "GLOBI_DB_FILE"
    semantic_fields_file_col = "GLOBI_SEMANTIC_FIELDS_FILE"
    component_map_file_col = "GLOBI_COMPONENT_MAP_FILE"
    gdf[db_file_col] = file_config.db_file
    gdf[semantic_fields_file_col] = file_config.semantic_fields_file
    gdf[component_map_file_col] = file_config.component_map_file

    column_output_map = GISPreprocessorColumnMap(
        DB_File_col=db_file_col,
        Semantic_Fields_File_col=semantic_fields_file_col,
        Component_Map_File_col=component_map_file_col,
        EPWZip_File_col=semantic_fields.Weather_File_col,
        Semantic_Field_Context_col=semantic_fields_context_col,
        Neighbor_Polys_col=injected_neighbor_column_map.Neighbor_Polys_col,
        Neighbor_Heights_col=injected_neighbor_column_map.Neighbor_Heights_col,
        Neighbor_Floors_col=injected_neighbor_column_map.Neighbor_Floors_col,
        Rotated_Rectangle_col=injected_geometry_column_map.Rotated_Rectangle_col,
        Long_Edge_Angle_col=injected_geometry_column_map.Long_Edge_Angle_col,
        Long_Edge_col=injected_geometry_column_map.Long_Edge_col,
        Short_Edge_col=injected_geometry_column_map.Short_Edge_col,
        Aspect_Ratio_col=injected_geometry_column_map.Aspect_Ratio_col,
        Rotated_Rectangle_Area_Ratio_col=injected_geometry_column_map.Rotated_Rectangle_Area_Ratio_col,
        WWR_col=semantic_fields.WWR_col,
        Height_col=semantic_fields.Height_col,
        Num_Floors_col=semantic_fields.Num_Floors_col,
        F2F_Height_col=f2f_height_col,
        Basement_col=semantic_fields.Basement_col,
        Attic_col=semantic_fields.Attic_col,
        Exposed_Basement_Frac_col=semantic_fields.Exposed_Basement_Frac_col,
    )

    # TODO: make sure we can save the file still

    if output_path is not None:
        # TODO: make sure path is correct, geojson, etc.
        logger.info(f"saving preprocessed gis file to: {output_path}")
        gdf_output_path = output_path / "globi_gdf.pq"
        column_output_map_output_path = output_path / "globi_column_output_map.yaml"
        gdf.to_parquet(gdf_output_path)
        with open(column_output_map_output_path, "w") as f:
            yaml.dump(
                column_output_map.model_dump(mode="json"), f, sort_keys=False, indent=2
            )
        logger.info(f"saved {len(gdf)} features to {output_path}")

    return gdf, column_output_map
    # print("\nOutput dataframes:", list(output.dataframes.keys()))
    # results_df = output.dataframes["Results"]
    # print("Results shape:", results_df.shape)
    # print("Results index levels:", results_df.index.names)
    # print("\nEnergy data:")
    # print(results_df.loc["Energy"])
    # print("\nPeak data:")
    # print(results_df.loc["Peak"])


# TODO: move to epinterface
def shading_fence_closed_ring(
    elevations: ArrayLike,
    d: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Construct N vertical 'shading fence' rectangles whose bases are tangent segments forming a closed regular polygon around a circle of radius d.

    Inputs:
      elevations: (N,) elevation angles theta_k [radians]
      d: radius to tangency points (base midpoints)

    Outputs:
      azimuths: (N,) inferred azimuths alpha_k = 2πk/N
      p0:       (N, 2) base endpoint A (x,y)
      p1:       (N, 2) base endpoint B (x,y)
      h:        (N,) heights h_k = d * tan(theta_k)
      w:        scalar side length / segment width = 2 d tan(π/N)

    Notes:
      - With this construction, the segments intersect/meet: p1[k] == p0[k+1] (cyclic),
        up to floating point tolerance.
      - N must be >= 3 for a closed polygon.
    """
    theta = np.asarray(elevations, dtype=np.float64)
    if theta.ndim != 1:
        msg = f"elevations must be 1D, got shape {theta.shape}"
        raise ValueError(msg)

    N = theta.shape[0]
    if N < 3:
        msg = "Need at least 3 elevations (N >= 3) to form a closed ring."
        raise ValueError(msg)

    # Inferred equally spaced azimuths
    k = np.arange(N, dtype=np.float64)
    azimuths = 2.0 * np.pi * k / N

    ca, sa = np.cos(azimuths), np.sin(azimuths)

    # Tangency points (base midpoints) on circle radius d
    px = d * ca
    py = d * sa

    # Unit tangent direction (perpendicular to radius)
    tx = -sa
    ty = ca

    # Choose width so adjacent tangent segments meet (circumscribed regular N-gon)
    half_w = d * np.tan(np.pi / N)
    w = 2.0 * half_w

    # Endpoints in xy: p ± half_w * t
    p0 = np.stack([px - half_w * tx, py - half_w * ty], axis=-1)
    p1 = np.stack([px + half_w * tx, py + half_w * ty], axis=-1)

    # Heights from elevation angles
    h = d * np.tan(theta)

    return azimuths, p0, p1, h, w


if __name__ == "__main__":
    from globi.models import GloBIExperimentSpec

    spec = GloBIExperimentSpec.from_(Path("data/models/Cambridge_UK/manifest.yml"))
    print(yaml.dump(spec.model_dump(mode="json"), indent=2, sort_keys=False))
    # gdf = gpd.read_file(spec.file_config.gis_file)
    logging.basicConfig(level=logging.DEBUG)
    if spec.gis_preprocessor_config is not None:
        new_gdf_path = (
            spec.file_config.gis_file.parent / "buildings-seed-updated.geojson"
        )
        old_gdf: gpd.GeoDataFrame = gpd.read_file(spec.file_config.gis_file)
        old_gdf["Region"] = "CB"
        old_gdf["Age_bracket"] = (
            old_gdf["Age_bracket"].str.replace(" ", "_").str.replace("1999", "1960")
        )
        old_gdf["OCCUPANCY_DENSITY"] = old_gdf["OCCUPANCY_DENSITY"].str.replace(
            "MediumDensity", "MedDensity"
        )
        old_gdf.to_file(new_gdf_path, driver="GeoJSON")
        spec.file_config.gis_file = new_gdf_path
        gdf, colmap = preprocess_gis_file(
            config=spec.gis_preprocessor_config,
            file_config=spec.file_config,
        )
        print(gdf.columns)
        print(colmap.model_dump_json(indent=2))
        print(gdf.head())
        import pandas as pd

        print(cast(pd.Series, gdf[colmap.EPWZip_File_col]).unique())
