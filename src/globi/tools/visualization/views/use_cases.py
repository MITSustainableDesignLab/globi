"""Use Cases page for specialized analyses."""

from __future__ import annotations

import contextlib
import math
from collections.abc import Callable
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.plotting import (
    Theme,
    convert_energy_intensity_values,
    create_binned_bar_d3_html,
    create_box_plot_by_floors_d3_html,
    create_building_map_deck,
    create_building_map_deck_from_cache,
    create_flat_footprint_deck,
    create_heat_index_stacked_bar_d3_html,
    create_histogram_d3_html,
    create_overheating_threshold_fan_d3_html,
    create_parallel_coordinates_d3_html,
    create_scatter_d3_html,
    create_threshold_overlay_kde_d3_html,
    create_threshold_sensitivity_dot_range_d3_html,
    energy_intensity_axis_label,
    energy_intensity_factor,
)
from globi.tools.visualization.results_data import filter_mask
from globi.tools.visualization.utils import (
    BUILDING_ID_COL,
    build_building_area_df,
    build_consecutive_exceedances_building_df,
    build_eui_vs_edh_df,
    build_heat_index_per_building_df,
    build_overheating_map_df,
    build_overheating_threshold_fan_wide_df,
    build_portfolio_multi_metric_df,
    build_priority_table_df,
    build_run_buildings_df,
    build_worst_zone_ratio_df,
    get_overheating_file_for_run,
    get_pq_file_for_run,
    infer_rotated_rectangle_crs_hint,
    read_parquet_sample_for_crs_inference,
    sample_overheating_fan_payload,
    threshold_sensitivity_from_wide,
)
from globi.tools.visualization.views.common import (
    building_filters,
    load_run,
    resolve_map_crs,
    run_label,
)
from globi.tools.visualization.views.common import (
    eui_unit as current_eui_unit,
)
from globi.tools.visualization.views.common import (
    render_colormap_legend as _render_colormap_legend,
)
from globi.tools.visualization.views.common import (
    streamlit_theme as _streamlit_theme,
)

_OH_HIST_NBINS = 40

# ---------------------------------------------------------------------------
# Formula strings — drawn from docs/reference/overheating_metrics.md
# ---------------------------------------------------------------------------
_FORMULA_BASIC_ZONE = r"H^{\text{over}}_{k,z} = \sum_{t=0}^{8759} \mathbf{1}\!\left[T_{\mathrm{db},z,t} > T^{\text{heat}}_k\right]"
_FORMULA_BASIC_ZW = r"\text{Zone Weighted} = \sum_z \tilde{w}_z\, H^{\text{over}}_{k,z}, \quad \tilde{w}_z = w_z \big/ \textstyle\sum_j w_j"
_FORMULA_BASIC_WZ = r"\text{Worst Zone} = \max_z H^{\text{over}}_{k,z}"
_FORMULA_EDH_ZONE = r"\mathrm{EDH}^{\text{hot}}_{k,z} = \sum_{t=0}^{8759} \max\!\bigl(0,\; \mathrm{SET}_{z,t} - T^{\text{heat}}_k\bigr)"
_FORMULA_EDH_ZW = (
    r"\text{Zone Weighted} = \sum_z \tilde{w}_z\, \mathrm{EDH}^{\text{hot}}_{k,z}"
)
_FORMULA_EDH_WZ = r"\text{Worst Zone} = \max_z \mathrm{EDH}^{\text{hot}}_{k,z}"
_FORMULA_HI_REG = (
    r"\mathrm{HI} = -42.379 + 2.049\,T_{\!f} + 10.143\,\mathrm{RH}"
    r" - 0.225\,T_{\!f}\mathrm{RH} - 6.84\times10^{-3}T_{\!f}^2"
    r" - 5.48\times10^{-2}\mathrm{RH}^2 + \cdots"
)
_FORMULA_HI_ZW = r"\overline{\mathrm{HI}}_t = \sum_z \tilde{w}_z\, \mathrm{HI}_{z,t}"
_FORMULA_STREAK = (
    r"\text{max\_streak\_hr} = \max_{\text{zone } z,\; \text{run } r}"
    r"\; L_r \quad \text{where } L_r = \#\{t \in \text{run } r : T_{\mathrm{db},z,t} > T^{\text{heat}}_k\}"
)


def _formula_expander(label: str, items: list[tuple[str | None, str | None]]) -> None:
    """Render a collapsed expander with text + LaTeX formula pairs.

    Args:
        label: expander button label.
        items: list of (markdown_text, latex_string) pairs; either may be None.
    """
    with st.expander(label, expanded=False):
        for text, latex in items:
            if text:
                st.markdown(text)
            if latex:
                st.latex(latex)


def _overheating_metric_bin_colors(n_bins: int) -> list[str]:
    """Left bin (low metric) -> yellows, middle -> oranges, right (high) -> reds."""
    if n_bins <= 0:
        return []
    c0 = np.array([254.0, 240.0, 138.0])
    c1 = np.array([249.0, 115.0, 22.0])
    c2 = np.array([185.0, 28.0, 28.0])
    out: list[str] = []
    for i in range(n_bins):
        t = i / max(n_bins - 1, 1)
        if t <= 0.5:
            u = t / 0.5
            rgb = c0 * (1.0 - u) + c1 * u
        else:
            u = (t - 0.5) / 0.5
            rgb = c1 * (1.0 - u) + c2 * u
        rgb_u = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
        out.append(f"#{rgb_u[0]:02x}{rgb_u[1]:02x}{rgb_u[2]:02x}")
    return out


def _render_overheating_metric_histograms(
    vals_list: list[float],
    area_weights: list[float] | None,
    x_hist: str,
    theme: Theme,
) -> tuple[str, str | None, np.ndarray | None, np.ndarray | None]:
    """Count vs conditioned-area histograms (plotly or d3); returns html + bin arrays for csv."""
    vals_arr = np.asarray(vals_list, dtype=float)
    counts, edges = np.histogram(vals_arr, bins=_OH_HIST_NBINS)
    heat_colors = _overheating_metric_bin_colors(len(counts))
    count_ints = [int(c) for c in counts]
    hist_html = create_histogram_d3_html(
        vals_list,
        title="Distribution",
        x_label=x_hist,
        theme=theme,
        bin_edges=edges.tolist(),
        counts=count_ints,
        bar_colors=heat_colors,
    )
    area_bar_html: str | None = None
    oh_area_bin_edges: np.ndarray | None = None
    oh_area_bin_sums: np.ndarray | None = None
    if area_weights is not None:
        w_arr = np.asarray(area_weights, dtype=float)
        oh_area_bin_sums, _ = np.histogram(vals_arr, bins=edges, weights=w_arr)
        oh_area_bin_edges = edges
        area_bar_html = create_binned_bar_d3_html(
            oh_area_bin_edges.tolist(),
            oh_area_bin_sums.tolist(),
            title="floor area by metric",
            x_label=x_hist,
            y_label="conditioned floor area (m²)",
            theme=theme,
            bar_colors=heat_colors,
        )

    bin_centers = ((edges[:-1] + edges[1:]) / 2.0).astype(float)
    bar_w = float(edges[1] - edges[0])

    try:
        import plotly.graph_objects as go
    except ImportError:
        go = None
    if go is not None:
        fig_count = go.Figure()
        fig_count.add_trace(
            go.Bar(
                x=bin_centers.tolist(),
                y=count_ints,
                width=bar_w,
                marker_color=heat_colors,
                opacity=0.88,
            )
        )
        fig_count.update_layout(
            xaxis_title=x_hist,
            yaxis_title="count",
            margin={"l": 40, "r": 20, "t": 40, "b": 40},
            height=320,
            showlegend=False,
            bargap=0,
        )
        if area_weights is not None and oh_area_bin_sums is not None:
            fig_area = go.Figure()
            fig_area.add_trace(
                go.Bar(
                    x=bin_centers.tolist(),
                    y=oh_area_bin_sums.tolist(),
                    width=bar_w,
                    marker_color=heat_colors,
                    opacity=0.88,
                )
            )
            fig_area.update_layout(
                xaxis_title=x_hist,
                yaxis_title="conditioned floor area (m²)",
                margin={"l": 52, "r": 20, "t": 40, "b": 40},
                height=320,
                showlegend=False,
                bargap=0,
            )
            col_c, col_a = st.columns(2)
            with col_c:
                st.caption("Buildings per metric bin")
                st.plotly_chart(fig_count, width="stretch")
            with col_a:
                st.caption("Total conditioned floor area per metric bin")
                st.plotly_chart(fig_area, width="stretch")
        else:
            st.caption(
                "Conditioned floor area is unavailable for this run; add energy outputs "
                "with floor area to see area-weighted bins."
            )
            st.plotly_chart(fig_count, width="stretch")
    else:
        if area_bar_html is not None:
            col_d3_c, col_d3_a = st.columns(2)
            with col_d3_c:
                st.caption("Buildings per metric bin")
                components.html(hist_html, height=350, scrolling=False)
            with col_d3_a:
                st.caption("Total conditioned floor area per metric bin")
                components.html(area_bar_html, height=350, scrolling=False)
        else:
            components.html(hist_html, height=350, scrolling=False)

    return hist_html, area_bar_html, oh_area_bin_edges, oh_area_bin_sums


