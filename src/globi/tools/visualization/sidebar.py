"""Shared sidebar: data source config. Used by all pages in the multipage app."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from globi.tools.visualization.data_sources import (
    DataSource,
    S3ExperimentInfo,
    list_s3_experiments,
)
from globi.tools.visualization.models import LocalDataSourceConfig, S3DataSourceConfig


@st.cache_data(ttl=300, show_spinner="Fetching experiments from S3...")
def _fetch_s3_experiments() -> list[S3ExperimentInfo]:
    """Fetch available experiments from S3 with caching."""
    try:
        return list_s3_experiments()
    except Exception as e:
        st.error(f"Failed to fetch experiments: {e}")
        return []


def _render_local_source() -> DataSource:
    """Render local data source controls."""
    base_dir = st.text_input("Output directory", value="outputs")
    return DataSource.from_config(LocalDataSourceConfig(base_dir=Path(base_dir)))


def _render_s3_source() -> DataSource | None:
    """Render S3 data source controls with experiment dropdown."""
    _, col2 = st.columns([3, 1])
    with col2:
        if st.button(
            "Refresh", key="refresh_s3_experiments", help="Refresh experiment list"
        ):
            _fetch_s3_experiments.clear()
            st.rerun()

    experiments = _fetch_s3_experiments()

    if not experiments:
        st.warning("No experiments found in S3. Check your AWS credentials.")
        st.markdown("---")
        st.markdown("**Manual entry:**")
        run_name = st.text_input("S3 run name", value="")
        version = st.text_input("Version (optional)", value="")
        dataframe_key = st.selectbox(
            "Dataframe",
            options=["Results", "EnergyAndPeak"],
            index=0,
        )
        if not run_name:
            return None
        return DataSource.from_config(
            S3DataSourceConfig(
                run_name=run_name,
                version=version if version else None,
                dataframe_key=dataframe_key,
            )
        )

    exp_options = {str(exp): exp for exp in experiments}
    selected_exp_str = st.selectbox(
        "Experiment",
        options=list(exp_options.keys()),
        index=0,
        help="Select an experiment from S3",
    )

    if not selected_exp_str:
        return None

    selected_exp = exp_options[selected_exp_str]

    version_options = ["latest", *reversed(selected_exp.versions)]
    selected_version = st.selectbox(
        "Version",
        options=version_options,
        index=0,
        help="Select a version or use latest",
    )

    version_value = None if selected_version == "latest" else selected_version

    dataframe_options = ["Results", "EnergyAndPeak"]
    selected_df_key = st.selectbox(
        "Dataframe",
        options=dataframe_options,
        index=0,
        help="Select which results dataframe to load",
    )

    return DataSource.from_config(
        S3DataSourceConfig(
            run_name=selected_exp.run_name,
            version=version_value,
            dataframe_key=selected_df_key,
        )
    )


def render_data_source_sidebar() -> DataSource | None:
    """Render data source controls in sidebar.

    Returns DataSource or None if invalid configuration.
    """
    with st.sidebar:
        st.markdown("### Data source")
        source_type = st.radio("Source", options=["Local", "S3"], index=0)

        if source_type == "Local":
            return _render_local_source()
        return _render_s3_source()
