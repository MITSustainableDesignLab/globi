"""Use Cases page for specialized analyses."""

from __future__ import annotations

import streamlit as st

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.models import BuildingMetric, UseCaseType


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
    """Render general scenario comparison (scaffolding)."""
    st.markdown("### Scenario Comparison")
    st.markdown("Compare any two scenarios and visualize differences.")

    available_runs = data_source.list_available_runs()
    if len(available_runs) < 2:
        st.warning("Need at least 2 runs for comparison.")
        return

    col1, col2 = st.columns(2)
    with col1:
        scenario_a = st.selectbox(
            "Scenario A", options=available_runs, key="scenario_a"
        )
    with col2:
        scenario_b_options = [r for r in available_runs if r != scenario_a]
        scenario_b = st.selectbox(
            "Scenario B", options=scenario_b_options, key="scenario_b"
        )

    metric = st.selectbox(
        "Comparison Metric",
        options=[m.value for m in BuildingMetric if m != BuildingMetric.CUSTOM],
        format_func=lambda x: x.replace("_", " ").title(),
    )

    if st.button("Generate Comparison"):
        st.info(
            f"Would compare {scenario_a} vs {scenario_b} using {metric}. Full implementation pending."
        )
