"""Explore a run: headline numbers, charts, map and a buildings table for one run."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.plotting import (
    EnergyIntensityUnit,
    convert_energy_intensity_values,
    create_building_map_deck,
    create_building_map_deck_from_cache,
    create_column_layer_chart,
    create_histogram_d3_html,
    create_monthly_timeseries_d3_html,
    create_pie_d3_html,
    create_raw_data_d3_html,
    energy_intensity_axis_label,
    energy_intensity_factor,
    scale_monthly_eui_records,
)
from globi.tools.visualization.results_data import (
    extract_d3_data,
    filter_candidates,
    filter_label,
    filter_mask,
    is_results_format,
    per_building_metrics,
    portfolio_kpis,
)
from globi.tools.visualization.utils import (
    LAT_COL,
    LON_COL,
    build_map_df_and_geometry_from_output,
    has_geo_columns,
    has_rotated_rectangle_for_visualization,
    infer_rotated_rectangle_crs_hint,
    list_categorical_columns,
    list_numeric_columns,
    read_parquet_sample_for_crs_inference,
)
from globi.tools.visualization.views.common import (
    building_filters,
    cached_load_run_parquet,
    eui_unit,
    eui_unit_suffix,
    kpi_row,
    load_run,
    map_caption,
    map_crs_caption,
    render_colormap_legend,
    resolve_map_crs,
    run_label,
    section_download,
    streamlit_theme,
)

_MAX_CONDITIONED_AREA_M2 = 10_000.0
_MAP_MAX_BUILDINGS_WITHOUT_DOWNSAMPLE = 250_000
# the buildings table shows at most this many rows; the CSV download has them all
_TABLE_ROWS = 10_000


@st.cache_data(show_spinner=False)
def _cached_extract_d3_for_run(path_str: str, mtime: float, run_label: str) -> dict:
    df = cached_load_run_parquet(path_str, mtime)
    return extract_d3_data(df, region_name=run_label, scenario_name="")


@st.cache_data(show_spinner=False)
def _cached_crs_hint_from_pq(path_str: str, mtime: float) -> dict:
    sample = read_parquet_sample_for_crs_inference(Path(path_str), max_rows=80)
    if sample is None or sample.empty:
        return {
            "has_footprints": False,
            "suggested_crs": None,
            "scores": {},
            "n_geoms": 0,
            "native_bounds": None,
            "ambiguous": False,
            "tied_crs": (),
        }
    return infer_rotated_rectangle_crs_hint(sample)


@st.cache_data(show_spinner="Building map data (geometry + metrics)...")
def _build_map_cache_local(
    path_str: str,
    mtime: float,
    cart_crs: str,
    max_buildings: int | None,
    _df: pd.DataFrame,
):
    """Map cache keyed by parquet path, mtime, and CRS; dataframe body not hashed."""
    pair = build_map_df_and_geometry_from_output(
        _df, cart_crs=cart_crs, max_buildings=max_buildings
    )
    if pair is None:
        return None
    map_df, geometry = pair
    return map_df, geometry


@st.cache_data(show_spinner="Building map data (geometry + metrics)...")
def _build_map_cache_remote(
    run_label: str, cart_crs: str, max_buildings: int | None, _df: pd.DataFrame
):
    """Fallback when parquet path identity is unavailable (e.g. S3)."""
    pair = build_map_df_and_geometry_from_output(
        _df, cart_crs=cart_crs, max_buildings=max_buildings
    )
    if pair is None:
        return None
    return pair[0], pair[1]


def _trim_map_df_for_render(
    map_df: pd.DataFrame,
    value_col: str | tuple | None,
) -> pd.DataFrame:
    """Keep only columns required for map rendering (and the id for tooltips)."""
    keep_cols: list[str | tuple] = [
        c for c in ("building_id", "conditioned_area") if c in map_df.columns
    ]
    if (
        value_col is not None
        and value_col in map_df.columns
        and value_col not in keep_cols
    ):
        keep_cols.append(value_col)
    if not keep_cols:
        return map_df.iloc[:, 0:0].copy()
    return map_df.loc[:, keep_cols].copy()


def _filter_map_cache_by_conditioned_area(
    geometry: list[dict],
    map_df: pd.DataFrame,
    max_conditioned_area_m2: float | None,
) -> tuple[list[dict], pd.DataFrame]:
    """Filter cached geometry/map rows by conditioned area before rendering."""
    if (
        max_conditioned_area_m2 is None
        or max_conditioned_area_m2 <= 0
        or "conditioned_area" not in map_df.columns
        or len(geometry) != len(map_df)
    ):
        return geometry, map_df

    area = cast(
        pd.Series, pd.to_numeric(map_df["conditioned_area"], errors="coerce")
    ).to_numpy()
    keep = np.isnan(area) | (area <= float(max_conditioned_area_m2))
    return _subset_map_cache(geometry, map_df, keep)


def _subset_map_cache(
    geometry: list[dict], map_df: pd.DataFrame, keep: np.ndarray
) -> tuple[list[dict], pd.DataFrame]:
    """Keep the same rows of the aligned (geometry, map_df) pair."""
    if keep.all():
        return geometry, map_df
    filtered_geometry = [g for g, k in zip(geometry, keep, strict=True) if k]
    return filtered_geometry, map_df.loc[keep].reset_index(drop=True)


def _auto_downsample_max_buildings(geometry: list[dict]) -> int | None:
    """Only cap maps larger than 250k buildings."""
    if len(geometry) <= _MAP_MAX_BUILDINGS_WITHOUT_DOWNSAMPLE:
        return None
    return _MAP_MAX_BUILDINGS_WITHOUT_DOWNSAMPLE


def _select_and_load_run(
    data_source: DataSource,
    *,
    run_key: str = "explore_run",
) -> tuple[str, pd.DataFrame, tuple[str, float] | None] | None:
    """Select run and load parquet once for the current page."""
    available_runs = data_source.list_available_runs()
    if not available_runs:
        st.info("No runs found. Check the data source in the sidebar.")
        return None

    selected_run = st.selectbox(
        "Run", options=available_runs, format_func=run_label, key=run_key
    )

    try:
        df, pq_token = load_run(data_source, selected_run)
    except Exception as e:
        st.error(f"Couldn't load this run: {e}")
        return None

    return selected_run, df, pq_token


def _crs_hint(df: pd.DataFrame, pq_token: tuple[str, float] | None) -> dict:
    if pq_token is not None:
        return _cached_crs_hint_from_pq(pq_token[0], pq_token[1])
    return infer_rotated_rectangle_crs_hint(df.iloc[: min(400, len(df))])


def render_raw_data_page(data_source: DataSource) -> None:
    """Render the Explore a run page."""
    st.header("Explore a run")
    loaded = _select_and_load_run(data_source)
    if loaded is None:
        return
    selected_run, df, pq_token = loaded

    if not is_results_format(df):
        _render_generic_format(df, selected_run, pq_token)
        return

    unit = eui_unit()
    selections = building_filters(df)
    mask = filter_mask(df, selections)
    if not mask.any():
        st.warning("No buildings match the filters.")
        return
    view = df if mask.all() else cast(pd.DataFrame, df[mask])
    if not mask.all():
        st.caption(f"Showing {mask.sum():,} of {len(df):,} buildings (filtered)")
    kpi_row(portfolio_kpis(view), unit)

    # one view at a time: st.tabs would build the map (slow at 100k) on every rerun
    view_name = st.radio(
        "View",
        options=["Charts", "Map", "Buildings"],
        horizontal=True,
        key="explore_view",
        label_visibility="collapsed",
    )
    if view_name == "Charts":
        # the unfiltered summary is cached by file; a filtered one is recomputed
        if pq_token is not None and mask.all():
            d3_data = _cached_extract_d3_for_run(pq_token[0], pq_token[1], selected_run)
        else:
            d3_data = extract_d3_data(view, region_name=selected_run, scenario_name="")
        _render_results_summary(d3_data, unit)
    elif view_name == "Map":
        _render_results_map(
            df, selected_run, unit, pq_token, mask, f"{selected_run}|{selections!r}"
        )
    else:
        _render_buildings_table(view, unit, f"{selected_run}|{selections!r}")


def _render_results_summary(d3_data: dict, eui_unit: EnergyIntensityUnit) -> None:
    """D3 summary charts for Results format, with one download for all of them."""
    theme = streamlit_theme()
    eui_lbl = energy_intensity_axis_label(eui_unit)
    files: dict[str, str] = {}

    def chart(name: str, html: str, csv: str, height: int) -> None:
        components.html(html, height=height, scrolling=False)
        files[f"{name}.html"] = html
        files[f"{name}.csv"] = csv

    col_eui, col_peak = st.columns(2)
    with col_eui:
        st.markdown("#### Energy use intensity")
        eui_vals = convert_energy_intensity_values(d3_data["eui"], eui_unit)
        chart(
            "eui",
            create_histogram_d3_html(
                eui_vals, "EUI Distribution", eui_lbl, theme=theme
            ),
            pd.Series(eui_vals, name="eui").to_csv(index=False),
            320,
        )
    with col_peak:
        st.markdown("#### Peak demand")
        chart(
            "peak",
            create_histogram_d3_html(
                d3_data["peak"], "Peak Distribution", "Peak (kW/m²)", theme=theme
            ),
            pd.Series(d3_data["peak"], name="peak_kw_m2").to_csv(index=False),
            320,
        )

    col_end_uses, col_utilities = st.columns(2)
    with col_end_uses:
        st.markdown("#### End uses")
        chart(
            "end_uses",
            create_pie_d3_html(
                d3_data["end_uses_total"],
                "End Uses Share",
                d3_data["end_use_colors"],
                theme=theme,
            ),
            pd.Series(d3_data["end_uses_total"], name="energy_kwh")
            .rename_axis("end_use")
            .to_csv(),
            320,
        )
    with col_utilities:
        st.markdown("#### Fuels")
        chart(
            "fuels",
            create_pie_d3_html(
                d3_data["utilities_total"],
                "Utilities Share",
                d3_data["fuel_colors"],
                theme=theme,
            ),
            pd.Series(d3_data["utilities_total"], name="energy_kwh")
            .rename_axis("fuel")
            .to_csv(),
            320,
        )

    st.markdown("#### Monthly EUI by end use")
    monthly_eu = scale_monthly_eui_records(d3_data["monthly_end_uses"], eui_unit)
    chart(
        "monthly_end_uses",
        create_monthly_timeseries_d3_html(
            monthly_eu,
            d3_data["end_use_meters"],
            d3_data["end_use_colors"],
            "Monthly EUI by End Use",
            eui_lbl,
            theme=theme,
        ),
        pd.DataFrame(monthly_eu).to_csv(index=False),
        360,
    )

    st.markdown("#### Monthly EUI by fuel")
    monthly_fu = scale_monthly_eui_records(d3_data["monthly_fuels"], eui_unit)
    chart(
        "monthly_fuels",
        create_monthly_timeseries_d3_html(
            monthly_fu,
            d3_data["fuel_meters"],
            d3_data["fuel_colors"],
            "Monthly EUI by Utility",
            eui_lbl,
            theme=theme,
        ),
        pd.DataFrame(monthly_fu).to_csv(index=False),
        360,
    )

    section_download(files, "run_charts", key="dl_run_charts")


@st.fragment
def _render_results_map(
    df: pd.DataFrame,
    run_label: str,
    eui_unit: EnergyIntensityUnit,
    pq_token: tuple[str, float] | None,
    mask: np.ndarray,
    filter_key: str,
) -> None:
    """3D building map coloured by a chosen measure; geometry is cached per run and CRS."""
    run_norm = run_label.replace("\\", "/").strip("/")
    if any(seg.lower() == "dryrun" for seg in run_norm.split("/") if seg):
        st.info(
            "Dry runs have no building footprints to map; here are the raw outputs."
        )
        st.dataframe(df)
        return

    hint = _crs_hint(df, pq_token)
    cart_crs = resolve_map_crs(hint)

    eui_lbl = energy_intensity_axis_label(eui_unit)
    value_col, cmap, metric_label = st.selectbox(
        "Colour by",
        options=[
            ("eui", "greens", eui_lbl),
            ("total_energy", "viridis", "Annual energy (kWh)"),
            ("peak_per_sqm", "reds", "Peak per m² (kW/m²)"),
            ("total_peak", "plasma", "Peak (kW)"),
            (None, "viridis", "No colour"),
        ],
        format_func=lambda x: x[2],
        key="map_metric",
    )

    if pq_token is not None:
        cached = _build_map_cache_local(pq_token[0], pq_token[1], cart_crs, None, df)
    else:
        cached = _build_map_cache_remote(run_label, cart_crs, None, df)
    hidden_large = 0
    max_buildings: int | None = None
    if cached is not None:
        map_df, geometry = cached
        if not mask.all() and "building_id" in map_df.columns:
            allowed = set(df.index.get_level_values("building_id")[mask].astype(str))
            keep = map_df["building_id"].astype(str).isin(list(allowed)).to_numpy()
            geometry, map_df = _subset_map_cache(geometry, map_df, keep)
        n_before = len(geometry)
        geometry, map_df = _filter_map_cache_by_conditioned_area(
            geometry, map_df, _MAX_CONDITIONED_AREA_M2
        )
        hidden_large = n_before - len(geometry)
        map_df = _trim_map_df_for_render(map_df, value_col)
        max_buildings = _auto_downsample_max_buildings(geometry)
        result = create_building_map_deck_from_cache(
            geometry,
            map_df,
            value_col=value_col,
            cmap=cmap,
            max_buildings=max_buildings,
            eui_unit=eui_unit,
            value_label=metric_label,
        )
        n_total = len(geometry)
    else:
        result = create_building_map_deck(
            df if mask.all() else cast(pd.DataFrame, df[mask]),
            cart_crs=cart_crs,
            value_col=value_col,
            cmap=cmap,
            max_conditioned_area_m2=_MAX_CONDITIONED_AREA_M2,
            eui_unit=eui_unit,
            value_label=metric_label,
        )
        n_total = None
    if result is None:
        st.info(
            "No building footprints could be placed on the map. Check the "
            "map coordinate system under Settings in the sidebar."
        )
        return

    deck, n_features, value_stats = result
    st.pydeck_chart(deck)
    map_caption(
        n_features,
        hidden_large=hidden_large,
        downsampled_from=n_total if max_buildings else None,
    )
    map_crs_caption(hint, cart_crs)
    if value_col and value_stats:
        render_colormap_legend(metric_label, value_stats, cmap)

    _map_download(deck, f"{filter_key}|{cart_crs}|{value_col}|{eui_unit}", "results")


def _map_download(deck, settings_key: str, key: str) -> None:
    """Map as a standalone HTML file, built only when asked for (it is large at 100k buildings)."""
    state_key = f"_map_html_{key}"
    ready = st.session_state.get(state_key)
    if ready is None or ready[0] != settings_key:
        if st.button(
            "Prepare map download", icon=":material/download:", key=f"prep_{key}"
        ):
            with st.spinner("Preparing map file..."):
                st.session_state[state_key] = (
                    settings_key,
                    str(deck.to_html(as_string=True) or ""),
                )
            ready = st.session_state[state_key]
        else:
            return
    st.download_button(
        "Download map (HTML)",
        data=ready[1],
        file_name="building_map.html",
        mime="text/html",
        icon=":material/download:",
        on_click="ignore",
        key=f"download_map_html_{key}",
    )


@st.cache_data(max_entries=4, show_spinner=False)
def _buildings_csv(_table: pd.DataFrame, cache_key: str) -> str:
    """CSV of the buildings table; keyed on run + filters since the frame itself isn't hashed."""
    return _table.to_csv(index=False)


