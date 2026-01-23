"""Utilities for GIS preprocessor."""

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast, get_args
from urllib.parse import urljoin

import geopandas as gpd
import numpy as np
import pandas as pd
from epinterface.sbem.fields.spec import (
    CategoricalFieldSpec,
    NumericFieldSpec,
    SemanticModelFields,
)

from globi.gis.errors import (
    GISFileHasInvalidCategoricalSemanticFieldError,
    GISFileHasMissingBuildingIDsError,
    GISFileHasMissingColumnsError,
    GISFileHasNoBuildingIDColumnError,
    GISFileHasNoCRSError,
    GISFileHasNoFeaturesError,
    GISFileHasNonNumericFloorsError,
    GISFileHasNonNumericHeightError,
    GISFileHasNonUniqueBuildingIDsError,
    GISFileHasOutOfBoundsNumericSemanticFieldError,
    GISFileHasSemanticFieldWithNoValidatorError,
    GISFileHasUnexpectedCRSError,
    GISFileMissingBothHeightAndFloorsError,
)
from globi.gis.weather import closest_epw
from globi.type_utils import BasementAtticOccupationConditioningStatus

logger = logging.getLogger(__name__)


LogLikeFn = Callable[[str], None]


def reproject_gdf(
    gdf: gpd.GeoDataFrame, cart_crs: str, log_fn: LogLikeFn | None = None
) -> gpd.GeoDataFrame:
    """We want to have some safety to ensure there is no confusing behavior with the provided CRS.

    We want to ensure that either:
    - the gdf is already in the desired crs or EPSG:3857, in which case we bring it back up to 4326
    - the gdf is already in 4326, in which case we leave it alone
    - the gdf has no crs, in which case we raise an error
    - the gdf is in some other crs, in which case we raise an error

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        cart_crs (str): The eventually desired cartesian crs.
        log_fn (Callable | None): The function to use for logging.

    Raises:
        GISFileHasNoCRSError: If the gdf has no crs.
        GISFileHasUnexpectedCRSError: If the gdf is in some other crs.

    Returns:
        gdf (gpd.GeoDataFrame): The reprojected GeoDataFrame.

    """
    log = log_fn or logger.info
    log("Checking GIS file crs and reprojecting if necessary...")
    if not gdf.crs:
        raise GISFileHasNoCRSError()

    if gdf.crs == "EPSG:3857":
        log("Reprojecting gis file to EPSG:4326 from EPSG:3857.")
        gdf.to_crs("EPSG:4326", inplace=True)
    current_crs = gdf.crs

    log(f"GIS file has crs {current_crs}")
    if str(current_crs) not in ["EPSG:4326", str(cart_crs)]:
        raise GISFileHasUnexpectedCRSError(str(cart_crs), str(current_crs))

    if current_crs != "EPSG:4326":
        log("Projecting gis file to EPSG:4326 from {current_crs}.")
        gdf.to_crs("EPSG:4326", inplace=True)

    return gdf


def rename_shp_cols(
    gdf: gpd.GeoDataFrame,
    expected_cols: list[str | None],
    log_fn: LogLikeFn | None = None,
) -> gpd.GeoDataFrame:
    """Rename columns of a shapefile to the expected column names.

    This is necessary because shapefiles will truncate the column
    name to 10 characters, but users might not realize this when they
    export from e.g. ArcGIS.

    """
    log = log_fn or logger.info
    log("Renaming SHAPEFILE columns which may have been truncated...")
    for col_name in expected_cols:
        if col_name is None:
            continue
        if col_name[:10] in gdf.columns:
            if col_name[:10] != col_name:
                log(
                    f"Renaming column '{col_name[:10]}' to '{col_name}' as per semantic fields."
                )
            gdf.rename(columns={col_name[:10]: col_name}, inplace=True)
    log("Done renaming SHAPEFILE columns.")
    return gdf