def _overheating_map_inputs_mtime(run_dir: Path, data_source_type: str) -> float:
    """Max mtime of overheating + Energy parquet inputs for cache invalidation."""
    t = 0.0
    oh = get_overheating_file_for_run(run_dir, data_source_type)
    en = get_pq_file_for_run(run_dir)
    for p in (oh, en):
        if p is not None and p.is_file():
            with contextlib.suppress(OSError):
                t = max(t, p.stat().st_mtime)
    return t


@st.cache_data(show_spinner=False)
def _cached_build_overheating_map_df(
    run_dir_str: str,
    inputs_mtime: float,
    cart_crs: str,
    heat_threshold_c: float,
    aggregation: str,
    data_source_type: str,
    heat_index_metric: str,
) -> pd.DataFrame | None:
    """Disk + merge + geometry for overheating map; keyed by run contents + params."""
    return build_overheating_map_df(
        Path(run_dir_str),
        cart_crs=cart_crs,
        heat_threshold_c=heat_threshold_c,
        aggregation=aggregation,
        data_source_type=data_source_type,
        heat_index_metric=heat_index_metric,
    )


@st.cache_data(show_spinner="Building map geometry...")
def _build_overheating_geometry_cache(
    run_dir_str: str,
    inputs_mtime: float,
    cart_crs: str,
    heat_threshold_c: float,
    aggregation: str,
    data_source_type: str,
    filter_key: str,
    _map_df: pd.DataFrame,
):
    """Geometry from map_df; _map_df excluded from key, so the other args (incl. filters) must identify it."""
    from globi.tools.visualization.utils import build_map_features_from_df

    return build_map_features_from_df(_map_df, cart_crs=cart_crs, value_col=None)


@st.cache_data(show_spinner=False)
def _cached_infer_rotated_rectangle_crs_hint(pq_path: str, mtime: float) -> dict:
    """CRS hint from a prefix of EnergyAndPeak; cache invalidates when file changes."""
    sample = read_parquet_sample_for_crs_inference(pq_path, max_rows=80)
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


@st.cache_data(show_spinner=False)
def _load_overheating_dashboard_data_cached(
    run_dir: Path | None,
    available_files: tuple[str, ...],
    thresholds: tuple[float, ...],
    heat_threshold: float,
    aggregation: str,
    cart_crs: str,
    _buildings_fallback: Callable[[], pd.DataFrame | None],
) -> dict:
    """Cached loader keyed on run, files, threshold, aggregation and CRS.

    The buildings fallback is a loader (not hashed) so inputs/buildings.parquet is
    only read on a cache miss, and only when the run has no buildings file of its own.
    """
    primary_dstype = (
        "ExceedanceDegreeHours"
        if "ExceedanceDegreeHours" in available_files
        else (available_files[0] if available_files else "BasicOverheating")
    )

    map_df = None
    multi_metric_df = None
    heat_index_df = None
    threshold_sensitivity_df = None
    fan_wide = None
    eui_edh_df = None
    buildings_df = None
    building_area_df = None
    consecutive_df = None

    if run_dir is not None:
        _oh_mtime = _overheating_map_inputs_mtime(run_dir, primary_dstype)
        map_df = _cached_build_overheating_map_df(
            str(run_dir.resolve()),
            _oh_mtime,
            cart_crs,
            heat_threshold,
            aggregation,
            primary_dstype,
            "danger_hours",
        )
        multi_metric_df = build_portfolio_multi_metric_df(
            run_dir, heat_threshold, aggregation
        )
        heat_index_df = build_heat_index_per_building_df(run_dir, aggregation)
        fan_wide = build_overheating_threshold_fan_wide_df(
            run_dir, primary_dstype, aggregation
        )
        threshold_sensitivity_df = (
            threshold_sensitivity_from_wide(fan_wide)
            if primary_dstype in ("BasicOverheating", "ExceedanceDegreeHours")
            else None
        )
        eui_edh_df = build_eui_vs_edh_df(run_dir, heat_threshold, aggregation)
        buildings_df = build_run_buildings_df(run_dir)
        if buildings_df is None:
            buildings_df = _buildings_fallback()
        building_area_df = build_building_area_df(run_dir)
        if "ConsecutiveExceedances" in available_files:
            consecutive_df = build_consecutive_exceedances_building_df(
                run_dir, heat_threshold
            )

    return {
        "map_df": map_df,
        "multi_metric_df": multi_metric_df,
        "heat_index_df": heat_index_df,
        "threshold_sensitivity_df": threshold_sensitivity_df,
        "fan_wide": fan_wide,
        "run_dir": run_dir,
        "available_files": list(available_files),
        "thresholds": list(thresholds),
        "eui_edh_df": eui_edh_df,
        "buildings_df": buildings_df,
        "building_area_df": building_area_df,
        "consecutive_df": consecutive_df,
        "primary_dstype": primary_dstype,
    }


def _load_overheating_dashboard_data(
    data_source: DataSource,
    selected_run: str,
    heat_threshold: float,
    aggregation: str,
    cart_crs: str,
) -> dict:
    """Load all overheating data at once; values may be None if unavailable."""
    run_dir = data_source.resolve_run_dir(selected_run)
    available_files = tuple(data_source.list_overheating_files(selected_run))
    thresholds = tuple(data_source.get_overheating_thresholds(selected_run))
    return _load_overheating_dashboard_data_cached(
        run_dir,
        available_files,
        thresholds,
        heat_threshold,
        aggregation,
        cart_crs,
        data_source.load_building_locations,
    )


def _portfolio_tiles(
    edh_vals: pd.Series,
    hours_vals: pd.Series,
    edh_wz_vals: pd.Series,
    hi_vals: pd.Series,
    multi: pd.DataFrame,
    building_area_df: pd.DataFrame | None,
    heat_threshold: float,
) -> list[tuple[str, str, str]]:
    """Headline numbers (label, value, help) for the measures present in this run."""
    tiles: list[tuple[str, str, str]] = []
    if not hours_vals.empty:
        tiles.append((
            "Buildings overheating",
            f"{(hours_vals > 0).mean() * 100:.0f}%",
            f"Share of buildings with at least one hour above {heat_threshold} °C.",
        ))
        if building_area_df is not None and not building_area_df.empty:
            area_hours = (
                multi[[BUILDING_ID_COL, "exceedance_hours"]]
                .merge(
                    building_area_df[[BUILDING_ID_COL, "conditioned_area_m2"]],
                    on=BUILDING_ID_COL,
                    how="inner",
                )
                .dropna(subset=["exceedance_hours", "conditioned_area_m2"])
            )
            total_area = area_hours["conditioned_area_m2"].sum()
            if total_area > 0:
                exceed_area = area_hours.loc[
                    area_hours["exceedance_hours"] > 0, "conditioned_area_m2"
                ].sum()
                tiles.append((
                    "Floor area overheating",
                    f"{exceed_area / total_area * 100:.0f}%",
                    "Share of floor area in buildings with at least one hour above "
                    f"{heat_threshold} °C.",
                ))
        tiles.append((
            "Typical hours above threshold",
            f"{hours_vals.median():,.0f} h",
            f"Median building's hours above {heat_threshold} °C.",
        ))
    if not edh_vals.empty:
        tiles.append((
            "Typical degree-hours (EDH)",
            f"{edh_vals.median():,.0f} °C·hr",
            f"Median building's degree-hours above {heat_threshold} °C, "
            "averaged over its rooms by floor area.",
        ))
    if not edh_wz_vals.empty:
        tiles.append((
            "Hottest-room EDH, top 10%",
            f"{float(np.percentile(edh_wz_vals, 90)):,.0f} °C·hr",
            "Degree-hours in each building's hottest room; 9 in 10 buildings "
            "are below this value (90th percentile).",
        ))
    if not hi_vals.empty:
        tiles.append((
            "Heat-index caution hours",
            f"{hi_vals.mean():,.0f} h",
            "Average hours per building with a heat index at Caution or worse "
            "(NOAA bands), averaged over rooms by floor area.",
        ))
    return tiles or [("Buildings", f"{len(multi):,}", "No overheating measures found.")]