def _render_buildings_table(
    df: pd.DataFrame, unit: EnergyIntensityUnit, cache_key: str
) -> None:
    """Per-building table, highest EUI first, with the building attributes."""
    metrics = per_building_metrics(df)
    if metrics is None:
        st.info("No per-building results in this run.")
        return
    attrs = [c for c in filter_candidates(df) if not c.endswith("conditioned_area")]
    table = pd.concat(
        [
            metrics[["building_id", "eui", "peak_per_sqm", "area", "total_energy"]]
            .assign(eui=metrics["eui"] * energy_intensity_factor(unit))
            .round({"area": 0, "total_energy": 0}),
            pd.DataFrame({
                filter_label(a): df.index.get_level_values(a) for a in attrs
            }),
        ],
        axis=1,
    ).sort_values("eui", ascending=False)

    st.dataframe(
        table.head(_TABLE_ROWS),
        hide_index=True,
        column_config={
            "building_id": st.column_config.TextColumn("Building"),
            "eui": st.column_config.NumberColumn(
                f"EUI ({eui_unit_suffix(unit)})", format="%.1f"
            ),
            "peak_per_sqm": st.column_config.NumberColumn(
                "Peak (kW/m²)", format="%.3f"
            ),
            "area": st.column_config.NumberColumn(
                "Floor area (m²)", format="localized"
            ),
            "total_energy": st.column_config.NumberColumn(
                "Annual energy (kWh)", format="localized"
            ),
        },
    )
    if len(table) > _TABLE_ROWS:
        st.caption(
            f"Showing the {_TABLE_ROWS:,} highest-EUI buildings of {len(table):,}. "
            "The download has all of them."
        )
    st.download_button(
        "Download table (CSV)",
        data=_buildings_csv(table, cache_key),
        file_name="buildings.csv",
        mime="text/csv",
        icon=":material/download:",
        on_click="ignore",
        key="dl_buildings",
    )


