"""Entry point for the GLOBI visualization app."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.models import LocalDataSourceConfig, S3DataSourceConfig
from globi.tools.visualization.pages import render_raw_data_page, render_use_cases_page


def main() -> None:
    """Entry point for the visualization app."""
    st.set_page_config(page_title="GLOBI Visualization", layout="wide")
    st.title("GLOBI Visualization")

    with st.sidebar:
        source_type = st.radio("Data Source", options=["Local", "S3"], index=0)

        if source_type == "Local":
            base_dir = st.text_input("Output Directory", value="outputs")
            config = LocalDataSourceConfig(base_dir=Path(base_dir))
        else:
            run_name = st.text_input("S3 Run Name", value="")
            version = st.text_input("Version (optional)", value="")
            if not run_name:
                st.warning("Enter a run name to load from S3.")
                return
            config = S3DataSourceConfig(
                run_name=run_name,
                version=version if version else None,
            )

        data_source = DataSource.from_config(config)

    page = st.sidebar.selectbox(
        "Page",
        options=["Raw Data Visualization", "Use Cases"],
        index=0,
    )

    if page == "Raw Data Visualization":
        render_raw_data_page(data_source)
    elif page == "Use Cases":
        render_use_cases_page(data_source)


if __name__ == "__main__":
    main()
