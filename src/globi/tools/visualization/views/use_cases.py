"""Use Cases page for specialized analyses."""

from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.models import UseCaseType
from globi.tools.visualization.plotting import (
    create_comparison_kde_d3_html,
    create_comparison_stacked_bar_d3_html,
)
from globi.tools.visualization.results_data import (
    extract_comparison_data,
    is_results_format,
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


def _render_retrofit_use_case(data_source: DataSource) -> None:
    """Render retrofit analysis use case (scaffolding)."""
    st.markdown("### Retrofit Analysis")
    st.markdown("Compare baseline and retrofit scenarios to visualize energy savings.")

    available_runs = data_source.list_available_runs()
    if len(available_runs) < 2:
        st.warning("Need at least 2 runs for retrofit comparison.")
        return

    col1, col2 = st.columns(2)
    with col1:
        baseline_run = st.selectbox(
            "Baseline Scenario", options=available_runs, key="baseline"
        )
    with col2:
        comparison_options = [r for r in available_runs if r != baseline_run]
        retrofit_run = st.selectbox(
            "Retrofit Scenario", options=comparison_options, key="retrofit"
        )

    if st.button("Compare Scenarios"):
        st.info(
            f"Comparison of {baseline_run} vs {retrofit_run} - implementation pending."
        )


# TODO: implement this update with the new overheating format
def _render_overheating_use_case(data_source: DataSource) -> None:
    """Render overheating analysis use case (scaffolding)."""
    st.markdown("### Overheating Analysis")
    st.markdown(
        "Identify buildings at risk of overheating based on simulation results."
    )

    threshold_hours = st.number_input(
        "Overheating Threshold (hours above temperature)",
        min_value=0,
        max_value=8760,
        value=200,
    )
    temp_threshold = st.number_input(
        "Temperature Threshold (C)",
        min_value=20.0,
        max_value=40.0,
        value=26.0,
    )

    available_runs = data_source.list_available_runs()
    selected_run = st.selectbox("Select Run", options=available_runs)

    if st.button("Analyze Overheating"):
        st.info(
            f"Would analyze {selected_run} for buildings exceeding "
            f"{threshold_hours} hours above {temp_threshold}C. "
            "Full implementation requires hourly data access."
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

    with st.spinner("Building comparison dashboard..."):
        comparison_data = extract_comparison_data(dfs, region_name="")

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
