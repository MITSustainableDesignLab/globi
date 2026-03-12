"""Use Cases page for specialized analyses."""

from __future__ import annotations

from typing import cast

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.models import UseCaseType
from globi.tools.visualization.plotting import (
    Theme,
    create_comparison_bar_d3_html,
    create_comparison_kde_d3_html,
    create_comparison_stacked_bar_d3_html,
    create_histogram_d3_html,
    create_overheating_heatmap_d3_html,
)
from globi.tools.visualization.results_data import (
    apply_scenario_display_names,
    extract_comparison_data,
    extract_retrofit_comparison_data,
    is_results_format,
    normalize_fuel_name,
)
from globi.tools.visualization.views.raw_data import _chart_download, _streamlit_theme


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
        )


def _render_retrofit_charts(
    comparison_data: dict,
    dfs: dict[str, pd.DataFrame] | None = None,
    per_scenario_energy_costs: dict[str, dict[str, float]] | None = None,
    per_scenario_emissions: dict[str, dict[str, float]] | None = None,
    system_costs_per_sqm: dict[str, float] | None = None,
) -> None:
    """Render retrofit comparison charts (EUI, end uses, fuel, cost, emissions) and map."""
    st.markdown("#### EUI distribution comparison")
    kde_html = create_comparison_kde_d3_html(comparison_data)
    components.html(kde_html, height=360, scrolling=False)
    _chart_download(
        "retro_kde",
        _build_eui_csv(comparison_data).to_csv(index=False),
        kde_html,
        "eui_distribution",
    )

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
        _chart_download(
            "retro_eu",
            _build_stacked_csv(comparison_data, "end_uses_data").to_csv(index=False),
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
        )
        components.html(fuel_html, height=360, scrolling=False)
        _chart_download(
            "retro_fuel",
            _build_stacked_csv(comparison_data, "utilities_data").to_csv(index=False),
            fuel_html,
            "fuel_utilities",
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


def _render_retrofit_map(
    dfs: dict[str, pd.DataFrame],
    per_scenario_energy_costs: dict[str, dict[str, float]],
    per_scenario_emissions: dict[str, dict[str, float]],
    system_costs_per_sqm: dict[str, float],
) -> None:
    """Render pydeck map with selectable metric and colormap. Caches geometry per scenario/CRS."""
    from globi.tools.visualization.plotting import (
        create_building_map_deck,
        create_building_map_deck_from_cache,
    )
    from globi.tools.visualization.results_data import build_retrofit_map_df
    from globi.tools.visualization.utils import build_map_features_from_df
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
        options=["EPSG:3857", "EPSG:32633", "EPSG:32632", "EPSG:4326"],
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

    cache_key = f"_retrofit_map_{scenario}_{cart_crs}"
    if cache_key not in st.session_state:
        with st.spinner("Building map geometry..."):
            geometry = build_map_features_from_df(
                map_df, cart_crs=cart_crs, value_col=None
            )
            if geometry is not None:
                st.session_state[cache_key] = geometry

    if cache_key in st.session_state:
        geometry = st.session_state[cache_key]
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


_HEAT_INDEX_METRICS = [
    ("danger_hours", "Total discomfort hours (Danger + Caution + etc)"),
    ("Extreme Danger [hr]", "Extreme Danger [hr]"),
    ("Danger [hr]", "Danger [hr]"),
    ("Extreme Caution [hr]", "Extreme Caution [hr]"),
    ("Caution [hr]", "Caution [hr]"),
    ("Normal [hr]", "Normal [hr]"),
]


def _render_overheating_summary_charts(
    map_df: pd.DataFrame,
    data_source_type: str,
    heat_threshold: float,
    heat_index_metric: str,
    theme: Theme,
) -> None:
    """Render histogram with download."""
    map_values = map_df["map_value"].dropna().tolist()
    if not map_values:
        return
    if data_source_type == "BasicOverheating":
        x_label = f"Hours above {heat_threshold}C"
    elif data_source_type == "ExceedanceDegreeHours":
        x_label = f"Degree-hours above {heat_threshold}C"
    else:
        x_label = heat_index_metric.replace("_", " ").title()
    hist_html = create_histogram_d3_html(
        map_values, title="Distribution", x_label=x_label, theme=theme
    )
    components.html(hist_html, height=320, scrolling=False)
    hist_df = pd.DataFrame({
        "building_id": map_df["building_id"],
        "value": map_df["map_value"],
    })
    _chart_download(
        "oh_hist",
        hist_df.to_csv(index=False),
        hist_html,
        "overheating_distribution",
    )


def _overheating_form_controls(
    available_files: list[str],
    thresholds: list[float],
) -> tuple[str, float, str, str, str] | None:
    """Render overheating form, return (data_source_type, threshold, aggregation, metric, crs) or None."""
    data_source_type = st.selectbox(
        "Data source",
        options=available_files,
        format_func=lambda x: x.replace("_", " "),
        key="overheating_data_source",
    )
    col1, col2 = st.columns(2)
    with col1:
        heat_threshold = st.selectbox(
            "Temperature threshold (C)",
            options=thresholds,
            index=0,
            key="overheating_threshold",
            disabled=(data_source_type == "HeatIndexCategories"),
        )
    with col2:
        aggregation = st.selectbox(
            "Aggregation",
            options=["Zone Weighted", "Worst Zone"],
            index=0,
            key="overheating_aggregation",
        )
    heat_index_metric = "danger_hours"
    if data_source_type == "HeatIndexCategories":
        heat_index_metric = st.selectbox(
            "Metric",
            options=[m[0] for m in _HEAT_INDEX_METRICS],
            format_func=lambda x: next(
                (m[1] for m in _HEAT_INDEX_METRICS if m[0] == x), x
            ),
            index=0,
            key="overheating_heat_index_metric",
        )
    cart_crs = st.selectbox(
        "Polygon CRS (rotated_rectangle)",
        options=["EPSG:3857", "EPSG:32633", "EPSG:32632", "EPSG:4326"],
        index=0,
        key="overheating_crs",
    )
    if not st.button("Show Overheating Map", key="overheating_map_btn"):
        return None
    return data_source_type, heat_threshold, aggregation, heat_index_metric, cart_crs


def _render_overheating_use_case(data_source: DataSource) -> None:
    """Render overheating analysis: map, summary stats, and D3 charts."""
    st.markdown("### Overheating Analysis")
    st.markdown(
        "Identify buildings at risk of overheating. Supports BasicOverheating, "
        "ExceedanceDegreeHours, and HeatIndexCategories outputs."
    )

    runs_with_oh = data_source.list_runs_with_overheating()
    if not runs_with_oh:
        st.warning(
            "No runs with overheating outputs found. Enable overheating in your "
            "manifest (overheating_config) and re-run simulations."
        )
        return

    selected_run = st.selectbox(
        "Select Run",
        options=runs_with_oh,
        key="overheating_run",
    )
    available_files = data_source.list_overheating_files(selected_run)
    if not available_files:
        st.warning("No overheating parquet files found for this run.")
        return

    # summary heatmap: aggregate stats across all buildings and thresholds
    theme = cast(Theme, _streamlit_theme())
    summary_df = data_source.load_overheating_summary(
        selected_run, aggregation="Zone Weighted"
    )
    if summary_df is not None and not summary_df.empty:
        st.markdown("#### Overheating summary across metrics and thresholds")
        st.caption(
            "Summary statistics (mean, median, p95, max) across all buildings. "
            "Each column is independently color-scaled."
        )
        heatmap_html = create_overheating_heatmap_d3_html(summary_df, theme=theme)
        components.html(heatmap_html, height=480, scrolling=False)
        heatmap_csv = summary_df.to_csv(index=False)
        _chart_download("oh_heatmap", heatmap_csv, heatmap_html, "overheating_summary")

    thresholds = data_source.get_overheating_thresholds(selected_run)
    form_result = _overheating_form_controls(available_files, thresholds)
    if form_result is None:
        return
    data_source_type, heat_threshold, aggregation, heat_index_metric, cart_crs = (
        form_result
    )

    with st.spinner("Loading overheating data..."):
        map_df = data_source.load_overheating_map_data(
            selected_run,
            cart_crs=cart_crs,
            heat_threshold_c=heat_threshold,
            aggregation=aggregation,
            data_source_type=data_source_type,
            heat_index_metric=heat_index_metric,
        )

    if map_df is None or map_df.empty:
        st.error("Could not load overheating map data for this run.")
        return

    from globi.tools.visualization.plotting import create_building_map_deck
    from globi.tools.visualization.views.raw_data import _render_colormap_legend

    theme = cast(Theme, _streamlit_theme())

    st.markdown("#### Summary statistics")
    _render_overheating_summary_charts(
        map_df, data_source_type, heat_threshold, heat_index_metric, theme
    )

    # map
    metric_label = "map value"
    if data_source_type == "BasicOverheating":
        metric_label = f"Hours above {heat_threshold}C"
    elif data_source_type == "ExceedanceDegreeHours":
        metric_label = f"Degree-hours above {heat_threshold}C"
    else:
        metric_label = heat_index_metric.replace("_", " ").title()

    st.markdown("#### Building map")
    result = create_building_map_deck(
        map_df,
        cart_crs=cart_crs,
        value_col="map_value",
        cmap="reds",
    )
    if result is None:
        st.error("Could not build map.")
        return

    deck, n_features, value_stats = result
    st.pydeck_chart(deck)
    st.caption(f"{n_features} buildings displayed")

    if value_stats:
        _render_colormap_legend(metric_label, value_stats, "reds")


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
