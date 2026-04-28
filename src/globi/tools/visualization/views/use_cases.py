"""Use Cases page for specialized analyses."""

from __future__ import annotations

import math
from typing import cast

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.models import UseCaseType
from globi.tools.visualization.plotting import (
    Theme,
    create_binned_bar_d3_html,
    create_box_plot_by_floors_d3_html,
    create_building_map_deck,
    create_building_map_deck_from_cache,
    create_comparison_bar_d3_html,
    create_comparison_kde_d3_html,
    create_comparison_stacked_bar_d3_html,
    create_flat_footprint_deck,
    create_heat_index_stacked_bar_d3_html,
    create_histogram_d3_html,
    create_overheating_threshold_fan_d3_html,
    create_parallel_coordinates_d3_html,
    create_scatter_d3_html,
    create_threshold_overlay_kde_d3_html,
    create_threshold_sensitivity_dot_range_d3_html,
)
from globi.tools.visualization.results_data import (
    apply_scenario_display_names,
    extract_comparison_data,
    extract_retrofit_comparison_data,
    is_results_format,
    normalize_fuel_name,
)
from globi.tools.visualization.utils import (
    BUILDING_ID_COL,
    build_building_area_df,
    build_consecutive_exceedances_building_df,
    build_eui_vs_edh_df,
    build_heat_index_per_building_df,
    build_overheating_threshold_fan_wide_df,
    build_portfolio_multi_metric_df,
    build_priority_table_df,
    build_threshold_sensitivity_df,
    build_worst_zone_ratio_df,
    resolve_buildings_df_for_overheating_plots,
    sample_overheating_fan_payload,
)
from globi.tools.visualization.views.raw_data import (
    _chart_download,
    _render_colormap_legend,
    _streamlit_theme,
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
                st.plotly_chart(fig_count, use_container_width=True)
            with col_a:
                st.caption("Total conditioned floor area per metric bin")
                st.plotly_chart(fig_area, use_container_width=True)
        else:
            st.caption(
                "Conditioned floor area is unavailable for this run; add energy outputs "
                "with floor area to see area-weighted bins."
            )
            st.plotly_chart(fig_count, use_container_width=True)
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


def render_use_cases_page(data_source: DataSource) -> None:
    """Render the use cases page (scaffolding)."""
    st.subheader("Use Cases")

    use_case = st.selectbox(
        "Select Use Case",
        options=[uc.value for uc in UseCaseType],
        format_func=lambda x: x.replace("_", " ").title(),
    )

    if use_case == UseCaseType.RETROFIT.value:
        _render_retrofit_use_case(data_source)
    elif use_case == UseCaseType.OVERHEATING.value:
        _render_overheating_use_case(data_source)
    elif use_case == UseCaseType.SCENARIO_COMPARISON.value:
        _render_scenario_comparison(data_source)


# fuel labels matching simulation output (EnergyPlus Utilities meters)
_FUEL_LABELS = ("Electricity", "Natural Gas", "Fuel Oil", "Propane")
_DEFAULT_ENERGY_COSTS = (0.22, 0.05, 0.10, 0.08)
_DEFAULT_EMISSIONS = (0.4, 0.2, 0.27, 0.23)


def _build_eui_csv(comparison_data: dict) -> pd.DataFrame:
    """Build csv-friendly dataframe from eui distribution data."""
    eui = comparison_data.get("eui_data", {})
    if not eui:
        return pd.DataFrame()
    max_len = max((len(v) for v in eui.values()), default=0)
    return pd.DataFrame({k: v + [None] * (max_len - len(v)) for k, v in eui.items()})


def _build_stacked_csv(comparison_data: dict, data_key: str) -> pd.DataFrame:
    """Build csv-friendly dataframe from stacked bar data."""
    data = comparison_data.get(data_key, {})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data).T.fillna(0)
    df.index.name = "scenario"
    return df.reset_index()


def _build_totals_csv(
    comparison_data: dict,
    value_key: str,
    label: str = "value",
) -> pd.DataFrame:
    """Build csv-friendly dataframe from scenario totals."""
    scenarios = comparison_data.get("scenarios", [])
    values = comparison_data.get(value_key, {})
    if not values:
        return pd.DataFrame()
    return pd.DataFrame({
        "scenario": [s for s in scenarios if s in values],
        label: [values[s] for s in scenarios if s in values],
    })


def _uniquify_display_names(
    run_ids,
    raw_names: dict[str, str],
) -> dict[str, str]:
    """Build run_id -> unique display name mapping, appending (n) on collisions."""
    seen: dict[str, int] = {}
    out: dict[str, str] = {}
    for rid in run_ids:
        d = (raw_names.get(rid, rid) or "").strip() or rid
        if d in seen:
            seen[d] += 1
            d = f"{d} ({seen[d]})"
        else:
            seen[d] = 1
        out[rid] = d
    return out


