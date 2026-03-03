"""Use Cases page for specialized analyses."""

from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.models import UseCaseType
from globi.tools.visualization.plotting import (
    create_comparison_bar_d3_html,
    create_comparison_kde_d3_html,
    create_comparison_stacked_bar_d3_html,
)
from globi.tools.visualization.results_data import (
    apply_scenario_display_names,
    extract_comparison_data,
    extract_retrofit_comparison_data,
    is_results_format,
    normalize_fuel_name,
)


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


def _retrofit_params_form(
    selected_runs: list[str],
) -> tuple[dict, dict, dict | None, bool]:
    """Render retrofit cost/emissions form, return factors and unit costs."""
    st.markdown("**Energy cost factors** ($/kWh by fuel type)")
    energy_cost_factors = {}
    emissions_factors = {}
    ec_cols = st.columns(4)
    for i, (label, default) in enumerate(
        zip(_FUEL_LABELS, _DEFAULT_ENERGY_COSTS, strict=True)
    ):
        with ec_cols[i % 4]:
            key = normalize_fuel_name(label)
            energy_cost_factors[key] = st.number_input(
                label,
                min_value=0.0,
                value=default,
                format="%.3f",
                key=f"ec_{key}",
            )
    st.markdown("**Emissions factors** (kg CO2/kWh by fuel type)")
    em_cols = st.columns(4)
    for i, (label, default) in enumerate(
        zip(_FUEL_LABELS, _DEFAULT_EMISSIONS, strict=True)
    ):
        with em_cols[i % 4]:
            key = normalize_fuel_name(label)
            emissions_factors[key] = st.number_input(
                label,
                min_value=0.0,
                value=default,
                format="%.3f",
                key=f"em_{key}",
            )
    st.markdown("**Unit costs** (capital cost $ per scenario, optional)")
    use_unit_costs = st.checkbox("Include capital costs per scenario", value=False)
    unit_costs: dict[str, float] = {}
    if use_unit_costs:
        uc_cols = st.columns(min(4, len(selected_runs)))
        for i, run_id in enumerate(selected_runs):
            with uc_cols[i % 4]:
                unit_costs[run_id] = st.number_input(
                    run_id,
                    min_value=0.0,
                    value=0.0,
                    format="%.0f",
                    key=f"uc_{run_id}",
                )
    return energy_cost_factors, emissions_factors, unit_costs or None, use_unit_costs


def _render_retrofit_use_case(data_source: DataSource) -> None:
    """Render retrofit analysis: compare scenarios with cost, emissions, energy."""
    st.markdown("### Retrofit Analysis")
    st.markdown(
        "Compare retrofit scenarios with energy savings, costs, and emissions. "
        "Enter unit costs, emissions factors, and energy cost factors to see cost/emissions comparison."
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
        energy_cost_factors, emissions_factors, unit_costs, use_unit_costs = (
            _retrofit_params_form(selected_runs)
        )

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

    with st.spinner("Building comparison dashboard..."):
        comparison_data = extract_retrofit_comparison_data(
            dfs,
            region_name="",
            energy_cost_factors=energy_cost_factors,
            emissions_factors=emissions_factors,
            unit_costs=unit_costs if use_unit_costs else None,
        )
        _render_retrofit_charts(
            comparison_data,
            dfs=dfs,
            energy_cost_factors=energy_cost_factors,
            emissions_factors=emissions_factors,
            unit_costs=unit_costs if use_unit_costs else None,
        )


def _render_retrofit_charts(
    comparison_data: dict,
    dfs: dict[str, pd.DataFrame] | None = None,
    energy_cost_factors: dict[str, float] | None = None,
    emissions_factors: dict[str, float] | None = None,
    unit_costs: dict[str, float] | None = None,
) -> None:
    """Render retrofit comparison charts (EUI, end uses, fuel, cost, emissions) and map."""
    st.markdown("#### EUI distribution comparison")
    kde_html = create_comparison_kde_d3_html(comparison_data)
    components.html(kde_html, height=360, scrolling=False)

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("#### End uses comparison")
        eu_html = create_comparison_stacked_bar_d3_html(
            comparison_data,
            data_key="end_uses_data",
            color_key="end_use_colors",
            title="end uses comparison",
        )
        components.html(eu_html, height=360, scrolling=False)
    with col_right:
        st.markdown("#### Fuel/utilities comparison")
        fuel_html = create_comparison_stacked_bar_d3_html(
            comparison_data,
            data_key="utilities_data",
            color_key="fuel_colors",
            title="fuel/utilities comparison",
        )
        components.html(fuel_html, height=360, scrolling=False)

    if comparison_data.get("cost_totals"):
        st.markdown("#### Total cost comparison (energy + capital)")
        cost_data = {
            "scenarios": comparison_data["scenarios"],
            "cost_totals": comparison_data["cost_totals"],
        }
        cost_html = create_comparison_bar_d3_html(
            cost_data,
            value_key="cost_totals",
            title="total cost",
            value_label="annual cost ($)",
        )
        components.html(cost_html, height=200, scrolling=False)

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
        )
        components.html(em_html, height=200, scrolling=False)

    if dfs and energy_cost_factors is not None and emissions_factors is not None:
        _render_retrofit_map(
            dfs,
            energy_cost_factors,
            emissions_factors,
            unit_costs or {},
        )