def _render_tab_portfolio(  # noqa: C901
    data: dict,
    heat_threshold: float,
    aggregation: str,
    theme: Theme,
) -> None:
    """Tab 1 — Portfolio: KPIs, scatters, histograms, threshold sensitivity, heat index."""
    multi = data.get("multi_metric_df")
    if multi is None or multi.empty:
        st.info("No overheating data loaded for portfolio view.")
        return

    # --- KPIs ---
    edh_vals = (
        multi["edh_zone_weighted"].dropna()
        if "edh_zone_weighted" in multi.columns
        else pd.Series(dtype=float)
    )
    hours_vals = (
        multi["exceedance_hours"].dropna()
        if "exceedance_hours" in multi.columns
        else pd.Series(dtype=float)
    )
    edh_wz_vals = (
        multi["edh_worst_zone"].dropna()
        if "edh_worst_zone" in multi.columns
        else pd.Series(dtype=float)
    )
    hi_vals = (
        multi["heat_index_caution_hours"].dropna()
        if "heat_index_caution_hours" in multi.columns
        else pd.Series(dtype=float)
    )

    building_area_df = data.get("building_area_df")

    tiles = _portfolio_tiles(
        edh_vals,
        hours_vals,
        edh_wz_vals,
        hi_vals,
        multi,
        building_area_df,
        heat_threshold,
    )
    # only measures this run has; at most three per row so labels and values fit
    for start in range(0, len(tiles), 3):
        row = tiles[start : start + 3]
        for col, (label, value, help_text) in zip(st.columns(3), row, strict=False):
            col.metric(label, value, help=help_text)

    st.divider()

    # --- Worst-zone vs zone-weighted scatter ---
    run_dir = data.get("run_dir")
    primary_dstype = data.get("primary_dstype", "ExceedanceDegreeHours")

    if run_dir is not None and primary_dstype in (
        "BasicOverheating",
        "ExceedanceDegreeHours",
    ):
        st.markdown("#### Worst-zone vs zone-weighted")
        st.caption(
            "Buildings along the diagonal are uniformly overheating. "
            "Buildings well above the diagonal have concentrated hot spots."
        )
        rdf = build_worst_zone_ratio_df(run_dir, heat_threshold, primary_dstype)
        if rdf is not None and not rdf.empty:
            scatter_html = create_scatter_d3_html(
                rdf["zone_weighted"].tolist(),
                rdf["worst_zone"].tolist(),
                rdf[BUILDING_ID_COL].astype(str).tolist(),
                title="worst-zone vs zone-weighted",
                x_label=f"zone-weighted EDH at {heat_threshold}°C",
                y_label=f"worst-zone EDH at {heat_threshold}°C",
                theme=theme,
            )
            components.html(scatter_html, height=530, scrolling=False)
            if primary_dstype == "ExceedanceDegreeHours":
                _formula_expander(
                    "How are these values calculated?",
                    [
                        (
                            "Each axis is a **building-level EDH aggregation** from zone-level values:",
                            None,
                        ),
                        ("*Zone Weighted:*", None),
                        (None, _FORMULA_EDH_ZW),
                        ("*Worst Zone:*", None),
                        (None, _FORMULA_EDH_WZ),
                        ("where", None),
                        (None, _FORMULA_EDH_ZONE),
                    ],
                )
            else:
                _formula_expander(
                    "How are these values calculated?",
                    [
                        (
                            "Each axis is a **building-level aggregation** of per-zone total hours above threshold:",
                            None,
                        ),
                        ("*Zone Weighted:*", None),
                        (None, _FORMULA_BASIC_ZW),
                        ("*Worst Zone:*", None),
                        (None, _FORMULA_BASIC_WZ),
                        ("where", None),
                        (None, _FORMULA_BASIC_ZONE),
                    ],
                )

    st.divider()

    # --- Distribution histograms (side by side) ---
    st.markdown("#### Metric distributions")

    # Toggle: count of buildings vs floor area
    building_area_df = data.get("building_area_df")
    _area_mode_options = ["Count of buildings", "Floor area (m²)"]
    _area_mode_disabled = building_area_df is None or building_area_df.empty
    area_mode = st.radio(
        "Y-axis",
        options=_area_mode_options,
        index=0,
        horizontal=True,
        key="hist_area_mode",
        disabled=_area_mode_disabled,
        help=(
            "Floor area requires conditioned area data from EnergyAndPeak outputs."
            if _area_mode_disabled
            else "Switch between number of buildings per bin and total floor area per bin."
        ),
    )
    use_area_weights = area_mode == "Floor area (m²)" and not _area_mode_disabled

    # Merge consecutive streak data into hist_df if available
    consecutive_df = data.get("consecutive_df")
    hist_df = multi.copy()
    if (
        consecutive_df is not None
        and not consecutive_df.empty
        and "max_streak_hr" in consecutive_df.columns
    ):
        hist_df = hist_df.merge(
            consecutive_df[[BUILDING_ID_COL, "max_streak_hr"]],
            on=BUILDING_ID_COL,
            how="left",
        )

    # Pre-join area weights onto hist_df once
    if use_area_weights and building_area_df is not None:
        area_join = hist_df.merge(
            building_area_df[[BUILDING_ID_COL, "conditioned_area_m2"]],
            on=BUILDING_ID_COL,
            how="left",
        )
    else:
        area_join = None

    _hist_specs = [
        (
            "edh_zone_weighted",
            "Degree-hours (EDH), all rooms",
            f"EDH at {heat_threshold}°C (°C·hr)",
        ),
        (
            "exceedance_hours",
            "Total hours above threshold",
            f"Total hours above {heat_threshold}°C",
        ),
        (
            "heat_index_caution_hours",
            "Heat-index caution hours",
            "Caution or worse (hr)",
        ),
        ("max_streak_hr", "Longest consecutive streak", "Longest streak (hr)"),
    ]
    # Only include specs whose column is present and non-empty
    active_specs = [
        spec
        for spec in _hist_specs
        if spec[0] in hist_df.columns and not hist_df[spec[0]].dropna().empty
    ]

    hist_cols = st.columns(len(active_specs)) if active_specs else []

    for (col_key, title, x_label), col_ctx in zip(active_specs, hist_cols, strict=True):
        vals = hist_df[col_key].dropna().astype(float).tolist()
        arr = np.array(vals)
        med = float(np.median(arr))
        p90 = float(np.percentile(arr, 90))
        annots = [
            {"value": med, "label": "median", "color": "#374151"},
            {"value": p90, "label": "P90", "color": "#9ca3af"},
        ]

        # Build area-weighted bins when requested
        bin_edges_out: list[float] | None = None
        counts_out: list[int] | None = None
        y_label_out = "count"
        if (
            use_area_weights
            and area_join is not None
            and "conditioned_area_m2" in area_join.columns
        ):
            ok = area_join[col_key].notna() & area_join["conditioned_area_m2"].notna()
            sub = area_join.loc[ok]
            if len(sub) >= 2:
                metric_vals = sub[col_key].astype(float).values
                area_vals = sub["conditioned_area_m2"].astype(float).values
                _, edges = np.histogram(metric_vals, bins=25)
                bin_sums = np.zeros(len(edges) - 1)
                for v, a in zip(metric_vals, area_vals, strict=True):
                    idx = min(np.searchsorted(edges[1:], v), len(bin_sums) - 1)
                    bin_sums[idx] += a
                bin_edges_out = edges.tolist()
                counts_out = [float(s) for s in bin_sums]  # type: ignore[assignment]
                y_label_out = "floor area (m²)"

        with col_ctx:
            st.caption(title)
            h = create_histogram_d3_html(
                vals,
                title=title,
                x_label=x_label,
                theme=theme,
                annotation_values=annots,
                bin_edges=bin_edges_out,
                counts=counts_out,
                y_label=y_label_out,
            )
            components.html(h, height=350, scrolling=False)
            if col_key == "edh_zone_weighted":
                _formula_expander(
                    "Formula",
                    [
                        ("Zone-weighted EDH across the portfolio (SET-based):", None),
                        (None, _FORMULA_EDH_ZW),
                        ("where", None),
                        (None, _FORMULA_EDH_ZONE),
                    ],
                )
            elif col_key == "exceedance_hours":
                _formula_expander(
                    "Formula",
                    [
                        (
                            "**Total hours above threshold** - counts hours (dry-bulb) exceeding the configured threshold, zone-weighted:",
                            None,
                        ),
                        (None, _FORMULA_BASIC_ZW),
                        ("where", None),
                        (None, _FORMULA_BASIC_ZONE),
                    ],
                )
            elif col_key == "heat_index_caution_hours":
                _formula_expander(
                    "Formula",
                    [
                        (
                            "Hours in **Caution or above** (NOAA heat index), zone-weighted mean HI per hour:",
                            None,
                        ),
                        (None, _FORMULA_HI_ZW),
                        (
                            "Caution threshold: HI >= 80 deg-F. HI uses the Rothfusz regression (dry-bulb + RH):",
                            None,
                        ),
                        (None, _FORMULA_HI_REG),
                    ],
                )
            elif col_key == "max_streak_hr":
                _formula_expander(
                    "Formula",
                    [
                        (
                            "**Longest consecutive streak** - longest unbroken run of hours where dry-bulb exceeds the threshold, taken as the worst zone across the building:",
                            None,
                        ),
                        (None, _FORMULA_STREAK),
                    ],
                )

    st.divider()

    # --- Threshold sensitivity panel ---
    sens_df = data.get("threshold_sensitivity_df")
    if sens_df is not None and not sens_df.empty:
        st.markdown("#### Threshold sensitivity")
        st.caption(
            "Dot = median building; bar = middle half of buildings (25th to 75th percentile). "
            "Shows how apparent severity changes with threshold choice."
        )
        y_sens = (
            "EDH (°C·hr)"
            if primary_dstype == "ExceedanceDegreeHours"
            else "Total hours above threshold"
        )
        sens_html = create_threshold_sensitivity_dot_range_d3_html(
            sens_df["threshold_c"].tolist(),
            sens_df["median"].tolist(),
            sens_df["p25"].tolist(),
            sens_df["p75"].tolist(),
            y_label=y_sens,
            theme=theme,
        )
        components.html(sens_html, height=320, scrolling=False)

        # per-building fan in expander
        fan_wide = data.get("fan_wide")
        if fan_wide is not None:
            with st.expander("Per-building threshold fan (detail)", expanded=False):
                sampled = sample_overheating_fan_payload(fan_wide)
                if sampled is not None:
                    thr, lines, mean_v = sampled
                    fan_html = create_overheating_threshold_fan_d3_html(
                        thr,
                        lines,
                        mean_v,
                        title="threshold sensitivity (per building)",
                        y_label=y_sens,
                        theme=theme,
                    )
                    components.html(fan_html, height=360, scrolling=False)

        if primary_dstype == "ExceedanceDegreeHours":
            _formula_expander(
                "How is threshold sensitivity calculated?",
                [
                    (
                        "Each point shows the median building's EDH and P25-P75 IQR at a given threshold:",
                        None,
                    ),
                    (None, _FORMULA_EDH_ZONE),
                    ("Zone-weighted to building level:", None),
                    (None, _FORMULA_EDH_ZW),
                    (
                        "**SET** (Standard Effective Temperature) accounts for dry-bulb, mean radiant temperature, humidity, clothing (CLO), metabolic rate (MET), and air speed.",
                        None,
                    ),
                ],
            )
        else:
            _formula_expander(
                "How is threshold sensitivity calculated?",
                [
                    (
                        "Each point shows the median building's total hours above threshold and P25-P75 IQR at a given threshold:",
                        None,
                    ),
                    (None, _FORMULA_BASIC_ZONE),
                    ("Zone-weighted to building level:", None),
                    (None, _FORMULA_BASIC_ZW),
                ],
            )

    st.divider()

    # --- Heat index stacked bar ---
    hi_df = data.get("heat_index_df")
    if hi_df is not None and not hi_df.empty:
        st.markdown("#### Heat index hours by building")
        st.caption(
            "Buildings sorted by hours at Caution or worse (highest at top). Shows up to 200 buildings."
        )
        cat_cols = [
            c
            for c in (
                "Normal [hr]",
                "Caution [hr]",
                "Extreme Caution [hr]",
                "Danger [hr]",
                "Extreme Danger [hr]",
            )
            if c in hi_df.columns
        ]
        if cat_cols:
            cat_data = {c: hi_df[c].tolist() for c in cat_cols}
            hi_html = create_heat_index_stacked_bar_d3_html(
                hi_df[BUILDING_ID_COL].astype(str).tolist(),
                cat_data,
                theme=theme,
            )
            n_bld = len(hi_df)
            bar_px = max(300, min(600, n_bld * 8 + 80))
            components.html(hi_html, height=bar_px, scrolling=True)
            _formula_expander(
                "How are heat index categories calculated?",
                [
                    (
                        "**Step 1 — Rothfusz regression** (dry-bulb in °F + relative humidity):",
                        None,
                    ),
                    (None, _FORMULA_HI_REG),
                    (
                        "**Step 2 — NOAA categories** (HI in °F):\n"
                        "- Normal: HI < 80\n"
                        "- Caution: 80-89\n"
                        "- Extreme Caution: 90-104\n"
                        "- Danger: 105-129\n"
                        "- Extreme Danger: ≥ 130",
                        None,
                    ),
                    (
                        "**Step 3 — Zone Weighted** mean HI per hour, then categorised:",
                        None,
                    ),
                    (None, _FORMULA_HI_ZW),
                ],
            )


