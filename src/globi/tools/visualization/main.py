"""streamlit visualizations for globi outputs."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components
from shapely import wkt as shapely_wkt
from shapely.geometry import MultiPolygon, Polygon

from globi.tools.visualization.plotting import (
    create_histogram_d3_html,
    create_monthly_timeseries_d3_html,
    create_pie_d3_html,
    create_raw_data_d3_html,
)
from globi.tools.visualization.results_data import (
    extract_d3_data,
    is_results_format,
)
from globi.tools.visualization.utils import (
    BUILDING_ID_COL,
    LAT_COL,
    LON_COL,
    ROTATED_RECTANGLE_COL,
    find_output_run_dirs,
    get_pq_file_for_run,
    has_geo_columns,
    list_categorical_columns,
    list_numeric_columns,
    load_output_table,
)


def _select_output_run(base_dir: Path) -> Path | None:
    """Select a run by folder path (e.g. TestRegion/dryrun/Baseline/v1.0.0). Returns run dir or None."""
    run_dirs = find_output_run_dirs(base_dir)
    if not run_dirs:
        st.warning(f"no .pq runs found under {base_dir}")
        return None
    labels = [str(d.relative_to(base_dir)) for d in run_dirs]
    selected_label = st.selectbox("Select Run", options=labels)
    idx = labels.index(selected_label)
    return run_dirs[idx]


def _build_pydeck_chart(df: pd.DataFrame, value_col: str | tuple[str, ...]) -> None:
    """Render a 3d map using pydeck column layer. Requires lat, lon in df."""
    df_map = df.dropna(subset=[LAT_COL, LON_COL, value_col]).copy()
    if df_map.empty:
        st.info("no rows with valid lat/lon and selected metric.")
        return

    vals = df_map[value_col].astype("float64")
    q_low, q_high = vals.quantile([0.05, 0.95])
    clipped = vals.clip(q_low, q_high)
    df_map["__height__"] = clipped - clipped.min() + 1.0

    center_lat = float(df_map[LAT_COL].mean())
    center_lon = float(df_map[LON_COL].mean())

    layer = pdk.Layer(
        "ColumnLayer",
        data=df_map,
        get_position=[LON_COL, LAT_COL],
        get_elevation="__height__",
        elevation_scale=10,
        radius=8,
        get_fill_color=[32, 99, 210, 190],
        pickable=True,
        auto_highlight=True,
    )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=12,
        pitch=50,
        bearing=0,
    )

    tooltip: Any = {
        "html": f"<b>{value_col}</b>: {{{{{{ {value_col} }}}}}}",
        "style": {"backgroundColor": "black", "color": "white"},
    }

    deck = pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip=tooltip)
    st.pydeck_chart(deck)


def _load_rotated_polygon(wkt_value: str) -> list[tuple[float, float]] | None:
    """Load a polygon from a wkt string and return exterior coords."""
    try:
        geom = shapely_wkt.loads(wkt_value)
    except Exception:
        return None
    if geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        coords = list(geom.exterior.coords)
    elif isinstance(geom, MultiPolygon):
        poly = max(geom.geoms, key=lambda g: g.area)
        coords = list(poly.exterior.coords)
    else:
        return None
    return [(float(x), float(y)) for x, y in coords]


def _load_building_locations(buildings_path: Path) -> pd.DataFrame:
    """Load building locations with lat/lon from inputs/buildings.parquet."""
    gdf = gpd.read_file(buildings_path)
    if "lat" in gdf.columns and "lon" in gdf.columns:
        gdf["lat"] = gdf["lat"].astype("float64")
        gdf["lon"] = gdf["lon"].astype("float64")
    else:
        centroids = gdf.geometry.centroid
        gdf["lat"] = centroids.y.astype("float64")
        gdf["lon"] = centroids.x.astype("float64")
    return pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore"))


def _merge_with_locations(df_reset: pd.DataFrame) -> pd.DataFrame | None:
    """Merge output rows with inputs/buildings.parquet locations. Expects BUILDING_ID_COL in both."""
    if BUILDING_ID_COL not in df_reset.columns:
        return None
    buildings_path = Path("inputs/buildings.parquet")
    if not buildings_path.exists():
        return None
    locations_df = _load_building_locations(buildings_path)
    if BUILDING_ID_COL not in locations_df.columns:
        return None
    locations_df = locations_df[[BUILDING_ID_COL, "lat", "lon"]].dropna()
    merged = df_reset.merge(locations_df, on=BUILDING_ID_COL, how="inner")
    return merged if not merged.empty else None


def _compute_cartesian_offsets(
    offsets: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Project lat/lon offsets to a local cartesian plane."""
    lat0 = sum(lat for _, lat in offsets) / len(offsets)
    lon0 = sum(lon for lon, _ in offsets) / len(offsets)
    meters_per_deg_lat = 110540.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))
    return [
        ((lon - lon0) * meters_per_deg_lon, (lat - lat0) * meters_per_deg_lat)
        for lon, lat in offsets
    ]