def _retrofit_params_form(
    selected_runs: list[str],
) -> tuple[
    dict[str, dict[str, float]],
    dict[str, dict[str, float]],
    dict[str, float],
    dict[str, str],
]:
    """Render per-scenario cost/emissions/system-cost form.

    Returns (per_scenario_energy_costs, per_scenario_emissions,
    system_costs_per_sqm, display_names).  All dicts keyed by run_id.
    """
    per_scenario_energy_costs: dict[str, dict[str, float]] = {}
    per_scenario_emissions: dict[str, dict[str, float]] = {}
    system_costs_per_sqm: dict[str, float] = {}
    display_names: dict[str, str] = {}

    for run_id in selected_runs:
        with st.expander(
            f"Parameters: {run_id}",
            expanded=(run_id == selected_runs[0]),
        ):
            val = st.text_input(
                "Display name",
                value=run_id,
                key=f"retrofit_display_{run_id}",
                placeholder=run_id,
            )
            display_names[run_id] = (val.strip() or run_id) if val else run_id

            st.markdown("**Energy cost factors** ($/kWh by fuel type)")
            ec_factors: dict[str, float] = {}
            ec_cols = st.columns(4)
            for i, (label, default) in enumerate(
                zip(_FUEL_LABELS, _DEFAULT_ENERGY_COSTS, strict=True)
            ):
                with ec_cols[i % 4]:
                    key = normalize_fuel_name(label)
                    ec_factors[key] = st.number_input(
                        label,
                        min_value=0.0,
                        value=default,
                        format="%.3f",
                        key=f"ec_{key}_{run_id}",
                    )
            per_scenario_energy_costs[run_id] = ec_factors

            st.markdown("**Emissions factors** (kg CO2/kWh by fuel type)")
            em_factors: dict[str, float] = {}
            em_cols = st.columns(4)
            for i, (label, default) in enumerate(
                zip(_FUEL_LABELS, _DEFAULT_EMISSIONS, strict=True)
            ):
                with em_cols[i % 4]:
                    key = normalize_fuel_name(label)
                    em_factors[key] = st.number_input(
                        label,
                        min_value=0.0,
                        value=default,
                        format="%.3f",
                        key=f"em_{key}_{run_id}",
                    )
            per_scenario_emissions[run_id] = em_factors

            st.markdown(
                "**System cost** ($/m² applied per building by conditioned area)"
            )
            system_costs_per_sqm[run_id] = st.number_input(
                "System cost ($/m²)",
                min_value=0.0,
                value=0.0,
                format="%.2f",
                key=f"syscost_{run_id}",
            )

    return (
        per_scenario_energy_costs,
        per_scenario_emissions,
        system_costs_per_sqm,
        display_names,
    )


def _render_retrofit_use_case(data_source: DataSource) -> None:
    """Render retrofit analysis: compare scenarios with cost, emissions, energy."""
    st.markdown("### Retrofit Analysis")
    st.markdown(
        "Compare retrofit scenarios with energy savings, costs, and emissions. "
        "Each scenario has its own energy cost factors, emissions factors, and "
        "system cost ($/m², applied per building by conditioned area)."
    )

    available_runs = data_source.list_available_runs()
    if len(available_runs) < 2:
        st.warning("Need at least 2 runs for retrofit comparison.")
        return

    selected_runs = st.multiselect(
        "Select scenarios to compare",
        options=available_runs,
        default=available_runs[:2],
        key="retrofit_scenarios",
    )

    with st.expander("Retrofit cost and emissions parameters", expanded=True):
        (
            per_scenario_energy_costs,
            per_scenario_emissions,
            system_costs_per_sqm,
            display_names,
        ) = _retrofit_params_form(selected_runs)

    if len(selected_runs) < 2:
        st.info("Select at least 2 scenarios to generate a comparison.")
        return

    if not st.button("Compare Scenarios", key="retrofit_compare"):
        return

    dfs: dict[str, pd.DataFrame] = {}
    for run_id in selected_runs:
        try:
            df = data_source.load_run_data(run_id)
            if not is_results_format(df):
                st.warning(
                    f"Run '{run_id}' is not in the expected results format, skipping."
                )
                continue
            dfs[run_id] = df
        except Exception as exc:
            st.warning(f"Could not load '{run_id}': {exc}")

    if len(dfs) < 2:
        st.error("Could not load enough valid scenarios for comparison.")
        return

    # build unique display-name mapping (disambiguate duplicates)
    name_map = _uniquify_display_names(dfs.keys(), display_names)

    # remap all dicts to display names so charts/map use them throughout
    dfs = {name_map[k]: v for k, v in dfs.items()}
    per_scenario_energy_costs = {
        name_map.get(k, k): v for k, v in per_scenario_energy_costs.items()
    }
    per_scenario_emissions = {
        name_map.get(k, k): v for k, v in per_scenario_emissions.items()
    }
    system_costs_per_sqm = {
        name_map.get(k, k): v for k, v in system_costs_per_sqm.items()
    }

    theme = cast(Theme, _streamlit_theme())
    with st.spinner("Building comparison dashboard..."):
        comparison_data = extract_retrofit_comparison_data(
            dfs,
            region_name="",
            per_scenario_energy_costs=per_scenario_energy_costs,
            per_scenario_emissions=per_scenario_emissions,
            system_costs_per_sqm=system_costs_per_sqm,
        )
        _render_retrofit_charts(
            comparison_data,
            dfs=dfs,
            per_scenario_energy_costs=per_scenario_energy_costs,
            per_scenario_emissions=per_scenario_emissions,
            system_costs_per_sqm=system_costs_per_sqm,
            theme=theme,
        )


