"""Geometry utilities."""

import logging
from collections.abc import Callable
from typing import cast

import geopandas as gpd
import numpy as np
import pandas as pd
from pydantic import BaseModel
from scipy.spatial import cKDTree
from shapely.geometry import Point, Polygon

logger = logging.getLogger(__name__)


class InjectedGeometryColumnMap(BaseModel):
    """A map of the columns that are injected into the GeoDataFrame."""

    Geometry_Cart_col: str
    Footprint_Area_col: str
    Rotated_Rectangle_col: str
    Rotated_Rectangle_Area_Ratio_col: str
    Short_Edge_col: str
    Long_Edge_col: str
    Long_Edge_Angle_col: str
    Aspect_Ratio_col: str

    @property
    def all_cols(self) -> list[str]:
        """Get all the column names as a list."""
        return list(self.model_dump().values())


def inject_rotated_rectangles(
    gdf: gpd.GeoDataFrame, cart_crs: str
) -> tuple[gpd.GeoDataFrame, InjectedGeometryColumnMap]:
    """Inject rotated rectangles into a GeoDataFrame.

    This will fit a rectangle around the geometry of each building, and additionally compute
    some useful summary features.

    Adds the following columns:
        - geometry_cart: the geometry in the cartesian CRS
        - footprint_area: the area of the footprint of the building
        - rotated_rectangle: the minimum rotated rectangle that bounds the building
        - rotated_rectangle_area_ratio: the ratio of the area of the rotated rectangle to the footprint area
        - short_edge: the shorter edge of the rotated rectangle
        - long_edge: the longer edge of the rotated rectangle
        - long_edge_angle: the angle of the long edge of the rotated rectangle
        - aspect_ratio: the ratio of the long edge to the short edge of the rotated rectangle

    Args:
        gdf (gpd.GeoDataFrame): The GeoDataFrame of buildings.
        cart_crs (str): The cartesian CRS to project the buildings to.

    Returns:
        gdf (gpd.GeoDataFrame): The GeoDataFrame with the rotated rectangles.
        injected_cols (list[str]): The injected columns
    """
    injected_column_map = InjectedGeometryColumnMap(
        Geometry_Cart_col="GLOBI_GEOMETRY_CART",
        Footprint_Area_col="GLOBI_FOOTPRINT_AREA",
        Rotated_Rectangle_col="GLOBI_ROTATED_RECTANGLE",
        Rotated_Rectangle_Area_Ratio_col="GLOBI_ROTATED_RECTANGLE_AREA_RATIO",
        Short_Edge_col="GLOBI_SHORT_EDGE",
        Long_Edge_col="GLOBI_LONG_EDGE",
        Long_Edge_Angle_col="GLOBI_LONG_EDGE_ANGLE",
        Aspect_Ratio_col="GLOBI_ASPECT_RATIO",
    )

    gdf_cart = cast(gpd.GeoDataFrame, gdf.to_crs(cart_crs))
    gdf[injected_column_map.Geometry_Cart_col] = gdf_cart.geometry
    gdf[injected_column_map.Footprint_Area_col] = gdf_cart.geometry.area
    gdf[injected_column_map.Rotated_Rectangle_col] = (
        gdf_cart.geometry.minimum_rotated_rectangle()
    )
    gdf[injected_column_map.Rotated_Rectangle_Area_Ratio_col] = (
        gdf[injected_column_map.Rotated_Rectangle_col].area
        / gdf[injected_column_map.Footprint_Area_col]
    )
    a1 = cast(
        pd.DataFrame,
        gdf[injected_column_map.Rotated_Rectangle_col].apply(
            lambda x: pd.Series({
                "x": x.exterior.coords[0][0],
                "y": x.exterior.coords[0][1],
            })
        ),
    )
    b1 = cast(
        pd.DataFrame,
        gdf[injected_column_map.Rotated_Rectangle_col].apply(
            lambda x: pd.Series({
                "x": x.exterior.coords[1][0],
                "y": x.exterior.coords[1][1],
            })
        ),
    )
    a2 = cast(
        pd.DataFrame,
        gdf[injected_column_map.Rotated_Rectangle_col].apply(
            lambda x: pd.Series({
                "x": x.exterior.coords[2][0],
                "y": x.exterior.coords[2][1],
            })
        ),
    )
    d1 = ((a1 - b1) ** 2).sum(axis=1) ** 0.5
    d2 = ((a2 - b1) ** 2).sum(axis=1) ** 0.5
    d1_is_long = d1 > d2
    short = d1.where(d1 < d2, d2)
    long = d1.where(d1 > d2, d2)
    long_edge_vector = (b1 - a1) * d1_is_long.values[:, None] + (
        a2 - b1
    ) * ~d1_is_long.values[:, None]
    long_edge_angle = np.arctan2(long_edge_vector.y, long_edge_vector.x)
    aspect_ratio = long / short
    gdf[injected_column_map.Short_Edge_col] = short
    gdf[injected_column_map.Long_Edge_col] = long
    gdf[injected_column_map.Long_Edge_Angle_col] = long_edge_angle
    gdf[injected_column_map.Aspect_Ratio_col] = aspect_ratio

    return (gdf, injected_column_map)