def _extract_polygons(
    df_reset: pd.DataFrame,
    rect_col: str,
    height_col: str,
) -> tuple[list[list[tuple[float, float]]], list[float], list[tuple[float, float]]]:
    """Extract normalized polygons, heights, and lat/lon offsets."""
    rect_series = df_reset[rect_col]
    height_series = (
        df_reset[height_col].astype("float64")
        if height_col in df_reset.columns
        else None
    )
    polygons: list[list[tuple[float, float]]] = []
    heights: list[float] = []
    offsets: list[tuple[float, float]] = []
    for i, wkt_value in enumerate(rect_series):
        if hasattr(wkt_value, "wkt"):
            wkt_value = wkt_value.wkt
        if not isinstance(wkt_value, str):
            continue
        coords = _load_rotated_polygon(wkt_value)
        if not coords:
            continue
        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        centroid_x = sum(xs) / len(xs)
        centroid_y = sum(ys) / len(ys)
        normalized = [(x - centroid_x, y - centroid_y) for x, y in coords]
        height = 10.0
        if height_series is not None:
            height = float(height_series.iloc[i])
        lat = float(df_reset.iloc[i]["lat"])
        lon = float(df_reset.iloc[i]["lon"])
        polygons.append(normalized)
        heights.append(height)
        offsets.append((lon, lat))
    return polygons, heights, offsets


def _build_rotated_rectangle_map(df: pd.DataFrame, height_col: str = "height") -> None:
    """Render a 3d map using rotated rectangle polygons on a plane."""
    df_reset = df.reset_index()
    if ROTATED_RECTANGLE_COL not in df_reset.columns:
        st.info("no rotated rectangle column found for map view.")
        return

    merged = _merge_with_locations(df_reset)
    if merged is None:
        st.info("no matching building_id values found between outputs and inputs.")
        return

    polygons, heights, offsets = _extract_polygons(
        merged, ROTATED_RECTANGLE_COL, height_col
    )

    if not polygons:
        st.info("no valid rotated rectangle geometries found.")
        return

    offsets_xy = _compute_cartesian_offsets(offsets)
    features: list[dict[str, Any]] = []
    for idx, polygon in enumerate(polygons):
        offset_x, offset_y = offsets_xy[idx]
        shifted = [[x + offset_x, y + offset_y] for x, y in polygon]
        features.append({"polygon": shifted, "height": heights[idx]})

    center_lon = 0.0
    center_lat = 0.0

    layer = pdk.Layer(
        "PolygonLayer",
        data=features,
        get_polygon="polygon",
        get_elevation="height",
        elevation_scale=2,
        get_fill_color=[32, 99, 210, 160],
        pickable=True,
        auto_highlight=True,
        extruded=True,
        wireframe=True,
    )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=0.8,
        pitch=55,
        bearing=0,
    )

    tooltip: Any = {
        "html": "<b>height</b>: {height}",
        "style": {"backgroundColor": "black", "color": "white"},
    }
    deck = pdk.Deck(  # type: ignore[call-arg]
        layers=[layer],
        initial_view_state=view_state,
        tooltip=tooltip,
        map_style=None,
        coordinate_system=pdk.constants.COORDINATE_SYSTEM.CARTESIAN,  # type: ignore[attr-defined]
    )
    st.pydeck_chart(deck)


