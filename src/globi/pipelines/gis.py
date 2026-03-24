"""GIS processing pipelines for the GloBI project."""

import logging
from pathlib import Path
from typing import cast

import geopandas as gpd
import yaml
from epinterface.sbem.fields.spec import SemanticModelFields

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
from globi.models.configs import (
    DeterministicGISPreprocessorConfig,
    FileConfig,
    GISPreprocessorColumnMap,
)

logger = logging.getLogger(__name__)


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
    gdf, estimated_utm_crs = reproject_gdf(gdf, config.cart_crs)

    required_col_names_semantic = semantic_fields.semantic_field_names
    required_col_names_rich = semantic_fields.rich_field_names

    # We need to deal with the fact that shapefiles will trucnate the column
    # name to 10 characters, but users might not realize this when they
    # export from e.g. ArcGIS.
    gdf = rename_shp_cols(gdf, required_col_names_rich, log_fn=logger.info)
    gdf = rename_shp_cols(
        gdf,
        [c for c in required_col_names_semantic if c is not None],
        log_fn=logger.info,
    )
    if scenario is not None:
        gdf["scenario"] = scenario

    # We want to run a consistency check to make sure that the requested semantic fields
    # are actually in the GDF after we have dealt with appropriate renaming.
    # We also should run a consistency check to make sure that every cell value that is listed as a
    # semantic field is actually one of the expected values.
    if config.check_semantic_fields:
        check_for_column_existence(gdf, required_col_names_semantic, log_fn=logger.info)
        validate_semantic_field_compatibility(
            gdf,
            semantic_fields,
            missing_ok=False,
            log_fn=logger.info,
        )
    check_for_column_existence(gdf, required_col_names_rich, log_fn=logger.info)

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
        gdf, cart_crs=estimated_utm_crs
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
    gdf, semantic_fields_context_col = inject_semantic_fields(
        gdf, semantic_fields if config.check_semantic_fields else None
    )

    # EPW FILE HANDLING
    gdf, semantic_fields.Weather_File_col = handle_epwzip(
        gdf,
        weather_file_col=semantic_fields.Weather_File_col,
        assumed_epwzip=file_config.epwzip_file,
        epw_query=config.epw_query,
        cart_crs=estimated_utm_crs,
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
        Building_ID_col=semantic_fields.Building_ID_col,
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