def _render_retrofit_charts(
    comparison_data: dict,
    dfs: dict[str, pd.DataFrame] | None = None,
    per_scenario_energy_costs: dict[str, dict[str, float]] | None = None,
    per_scenario_emissions: dict[str, dict[str, float]] | None = None,
    system_costs_per_sqm: dict[str, float] | None = None,
    *,
    theme: Theme,
) -> None:
    """Render retrofit comparison charts (EUI, end uses, fuel, cost, emissions) and map."""
    st.markdown("#### EUI distribution comparison")
    kde_html = create_comparison_kde_d3_html(comparison_data, theme=theme)
    components.html(kde_html, height=360, scrolling=False)
    _chart_download(
        "retro_kde",
        _build_eui_csv(comparison_data).to_csv(index=False),
        kde_html,
        "eui_distribution",
    )

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("#### End uses comparison (share)")
        eu_html = create_comparison_stacked_bar_d3_html(
            comparison_data,
            data_key="end_uses_data",
            color_key="end_use_colors",
            title="end uses comparison",
            theme=theme,
        )
        components.html(eu_html, height=360, scrolling=False)
        _chart_download(
            "retro_eu",
            _build_stacked_csv(comparison_data, "end_uses_data").to_csv(index=False),
            eu_html,
            "end_uses",
        )
    with col_right:
        st.markdown("#### Fuel/utilities comparison (share)")
        fuel_html = create_comparison_stacked_bar_d3_html(
            comparison_data,
            data_key="utilities_data",
            color_key="fuel_colors",
            title="fuel/utilities comparison",
            theme=theme,
        )
        components.html(fuel_html, height=360, scrolling=False)
        _chart_download(
            "retro_fuel",
            _build_stacked_csv(comparison_data, "utilities_data").to_csv(index=False),
            fuel_html,
            "fuel_utilities",
        )

    abs_left, abs_right = st.columns(2)
    with abs_left:
        st.markdown("#### End uses comparison (absolute)")
        eu_abs_html = create_comparison_stacked_bar_d3_html(
            comparison_data,
            data_key="end_uses_data",
            color_key="end_use_colors",
            title="end uses comparison (absolute)",
            theme=theme,
            mode="absolute",
            value_label="energy (kWh)",
        )
        components.html(eu_abs_html, height=360, scrolling=False)
        _chart_download(
            "retro_eu_abs",
            _build_stacked_csv(comparison_data, "end_uses_data").to_csv(index=False),
            eu_abs_html,
            "end_uses_absolute",
        )
    with abs_right:
        st.markdown("#### Fuel/utilities comparison (absolute)")
        fuel_abs_html = create_comparison_stacked_bar_d3_html(
            comparison_data,
            data_key="utilities_data",
            color_key="fuel_colors",
            title="fuel/utilities comparison (absolute)",
            theme=theme,
            mode="absolute",
            value_label="energy (kWh)",
        )
        components.html(fuel_abs_html, height=360, scrolling=False)
        _chart_download(
            "retro_fuel_abs",
            _build_stacked_csv(comparison_data, "utilities_data").to_csv(index=False),
            fuel_abs_html,
            "fuel_utilities_absolute",
        )

    if comparison_data.get("cost_totals"):
        st.markdown("#### Total cost comparison (energy + system)")
        cost_data = {
            "scenarios": comparison_data["scenarios"],
            "cost_totals": comparison_data["cost_totals"],
        }
        cost_html = create_comparison_bar_d3_html(
            cost_data,
            value_key="cost_totals",
            title="total cost",
            value_label="annual cost ($)",
            theme=theme,
        )
        components.html(cost_html, height=200, scrolling=False)
        _chart_download(
            "retro_cost",
            _build_totals_csv(comparison_data, "cost_totals", "annual_cost_usd").to_csv(
                index=False
            ),
            cost_html,
            "total_cost",
        )

    if comparison_data.get("emissions_totals"):
        st.markdown("#### Total emissions comparison")
        em_data = {
            "scenarios": comparison_data["scenarios"],
            "emissions_totals": comparison_data["emissions_totals"],
        }
        em_html = create_comparison_bar_d3_html(
            em_data,
            value_key="emissions_totals",
            title="emissions",
            value_label="kg CO2/year",
            theme=theme,
        )
        components.html(em_html, height=200, scrolling=False)
        _chart_download(
            "retro_em",
            _build_totals_csv(
                comparison_data, "emissions_totals", "kg_co2_per_year"
            ).to_csv(index=False),
            em_html,
            "emissions",
        )

    if dfs and per_scenario_energy_costs and per_scenario_emissions:
        _render_retrofit_map(
            dfs,
            per_scenario_energy_costs,
            per_scenario_emissions,
            system_costs_per_sqm or {},
        )