def _geo_metric_formula_expander(chosen: str) -> None:
    """Show the formula expander appropriate for the chosen map metric."""
    if chosen == "ExceedanceDegreeHours":
        _formula_expander(
            "Formula",
            [
                (None, _FORMULA_EDH_ZONE),
                ("Zone-weighted:", None),
                (None, _FORMULA_EDH_ZW),
            ],
        )
    elif chosen == "BasicOverheating":
        _formula_expander(
            "Formula",
            [
                (None, _FORMULA_BASIC_ZONE),
                ("Zone-weighted:", None),
                (None, _FORMULA_BASIC_ZW),
            ],
        )
    elif chosen == "HeatIndexCategories":
        _formula_expander(
            "Formula",
            [
                ("Zone-weighted mean HI per hour:", None),
                (None, _FORMULA_HI_ZW),
                ("Rothfusz regression (deg-F):", None),
                (None, _FORMULA_HI_REG),
            ],
        )


def _render_geo_flat_map(
    map_df: pd.DataFrame,
    filtered_map: pd.DataFrame,
    metric_label: str,
    cart_crs: str,
    fill_color: list[int] | None = None,
    geometry: list[dict] | None = None,
) -> None:
    """Render the plan-view flat footprint map for the selected buildings.

    If fill_color is provided, all buildings are drawn in that single RGBA colour
    (no colormap gradient). With cached geometry (features carrying building_id),
    the selection is picked from it instead of re-parsing footprints on every move.
    """
    st.markdown("**Where are the buildings located?**")
    if filtered_map.empty:
        st.info("No buildings in the selected range.")
        return
    features = None
    if geometry is not None and BUILDING_ID_COL in filtered_map.columns:
        values = dict(
            zip(
                filtered_map[BUILDING_ID_COL].astype(str),
                cast(
                    pd.Series, pd.to_numeric(filtered_map["map_value"], errors="coerce")
                ),
                strict=True,
            )
        )
        features = [
            {**f, "value": float(values[f["building_id"]])}
            for f in geometry
            if f.get("building_id") in values
        ]
    flat_result = create_flat_footprint_deck(
        filtered_map,
        cart_crs=cart_crs,
        value_col=None if fill_color else "map_value",
        cmap="reds",
        fill_color=fill_color,
        features=features or None,
    )
    if flat_result is not None:
        flat_deck, flat_n, _ = flat_result
        st.pydeck_chart(flat_deck)
        label = f"{flat_n} buildings shown - {metric_label}"
        if fill_color is None:
            label += " (coloured by value)"
        st.caption(label)
    else:
        st.info(
            "Building footprints unavailable - check that rotated_rectangle and height columns are present."
        )