class InjectedNeighborColumnMap(BaseModel):
    """A map of the columns that are injected into the GeoDataFrame."""

    Neighbor_Ixs_col: str
    Neighbor_Polys_col: str
    Neighbor_Heights_col: str
    Neighbor_Floors_col: str


def inject_neighbor_ixs(
    gdf: gpd.GeoDataFrame,
    injected_geometry_col_map: InjectedGeometryColumnMap,
    neighbor_threshold: float = 50,
    remove_intersections: bool = True,
    log_fn: Callable | None = None,
) -> tuple[gpd.GeoDataFrame, InjectedNeighborColumnMap]:
    """Compute neighbors for each building in a GeoDataFrame.

    Note that this does mutate the input GeoDataFrame (in addition to returning it).

    Args:
        gdf (gpd.GeoDataFrame): The GeoDataFrame of buildings.
        injected_geometry_col_map (InjectedGeometryColumnMap): The injected geometry columns.
        neighbor_threshold (float): The distance threshold for neighbors.
        remove_intersections (bool): Whether to remove intersecting neighbors.
        log_fn (Callable | None): A function to log messages.

    Returns:
        gdf (gpd.GeoDataFrame): The GeoDataFrame with neighbors.
        injected_neighbor_column_map (InjectedNeighborColumnMap): The injected columns
    """
    injected_neighbor_column_map = InjectedNeighborColumnMap(
        Neighbor_Ixs_col="GLOBI_NEIGHBOR_IXS",
        Neighbor_Polys_col="GLOBI_NEIGHBOR_POLYS",
        Neighbor_Heights_col="GLOBI_NEIGHBOR_HEIGHTS",
        Neighbor_Floors_col="GLOBI_NEIGHBOR_FLOORS",
    )
    log = log_fn or logger.info
    # 2. Compute centroids of the rectangles
    rotated_rectangles = gdf[injected_geometry_col_map.Rotated_Rectangle_col]
    rectangle_centers = rotated_rectangles.apply(lambda x: x.centroid)

    # 3. Extract centroid coordinates
    coords = np.array([
        (geom.x, geom.y) for geom in cast(list[Point], rectangle_centers)
    ])

    # 4. Build a KDTree for efficient spatial queries
    log("building tree")
    tree = cKDTree(coords)
    log("done building tree")

    # 5. Query for neighbors within 50 meters (exclude the point itself)
    indices = tree.query_ball_point(coords, r=neighbor_threshold)
    log("done querying")

    # Remove self from neighbors
    neighbors = [list(set(ind) - {i}) for i, ind in enumerate(indices)]
    log("done removing self")

    # 6. Add the neighbors list to the GeoDataFrame
    gdf[injected_neighbor_column_map.Neighbor_Ixs_col] = neighbors

    def check_row_for_ixs(row: gpd.GeoSeries):
        neighbor_ixs = row[injected_neighbor_column_map.Neighbor_Ixs_col]
        neighbor_rects = gdf.iloc[neighbor_ixs][
            injected_geometry_col_map.Rotated_Rectangle_col
        ]
        current_rect = row[injected_geometry_col_map.Rotated_Rectangle_col]
        intersection = neighbor_rects.apply(lambda x: x.intersects(current_rect))
        non_intersecting_neighbors = pd.Series(
            neighbor_ixs, index=neighbor_rects.index
        )[~intersection].tolist()
        return non_intersecting_neighbors

    if remove_intersections:
        log("removing intersections")
        gdf[injected_neighbor_column_map.Neighbor_Ixs_col] = gdf.apply(
            check_row_for_ixs, axis=1
        )
        log("done removing intersections")
    return gdf, injected_neighbor_column_map