@st.cache_data(show_spinner="Building map geometry...")
def _build_retrofit_geometry_cache(scenario: str, cart_crs: str, _map_df: pd.DataFrame):
    """Build geometry from map_df. _map_df excluded from cache key (use scenario)."""
    from globi.tools.visualization.utils import build_map_features_from_df

    return build_map_features_from_df(_map_df, cart_crs=cart_crs, value_col=None)


def _render_retrofit_map(
    dfs: dict[str, pd.DataFrame],
    per_scenario_energy_costs: dict[str, dict[str, float]],
    per_scenario_emissions: dict[str, dict[str, float]],
    system_costs_per_sqm: dict[str, float],
) -> None:
    """Render pydeck map with selectable metric and colormap. Caches geometry per scenario/CRS."""
    from globi.tools.visualization.results_data import build_retrofit_map_df

    st.markdown("#### Building map by retrofit metric")

    col1, col2, col3 = st.columns(3)
    with col1:
        scenario = st.selectbox(
            "Scenario",
            options=list(dfs.keys()),
            key="retrofit_map_scenario",
        )
    with col2:
        metric_option = st.selectbox(
            "Color by",
            options=[
                ("eui", "greens", "EUI (kWh/m²)"),
                ("total_energy", "viridis", "Total energy (kWh)"),
                ("energy_cost", "reds", "Energy cost ($)"),
                ("emissions", "reds", "Emissions (kg CO2)"),
                ("capital_cost", "plasma", "System cost ($)"),
                ("total_cost", "reds", "Total cost ($)"),
                ("peak_per_sqm", "reds", "Peak per sqm (kW/m²)"),
                ("total_peak", "plasma", "Total peak (kW)"),
            ],
            format_func=lambda x: x[2],
            key="retrofit_map_metric",
        )
        value_col, default_cmap, metric_label = metric_option
    with col3:
        cmap = st.selectbox(
            "Colormap",
            options=["reds", "greens", "viridis", "plasma"],
            index=["reds", "greens", "viridis", "plasma"].index(default_cmap),
            key="retrofit_map_cmap",
        )

    cart_crs = st.selectbox(
        "Polygon CRS",
        options=[
            "EPSG:3857",
            "EPSG:32633",
            "EPSG:32632",
            "EPSG:4326",
            "EPSG:3035",  # Budapest buddies
            "EPSG:32610",  # Seattle
            "EPSG:32612",  # TeamSuns, Phoenix2
            "EPSG:32619",  # Everett2, EverlastingEverett
        ],
        index=0,
        key="retrofit_map_crs",
    )

    scenario_ec = per_scenario_energy_costs.get(scenario, {})
    scenario_em = per_scenario_emissions.get(scenario, {})
    scenario_syscost = system_costs_per_sqm.get(scenario, 0.0)
    map_df = build_retrofit_map_df(
        dfs[scenario],
        scenario_ec,
        scenario_em,
        system_cost_per_sqm=scenario_syscost,
        cart_crs=cart_crs,
    )
    if map_df is None or map_df.empty:
        st.info(
            "Map unavailable. Output must have rotated_rectangle and height. "
            "Check that the selected scenario has valid geometry."
        )
        return

    if value_col not in map_df.columns:
        st.warning(f"Metric '{value_col}' not available for this scenario.")
        return

    geometry = _build_retrofit_geometry_cache(scenario, cart_crs, map_df)
    if geometry is not None:
        result = create_building_map_deck_from_cache(
            geometry,
            map_df,
            value_col=value_col,
            cmap=cmap,
        )
    else:
        result = create_building_map_deck(
            map_df,
            cart_crs=cart_crs,
            value_col=value_col,
            cmap=cmap,
        )
    if result is None:
        st.info("Could not build map.")
        return

    deck, n_features, value_stats = result
    st.pydeck_chart(deck)
    st.caption(f"{n_features} buildings displayed")

    if value_stats:
        _render_colormap_legend(metric_label, value_stats, cmap)