def validate_semantic_field_compatibility(
    gdf: gpd.GeoDataFrame,
    semantic_fields_data: SemanticModelFields,
    missing_ok: bool = True,
    log_fn: LogLikeFn | None = None,
) -> None:
    """Validate the user provided semantic fields against the provided GeoDataFrame.

    Args:
        gdf: The input GeoDataFrame.
        semantic_fields_data: The semantic fields data loaded from YAML.
        missing_ok: Whether to allow missing values for a field.
        log_fn: The function to use for logging.

    Raises:
        GISFileHasInvalidCategoricalSemanticFieldError: If an option is not found in the allowed options for a given semantic field.
        GISFileHasOutOfBoundsNumericSemanticFieldError: If a numeric value is out of bounds.
        GISFileHasSemanticFieldWithNoValidatorError: If a semantic field has no validator.
    """
    log = log_fn or logger.info
    for field in semantic_fields_data.Fields:
        field_name = field.Name
        if field_name not in gdf.columns:
            continue
        if isinstance(field, CategoricalFieldSpec):
            valid_opts = field.Options
            if valid_opts:
                field_vals = gdf[field_name]
                is_missing = field_vals.isna()

                is_valid = cast(
                    pd.Series,
                    field_vals.isin(valid_opts)
                    | (is_missing & pd.Series([missing_ok] * len(field_vals))),
                )
                is_not_valid = ~is_valid
                if cast(pd.Series, is_not_valid).any():
                    invalid_series = cast(pd.Series, field_vals[is_not_valid])
                    invalid_values = invalid_series.unique().tolist()
                    raise GISFileHasInvalidCategoricalSemanticFieldError(
                        field_name, invalid_values, valid_opts
                    )
        elif isinstance(field, NumericFieldSpec):
            min_val: float = field.Min
            max_val: float = field.Max
            if min_val is not None and max_val is not None:
                field_vals = cast(pd.Series, gdf[field_name])
                is_missing = field_vals.isna()
                is_valid = cast(
                    pd.Series,
                    field_vals.between(min_val, max_val, inclusive="both")
                    | (is_missing & pd.Series([missing_ok] * len(field_vals))),
                )
                is_not_valid = ~is_valid
                if cast(pd.Series, is_not_valid).any():
                    invalid_series = cast(pd.Series, field_vals[is_not_valid])
                    invalid_values = invalid_series.unique().tolist()
                    raise GISFileHasOutOfBoundsNumericSemanticFieldError(
                        field_name, invalid_values, min_val, max_val
                    )
        else:
            raise GISFileHasSemanticFieldWithNoValidatorError(field_name)

    log("Semantic field compatibility validation complete.")


def validate_has_rows(gdf: gpd.GeoDataFrame) -> None:
    """Validate that the GeoDataFrame has rows."""
    if len(gdf) == 0:
        raise GISFileHasNoFeaturesError()


def check_for_column_existence(
    gdf: gpd.GeoDataFrame,
    expected_cols: Sequence[str | None],
    log_fn: LogLikeFn | None = None,
) -> None:
    """Check if the expected columns exist in the GeoDataFrame.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        expected_cols (Sequence[str | None]): The expected column names.
        log_fn (Callable | None): The function to use for logging.

    Raises:
        GISFileHasMissingColumnsError: If a column is not found in the GeoDataFrame.
    """
    log = log_fn or logger.info
    log("Checking for column existence...")
    missing_cols = []
    for col_name in expected_cols:
        if col_name is None:
            continue
        if col_name not in gdf.columns:
            missing_cols.append(col_name)
        else:
            log(f"Column '{col_name}' found in gdf.")
    if missing_cols:
        raise GISFileHasMissingColumnsError(missing_cols, gdf.columns.tolist())
    log("All expected columns found in gdf.")