def lon_lat_from_poly(poly: Polygon):
    """Extracts the longitude and latitude coordinates from a given polygon.

    Parameters:
        poly (Polygon): The polygon from which to extract the coordinates.

    Returns:
        lons (list[float]): The longitude coordinates.
        lats (list[float]): The latitude coordinates.
    """
    x, y = poly.exterior.coords.xy
    return x.tolist(), y.tolist()


def extract_neighbors_geo(
    gdf: gpd.GeoDataFrame,
    neighbor_ixs: list[int] | None,
    geometry_col: str = "rotated_rectangle",
) -> list[Polygon | str]:
    """Convert neighbor indices to polygons (or wkt) for a single building.

    Args:
        gdf (gpd.GeoDataFrame): The GeoDataFrame.
        neighbor_ixs (list[int]): The neighbor indices.
        geometry_col (str, optional): The geometry column. Defaults to `rotated_rectangle`.

    Returns:
        list[Polygon | str]: The neighbor polygons.
    """
    if neighbor_ixs is None or len(neighbor_ixs) == 0 or neighbor_ixs is np.nan:
        return []
    polys = gdf.iloc[neighbor_ixs][geometry_col]
    return polys.tolist()


def extract_neighbor_heights(
    gdf: gpd.GeoDataFrame,
    neighbor_ixs: list[int],
    height_col: str = "height",
    fill_na_val: float = 8,
) -> list[float]:
    """Convert neighbor indices to heights for a single building.

    Args:
        gdf (gpd.GeoDataFrame): The GeoDataFrame.
        neighbor_ixs (list[int]): The neighbor indices.
        height_col (str, optional): The height column. Defaults to `height`.
        fill_na_val (float, optional): The value to fill NaNs with. Defaults to 8.

    Returns:
        heights (list[float]): The neighbor heights.
    """
    if neighbor_ixs is None or len(neighbor_ixs) == 0 or neighbor_ixs is np.nan:
        return []
    heights = gdf.iloc[neighbor_ixs][height_col].fillna(fill_na_val)
    return heights.tolist()


def convert_neighbors(
    gdf: gpd.GeoDataFrame,
    neighbor_col: str,
    geometry_col: str,
    height_col: str,
    neighbor_geo_out_col: str,
    neighbor_heights_out_col: str,
    neighbor_floors_out_col: str,
    neighbor_f2f_height: float,
    fill_na_val: float = 2,
) -> gpd.GeoDataFrame:
    """Convert neighbor indices to polygons and heights for all buildings in a GeoDataFrame.

    Args:
        gdf (gpd.GeoDataFrame): The GeoDataFrame.
        neighbor_col (str, optional): The neighbor indices column. Defaults to `neighbor_ixs`.
        geometry_col (str, optional): The geometry column. Defaults to `rotated_rectangle`.
        height_col (str, optional): The height column. Defaults to `height`.
        neighbor_geo_out_col (str, optional): The output column for neighbor polygons. Defaults to `neighbor_polys`.
        neighbor_heights_out_col (str, optional): The output column for neighbor heights. Defaults to `neighbor_heights`.
        neighbor_floors_out_col (str, optional): The output column for neighbor floors. Defaults to `neighbor_floors`.
        neighbor_f2f_height (float, optional): The height of a floor to floor assumption.
        fill_na_val (float, optional): The value to fill NaNs with. Defaults to 2.

    Returns:
        gdf (gpd.GeoDataFrame): The GeoDataFrame
    """
    neighbors = gdf[neighbor_col].apply(
        lambda x: extract_neighbors_geo(
            gdf=gdf,
            neighbor_ixs=x,
            geometry_col=geometry_col,
        )
    )
    neighbor_heights = gdf[neighbor_col].apply(
        lambda x: extract_neighbor_heights(
            gdf=gdf,
            neighbor_ixs=x,
            height_col=height_col,
            fill_na_val=fill_na_val,
        )
    )
    gdf[neighbor_geo_out_col] = neighbors
    gdf[neighbor_heights_out_col] = neighbor_heights
    gdf[neighbor_floors_out_col] = gdf[neighbor_heights_out_col].apply(
        lambda heights: (
            [
                int(h / neighbor_f2f_height)
                if h is not None and not np.isnan(h)
                else None
                for h in heights
            ]
            if isinstance(heights, list)
            else []
        )
    )

    return gdf