def _render_generic_rotated_rectangle_map(
    df: pd.DataFrame,
    run_label: str,
    safe_key: str,
    pq_token: tuple[str, float] | None,
) -> None:
    """Footprint + extrusion map for flat or mixed parquet (no Summary tab MultiIndex required)."""
    hint = _crs_hint(df, pq_token)
    cart_crs = resolve_map_crs(hint)
    numeric_cols = list_numeric_columns(df)
    map_color_col: str | tuple | None = None
    cmap = "viridis"
    metric_label = "metric"
    if numeric_cols:
        choice = st.selectbox(
            "Colour by",
            options=["(none)", *numeric_cols],
            format_func=lambda x: "(none)" if x == "(none)" else str(x),
            key=f"generic_rr_metric_{safe_key}",
        )
        if choice != "(none)":
            map_color_col = choice
            metric_label = str(choice)
    max_buildings: int | None = None
    if pq_token is not None:
        cached = _build_map_cache_local(pq_token[0], pq_token[1], cart_crs, None, df)
    else:
        cached = _build_map_cache_remote(f"generic:{run_label}", cart_crs, None, df)
    hidden_large = 0
    if cached is not None:
        map_df, geometry = cached
        n_before = len(geometry)
        geometry, map_df = _filter_map_cache_by_conditioned_area(
            geometry, map_df, _MAX_CONDITIONED_AREA_M2
        )
        hidden_large = n_before - len(geometry)
        map_df = _trim_map_df_for_render(map_df, map_color_col)
        max_buildings = _auto_downsample_max_buildings(geometry)
        result = create_building_map_deck_from_cache(
            geometry,
            map_df,
            value_col=map_color_col,
            cmap=cmap,
            max_buildings=max_buildings,
            value_label=metric_label,
        )
    else:
        result = create_building_map_deck(
            df,
            cart_crs=cart_crs,
            value_col=map_color_col,
            cmap=cmap,
            max_conditioned_area_m2=_MAX_CONDITIONED_AREA_M2,
            value_label=metric_label,
        )
    if result is None:
        st.info(
            "Could not build the footprint map. Check the map coordinate system "
            "under Settings in the sidebar."
        )
        return
    deck, n_features, value_stats = result
    st.pydeck_chart(deck)
    map_caption(n_features, hidden_large=hidden_large)
    map_crs_caption(hint, cart_crs)
    if map_color_col and value_stats:
        render_colormap_legend(metric_label, value_stats, cmap)
    _map_download(
        deck, f"{run_label}|{cart_crs}|{map_color_col}", f"generic_{safe_key}"
    )