def _render_raw_data_page(base_dir: Path) -> None:
    """Raw data viewer with map and d3 summaries."""
    st.subheader("raw outputs")
    run_dir = _select_output_run(base_dir)
    if run_dir is None:
        return

    pq_file = get_pq_file_for_run(run_dir)
    if pq_file is None:
        st.warning(f"no .pq file found in {run_dir.relative_to(base_dir)}")
        return

    with st.spinner(f"loading {pq_file.name}..."):
        df = load_output_table(pq_file)

    st.caption(f"shape: {df.shape[0]} rows x {df.shape[1]} columns")

    numeric_cols = list_numeric_columns(
        df, exclude=[LAT_COL, LON_COL] if has_geo_columns(df) else None
    )

    if is_results_format(df):
        summary_tab, map_tab = st.tabs(["summary", "map"])
        with summary_tab:
            st.markdown("### Results summary")
            run_label = str(run_dir.relative_to(base_dir))
            d3_data = extract_d3_data(df, region_name=run_label, scenario_name="")

            st.subheader("EUI Distribution")
            components.html(
                create_histogram_d3_html(
                    d3_data["eui"], "EUI Distribution", "EUI (kWh/m2)"
                ),
                height=320,
                scrolling=False,
            )
            st.download_button(
                "Download EUI Values (csv)",
                pd.Series(d3_data["eui"], name="eui").to_csv(index=False),
                file_name="eui_values.csv",
                mime="text/csv",
            )

            st.subheader("Peak distribution")
            components.html(
                create_histogram_d3_html(
                    d3_data["peak"], "Peak distribution", "Peak (kW/m2)"
                ),
                height=320,
                scrolling=False,
            )
            st.download_button(
                "Download Peak Values (csv)",
                pd.Series(d3_data["peak"], name="peak").to_csv(index=False),
                file_name="peak_values.csv",
                mime="text/csv",
            )

            st.subheader("End Uses and Utilities Share")
            col_end_uses, col_utilities = st.columns(2)
            with col_end_uses:
                components.html(
                    create_pie_d3_html(
                        d3_data["end_uses_total"],
                        "End uses share",
                        d3_data["end_use_colors"],
                    ),
                    height=320,
                    scrolling=False,
                )
                st.download_button(
                    "Download End Use Totals (csv)",
                    pd.Series(d3_data["end_uses_total"], name="energy_kwh")
                    .rename_axis("end_use")
                    .to_csv(),
                    file_name="end_uses_total.csv",
                    mime="text/csv",
                )
            with col_utilities:
                components.html(
                    create_pie_d3_html(
                        d3_data["utilities_total"],
                        "Utilities share",
                        d3_data["fuel_colors"],
                    ),
                    height=320,
                    scrolling=False,
                )
                st.download_button(
                    "Download Utilities Totals (csv)",
                    pd.Series(d3_data["utilities_total"], name="energy_kwh")
                    .rename_axis("utility")
                    .to_csv(),
                    file_name="utilities_total.csv",
                    mime="text/csv",
                )

            st.subheader("Monthly EUI by End Use")
            components.html(
                create_monthly_timeseries_d3_html(
                    d3_data["monthly_end_uses"],
                    d3_data["end_use_meters"],
                    d3_data["end_use_colors"],
                    "Monthly EUI by end use",
                    "EUI (kWh/m2)",
                ),
                height=360,
                scrolling=False,
            )
            st.download_button(
                "Download Monthly End Uses (csv)",
                pd.DataFrame(d3_data["monthly_end_uses"]).to_csv(index=False),
                file_name="monthly_end_uses.csv",
                mime="text/csv",
            )

            st.subheader("Monthly EUI by Utility")
            components.html(
                create_monthly_timeseries_d3_html(
                    d3_data["monthly_fuels"],
                    d3_data["fuel_meters"],
                    d3_data["fuel_colors"],
                    "Monthly EUI by utility",
                    "EUI (kWh/m2)",
                ),
                height=360,
                scrolling=False,
            )
            st.download_button(
                "download monthly utilities (csv)",
                pd.DataFrame(d3_data["monthly_fuels"]).to_csv(index=False),
                file_name="monthly_utilities.csv",
                mime="text/csv",
            )
        with map_tab:
            st.markdown("### map")
            _build_rotated_rectangle_map(df, "height")
        return

    st.markdown("### map overview")
    if not has_geo_columns(df):
        st.info("expected columns 'lat' and 'lon'; map unavailable for this file.")
    elif not numeric_cols:
        st.info("no numeric columns available for height metric.")
    else:
        metric = st.selectbox("metric for column height", options=numeric_cols)
        _build_pydeck_chart(df, metric)

    st.markdown("### summary visualizations")
    if not numeric_cols:
        st.info("no numeric columns available for d3 summaries.")
        return

    value_col = st.selectbox("value column", options=numeric_cols, index=0)
    categorical_cols = list_categorical_columns(df)
    category_col = st.selectbox(
        "category column (optional)",
        options=["(none)", *categorical_cols],
        index=0,
    )
    category = None if category_col == "(none)" else category_col

    html = create_raw_data_d3_html(
        df, value_column=value_col, category_column=category, title="raw data summary"
    )
    components.html(html, height=700, scrolling=True)


def main() -> None:
    """Entry point for the visualization app."""
    st.set_page_config(page_title="GLOBI Visualization", layout="wide")
    st.title("GLOBI Visualization")

    base_dir = Path("outputs")

    page = st.sidebar.selectbox(
        "page",
        options=["Raw Data", "Use Case Implementation"],
        index=0,
    )

    if page == "Raw Data":
        _render_raw_data_page(base_dir)
        return

    st.subheader("Use Case Implementation")
    st.info(
        "this page will show processed use cases (overheating, retrofits, etc.). coming soon."
    )


if __name__ == "__main__":
    main()