def _load_overheating_dashboard_data(
    data_source: DataSource,
    selected_run: str,
    heat_threshold: float,
    aggregation: str,
    cart_crs: str,
) -> dict:
    """Load all overheating data at once; values may be None if unavailable."""
    run_dir = data_source.resolve_run_dir(selected_run)
    available_files = data_source.list_overheating_files(selected_run)
    thresholds = data_source.get_overheating_thresholds(selected_run)

    primary_dstype = (
        "ExceedanceDegreeHours"
        if "ExceedanceDegreeHours" in available_files
        else (available_files[0] if available_files else "BasicOverheating")
    )

    map_df = data_source.load_overheating_map_data(
        selected_run,
        cart_crs=cart_crs,
        heat_threshold_c=heat_threshold,
        aggregation=aggregation,
        data_source_type=primary_dstype,
        heat_index_metric="danger_hours",
    )

    multi_metric_df = None
    heat_index_df = None
    threshold_sensitivity_df = None
    fan_wide = None
    eui_edh_df = None
    buildings_df = None

    building_area_df = None
    consecutive_df = None
    if run_dir is not None:
        multi_metric_df = build_portfolio_multi_metric_df(
            run_dir, heat_threshold, aggregation
        )
        heat_index_df = build_heat_index_per_building_df(run_dir, aggregation)
        threshold_sensitivity_df = build_threshold_sensitivity_df(
            run_dir, primary_dstype, aggregation
        )
        fan_wide = build_overheating_threshold_fan_wide_df(
            run_dir, primary_dstype, aggregation
        )
        eui_edh_df = build_eui_vs_edh_df(run_dir, heat_threshold, aggregation)
        buildings_df = resolve_buildings_df_for_overheating_plots(
            run_dir,
            data_source.load_building_locations,
        )
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
        "available_files": available_files,
        "thresholds": thresholds,
        "eui_edh_df": eui_edh_df,
        "buildings_df": buildings_df,
        "building_area_df": building_area_df,
        "consecutive_df": consecutive_df,
        "primary_dstype": primary_dstype,
    }


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

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        val = f"{edh_vals.median():.1f} °C·hr" if not edh_vals.empty else "—"
        st.metric(
            "Fleet median EDH",
            val,
            help=f"Zone-weighted EDH at {heat_threshold}°C threshold",
        )
    with c2:
        if not hours_vals.empty:
            pct = (hours_vals > 0).mean() * 100
            st.metric(
                "Buildings with any hours over threshold",
                f"{pct:.0f}%",
                help=f"Share of buildings with at least one hour above {heat_threshold}°C",
            )
        else:
            st.metric("Buildings with any hours over threshold", "—")
    with c3:
        # Floor area with any hours over threshold
        if (
            not hours_vals.empty
            and building_area_df is not None
            and not building_area_df.empty
        ):
            area_hours = (
                multi[[BUILDING_ID_COL, "exceedance_hours"]]
                .merge(
                    building_area_df[[BUILDING_ID_COL, "conditioned_area_m2"]],
                    on=BUILDING_ID_COL,
                    how="inner",
                )
                .dropna(subset=["exceedance_hours", "conditioned_area_m2"])
            )
            if not area_hours.empty:
                total_area = area_hours["conditioned_area_m2"].sum()
                exceed_area = area_hours.loc[
                    area_hours["exceedance_hours"] > 0, "conditioned_area_m2"
                ].sum()
                area_pct = (exceed_area / total_area * 100) if total_area > 0 else 0.0
                st.metric(
                    "Floor area with any hours over threshold",
                    f"{area_pct:.0f}%",
                    help=f"Share of total conditioned floor area (m²) in buildings with at least one hour above {heat_threshold}°C",
                )
            else:
                st.metric("Floor area with any hours over threshold", "—")
        else:
            st.metric(
                "Floor area with any hours over threshold",
                "—",
                help="Requires conditioned area data from EnergyAndPeak outputs",
            )
    with c4:
        val = (
            f"{float(np.percentile(edh_wz_vals, 90)):.1f} °C·hr"
            if not edh_wz_vals.empty
            else "—"
        )
        st.metric(
            "Worst-zone EDH (P90)",
            val,
            help="90th-percentile worst-zone EDH across the portfolio",
        )
    with c5:
        val = f"{hi_vals.mean():.0f} hr" if not hi_vals.empty else "—"
        st.metric(
            "Mean heat index caution hrs",
            val,
            help="Mean caution+ hours per building (zone-weighted)",
        )

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
            "EDH zone-weighted",
            f"EDH at {heat_threshold}°C (°C·hr)",
        ),
        (
            "exceedance_hours",
            "Total hours above threshold",
            f"Total hours above {heat_threshold}°C",
        ),
        ("heat_index_caution_hours", "Heat index caution+ hrs", "Caution+ hours (hr)"),
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
            "Dot = fleet median; bar = interquartile range (P25-P75). "
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
                        "Each point shows fleet median EDH and P25-P75 IQR at a given threshold:",
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
                        "Each point shows fleet median total hours above threshold and P25-P75 IQR at a given threshold:",
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
            "Buildings sorted by caution+ total (highest at top). Shows up to 200 buildings."
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
) -> None:
    """Render the plan-view flat footprint map for the selected buildings.

    If fill_color is provided, all buildings are drawn in that single RGBA colour
    (no colormap gradient).
    """
    st.markdown("**Where are the buildings located?**")
    if filtered_map.empty:
        st.info("No buildings in the selected range.")
        return
    flat_result = create_flat_footprint_deck(
        filtered_map,
        cart_crs=cart_crs,
        value_col=None if fill_color else "map_value",
        cmap="reds",
        fill_color=fill_color,
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
        metric_options.append(("HeatIndexCategories", "Heat index caution+ hours"))
    if not metric_options:
        st.info("No overheating outputs found.")
        return

    col_m, col_agg = st.columns([2, 1])
    with col_m:
        chosen = st.selectbox(
            "Map metric",
            options=[o[0] for o in metric_options],
            format_func=lambda x: next(
                label for key, label in metric_options if key == x
            ),
            key="geo_tab_metric",
        )
    with col_agg:
        geo_agg = st.selectbox(
            "Aggregation", ["Zone Weighted", "Worst Zone"], key="geo_tab_agg"
        )

    if chosen is None:
        return

    with st.spinner("Loading map data..."):
        map_df = data_source.load_overheating_map_data(
            selected_run,
            cart_crs=cart_crs,
            heat_threshold_c=heat_threshold,
            aggregation=geo_agg,
            data_source_type=chosen,
            heat_index_metric="danger_hours",
        )

    if map_df is None or map_df.empty:
        st.info("No map data available for this selection.")
        return

    metric_label = str(
        next((label for key, label in metric_options if key == chosen), chosen)
    )

    # 3D map
    st.markdown("#### 3D building map")
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
    sel_lo, sel_hi = st.slider(
        f"{metric_label} range",
        min_value=val_min,
        max_value=val_max,
        value=(val_min, val_max),
        step=_step,
        key=brush_key,
        format="%.1f",
    )

    # Convenience percentile readout
    lo_pct = float(np.mean(arr <= sel_lo) * 100)
    hi_pct = float(np.mean(arr <= sel_hi) * 100)
    n_sel = int(((arr >= sel_lo) & (arr <= sel_hi)).sum())
    st.caption(
        f"**{n_sel} of {len(arr)} buildings** selected "
        f"(P{lo_pct:.0f}-P{hi_pct:.0f} of the portfolio)"
    )

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
        )

    if "BasicOverheating" in available_files and chosen != "BasicOverheating":
        _render_geo_hours_brush_panel(
            data_source, selected_run, heat_threshold, geo_agg, cart_crs, theme
        )