def _render_retrofit_map(
    dfs: dict[str, pd.DataFrame],
    energy_cost_factors: dict[str, float],
    emissions_factors: dict[str, float],
    unit_costs: dict[str, float],
) -> None:
    """Render pydeck map with selectable metric and colormap."""
    from globi.tools.visualization.plotting import create_building_map_deck
    from globi.tools.visualization.results_data import build_retrofit_map_df
    from globi.tools.visualization.views.raw_data import _render_colormap_legend

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
                ("capital_cost", "plasma", "Capital cost ($)"),
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
        options=["EPSG:3857", "EPSG:32633", "EPSG:32632", "EPSG:4326"],
        index=0,
        key="retrofit_map_crs",
    )

    unit_cost = unit_costs.get(scenario, 0.0)
    map_df = build_retrofit_map_df(
        dfs[scenario],
        energy_cost_factors,
        emissions_factors,
        unit_cost=unit_cost,
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


def _render_overheating_use_case(data_source: DataSource) -> None:
    """Render overheating map: pydeck reds map highlighting buildings with higher overheating."""
    st.markdown("### Overheating Analysis")
    st.markdown(
        "Identify buildings at risk of overheating. Requires runs with overheating "
        "outputs (manifest with calculate_overheating: true)."
    )

    runs_with_oh = data_source.list_runs_with_overheating()
    if not runs_with_oh:
        st.warning(
            "No runs with overheating outputs found. Enable overheating in your "
            "manifest (calculate_overheating: true) and re-run simulations."
        )
        return

    selected_run = st.selectbox(
        "Select Run",
        options=runs_with_oh,
        key="overheating_run",
    )

    col1, col2 = st.columns(2)
    with col1:
        heat_threshold = st.selectbox(
            "Temperature threshold (C)",
            options=[26.0, 30.0, 35.0],
            index=0,
            key="overheating_threshold",
        )
    with col2:
        aggregation = st.selectbox(
            "Aggregation",
            options=["Zone Weighted", "Worst Zone"],
            index=0,
            key="overheating_aggregation",
        )

    cart_crs = st.selectbox(
        "Polygon CRS (rotated_rectangle)",
        options=["EPSG:3857", "EPSG:32633", "EPSG:32632", "EPSG:4326"],
        index=0,
        key="overheating_crs",
    )

    if not st.button("Show Overheating Map", key="overheating_map_btn"):
        return

    with st.spinner("Loading overheating data..."):
        map_df = data_source.load_overheating_map_data(
            selected_run,
            cart_crs=cart_crs,
            heat_threshold_c=heat_threshold,
            aggregation=aggregation,
        )

    if map_df is None or map_df.empty:
        st.error("Could not load overheating map data for this run.")
        return

    from globi.tools.visualization.plotting import create_building_map_deck
    from globi.tools.visualization.views.raw_data import _render_colormap_legend

    result = create_building_map_deck(
        map_df,
        cart_crs=cart_crs,
        value_col="overheating_hours",
        cmap="reds",
    )
    if result is None:
        st.error("Could not build map.")
        return

    deck, n_features, value_stats = result
    st.markdown("#### Overheating hours above threshold")
    st.pydeck_chart(deck)
    st.caption(f"{n_features} buildings displayed")

    if value_stats:
        _render_colormap_legend(
            f"Hours above {heat_threshold}C",
            value_stats,
            "reds",
        )


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
    with st.spinner("Building comparison dashboard..."):
        comparison_data = extract_comparison_data(dfs, region_name="")
        comparison_data = apply_scenario_display_names(
            comparison_data, run_id_to_display
        )

        # eui distribution comparison (full width)
        st.markdown("#### EUI distribution comparison")
        kde_html = create_comparison_kde_d3_html(comparison_data)
        components.html(kde_html, height=360, scrolling=False)

        # end uses and utilities side by side
        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown("#### End uses comparison")
            eu_html = create_comparison_stacked_bar_d3_html(
                comparison_data,
                data_key="end_uses_data",
                color_key="end_use_colors",
                title="end uses comparison",
            )
            components.html(eu_html, height=360, scrolling=False)
        with col_right:
            st.markdown("#### Fuel/utilities comparison")
            fuel_html = create_comparison_stacked_bar_d3_html(
                comparison_data,
                data_key="utilities_data",
                color_key="fuel_colors",
                title="fuel/utilities comparison",
            )
            components.html(fuel_html, height=360, scrolling=False)