def check_building_ids(
    gdf: gpd.GeoDataFrame,
    building_id_col: str,
    log_fn: LogLikeFn | None = None,
) -> tuple[gpd.GeoDataFrame, str]:
    """Inject building ids into the GeoDataFrame if they are not already present.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        building_id_col (str): The name of the building id column.
        log_fn (LogLikeFn | None): The function to use for logging.

    Raises:
        GISFileHasNoBuildingIDColumnError: If the building id column is not found.
        GISFileHasMissingBuildingIDsError: If the building id column has missing values.
        GISFileHasNonUniqueBuildingIDsError: If the building id column has non-unique values.

    Returns:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame with the building ids.
        building_id_col (str): The name of the building id column.
    """
    log = log_fn or logger.info
    log("Checking for building ids...")

    # If the building id column is not present, we will inject uuids
    if building_id_col not in gdf.columns:
        log("Building id column not found.")
        raise GISFileHasNoBuildingIDColumnError()

    # If there are missing ids, we will back fill them with new uuids
    has_missing_ids = cast(pd.Series, gdf[building_id_col].isna())
    if has_missing_ids.any():
        raise GISFileHasMissingBuildingIDsError()

    gdf[building_id_col] = gdf[building_id_col].astype(str)
    if gdf[building_id_col].nunique() != len(gdf):
        raise GISFileHasNonUniqueBuildingIDsError()

    return gdf, building_id_col


def drop_by_area(
    gdf: gpd.GeoDataFrame,
    area_col: str,
    min_area: float,
    log_fn: LogLikeFn | None = None,
) -> tuple[gpd.GeoDataFrame, int]:
    """Drop features with an area less than the minimum area.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        area_col (str): The name of the area column.
        min_area (float): The minimum area.
        log_fn (LogLikeFn | None): The function to use for logging.

    Returns:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame with the dropped features.
        n_dropped (int): The number of features dropped.
    """
    log = log_fn or logger.info
    log("Checking that features have an area greater than the minimum area...")
    is_valid_area = cast(pd.Series, gdf[area_col] >= min_area)
    n_dropped = len(gdf) - is_valid_area.sum()
    gdf = cast(gpd.GeoDataFrame, gdf[is_valid_area])
    if n_dropped > 0:
        log(
            f"Dropped {n_dropped / len(gdf):.1%} of remaining features with an area less than {min_area} (n={n_dropped})."
        )
    else:
        log("All features have an area greater than the minimum area.")
    return gdf, n_dropped


def drop_by_edge_length(
    gdf: gpd.GeoDataFrame,
    min_edge_length_m: float,
    max_edge_length_m: float,
    short_edge_col: str,
    long_edge_col: str,
    log_fn: LogLikeFn | None = None,
) -> tuple[gpd.GeoDataFrame, int]:
    """Drop features with an edge length less than the minimum or greater than the maximum edge length.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        min_edge_length_m (float): The minimum edge length.
        max_edge_length_m (float): The maximum edge length.
        short_edge_col (str): The name of the short edge column.
        long_edge_col (str): The name of the long edge column.
        log_fn (LogLikeFn | None): The function to use for logging.

    Returns:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame with the dropped features.
        n_dropped (int): The number of features dropped.
    """
    log = log_fn or logger.info
    log(
        "Checking that features have an edge length between the minimum and maximum edge length..."
    )
    is_valid_short_edge = cast(pd.Series, gdf[short_edge_col]).between(
        min_edge_length_m, max_edge_length_m, inclusive="both"
    )
    is_valid_long_edge = cast(pd.Series, gdf[long_edge_col]).between(
        min_edge_length_m, max_edge_length_m, inclusive="both"
    )
    is_valid_edge = is_valid_short_edge & is_valid_long_edge
    n_dropped = len(gdf) - is_valid_edge.sum()
    gdf = cast(gpd.GeoDataFrame, gdf[is_valid_edge])
    if n_dropped > 0:
        log(
            f"Dropped {n_dropped / len(gdf):.1%} of remaining features with an edge length less than {min_edge_length_m} or greater than {max_edge_length_m} (n={n_dropped})."
        )
    else:
        log(
            "All features have an edge length between the minimum and maximum edge length."
        )
    return gdf, n_dropped