def _render_generic_format(
    df: pd.DataFrame, run_label: str, pq_token: tuple[str, float] | None
) -> None:
    """Render generic parquet format with map and D3 summaries."""
    map_tab, summary_tab = st.tabs(["Map", "Summary"])
    with map_tab:
        _render_generic_map(df, run_label, pq_token)
    with summary_tab:
        _render_generic_summary(df)


def _render_generic_map(
    df: pd.DataFrame, run_label: str, pq_token: tuple[str, float] | None
) -> None:
    """Render generic parquet map section only."""
    numeric_cols = list_numeric_columns(
        df, exclude=[LAT_COL, LON_COL] if has_geo_columns(df) else None
    )
    safe_key = run_label.replace("/", "_").replace("\\", "_")
    if has_rotated_rectangle_for_visualization(df):
        _render_generic_rotated_rectangle_map(df, run_label, safe_key, pq_token)
    elif has_geo_columns(df):
        if not numeric_cols:
            st.info("No numeric columns available for height metric.")
        else:
            metric = st.selectbox("Metric for column height", options=numeric_cols)
            try:
                deck = create_column_layer_chart(df, metric)
                st.pydeck_chart(deck)
            except ValueError as e:
                st.warning(str(e))
    else:
        st.info(
            "This file has no building footprints or lat/lon columns, so it can't be mapped."
        )


def _render_generic_summary(df: pd.DataFrame) -> None:
    """Render generic parquet summary section only."""
    theme = streamlit_theme()
    numeric_cols = list_numeric_columns(
        df, exclude=[LAT_COL, LON_COL] if has_geo_columns(df) else None
    )
    if not numeric_cols:
        st.info("No numeric columns available for summaries.")
        return

    summary_value_col = st.selectbox("Value column", options=numeric_cols, index=0)
    categorical_cols = list_categorical_columns(df)
    category_col = st.selectbox(
        "Group by (optional)",
        options=["(none)", *categorical_cols],
        index=0,
    )
    category = None if category_col == "(none)" else category_col

    raw_summary_html = create_raw_data_d3_html(
        df,
        value_column=summary_value_col,
        category_column=category,
        title="Raw Data Summary",
        theme=theme,
    )
    components.html(raw_summary_html, height=700, scrolling=True)
    section_download(
        {
            "raw_data_summary.html": raw_summary_html,
            "raw_data_summary.csv": cast(
                pd.DataFrame, df[[summary_value_col] + ([category] if category else [])]
            ).to_csv(index=False),
        },
        "raw_data_summary",
        key="dl_raw_summary",
    )