def _render_geo_hours_brush_panel(
    data_source: DataSource,
    selected_run: str,
    heat_threshold: float,
    geo_agg: str,
    cart_crs: str,
    theme: Theme,
) -> None:
    """Second geography brush panel: total hours above threshold, buildings shown in flat red."""
    st.divider()
    with st.spinner("Loading total hours above threshold map..."):
        hrs_map_df = data_source.load_overheating_map_data(
            selected_run,
            cart_crs=cart_crs,
            heat_threshold_c=heat_threshold,
            aggregation=geo_agg,
            data_source_type="BasicOverheating",
            heat_index_metric="danger_hours",
        )
    if hrs_map_df is None or hrs_map_df.empty:
        return

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

    hrs_lo, hrs_hi = st.slider(
        f"Total hours above {heat_threshold}°C range",
        min_value=hrs_min,
        max_value=hrs_max,
        value=(hrs_min, hrs_max),
        step=_hrs_step,
        key=f"geo_brush_basic_{geo_agg}",
        format="%.1f",
    )

    n_hrs_sel = int(((hrs_arr >= hrs_lo) & (hrs_arr <= hrs_hi)).sum())
    lo_pct = float(np.mean(hrs_arr <= hrs_lo) * 100)
    hi_pct = float(np.mean(hrs_arr <= hrs_hi) * 100)
    st.caption(
        f"**{n_hrs_sel} of {len(hrs_arr)} buildings** selected "
        f"(P{lo_pct:.0f}-P{hi_pct:.0f} of the portfolio)"
    )

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
        )


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
            "edh_zone_weighted": f"EDH zone-weighted at {heat_threshold}°C",
            "edh_worst_zone": f"EDH worst zone at {heat_threshold}°C",
            "exceedance_hours": f"Total hours above {heat_threshold}°C",
            "heat_index_caution_hours": "Heat index caution+ hours",
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
            f"EDH zone-wtd ({heat_threshold}°C)",
            help="Zone-weighted EDH (°C·hr)",
            format="%.1f",
            min_value=0,
            max_value=float(table["edh_zone_weighted"].max(skipna=True) or 1),
        )
    if "edh_worst_zone" in table.columns:
        display_cols.append("edh_worst_zone")
        col_config["edh_worst_zone"] = st.column_config.ProgressColumn(
            f"EDH worst zone ({heat_threshold}°C)",
            help="Worst-zone EDH (°C·hr)",
            format="%.1f",
            min_value=0,
            max_value=float(table["edh_worst_zone"].max(skipna=True) or 1),
        )
    if "exceedance_hours" in table.columns:
        display_cols.append("exceedance_hours")
        col_config["exceedance_hours"] = st.column_config.NumberColumn(
            f"Total hrs above {heat_threshold}°C",
            help="Total hours with dry-bulb temperature above threshold (zone-weighted)",
            format="%.0f",
        )
    if "heat_index_caution_hours" in table.columns:
        display_cols.append("heat_index_caution_hours")
        col_config["heat_index_caution_hours"] = st.column_config.NumberColumn(
            "HI caution+ hrs",
            help="Hours in NOAA Caution or above (zone-weighted)",
            format="%.0f",
        )
    if "disagreement" in table.columns:
        display_cols.append("disagreement")
        col_config["disagreement"] = st.column_config.CheckboxColumn(
            "EDH/hrs disagree",
            help="EDH rank and exceedance-hours rank differ significantly — examine before choosing an intervention",
        )

    st.dataframe(
        table[display_cols],
        use_container_width=True,
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
            "Add buildings.parquet in the run output folder or under inputs/ "
            "(or the path set in visualization config) to enable the morphology "
            "trellis (numeric scatter + categorical box plots)."
        )

    # --- EUI vs EDH and EUI vs Total hours above threshold (side by side) ---
    has_edh = (
        eui_edh is not None
        and not eui_edh.empty
        and "eui" in eui_edh.columns
        and "edh_zone_weighted" in eui_edh.columns
    )
    # Join exceedance hours from multi_metric_df onto eui_edh for the second scatter
    eui_hours = None
    if (
        multi is not None
        and "exceedance_hours" in multi.columns
        and eui_edh is not None
        and "eui" in eui_edh.columns
    ):
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
            "Quadrant lines cross at evaluation area. "
            "Top-left = comfort via cooling. "
            "Bottom-right = efficient + overheating risk."
        )
        if has_edh:
            edf = cast(pd.DataFrame, eui_edh)
            ok = edf["eui"].notna() & edf["edh_zone_weighted"].notna()
            scat = edf.loc[ok]
            if len(scat) >= 2:
                mean_eui = float(scat["eui"].mean())
                mean_edh = float(scat["edh_zone_weighted"].mean())
                scat_html = create_scatter_d3_html(
                    scat["edh_zone_weighted"].astype(float).tolist(),
                    scat["eui"].astype(float).tolist(),
                    scat[BUILDING_ID_COL].astype(str).tolist(),
                    title="EUI vs EDH",
                    x_label=f"EDH zone-weighted at {heat_threshold}°C (°C·hr)",
                    y_label="EUI (kWh/m²)",
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
            mean_eui_h = float(eui_hours["eui"].mean())
            mean_hrs = float(eui_hours["exceedance_hours"].mean())
            hrs_html = create_scatter_d3_html(
                eui_hours["exceedance_hours"].astype(float).tolist(),
                eui_hours["eui"].astype(float).tolist(),
                eui_hours[BUILDING_ID_COL].astype(str).tolist(),
                title=f"EUI vs total hours above {heat_threshold}°C",
                x_label=f"Total hours above {heat_threshold}°C",
                y_label="EUI (kWh/m²)",
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

    # --- Box plot by number of floors ---
    if (
        eui_edh is not None
        and "num_floors" in eui_edh.columns
        and "edh_zone_weighted" in eui_edh.columns
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
                pc_records = [
                    {
                        col: float(row[col])
                        for col in pc_cols_full
                        if pd.notna(row.get(col))
                    }
                    for _, row in pc_df.iterrows()
                    if any(pd.notna(row.get(col)) for col in pc_cols_full)
                ]
                if pc_records:
                    pc_html = create_parallel_coordinates_d3_html(
                        pc_records,
                        pc_cols_full,
                        color_axis="edh_zone_weighted",
                        theme=theme,
                    )
                    components.html(pc_html, height=420, scrolling=False)


def _render_threshold_overlay_chart(
    run_dir: object,
    available_files: list[str],
    thresholds: list[float],
) -> None:
    """Show overlaid KDE distributions for all thresholds, one panel per metric."""
    from pathlib import Path

    from globi.tools.visualization.utils import build_overheating_threshold_fan_wide_df

    theme = cast(Theme, _streamlit_theme())
    run_dir = Path(run_dir)  # type: ignore[arg-type]

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
        wide = build_overheating_threshold_fan_wide_df(run_dir, dstype, "Zone Weighted")
        if wide is None or wide.empty:
            continue
        series: dict[float, list[float]] = {}
        for col_name in wide.columns:
            try:
                thr = float(col_name)
            except ValueError:
                continue
            vals = wide[col_name].dropna().tolist()
            if vals:
                series[thr] = vals

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


def _render_overheating_use_case(data_source: DataSource) -> None:
    """Render overheating analysis with 4-tab layout."""
    st.markdown("### Overheating Analysis")

    runs_with_oh = data_source.list_runs_with_overheating()
    if not runs_with_oh:
        st.warning(
            "No runs with overheating outputs found. Enable overheating in your "
            "manifest (overheating_config) and re-run simulations."
        )
        return

    selected_run = st.selectbox(
        "Select Run", options=runs_with_oh, key="overheating_run"
    )
    available_files = data_source.list_overheating_files(selected_run)
    if not available_files:
        st.warning("No overheating parquet files found for this run.")
        return

    thresholds = data_source.get_overheating_thresholds(selected_run)

    # Overlay distribution chart — all thresholds at once, color-coded yellow->red
    run_dir = data_source.resolve_run_dir(selected_run)
    if run_dir is not None and thresholds:
        _render_threshold_overlay_chart(run_dir, available_files, thresholds)

    # Global controls above tabs
    col1, col2, col3 = st.columns(3)
    with col1:
        heat_threshold = st.selectbox(
            "Temperature threshold (°C)",
            options=thresholds,
            index=0,
            key="oh_threshold",
        )
    with col2:
        aggregation = st.selectbox(
            "Aggregation",
            options=["Zone Weighted", "Worst Zone"],
            index=0,
            key="oh_aggregation",
        )
    with col3, st.expander("Advanced"):
        cart_crs = st.selectbox(
            "Polygon CRS",
            options=["EPSG:3857", "EPSG:32633", "EPSG:32632", "EPSG:4326"],
            index=0,
            key="oh_crs",
        )

    with st.spinner("Loading overheating data..."):
        dashboard_data = _load_overheating_dashboard_data(
            data_source, selected_run, heat_threshold, aggregation, cart_crs
        )

    theme = cast(Theme, _streamlit_theme())

    tab1, tab2, tab3, tab4 = st.tabs([
        "Portfolio",
        "Spatial",
        "Priority",
        "Correlations",
    ])
    with tab1:
        _render_tab_portfolio(dashboard_data, heat_threshold, aggregation, theme)
    with tab2:
        _render_tab_geography(
            dashboard_data,
            heat_threshold,
            aggregation,
            cart_crs,
            data_source,
            selected_run,
            theme,
        )
    with tab3:
        _render_tab_priority(dashboard_data, heat_threshold, aggregation, theme)
    with tab4:
        _render_tab_correlations(dashboard_data, heat_threshold, aggregation, theme)


def _render_scenario_comparison(data_source: DataSource) -> None:
    """Render scenario comparison with EUI, end uses, and utilities charts."""
    st.markdown("### Scenario Comparison")
    st.markdown("Compare energy distributions across multiple scenarios.")

    available_runs = data_source.list_available_runs()
    if len(available_runs) < 2:
        st.warning("Need at least 2 runs for comparison.")
        return

    selected_runs = st.multiselect(
        "Select scenarios to compare",
        options=available_runs,
        default=available_runs[:2],
        key="comparison_scenarios",
    )

    if len(selected_runs) < 2:
        st.info("Select at least 2 scenarios to generate a comparison.")
        return

    with st.expander("Scenario display names", expanded=False):
        st.caption("Optional short names for charts (defaults to run id).")
        display_names: dict[str, str] = {}
        for run_id in selected_runs:
            val = st.text_input(
                "Display name",
                value=run_id,
                key=f"scenario_display_{run_id}",
                placeholder=run_id,
            )
            display_names[run_id] = (val.strip() or run_id) if val else run_id

    if not st.button("Generate Comparison"):
        return

    # load data for each selected scenario
    dfs: dict[str, pd.DataFrame] = {}
    for run_id in selected_runs:
        try:
            df = data_source.load_run_data(run_id)
            if not is_results_format(df):
                st.warning(
                    f"Run '{run_id}' is not in the expected results format, skipping."
                )
                continue
            dfs[run_id] = df
        except Exception as exc:
            st.warning(f"Could not load '{run_id}': {exc}")

    if len(dfs) < 2:
        st.error("Could not load enough valid scenarios for comparison.")
        return

    run_id_to_display = {k: display_names.get(k, k) for k in dfs}
    theme = cast(Theme, _streamlit_theme())
    with st.spinner("Building comparison dashboard..."):
        comparison_data = extract_comparison_data(dfs, region_name="")
        comparison_data = apply_scenario_display_names(
            comparison_data, run_id_to_display
        )

        # eui distribution comparison (full width)
        st.markdown("#### EUI distribution comparison")
        kde_html = create_comparison_kde_d3_html(comparison_data, theme=theme)
        components.html(kde_html, height=360, scrolling=False)
        _chart_download(
            "sc_kde",
            _build_eui_csv(comparison_data).to_csv(index=False),
            kde_html,
            "eui_distribution",
        )

        # end uses and utilities side by side
        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown("#### End uses comparison")
            eu_html = create_comparison_stacked_bar_d3_html(
                comparison_data,
                data_key="end_uses_data",
                color_key="end_use_colors",
                title="end uses comparison",
                theme=theme,
            )
            components.html(eu_html, height=360, scrolling=False)
            _chart_download(
                "sc_eu",
                _build_stacked_csv(comparison_data, "end_uses_data").to_csv(
                    index=False
                ),
                eu_html,
                "end_uses",
            )
        with col_right:
            st.markdown("#### Fuel/utilities comparison")
            fuel_html = create_comparison_stacked_bar_d3_html(
                comparison_data,
                data_key="utilities_data",
                color_key="fuel_colors",
                title="fuel/utilities comparison",
                theme=theme,
            )
            components.html(fuel_html, height=360, scrolling=False)
            _chart_download(
                "sc_fuel",
                _build_stacked_csv(comparison_data, "utilities_data").to_csv(
                    index=False
                ),
                fuel_html,
                "fuel_utilities",
            )
