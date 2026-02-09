"""Shared sidebar: data source config. Used by all pages in the multipage app."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.models import LocalDataSourceConfig, S3DataSourceConfig


def render_data_source_sidebar() -> DataSource | None:
    """Render data source controls in sidebar. Returns DataSource or None if invalid (e.g. S3 with no run name)."""
    with st.sidebar:
        st.markdown("### Data source")
        source_type = st.radio("Source", options=["Local", "S3"], index=0)

        if source_type == "Local":
            base_dir = st.text_input("Output directory", value="outputs")
            return DataSource.from_config(
                LocalDataSourceConfig(base_dir=Path(base_dir))
            )
        run_name = st.text_input("S3 run name", value="")
        version = st.text_input("Version (optional)", value="")
        if not run_name:
            st.warning("Enter a run name to load from S3.")
            return None
        return DataSource.from_config(
            S3DataSourceConfig(
                run_name=run_name,
                version=version if version else None,
            )
        )