def _render_tab_geography(  # noqa: C901
    data: dict,
    heat_threshold: float,
    aggregation: str,
    cart_crs: str,
    data_source: DataSource,
    selected_run: str,
    theme: Theme,
) -> None:
    """Tab 2 — Geography: 3D map + histogram + flat 2D scatter map."""
    available_files = data.get("available_files", [])

    # metric selector within the tab
    metric_options = []
    if "ExceedanceDegreeHours" in available_files:
        metric_options.append(("ExceedanceDegreeHours", f"EDH at {heat_threshold}°C"))
    if "BasicOverheating" in available_files:
        metric_options.append((
            "BasicOverheating",
            f"Total hours above {heat_threshold}°C",
        ))
    if "HeatIndexCategories" in available_files:
        metric_options.append(("HeatIndexCategories", "Heat-index caution hours"))
    if not metric_options:
        st.info("No overheating outputs found.")
        return

    chosen = st.selectbox(
        "Colour by",
        options=[o[0] for o in metric_options],
        format_func=lambda x: next(label for key, label in metric_options if key == x),
        key="geo_tab_metric",
    )
    # one aggregation for the whole page (set above the sections)
    geo_agg = aggregation
    allowed = data.get("allowed_ids")

    if chosen is None:
        return

    run_dir = data_source.resolve_run_dir(selected_run)

    primary = data.get("primary_dstype")
    dash_map = data.get("map_df")
    map_df = None
    if (
        run_dir is not None
        and dash_map is not None
        and not getattr(dash_map, "empty", True)
        and chosen == primary
        and geo_agg == aggregation
    ):
        map_df = dash_map
    elif run_dir is not None:
        _om = _overheating_map_inputs_mtime(run_dir, chosen)
        map_df = _cached_build_overheating_map_df(
            str(run_dir.resolve()),
            _om,
            cart_crs,
            heat_threshold,
            geo_agg,
            chosen,
            "danger_hours",
        )
    else:
        map_df = data_source.load_overheating_map_data(
            selected_run,
            cart_crs=cart_crs,
            heat_threshold_c=heat_threshold,
            aggregation=geo_agg,
            data_source_type=chosen,
            heat_index_metric="danger_hours",
        )

    map_df = _only_allowed(map_df, allowed)
    if map_df is None or map_df.empty:
        st.info("No map data available for this selection.")
        return

    metric_label = str(
        next((label for key, label in metric_options if key == chosen), chosen)
    )

    # 3D map
    st.markdown("#### 3D building map")
    geometry_cache = None
    if run_dir is not None:
        _img_m = _overheating_map_inputs_mtime(run_dir, chosen)
        geometry_cache = _build_overheating_geometry_cache(
            str(run_dir.resolve()),
            _img_m,
            cart_crs,
            heat_threshold,
            geo_agg,
            chosen,
            _filter_key(allowed),
            map_df,
        )
    else:
        from globi.tools.visualization.utils import build_map_features_from_df

        geometry_cache = build_map_features_from_df(
            map_df, cart_crs=cart_crs, value_col=None
        )
    result = None
    if geometry_cache is not None:
        result = create_building_map_deck_from_cache(
            geometry_cache,
            map_df,
            value_col="map_value",
            cmap="reds",
        )
    if result is None:
        result = create_building_map_deck(
            map_df, cart_crs=cart_crs, value_col="map_value", cmap="reds"
        )
    if result is not None:
        deck, n_features, value_stats = result
        st.pydeck_chart(deck)
        st.caption(f"{n_features} buildings displayed")
        if value_stats:
            _render_colormap_legend(metric_label, value_stats, "reds")
    else:
        st.info("Could not build 3D map — check that buildings have geometry columns.")

    st.divider()

    # Histogram with brush range selector + filtered flat map
    map_values = map_df["map_value"].dropna().astype(float)
    vals = map_values.tolist()

    if not vals:
        return

    arr = np.array(vals)
    val_min, val_max = float(arr.min()), float(arr.max())

    # Determine a sensible slider step from the data range
    _range_span = val_max - val_min if val_max > val_min else 1.0
    _step = (
        float(10 ** math.floor(math.log10(_range_span / 100)))
        if _range_span >= 0.01
        else 0.01
    )

    st.markdown("#### Overview of spatial distribution of overheating")
    st.caption(
        "Drag the slider to select a value range. "
        "The histogram highlights matching bins; the plan view shows only those buildings."
    )

    # Range slider — keyed on metric + run to reset when context changes
    brush_key = f"geo_brush_{chosen}_{geo_agg}"
    sel_lo, sel_hi = _range_slider(
        f"{metric_label} range", val_min, val_max, _step, brush_key
    )

    # Convenience percentile readout
    n_sel = int(((arr >= sel_lo) & (arr <= sel_hi)).sum())
    st.caption(f"**{n_sel:,} of {len(arr):,} buildings** in the selected range")

    col_hist, col_flat = st.columns(2)
    with col_hist:
        st.markdown("**Distribution**")
        annots = [
            {"value": float(np.median(arr)), "label": "median", "color": "#374151"},
            {
                "value": float(np.percentile(arr, 90)),
                "label": "P90",
                "color": "#9ca3af",
            },
        ]
        h = create_histogram_d3_html(
            vals,
            title="distribution",
            x_label=metric_label,
            theme=theme,
            annotation_values=annots,
            selected_range=(sel_lo, sel_hi),
            wide_layout=True,
        )
        components.html(h, height=410, scrolling=False)
        _geo_metric_formula_expander(str(chosen))

    mv_geo = map_df["map_value"].astype(float)
    sel_mask = mv_geo.notna() & (mv_geo >= sel_lo) & (mv_geo <= sel_hi)
    filtered_geo = map_df.loc[sel_mask]
    with col_flat:
        _render_geo_flat_map(
            map_df,
            cast(pd.DataFrame, filtered_geo),
            metric_label,
            cart_crs,
            geometry=geometry_cache,
        )

    if "BasicOverheating" in available_files and chosen != "BasicOverheating":
        hrs_map_df = None
        if (
            run_dir is not None
            and dash_map is not None
            and not getattr(dash_map, "empty", True)
            and primary == "BasicOverheating"
            and geo_agg == aggregation
        ):
            hrs_map_df = dash_map
        elif run_dir is not None:
            _hrs_m = _overheating_map_inputs_mtime(run_dir, "BasicOverheating")
            hrs_map_df = _cached_build_overheating_map_df(
                str(run_dir.resolve()),
                _hrs_m,
                cart_crs,
                heat_threshold,
                geo_agg,
                "BasicOverheating",
                "danger_hours",
            )
        else:
            hrs_map_df = data_source.load_overheating_map_data(
                selected_run,
                cart_crs=cart_crs,
                heat_threshold_c=heat_threshold,
                aggregation=geo_agg,
                data_source_type="BasicOverheating",
                heat_index_metric="danger_hours",
            )
        hrs_map_df = _only_allowed(hrs_map_df, allowed)
        if hrs_map_df is not None and not hrs_map_df.empty:
            _render_geo_hours_brush_panel(
                hrs_map_df, heat_threshold, geo_agg, cart_crs, theme, geometry_cache
            )


def _filter_key(allowed: set[str] | None) -> str:
    """Short stable key for a building filter (for cache keys)."""
    if allowed is None:
        return "all"
    return f"{len(allowed)}:{hash(frozenset(allowed))}"


def _only_allowed(
    df: pd.DataFrame | None, allowed: set[str] | None
) -> pd.DataFrame | None:
    """Rows of a per-building table whose building is in the sidebar filter."""
    if df is None or allowed is None or BUILDING_ID_COL not in df.columns:
        return df
    return cast(pd.DataFrame, df[df[BUILDING_ID_COL].astype(str).isin(list(allowed))])


def _filter_dashboard(data: dict, allowed: set[str] | None) -> dict:
    """Apply the sidebar building filter to every per-building table and recompute summaries."""
    out = {**data, "allowed_ids": allowed}
    if allowed is None:
        return out
    for key in (
        "map_df",
        "multi_metric_df",
        "heat_index_df",
        "eui_edh_df",
        "buildings_df",
        "building_area_df",
        "consecutive_df",
    ):
        out[key] = _only_allowed(data.get(key), allowed)
    wide = data.get("fan_wide")
    if isinstance(wide, pd.DataFrame):
        out["fan_wide"] = cast(
            pd.DataFrame, wide[wide.index.astype(str).isin(list(allowed))]
        )
        if data.get("threshold_sensitivity_df") is not None:
            out["threshold_sensitivity_df"] = threshold_sensitivity_from_wide(
                out["fan_wide"]
            )
    return out


def _range_slider(
    label: str, lo: float, hi: float, step: float, key: str
) -> tuple[float, float]:
    """Range slider over [lo, hi]; with no spread there is nothing to pick, so say so and select all."""
    if hi <= lo:
        # st.slider raises when min == max, e.g. no building overheats at this threshold
        st.info(
            f"Every building has the same value ({lo:,.1f}), so there is no range "
            "to select. Try a lower temperature threshold."
        )
        return lo, hi
    return st.slider(
        label,
        min_value=lo,
        max_value=hi,
        value=(lo, hi),
        step=step,
        key=key,
        format="%.1f",
    )


def _render_geo_hours_brush_panel(
    hrs_map_df: pd.DataFrame,
    heat_threshold: float,
    geo_agg: str,
    cart_crs: str,
    theme: Theme,
    geometry: list[dict] | None = None,
) -> None:
    """Second geography brush panel: total hours above threshold, buildings shown in flat red."""
    st.divider()

    hrs_vals_raw = hrs_map_df["map_value"].dropna().astype(float)
    if hrs_vals_raw.empty:
        return

    hrs_arr = np.asarray(hrs_vals_raw, dtype=float)
    hrs_min, hrs_max = float(hrs_arr.min()), float(hrs_arr.max())
    _hrs_span = hrs_max - hrs_min if hrs_max > hrs_min else 1.0
    _hrs_step = (
        float(10 ** math.floor(math.log10(_hrs_span / 100)))
        if _hrs_span >= 0.01
        else 0.01
    )

    st.markdown("#### Total hours above threshold — distribution brush")
    st.caption(
        "Brush the distribution to highlight buildings by total hours above threshold. "
        "Selected buildings are shown in red on the plan view."
    )

    hrs_lo, hrs_hi = _range_slider(
        f"Total hours above {heat_threshold}°C range",
        hrs_min,
        hrs_max,
        _hrs_step,
        f"geo_brush_basic_{geo_agg}",
    )

    n_hrs_sel = int(((hrs_arr >= hrs_lo) & (hrs_arr <= hrs_hi)).sum())
    st.caption(f"**{n_hrs_sel:,} of {len(hrs_arr):,} buildings** in the selected range")

    col_hrs_hist, col_hrs_flat = st.columns(2)
    with col_hrs_hist:
        st.markdown("**Distribution**")
        annots = [
            {"value": float(np.median(hrs_arr)), "label": "median", "color": "#374151"},
            {
                "value": float(np.percentile(hrs_arr, 90)),
                "label": "P90",
                "color": "#9ca3af",
            },
        ]
        h_hrs = create_histogram_d3_html(
            hrs_vals_raw.tolist(),
            title="total hours above threshold",
            x_label=f"Total hours above {heat_threshold}°C",
            theme=theme,
            annotation_values=annots,
            selected_range=(hrs_lo, hrs_hi),
            wide_layout=True,
        )
        components.html(h_hrs, height=410, scrolling=False)
        _formula_expander(
            "Formula",
            [
                (
                    "**Total hours above threshold** - zone-weighted dry-bulb exceedance count:",
                    None,
                ),
                (None, _FORMULA_BASIC_ZW),
                ("where", None),
                (None, _FORMULA_BASIC_ZONE),
            ],
        )

    mv_hrs = hrs_map_df["map_value"].astype(float)
    hrs_sel_mask = mv_hrs.notna() & (mv_hrs >= hrs_lo) & (mv_hrs <= hrs_hi)
    filtered_hrs = hrs_map_df.loc[hrs_sel_mask]
    with col_hrs_flat:
        _render_geo_flat_map(
            hrs_map_df,
            cast(pd.DataFrame, filtered_hrs),
            f"total hours above {heat_threshold}°C",
            cart_crs,
            fill_color=[220, 38, 38, 200],
            geometry=geometry,
        )


