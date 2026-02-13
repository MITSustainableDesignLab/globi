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
    BUILDING_ID_COL,
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

    selected_run = st.selectbox(
        "Select Run",
        options=available_runs,
        index=max(len(available_runs) - 1, 0),
    )

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
        _render_results_map(df, run_label, data_source)


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


# todo: for dryrun runs, show a table instead of the map
def _render_results_map(  # noqa: C901
    df: pd.DataFrame,
    run_label: str,
    data_source: DataSource,
) -> None:
    """Render 3D building map for Results format."""
    # if a user selects a dryrun run, show a message and a table not a map
    if "dryrun" in run_label.lower():
        st.info("You have selected a dryrun which does not have a mapping option")
        st.markdown("### grid run outputs")
        st.dataframe(df)
        return

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

    energy_cols: list[tuple[object, ...]] = []
    peak_cols: list[tuple[object, ...]] = []
    end_use: str | None = None

    # compute per-building metrics (total energy and peak per sqm) from the
    # EnergyAndPeak-style dataframe and join onto the merged frame
    try:
        bid_col: tuple[object, ...] | None = None
        for col in df.columns:
            if isinstance(col, tuple) and any(
                isinstance(x, str) and x == "building_id" for x in col
            ):
                bid_col = col
                break
        if bid_col is None:
            raise ValueError("no building_id column in outputs")  # noqa: TRY003, TRY301

        bids = df[bid_col].astype("string")

        area_level: int | None = None
        for i, name in enumerate(df.index.names):
            if name == "feature.geometry.energy_model_conditioned_area":
                area_level = i
                break
        if area_level is None:
            raise ValueError("no conditioned area index level in outputs")  # noqa: TRY003, TRY301

        area = (
            pd.Series(df.index.get_level_values(area_level), index=df.index)
            .astype("float64")
            .replace(0, pd.NA)
        )

        energy_cols = [
            c
            for c in df.columns
            if isinstance(c, tuple) and c[0] == "Energy" and c[1] == "End Uses"
        ]
        peak_cols = [
            c
            for c in df.columns
            if isinstance(c, tuple) and c[0] == "Peak" and c[1] == "Raw"
        ]

        if not energy_cols or not peak_cols:
            raise ValueError("missing Energy/Peak columns in outputs")  # noqa: TRY003, TRY301

        total_energy = df[energy_cols].sum(axis=1)
        peak = df[peak_cols].max(axis=1)

        eui = (total_energy / area).astype("float64")
        peak_per_sqm = (peak / area).astype("float64")

        # per-end-use energy usage per sqm (for map coloring)
        end_uses = sorted({
            str(c[2]) for c in energy_cols if isinstance(c, tuple) and len(c) > 2
        })
        data_dict: dict[str, object] = {
            BUILDING_ID_COL: bids.values,
            "eui": eui.values,
            "peak_per_sqm": peak_per_sqm.values,
        }
        for meter in end_uses:
            cols_meter = [c for c in energy_cols if c[2] == meter]
            if not cols_meter:
                continue
            meter_total = df[cols_meter].sum(axis=1)
            meter_eui = (meter_total / area).astype("float64")
            key = f"eui_{meter.lower().replace(' ', '_')}"
            data_dict[key] = meter_eui.values

        metrics = pd.DataFrame(data_dict)

        merged = merged.merge(metrics, on=BUILDING_ID_COL, how="left")
    except Exception as exc:
        st.warning(f"could not compute EUI/peak metrics: {exc}")

    try:
        metric_choice = st.selectbox(
            "Metric for building color/height",
            options=[
                "Total energy usage per sqm",
                "Total peak per sqm",
                "End-use energy usage per sqm",
            ],
        )

        if metric_choice == "Total energy usage per sqm":
            height_col = "eui"
            cmap = "viridis"
        elif metric_choice == "Total peak per sqm":
            height_col = "peak_per_sqm"
            cmap = "plasma"
        else:
            # end-use selection
            available_end_uses = sorted({
                str(c[2]) for c in energy_cols if isinstance(c, tuple) and len(c) > 2
            })
            end_use = st.selectbox("End use", options=available_end_uses)
            if end_use is None:
                raise ValueError  # noqa: TRY301
            height_col = f"eui_{end_use.lower().replace(' ', '_')}"
            cmap = f"enduse_{end_use.lower().replace(' ', '_')}"

        features = extract_building_polygons(
            merged, height_col=height_col, value_col=height_col
        )
        if not features:
            st.info("No valid building polygons found.")
            return

        config = Building3DConfig()
        deck = create_polygon_layer_chart(
            features, config, cmap=cmap, value_key="value"
        )
        st.pydeck_chart(deck)

        # colorbar legend for the current colorscheme
        if metric_choice == "Total energy usage per sqm":
            label = "energy usage per sqm"
            gradient = (
                "linear-gradient(to right, #440154, #3b528b, #21918c, #5ec962, #fde725)"
            )
        elif metric_choice == "Total peak per sqm":
            label = "peak per sqm"
            gradient = (
                "linear-gradient(to right, #0d0887, #5c01a6, #9c179e, #ed7953, #f0f921)"
            )
        else:
            base_colors = {
                "heating": "#dc2626",
                "cooling": "#2563eb",
                "lighting": "#eab308",
                "equipment": "#10b981",
                "domestic hot water": "#f97316",
            }
            if end_use is not None:
                key = end_use.lower()
                base = base_colors.get(key, "#93c5fd")
                label = f"{end_use} energy per sqm"
            else:
                base = "#93c5fd"
                label = "end-use energy per sqm"
            gradient = f"linear-gradient(to right, {base}22, {base})"

        st.markdown(
            f"""
<div style="margin-top: 0.5rem; font-size: 0.85rem;">
  <div style="margin-bottom: 0.15rem;">{label} (low → high)</div>
  <div style="
    height: 12px;
    border-radius: 999px;
    background: {gradient};
    border: 1px solid #d1d5db;
  "></div>
</div>
""",
            unsafe_allow_html=True,
        )
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
