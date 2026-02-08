"""Raw Data Visualization page."""

from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.models import Building3DConfig
from globi.tools.visualization.plotting import (
    create_column_layer_chart,
    create_histogram_d3_html,
    create_monthly_timeseries_d3_html,
    create_pie_d3_html,
    create_polygon_layer_chart,
    create_raw_data_d3_html,
    extract_building_polygons,
)
from globi.tools.visualization.results_data import extract_d3_data, is_results_format
from globi.tools.visualization.utils import (
    LAT_COL,
    LON_COL,
    has_geo_columns,
    list_categorical_columns,
    list_numeric_columns,
    merge_with_building_locations,
)


def render_raw_data_page(data_source: DataSource) -> None:
    """Render the raw data visualization page."""
    st.subheader("Raw Outputs")

    available_runs = data_source.list_available_runs()
    if not available_runs:
        st.warning("No runs found in the configured data source.")
        return

    selected_run = st.selectbox("Select Run", options=available_runs)

    try:
        with st.spinner(f"Loading {selected_run}..."):
            df = data_source.load_run_data(selected_run)
    except Exception as e:
        st.error(f"Failed to load data: {e}")
        return

    st.caption(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")

    if is_results_format(df):
        _render_results_format(df, selected_run, data_source)
    else:
        _render_generic_format(df)


def _render_results_format(
    df: pd.DataFrame,
    run_label: str,
    data_source: DataSource,
) -> None:
    """Render Results.pq format with summary and map tabs."""
    summary_tab, map_tab = st.tabs(["Summary", "Map"])

    with summary_tab:
        _render_results_summary(df, run_label)

    with map_tab:
        _render_results_map(df, data_source)


def _render_results_summary(df: pd.DataFrame, run_label: str) -> None:
    """Render D3 summary visualizations for Results format."""
    st.markdown("### Results Summary")

    d3_data = extract_d3_data(df, region_name=run_label, scenario_name="")

    st.subheader("EUI Distribution")
    components.html(
        create_histogram_d3_html(d3_data["eui"], "EUI Distribution", "EUI (kWh/m2)"),
        height=320,
        scrolling=False,
    )
    st.download_button(
        "Download EUI Values (CSV)",
        pd.Series(d3_data["eui"], name="eui").to_csv(index=False),
        file_name="eui_values.csv",
        mime="text/csv",
    )

    st.subheader("Peak Distribution")
    components.html(
        create_histogram_d3_html(d3_data["peak"], "Peak Distribution", "Peak (kW/m2)"),
        height=320,
        scrolling=False,
    )
    st.download_button(
        "Download Peak Values (CSV)",
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
                "End Uses Share",
                d3_data["end_use_colors"],
            ),
            height=320,
            scrolling=False,
        )
        st.download_button(
            "Download End Use Totals (CSV)",
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
                "Utilities Share",
                d3_data["fuel_colors"],
            ),
            height=320,
            scrolling=False,
        )
        st.download_button(
            "Download Utilities Totals (CSV)",
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
            "Monthly EUI by End Use",
            "EUI (kWh/m2)",
        ),
        height=360,
        scrolling=False,
    )
    st.download_button(
        "Download Monthly End Uses (CSV)",
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
            "Monthly EUI by Utility",
            "EUI (kWh/m2)",
        ),
        height=360,
        scrolling=False,
    )
    st.download_button(
        "Download Monthly Utilities (CSV)",
        pd.DataFrame(d3_data["monthly_fuels"]).to_csv(index=False),
        file_name="monthly_utilities.csv",
        mime="text/csv",
    )


def _render_results_map(df: pd.DataFrame, data_source: DataSource) -> None:
    """Render 3D building map for Results format."""
    st.markdown("### 3D Building Map")

    locations_df = data_source.load_building_locations()
    if locations_df is None:
        st.info(
            "Building locations not available. Place inputs/buildings.parquet in working directory."
        )
        return

    merged = merge_with_building_locations(df, locations_df)
    if merged is None:
        st.info("No matching building IDs between outputs and locations.")
        return

    try:
        features = extract_building_polygons(merged, "height")
        if not features:
            st.info("No valid building polygons found.")
            return

        config = Building3DConfig()
        deck = create_polygon_layer_chart(features, config)
        st.pydeck_chart(deck)
    except ValueError as e:
        st.warning(str(e))


def _render_generic_format(df: pd.DataFrame) -> None:
    """Render generic parquet format with map and D3 summaries."""
    numeric_cols = list_numeric_columns(
        df, exclude=[LAT_COL, LON_COL] if has_geo_columns(df) else None
    )

    st.markdown("### Map Overview")
    if not has_geo_columns(df):
        st.info("No lat/lon columns found; map unavailable.")
    elif not numeric_cols:
        st.info("No numeric columns available for height metric.")
    else:
        metric = st.selectbox("Metric for Column Height", options=numeric_cols)
        try:
            deck = create_column_layer_chart(df, metric)
            st.pydeck_chart(deck)
        except ValueError as e:
            st.warning(str(e))

    st.markdown("### Summary Visualizations")
    if not numeric_cols:
        st.info("No numeric columns available for summaries.")
        return

    value_col = st.selectbox("Value Column", options=numeric_cols, index=0)
    categorical_cols = list_categorical_columns(df)
    category_col = st.selectbox(
        "Category Column (optional)",
        options=["(none)", *categorical_cols],
        index=0,
    )
    category = None if category_col == "(none)" else category_col

    html = create_raw_data_d3_html(
        df, value_column=value_col, category_column=category, title="Raw Data Summary"
    )
    components.html(html, height=700, scrolling=True)
