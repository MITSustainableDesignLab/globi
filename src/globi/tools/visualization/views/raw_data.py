"""Raw Data Visualization page."""

from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.export import render_html_to_png
from globi.tools.visualization.models import Building3DConfig
from globi.tools.visualization.plotting import (
    Theme,
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


def _streamlit_theme() -> Theme:
    """Detect Streamlit theme (light/dark) for embedded D3 charts."""
    try:
        ctx = getattr(st, "context", None)
        if ctx is not None and hasattr(ctx, "theme"):
            t = getattr(ctx.theme, "base", None) or getattr(ctx.theme, "type", None)
            if t in ("light", "dark"):
                return t
    except Exception:  # noqa: S110
        pass
    try:
        base = st.get_option("theme.base")
        if base in ("light", "dark"):
            return base
    except Exception:  # noqa: S110
        pass
    return "light"


def _chart_download(
    key: str,
    csv_data: str,
    html_content: str,
    base_filename: str,
) -> None:
    """Single download control: format dropdown + download button (CSV, HTML, PNG)."""
    col_sel, col_btn = st.columns([1, 2])
    with col_sel:
        fmt = st.selectbox(
            "Download as",
            options=["CSV", "HTML", "PNG"],
            key=f"format_{key}",
        )
    with col_btn:
        disabled = False
        if fmt == "CSV":
            data, mime, fname = csv_data, "text/csv", f"{base_filename}.csv"
        elif fmt == "HTML":
            data, mime, fname = html_content, "text/html", f"{base_filename}.html"
        else:
            cache_key = f"_png_{key}"
            if cache_key not in st.session_state:
                with st.spinner("Generating PNG..."):
                    st.session_state[cache_key] = render_html_to_png(html_content)
            png_bytes = st.session_state[cache_key]
            if png_bytes is None:
                st.caption(
                    "PNG requires: uv add playwright && uv run playwright install chromium"
                )
                data, mime, fname = b"", "image/png", f"{base_filename}.png"
                disabled = True
            else:
                data, mime, fname = png_bytes, "image/png", f"{base_filename}.png"
        st.download_button(
            "Download",
            data=data,
            file_name=fname,
            mime=mime,
            key=f"dl_{key}",
            disabled=disabled,
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
    theme = _streamlit_theme()
    d3_data = extract_d3_data(df, region_name=run_label, scenario_name="")

    st.subheader("EUI Distribution")
    eui_html = create_histogram_d3_html(
        d3_data["eui"], "EUI Distribution", "EUI (kWh/m2)", theme=theme
    )
    components.html(eui_html, height=320, scrolling=False)
    _chart_download(
        "eui",
        pd.Series(d3_data["eui"], name="eui").to_csv(index=False),
        eui_html,
        "eui_values",
    )

    st.subheader("Peak Distribution")
    peak_html = create_histogram_d3_html(
        d3_data["peak"], "Peak Distribution", "Peak (kW/m2)", theme=theme
    )
    components.html(peak_html, height=320, scrolling=False)
    _chart_download(
        "peak",
        pd.Series(d3_data["peak"], name="peak").to_csv(index=False),
        peak_html,
        "peak_values",
    )

    st.subheader("End Uses and Utilities Share")
    col_end_uses, col_utilities = st.columns(2)

    with col_end_uses:
        end_uses_html = create_pie_d3_html(
            d3_data["end_uses_total"],
            "End Uses Share",
            d3_data["end_use_colors"],
            theme=theme,
        )
        components.html(end_uses_html, height=320, scrolling=False)
        _chart_download(
            "end_uses",
            pd.Series(d3_data["end_uses_total"], name="energy_kwh")
            .rename_axis("end_use")
            .to_csv(),
            end_uses_html,
            "end_uses_total",
        )

    with col_utilities:
        utilities_html = create_pie_d3_html(
            d3_data["utilities_total"],
            "Utilities Share",
            d3_data["fuel_colors"],
            theme=theme,
        )
        components.html(utilities_html, height=320, scrolling=False)
        _chart_download(
            "utilities",
            pd.Series(d3_data["utilities_total"], name="energy_kwh")
            .rename_axis("utility")
            .to_csv(),
            utilities_html,
            "utilities_total",
        )

    st.subheader("Monthly EUI by End Use")
    monthly_end_uses_html = create_monthly_timeseries_d3_html(
        d3_data["monthly_end_uses"],
        d3_data["end_use_meters"],
        d3_data["end_use_colors"],
        "Monthly EUI by End Use",
        "EUI (kWh/m2)",
        theme=theme,
    )
    components.html(monthly_end_uses_html, height=360, scrolling=False)
    _chart_download(
        "monthly_end_uses",
        pd.DataFrame(d3_data["monthly_end_uses"]).to_csv(index=False),
        monthly_end_uses_html,
        "monthly_end_uses",
    )

    st.subheader("Monthly EUI by Utility")
    monthly_utilities_html = create_monthly_timeseries_d3_html(
        d3_data["monthly_fuels"],
        d3_data["fuel_meters"],
        d3_data["fuel_colors"],
        "Monthly EUI by Utility",
        "EUI (kWh/m2)",
        theme=theme,
    )
    components.html(monthly_utilities_html, height=360, scrolling=False)
    _chart_download(
        "monthly_utilities",
        pd.DataFrame(d3_data["monthly_fuels"]).to_csv(index=False),
        monthly_utilities_html,
        "monthly_utilities",
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
    theme = _streamlit_theme()
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

    raw_summary_html = create_raw_data_d3_html(
        df,
        value_column=value_col,
        category_column=category,
        title="Raw Data Summary",
        theme=theme,
    )
    components.html(raw_summary_html, height=700, scrolling=True)
    _chart_download(
        "raw_summary",
        df[[value_col] + ([category] if category else [])].to_csv(index=False),
        raw_summary_html,
        "raw_data_summary",
    )