def _oh_progress_column_max(series: pd.Series) -> float:
    # streamlit column_config json uses allow_nan=False — nan/inf in ProgressColumn breaks serialization
    m = series.max(skipna=True)
    try:
        x = float(m)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(x) or x <= 0:
        return 1.0
    return x


def _render_tab_priority(
    data: dict,
    heat_threshold: float,
    aggregation: str,
    theme: Theme,
) -> None:
    """Tab 3 — Priority: ranked table with multi-metric columns and disagreement flag."""
    import streamlit as st

    multi = data.get("multi_metric_df")
    if multi is None or multi.empty:
        st.info("No portfolio data for priority ranking.")
        return

    col_n, col_sort = st.columns([1, 2])
    with col_n:
        top_n = st.number_input(
            "Top N buildings",
            min_value=5,
            max_value=500,
            value=25,
            step=5,
            key="priority_top_n",
        )
    with col_sort:
        sort_options = {
            "edh_zone_weighted": f"EDH, all rooms ({heat_threshold}°C)",
            "edh_worst_zone": f"EDH, hottest room ({heat_threshold}°C)",
            "exceedance_hours": f"Total hours above {heat_threshold}°C",
            "heat_index_caution_hours": "Heat-index caution hours",
        }
        available_sort = {k: v for k, v in sort_options.items() if k in multi.columns}
        sort_by = st.selectbox(
            "Sort by",
            options=list(available_sort.keys()),
            format_func=lambda x: str(available_sort.get(x, x)),
            key="priority_sort",
        )

    table = build_priority_table_df(multi, top_n=int(top_n), sort_by=sort_by)
    if table is None or table.empty:
        st.info("No data for priority table.")
        return

    display_cols = [BUILDING_ID_COL]
    col_config: dict = {BUILDING_ID_COL: st.column_config.TextColumn("Building")}

    if "edh_zone_weighted" in table.columns:
        display_cols.append("edh_zone_weighted")
        col_config["edh_zone_weighted"] = st.column_config.ProgressColumn(
            f"EDH, all rooms ({heat_threshold}°C)",
            help="Degree-hours (°C·hr), averaged over rooms by floor area.",
            format="%.1f",
            min_value=0,
            max_value=_oh_progress_column_max(
                cast(pd.Series, table["edh_zone_weighted"])
            ),
        )
    if "edh_worst_zone" in table.columns:
        display_cols.append("edh_worst_zone")
        col_config["edh_worst_zone"] = st.column_config.ProgressColumn(
            f"EDH, hottest room ({heat_threshold}°C)",
            help="Degree-hours (°C·hr) in the building's hottest room.",
            format="%.1f",
            min_value=0,
            max_value=_oh_progress_column_max(cast(pd.Series, table["edh_worst_zone"])),
        )
    if "exceedance_hours" in table.columns:
        display_cols.append("exceedance_hours")
        col_config["exceedance_hours"] = st.column_config.NumberColumn(
            f"Hours above {heat_threshold}°C",
            help="Hours with indoor air temperature above the threshold.",
            format="%.0f",
        )
    if "heat_index_caution_hours" in table.columns:
        display_cols.append("heat_index_caution_hours")
        col_config["heat_index_caution_hours"] = st.column_config.NumberColumn(
            "Heat-index caution hours",
            help="Hours with a heat index at NOAA Caution or worse.",
            format="%.0f",
        )
    if "disagreement" in table.columns:
        display_cols.append("disagreement")
        col_config["disagreement"] = st.column_config.CheckboxColumn(
            "Rankings differ",
            help="The building ranks very differently by degree-hours and by hours "
            "above threshold. Check it before choosing an intervention.",
        )

    st.dataframe(
        table[display_cols],
        width="stretch",
        column_config=col_config,
        hide_index=True,
    )

    csv = table[display_cols].to_csv(index=False)
    st.download_button(
        "Download table (CSV)",
        csv,
        file_name="overheating_priority.csv",
        mime="text/csv",
    )

    if "disagreement" in table.columns:
        n_flag = int(table["disagreement"].sum())
        if n_flag:
            st.caption(
                f"{n_flag} building(s) flagged: their EDH rank and exceedance-hours rank differ "
                "significantly. High EDH + low hours = intense but brief events; "
                "low EDH + high hours = persistent mild overheating. These call for different responses."
            )