def add_lat_and_lon_cols(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add latitude and longitude columns to the GeoDataFrame."""
    # TODO: do we care that we may be overwriting here?
    centroids = cast(gpd.GeoDataFrame, gdf.to_crs("EPSG:3857")).geometry.centroid
    points = gpd.GeoSeries(centroids)
    points.crs = "EPSG:3857"
    points = points.to_crs("EPSG:4326")
    gdf["lat"] = points.y
    gdf["lon"] = points.x
    return gdf


def handle_height_and_floors(
    gdf: gpd.GeoDataFrame,
    height_col: str | None,
    nfloors_col: str | None,
    assumed_f2f_height: float,
    default_n_floors: int,
    min_floors: int,
    max_floors: int,
    min_height: float,
    max_height: float,
    log_fn: LogLikeFn | None = None,
) -> tuple[gpd.GeoDataFrame, str, str, str, int]:
    """Handle the height and floors columns.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        height_col (str | None): The name of the height column.
        nfloors_col (str | None): The name of the floors column.
        assumed_f2f_height (float): The assumed height of a floor to ceiling height.
        default_n_floors (int): The default number of floors.
        min_floors (int): The minimum number of floors.
        max_floors (int): The maximum number of floors.
        min_height (float): The minimum height.
        max_height (float): The maximum height.
        log_fn (LogLikeFn | None): The function to use for logging.

    Returns:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame with the height and floors columns.
        height_col (str): The name of the height column.
        nfloors_col (str): The name of the floors column.
        n_dropped (int): The number of buildings dropped due to invalid floors.
    """
    log = log_fn or logger.info

    log("Checking that height and floors columns have data...")

    if height_col is None and nfloors_col is None:
        raise GISFileMissingBothHeightAndFloorsError()

    if height_col is not None and gdf[height_col].dtype not in [
        float,
        int,
        np.float64,
        np.int64,
        np.float32,
        np.int32,
    ]:
        raise GISFileHasNonNumericHeightError(height_col)

    if nfloors_col is not None and gdf[nfloors_col].dtype not in [
        float,
        int,
        np.float64,
        np.int64,
        np.float32,
        np.int32,
    ]:
        raise GISFileHasNonNumericFloorsError(nfloors_col)

    if height_col is None:
        log(
            f"No height column provided, will impute based off of number floors and assumed floor-to-floor height ({assumed_f2f_height}m)..."
        )
        log(
            f"(Buildings with unknown floor counts will be assumed to have {default_n_floors} floors.)"
        )
        nfloors_col = nfloors_col or "GLOBI_NFLOORS"
        existing_floor_data = cast(
            pd.Series, gdf[nfloors_col].round(0).astype(int)
        ).fillna(default_n_floors)
        gdf[nfloors_col] = existing_floor_data
        new_height_data = existing_floor_data * assumed_f2f_height
        height_col = "GLOBI_HEIGHT"
        gdf[height_col] = new_height_data

    elif nfloors_col is None:
        log(
            f"No floors column provided, will impute based off of building height and assumed floor-to-floor height ({assumed_f2f_height}m)..."
        )
        log(
            f"(Buildings with unknown heights will be assumed to have {default_n_floors * assumed_f2f_height}m height.)"
        )
        height_col = height_col or "GLOBI_HEIGHT"
        existing_height_data = cast(pd.Series, gdf[height_col]).fillna(
            default_n_floors * assumed_f2f_height
        )
        gdf[height_col] = existing_height_data
        nfloors_col = "GLOBI_NFLOORS"
        gdf[nfloors_col] = (gdf[height_col] / assumed_f2f_height).round(0).astype(int)
        gdf[height_col] = gdf[nfloors_col] * assumed_f2f_height

    is_valid_height = cast(pd.Series, gdf[height_col]).between(
        min_height, max_height, inclusive="both"
    )
    is_valid_floors = cast(pd.Series, gdf[nfloors_col]).between(
        min_floors, max_floors, inclusive="both"
    )
    is_valid = is_valid_height & is_valid_floors
    n_dropped = len(gdf) - is_valid.sum()
    gdf = cast(gpd.GeoDataFrame, gdf[is_valid])
    if n_dropped > 0:
        log(
            f"Dropped {n_dropped / len(gdf):.1%} of remaining features with a height or floors out of bounds (n={n_dropped})."
        )
    f2f_height_col = "GLOBI_F2F_HEIGHT"
    gdf[f2f_height_col] = assumed_f2f_height
    log("Done handling height and floors columns.")
    return gdf, height_col, nfloors_col, f2f_height_col, n_dropped


def handle_wwr(
    gdf: gpd.GeoDataFrame,
    wwr_col: str | None,
    assumed_wwr: float,
    log_fn: LogLikeFn | None = None,
) -> tuple[gpd.GeoDataFrame, str, int]:
    """Handle the window-to-wall ratio column.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        wwr_col (str | None): The name of the window-to-wall ratio column.
        assumed_wwr (float): The assumed window-to-wall ratio.
        log_fn (LogLikeFn | None): The function to use for logging.

    Returns:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame with the window-to-wall ratio column.
        wwr_col (str): The name of the window-to-wall ratio column.
        n_dropped (int): The number of buildings dropped due to invalid window-to-wall ratio.
    """
    log = log_fn or logger.info
    log("Checking that window-to-wall ratio column has data...")
    if wwr_col is None:
        log(
            f"No window-to-wall ratio column provided, will impute based off of assumed window-to-wall ratio ({assumed_wwr})..."
        )
        wwr_col = "GLOBI_WWR"
        gdf[wwr_col] = assumed_wwr
    gdf[wwr_col] = cast(pd.Series, gdf[wwr_col]).fillna(assumed_wwr)
    # TODO: add a dtype checker
    min_wwr = 0
    max_wwr = 1
    is_valid = cast(pd.Series, gdf[wwr_col]).between(min_wwr, max_wwr, inclusive="both")
    n_dropped = len(gdf) - is_valid.sum()
    gdf = cast(gpd.GeoDataFrame, gdf[is_valid])
    if n_dropped > 0:
        log(
            f"Dropped {n_dropped / len(gdf):.1%} of remaining features with a window-to-wall ratio out of bounds ({min_wwr} - {max_wwr}) (n={n_dropped})."
        )
    log("Done handling window-to-wall ratio column.")
    return gdf, wwr_col, n_dropped


def handle_basement(
    gdf: gpd.GeoDataFrame,
    basement_col: str | None,
    assumed_basement: BasementAtticOccupationConditioningStatus,
    log_fn: LogLikeFn | None = None,
) -> tuple[gpd.GeoDataFrame, str, int]:
    """Handle the basement column.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        basement_col (str | None): The name of the basement column.
        assumed_basement (BasementAtticOccupationConditioningStatus): The assumed basement status.
        log_fn (LogLikeFn | None): The function to use for logging.

    Returns:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame with the basement column.
        basement_col (str): The name of the basement column.
        n_dropped (int): The number of buildings dropped due to invalid basement status.
    """
    log = log_fn or logger.info
    log("Checking that basement column has data...")
    if basement_col is None:
        log(
            f"No basement column provided, will impute based off of assumed basement status ('{assumed_basement}')..."
        )
        basement_col = "GLOBI_BASEMENT"
        gdf[basement_col] = assumed_basement
    # TODO: add count of NA's filled
    gdf[basement_col] = cast(pd.Series, gdf[basement_col]).fillna(assumed_basement)
    is_valid = cast(
        pd.Series,
        gdf[basement_col].isin(get_args(BasementAtticOccupationConditioningStatus)),
    )
    n_dropped = len(gdf) - is_valid.sum()
    gdf = cast(gpd.GeoDataFrame, gdf[is_valid])
    if n_dropped > 0:
        log(
            f"Dropped {n_dropped / len(gdf):.1%} of remaining features with a basement status value not in {get_args(BasementAtticOccupationConditioningStatus)} (n={n_dropped})."
        )
    log("Done handling basement column.")
    return gdf, basement_col, n_dropped


def handle_basement_exposed_fraction(
    gdf: gpd.GeoDataFrame,
    basement_exposed_fraction_col: str | None,
    assumed_basement_exposed_fraction: float,
    log_fn: LogLikeFn | None = None,
) -> tuple[gpd.GeoDataFrame, str, int]:
    """Handle the basement exposed fraction column.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        basement_exposed_fraction_col (str | None): The name of the basement exposed fraction column.
        assumed_basement_exposed_fraction (float): The assumed basement exposed fraction.
        log_fn (LogLikeFn | None): The function to use for logging.

    Returns:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame with the basement exposed fraction column.
        basement_exposed_fraction_col (str): The name of the basement exposed fraction column.
        n_dropped (int): The number of buildings dropped due to invalid basement exposed fraction.
    """
    log = log_fn or logger.info
    log("Checking that basement exposed fraction column has data...")
    if basement_exposed_fraction_col is None:
        log(
            f"No basement exposed fraction column provided, will impute based off of assumed basement exposed fraction ('{assumed_basement_exposed_fraction}')..."
        )
        basement_exposed_fraction_col = "GLOBI_EXPOSED_BASEMENT_FRAC"
        gdf[basement_exposed_fraction_col] = assumed_basement_exposed_fraction
    gdf[basement_exposed_fraction_col] = cast(
        pd.Series, gdf[basement_exposed_fraction_col]
    ).fillna(assumed_basement_exposed_fraction)
    is_valid = cast(pd.Series, gdf[basement_exposed_fraction_col]).between(
        0, 1, inclusive="both"
    )
    n_dropped = len(gdf) - is_valid.sum()
    gdf = cast(gpd.GeoDataFrame, gdf[is_valid])
    if n_dropped > 0:
        log(
            f"Dropped {n_dropped / len(gdf):.1%} of remaining features with a basement exposed fraction out of bounds (0 - 1) (n={n_dropped})."
        )
    log("Done handling basement exposed fraction column.")
    return gdf, basement_exposed_fraction_col, n_dropped


def handle_attic(
    gdf: gpd.GeoDataFrame,
    attic_col: str | None,
    assumed_attic: BasementAtticOccupationConditioningStatus,
    log_fn: LogLikeFn | None = None,
) -> tuple[gpd.GeoDataFrame, str, int]:
    """Handle the attic column.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        attic_col (str | None): The name of the attic column.
        assumed_attic (BasementAtticOccupationConditioningStatus): The assumed attic status.
        log_fn (LogLikeFn | None): The function to use for logging.

    Returns:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame with the attic column.
        attic_col (str): The name of the attic column.
        n_dropped (int): The number of buildings dropped due to invalid attic status.
    """
    log = log_fn or logger.info
    log("Checking that attic column has data...")
    if attic_col is None:
        log(
            f"No attic column provided, will impute based off of assumed attic status ('{assumed_attic}')..."
        )
        attic_col = "GLOBI_ATTIC"
        gdf[attic_col] = assumed_attic
    gdf[attic_col] = cast(pd.Series, gdf[attic_col]).fillna(assumed_attic)
    is_valid = cast(
        pd.Series,
        gdf[attic_col].isin(get_args(BasementAtticOccupationConditioningStatus)),
    )
    n_dropped = len(gdf) - is_valid.sum()
    gdf = cast(gpd.GeoDataFrame, gdf[is_valid])
    if n_dropped > 0:
        log(
            f"Dropped {n_dropped / len(gdf):.1%} of remaining features with an attic status value not in {get_args(BasementAtticOccupationConditioningStatus)} (n={n_dropped})."
        )
    log("Done handling attic column.")
    return gdf, attic_col, n_dropped


def drop_non_polygons(
    gdf: gpd.GeoDataFrame,
    log_fn: LogLikeFn | None = None,
) -> tuple[gpd.GeoDataFrame, int]:
    """Drop any features which are points."""
    log = log_fn or logger.info
    log("Checking that features are not points...")
    is_valid = cast(pd.Series, cast(gpd.GeoSeries, gdf.geometry).geom_type).isin([
        "Polygon",
        "MultiPolygon",
    ])
    n_dropped = len(gdf) - is_valid.sum()
    gdf = cast(gpd.GeoDataFrame, gdf[is_valid])
    if n_dropped > 0:
        log(
            f"Dropped {n_dropped / len(gdf):.1%} of remaining features which are not polygons (n={n_dropped})."
        )
    log("Done dropping non-polygons.")
    return gdf, n_dropped


def handle_epwzip(
    gdf: gpd.GeoDataFrame,
    weather_file_col: str | None,
    assumed_epwzip: Path | str | None,
    epw_query: str | None,
    cart_crs: str,
    log_fn: LogLikeFn | None = None,
) -> tuple[gpd.GeoDataFrame, str]:
    """Handle the epwzip column.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        weather_file_col (str | None): The name of the weather file column.
        assumed_epwzip (Path | str | None): The assumed EPW file.
        epw_query (str | None): The EPW query.
        cart_crs (str): The cartographic CRS.
        log_fn (LogLikeFn | None): The function to use for logging.

    Returns:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame with the epwzip column.
        weather_file_col (str): The name of the weather file column.
    """
    log = log_fn or logger.info
    crs = gdf.crs
    if str(crs) != "EPSG:4326":
        raise GISFileHasUnexpectedCRSError(
            expected_crs="EPSG:4326", actual_crs=str(crs)
        )

    # Precedence order:
    # 1. whatever is in the existing epwzip_file column
    # 2. the assumed epwzip
    # 3. the closest epw to the centroid of the building
    weather_file_col = weather_file_col or "GLOBI_EPWZIP"
    if weather_file_col not in gdf.columns:
        gdf[weather_file_col] = assumed_epwzip
    if assumed_epwzip is not None:
        gdf[weather_file_col] = cast(pd.Series, gdf[weather_file_col]).fillna(
            assumed_epwzip  # pyright: ignore [reportCallIssue, reportArgumentType]
        )

    is_na = cast(pd.Series, gdf[weather_file_col].isna())
    if is_na.sum() > 0:
        log("resolving remaining EPW files based on building locations...")
        needs_epw_gdf = cast(gpd.GeoDataFrame, gdf[is_na])
        # TODO: avoid calling centroid, instead construct points from lat lon
        epw_meta = closest_epw(
            needs_epw_gdf.geometry.centroid,
            source_filter=epw_query,
            crs=cart_crs,
            log_fn=log,
        )

        def handle_epw_path(x: str) -> str:
            """Format EPW path to full URL."""
            # TODO: updated this from the og method for path normalization - discuss if this method will work for all edge cases
            base_url = "https://climate.onebuilding.org/"
            return urljoin(base_url, x)

        gdf.loc[is_na, weather_file_col] = epw_meta["path"].apply(handle_epw_path)
    return gdf, weather_file_col


def inject_semantic_fields(
    gdf: gpd.GeoDataFrame,
    semantic_fields: SemanticModelFields,
) -> tuple[gpd.GeoDataFrame, str]:
    """Inject the semantic fields into the GeoDataFrame.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame.
        semantic_fields (SemanticModelFields): The semantic fields.

    Returns:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame with the semantic fields.
        semantic_fields_file_col (str): The name of the semantic fields file column.
    """
    semantic_fields_context_col = "GLOBI_SEMANTIC_FIELDS_CONTEXT"
    gdf[semantic_fields_context_col] = gdf.apply(
        lambda row: {
            field_name: row[field_name]
            for field_name in semantic_fields.semantic_field_names
        },
        axis=1,
    )
    return gdf, semantic_fields_context_col