def _render_tab_correlations(  # noqa: C901
    data: dict,
    heat_threshold: float,
    aggregation: str,
    theme: Theme,
) -> None:
    """Tab 4 — Correlations: morphology trellis, EUI vs EDH, box by floors, parallel coords."""
    eui_unit = current_eui_unit()  # set once under Settings in the sidebar
    eui_axis_lbl = energy_intensity_axis_label(eui_unit)
    eui_scale = energy_intensity_factor(eui_unit)
    multi = data.get("multi_metric_df")
    buildings_df = data.get("buildings_df")
    eui_edh = data.get("eui_edh_df")

    # --- Morphology small multiples ---
    edh_map = data.get("map_df")
    has_edh_map = (
        edh_map is not None and not edh_map.empty and "map_value" in edh_map.columns
    )

    if buildings_df is not None and has_edh_map:
        st.markdown("#### Design and Overheating Risk Relationships")

        # -- Categorical box plots --
        # Find object/category columns with bounded cardinality
        _SKIP_COLS = {"building_id", "id", "uuid", "LMK_KEY", "db_file", "Scenario"}
        cat_cols = [
            c
            for c in buildings_df.columns
            if c not in _SKIP_COLS
            and not pd.api.types.is_numeric_dtype(buildings_df[c])
            and 2 <= buildings_df[c].nunique() <= 20
        ][:8]  # cap at 8 panels

        if cat_cols:
            # Join EDH values onto buildings_df — resolve join key same way as numeric trellis
            from globi.tools.visualization.utils import (
                _resolve_buildings_join_key,
            )

            emap = cast(pd.DataFrame, edh_map)
            b_ids = emap[[BUILDING_ID_COL, "map_value"]].copy()
            b_ids[BUILDING_ID_COL] = b_ids[BUILDING_ID_COL].astype(str)
            map_ids = set(pd.unique(b_ids[BUILDING_ID_COL]))
            b_join = buildings_df.copy()
            join_key = _resolve_buildings_join_key(b_join, map_ids)
            if join_key is None:
                cat_cols = []  # no matching key — skip categorical panels
            else:
                if join_key != BUILDING_ID_COL:
                    b_join = b_join.drop(columns=[BUILDING_ID_COL], errors="ignore")
                    b_join = b_join.rename(columns={join_key: BUILDING_ID_COL})
                b_join[BUILDING_ID_COL] = b_join[BUILDING_ID_COL].astype(str)
            cat_merged = (
                b_join.merge(b_ids, on=BUILDING_ID_COL, how="inner")
                if cat_cols
                else pd.DataFrame()
            )
            if not cat_merged.empty and "map_value" in cat_merged.columns:
                cat_merged = cat_merged.dropna(subset=["map_value"])

            if not cat_merged.empty:
                st.divider()
                st.caption("Categorical attributes")
                cat_panels_per_row = 3
                for row_start in range(0, len(cat_cols), cat_panels_per_row):
                    row_cols_subset = cat_cols[
                        row_start : row_start + cat_panels_per_row
                    ]
                    cols_ui = st.columns(len(row_cols_subset))
                    for col, col_ui in zip(row_cols_subset, cols_ui, strict=False):
                        cat_vals = cat_merged[col].astype(str)
                        # Sort groups by median EDH descending
                        _gm = cat_merged.groupby(col)["map_value"].median()
                        grp_medians = cast(pd.Series, _gm).sort_values(ascending=False)
                        groups, boxes = [], []
                        for grp in grp_medians.index:
                            vals_g = (
                                cat_merged.loc[cat_vals == str(grp), "map_value"]
                                .astype(float)
                                .values
                            )
                            if len(vals_g) < 2:
                                continue
                            q1 = float(np.percentile(vals_g, 25))
                            med = float(np.median(vals_g))
                            q3 = float(np.percentile(vals_g, 75))
                            iqr = q3 - q1
                            lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                            w_lo = (
                                float(vals_g[vals_g >= lo_f].min())
                                if (vals_g >= lo_f).any()
                                else q1
                            )
                            w_hi = (
                                float(vals_g[vals_g <= hi_f].max())
                                if (vals_g <= hi_f).any()
                                else q3
                            )
                            outliers = vals_g[
                                (vals_g < lo_f) | (vals_g > hi_f)
                            ].tolist()
                            groups.append(str(grp))
                            boxes.append({
                                "min": w_lo,
                                "q1": q1,
                                "median": med,
                                "q3": q3,
                                "max": w_hi,
                                "n": len(vals_g),
                                "outliers": outliers,
                            })
                        if groups:
                            with col_ui:
                                box_html = create_box_plot_by_floors_d3_html(
                                    groups,
                                    boxes,
                                    x_label=col,
                                    y_label="EDH (°C·hr)",
                                    title=col,
                                    theme=theme,
                                )
                                components.html(box_html, height=430, scrolling=False)

    elif has_edh_map:
        st.info(
            "Building characteristics (buildings.parquet) aren't available for this "
            "run, so the design-vs-overheating charts are hidden. Put the file in the "
            "run's folder or in inputs/ to see them."
        )

    # --- EUI vs EDH and EUI vs Total hours above threshold (side by side) ---
    has_edh = (
        eui_edh is not None
        and not eui_edh.empty
        and "eui" in eui_edh.columns
        and "edh_zone_weighted" in eui_edh.columns
        and (eui_edh["eui"].notna() & eui_edh["edh_zone_weighted"].notna()).sum() >= 2
    )
    # exceedance hours: prefer columns from eui_edh (basic-only runs), else multi
    eui_hours = None
    if eui_edh is not None and "eui" in eui_edh.columns:
        if "exceedance_hours" in eui_edh.columns:
            eui_hours = eui_edh[[BUILDING_ID_COL, "eui", "exceedance_hours"]].dropna(
                subset=["eui", "exceedance_hours"]
            )
            if eui_hours.empty:
                eui_hours = None
        elif multi is not None and "exceedance_hours" in multi.columns:
            eui_hours = eui_edh[[BUILDING_ID_COL, "eui"]].merge(
                multi[[BUILDING_ID_COL, "exceedance_hours"]],
                on=BUILDING_ID_COL,
                how="inner",
            )
            eui_hours = eui_hours.dropna(subset=["eui", "exceedance_hours"])
            if eui_hours.empty:
                eui_hours = None

    if has_edh or eui_hours is not None:
        st.divider()
        st.markdown("#### EUI vs overheating metrics")
        st.caption(
            "Dashed lines mark the averages. Top-left: comfort bought with energy "
            "(e.g. cooling). Bottom-right: efficient but at risk of overheating."
        )
        if has_edh:
            edf = cast(pd.DataFrame, eui_edh)
            ok = edf["eui"].notna() & edf["edh_zone_weighted"].notna()
            scat = edf.loc[ok]
            if len(scat) >= 2:
                eui_y = convert_energy_intensity_values(
                    scat["eui"].astype(float).tolist(), eui_unit
                )
                mean_eui = float(sum(eui_y) / len(eui_y))
                mean_edh = float(scat["edh_zone_weighted"].mean())
                scat_html = create_scatter_d3_html(
                    scat["edh_zone_weighted"].astype(float).tolist(),
                    eui_y,
                    scat[BUILDING_ID_COL].astype(str).tolist(),
                    title="EUI vs EDH",
                    x_label=f"EDH ({aggregation.lower()}) at {heat_threshold}°C (°C·hr)",
                    y_label=eui_axis_lbl,
                    theme=theme,
                    vline=mean_edh,
                    hline=mean_eui,
                    quadrant_labels={
                        "tl": "comfort via cooling",
                        "tr": "energy + overheating concern",
                        "bl": "well performing",
                        "br": "efficient + overheating risk",
                    },
                )
                components.html(scat_html, height=510, scrolling=False)
                _formula_expander(
                    "How is EDH calculated?",
                    [
                        (
                            "**EDH** uses Standard Effective Temperature (SET) — accounts for dry-bulb, radiant temperature, humidity, MET, CLO, and air speed:",
                            None,
                        ),
                        (None, _FORMULA_EDH_ZONE),
                        ("Zone-weighted:", None),
                        (None, _FORMULA_EDH_ZW),
                    ],
                )

        if eui_hours is not None and len(eui_hours) >= 2:
            eui_h_y = convert_energy_intensity_values(
                eui_hours["eui"].astype(float).tolist(), eui_unit
            )
            mean_eui_h = float(sum(eui_h_y) / len(eui_h_y))
            mean_hrs = float(eui_hours["exceedance_hours"].mean())
            hrs_html = create_scatter_d3_html(
                eui_hours["exceedance_hours"].astype(float).tolist(),
                eui_h_y,
                eui_hours[BUILDING_ID_COL].astype(str).tolist(),
                title=f"EUI vs total hours above {heat_threshold}°C",
                x_label=f"Total hours above {heat_threshold}°C",
                y_label=eui_axis_lbl,
                theme=theme,
                vline=mean_hrs,
                hline=mean_eui_h,
                quadrant_labels={
                    "tl": "comfort via cooling",
                    "tr": "energy + long overheating periods",
                    "bl": "well performing",
                    "br": "efficient + overheating risk",
                },
            )
            components.html(hrs_html, height=510, scrolling=False)
            _formula_expander(
                "How are total hours above threshold calculated?",
                [
                    (
                        "**Total hours above threshold** — simple dry-bulb count, zone-weighted:",
                        None,
                    ),
                    (None, _FORMULA_BASIC_ZW),
                    ("where", None),
                    (None, _FORMULA_BASIC_ZONE),
                ],
            )

    # --- Box plot by number of floors (EDH only) ---
    if (
        eui_edh is not None
        and "num_floors" in eui_edh.columns
        and "edh_zone_weighted" in eui_edh.columns
        and (eui_edh["edh_zone_weighted"].notna()).sum() >= 3
    ):
        st.divider()
        st.markdown("#### EDH by number of floors")
        st.caption("Distribution of zone-weighted EDH grouped by floor count.")
        ok = eui_edh["edh_zone_weighted"].notna() & eui_edh["num_floors"].notna()
        bx_df = eui_edh.loc[ok].copy()
        bx_df["_floors"] = (
            bx_df["num_floors"].astype(float).round().astype(int).clip(1, 4)
        )
        bx_df["_floor_label"] = bx_df["_floors"].apply(
            lambda x: "4+" if x >= 4 else str(x)
        )
        groups_order = ["1", "2", "3", "4+"]
        groups, boxes = [], []
        for grp in groups_order:
            vals = (
                bx_df.loc[bx_df["_floor_label"] == grp, "edh_zone_weighted"]
                .astype(float)
                .values
            )
            if len(vals) < 3:
                continue
            q1, med, q3 = (
                float(np.percentile(vals, 25)),
                float(np.median(vals)),
                float(np.percentile(vals, 75)),
            )
            iqr = q3 - q1
            lo_fence, hi_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            whisker_lo = (
                float(vals[vals >= lo_fence].min()) if (vals >= lo_fence).any() else q1
            )
            whisker_hi = (
                float(vals[vals <= hi_fence].max()) if (vals <= hi_fence).any() else q3
            )
            outliers = vals[(vals < lo_fence) | (vals > hi_fence)].tolist()
            groups.append(grp)
            boxes.append({
                "min": whisker_lo,
                "q1": q1,
                "median": med,
                "q3": q3,
                "max": whisker_hi,
                "n": len(vals),
                "outliers": outliers,
            })
        if groups:
            box_html = create_box_plot_by_floors_d3_html(
                groups,
                boxes,
                y_label=f"EDH at {heat_threshold}°C (°C·hr)",
                theme=theme,
            )
            components.html(box_html, height=430, scrolling=False)
            _formula_expander(
                "Formula",
                [
                    (
                        "Each box shows the distribution of zone-weighted EDH by floor count (Tukey box: Q1-Q3, whiskers at 1.5xIQR):",
                        None,
                    ),
                    (None, _FORMULA_EDH_ZW),
                    ("where", None),
                    (None, _FORMULA_EDH_ZONE),
                ],
            )

    # --- Parallel coordinates (collapsed) ---
    if multi is not None and not multi.empty:
        with st.expander("Parallel coordinates", expanded=False):
            st.caption(
                "Each line is one building. Lines are coloured by EDH zone-weighted percentile "
                "(cool = low, warm = high). Useful for identifying multivariate patterns."
            )
            pc_cols = [
                c
                for c in (
                    "edh_zone_weighted",
                    "edh_worst_zone",
                    "exceedance_hours",
                    "heat_index_caution_hours",
                )
                if c in multi.columns
            ]
            if eui_edh is not None and "eui" in eui_edh.columns:
                pc_df = multi.merge(
                    eui_edh[[BUILDING_ID_COL, "eui"]], on=BUILDING_ID_COL, how="left"
                )
                pc_cols_full = [*pc_cols, "eui"]
            else:
                pc_df = multi
                pc_cols_full = pc_cols
            if pc_cols_full:
                pc = pc_df[pc_cols_full].dropna(how="all")
                # the chart keeps 500 evenly spaced lines; thin first instead of looping all rows
                if len(pc) > 500:
                    pc = pc.iloc[:: max(1, len(pc) // 500)].iloc[:500]
                if "eui" in pc.columns:
                    pc = pc.assign(eui=pc["eui"] * eui_scale)
                pc_records = [
                    {k: float(v) for k, v in rec.items() if pd.notna(v)}
                    for rec in pc.to_dict("records")
                ]
                if pc_records:
                    pc_html = create_parallel_coordinates_d3_html(
                        pc_records,
                        pc_cols_full,
                        color_axis="edh_zone_weighted",
                        theme=theme,
                        axis_labels={"eui": eui_axis_lbl},
                    )
                    components.html(pc_html, height=420, scrolling=False)


@st.cache_data(show_spinner=False, max_entries=16)
def _cached_fan_wide(
    run_dir_str: str, inputs_mtime: float, data_source_type: str, aggregation: str
) -> pd.DataFrame | None:
    """Building x threshold table for one metric, cached by run files."""
    return build_overheating_threshold_fan_wide_df(
        Path(run_dir_str), data_source_type, aggregation
    )


def _threshold_series(wide: pd.DataFrame) -> dict[float, list[float]]:
    """Per-threshold building values from the building x threshold table."""
    series: dict[float, list[float]] = {}
    for col_name in wide.columns:
        try:
            thr = float(col_name)
        except ValueError:
            continue
        vals = wide[col_name].dropna().tolist()
        if vals:
            series[thr] = vals
    return series


def _render_threshold_overlay_chart(
    run_dir: Path,
    available_files: list[str],
    allowed: set[str] | None,
) -> None:
    """Show overlaid KDE distributions for all thresholds, one panel per metric."""
    theme = cast(Theme, _streamlit_theme())

    metric_labels = {
        "ExceedanceDegreeHours": ("EDH (°C·hr)", "ExceedanceDegreeHours"),
        "BasicOverheating": ("Total hours above threshold", "BasicOverheating"),
    }
    panels: list[tuple[str, str]] = [
        (label, dstype)
        for dstype, (label, _) in metric_labels.items()
        if dstype in available_files
    ]

    if not panels:
        return

    cols = st.columns(len(panels))
    for col, (x_label, dstype) in zip(cols, panels, strict=False):
        wide = _cached_fan_wide(
            str(run_dir.resolve()),
            _overheating_map_inputs_mtime(run_dir, dstype),
            dstype,
            "Zone Weighted",
        )
        if wide is None or wide.empty:
            continue
        if allowed is not None:
            wide = cast(pd.DataFrame, wide[wide.index.astype(str).isin(list(allowed))])
        series = _threshold_series(wide)
        if not series:
            continue

        html = create_threshold_overlay_kde_d3_html(
            series,
            title=f"Distribution — {x_label}",
            x_label=x_label,
            theme=theme,
        )
        with col:
            components.html(html, height=260, scrolling=False)
            if dstype == "ExceedanceDegreeHours":
                _formula_expander(
                    "How is EDH calculated?",
                    [
                        (
                            "**Exceedance Degree Hours** — uses Standard Effective Temperature (SET), not dry-bulb:",
                            None,
                        ),
                        (None, _FORMULA_EDH_ZONE),
                        (
                            "Aggregated to building level with zone area weights $\\tilde{w}_z$.",
                            None,
                        ),
                    ],
                )
            elif dstype == "BasicOverheating":
                _formula_expander(
                    "How are total hours above threshold calculated?",
                    [
                        (
                            "**Total hours above threshold** — counts hours where dry-bulb exceeds the threshold:",
                            None,
                        ),
                        (None, _FORMULA_BASIC_ZONE),
                        ("Aggregated with zone area weights $\\tilde{w}_z$.", None),
                    ],
                )


_SECTIONS = ("Portfolio", "Map", "Priority list", "Correlations")


def _render_measures_explainer() -> None:
    """Plain-language meaning of the overheating measures used on this page."""
    with st.expander("What these measures mean"):
        st.markdown(
            "- **Hours above threshold**: hours in a year the indoor air is warmer "
            "than the chosen temperature.\n"
            "- **Degree-hours (EDH)**: like hours above threshold, but each hour counts "
            "by *how much* it is too warm (°C·hr). It uses a comfort temperature that "
            "also accounts for humidity and radiant heat, so hotter hours weigh more.\n"
            "- **Heat-index caution hours**: hours whose heat index (temperature plus "
            "humidity) is in NOAA's *Caution* band or worse.\n"
            "- **Longest streak**: the longest run of consecutive hours above the "
            "threshold in any room.\n"
            "- **All rooms (zone weighted)** averages a building's rooms by floor area; "
            "**hottest room (worst zone)** uses its worst room.\n"
            "- **Median / top 10% (P90)**: half of buildings are below the median; "
            "9 in 10 are below the P90 value.\n\n"
            "Formulas: the *Overheating metrics* reference in the GloBI docs."
        )


def render_overheating_page(data_source: DataSource) -> None:
    """Overheating page: hours and degree-hours above temperature thresholds, by building."""
    st.header("Overheating")
    _render_overheating_use_case(data_source)


def _building_filter_ids(data_source: DataSource, selected_run: str) -> set[str] | None:
    """Building ids allowed by the sidebar filters (None when nothing is filtered)."""
    try:
        energy_df, _ = load_run(data_source, selected_run)
    except Exception:
        return None
    if "building_id" not in (energy_df.index.names or []):
        return None
    selections = building_filters(energy_df)
    if not selections:
        return None
    mask = filter_mask(energy_df, selections)
    ids = energy_df.index.get_level_values("building_id")[mask].astype(str)
    st.caption(f"Showing {mask.sum():,} of {len(mask):,} buildings (filtered)")
    return set(ids)


def _render_overheating_use_case(data_source: DataSource) -> None:
    """Render overheating analysis: shared controls, then one section at a time."""
    runs_with_oh = data_source.list_runs_with_overheating()
    if not runs_with_oh:
        st.info(
            "No runs with overheating results. Add an overheating_config to the "
            "run's manifest and simulate again."
        )
        return

    selected_run = st.selectbox(
        "Run", options=runs_with_oh, format_func=run_label, key="overheating_run"
    )
    available_files = data_source.list_overheating_files(selected_run)
    if not available_files:
        st.info("This run has no overheating results.")
        return

    thresholds = data_source.get_overheating_thresholds(selected_run)

    oh_rr_hint: dict = {
        "has_footprints": False,
        "suggested_crs": None,
        "scores": {},
        "n_geoms": 0,
        "native_bounds": None,
        "ambiguous": False,
        "tied_crs": (),
    }
    run_dir = data_source.resolve_run_dir(selected_run)
    if run_dir is not None:
        pq_hint = get_pq_file_for_run(run_dir)
        if pq_hint is not None and pq_hint.exists():
            oh_rr_hint = _cached_infer_rotated_rectangle_crs_hint(
                str(pq_hint.resolve()),
                pq_hint.stat().st_mtime,
            )

    col1, col2 = st.columns(2)
    with col1:
        heat_threshold = st.selectbox(
            "Temperature threshold (°C)",
            options=thresholds,
            index=0,
            key="oh_threshold",
        )
    with col2:
        aggregation = st.selectbox(
            "Across a building's rooms",
            options=["Zone Weighted", "Worst Zone"],
            format_func=lambda a: "All rooms (zone weighted)"
            if a == "Zone Weighted"
            else "Hottest room (worst zone)",
            index=0,
            key="oh_aggregation",
            help="How room-by-room results become one number per building.",
        )
    cart_crs = resolve_map_crs(oh_rr_hint)
    _render_measures_explainer()

    allowed = _building_filter_ids(data_source, selected_run)
    with st.spinner("Loading overheating results..."):
        dashboard_data = _filter_dashboard(
            _load_overheating_dashboard_data(
                data_source, selected_run, heat_threshold, aggregation, cart_crs
            ),
            allowed,
        )

    theme = cast(Theme, _streamlit_theme())

    # one section at a time: st.tabs would compute all four on every interaction
    section = st.radio(
        "Section",
        options=_SECTIONS,
        horizontal=True,
        key="oh_section",
        label_visibility="collapsed",
    )
    if section == "Portfolio":
        if run_dir is not None and thresholds:
            _render_threshold_overlay_chart(run_dir, available_files, allowed)
        _render_tab_portfolio(dashboard_data, heat_threshold, aggregation, theme)
    elif section == "Map":
        _render_tab_geography(
            dashboard_data,
            heat_threshold,
            aggregation,
            cart_crs,
            data_source,
            selected_run,
            theme,
        )
    elif section == "Priority list":
        _render_tab_priority(dashboard_data, heat_threshold, aggregation, theme)
    else:
        _render_tab_correlations(dashboard_data, heat_threshold, aggregation, theme)
