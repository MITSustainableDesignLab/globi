"""Entry point for the GLOBI visualization app. Uses st.navigation so the first page displays as "Overview"."""

from __future__ import annotations

import streamlit as st

from globi.tools.visualization.sidebar import render_data_source_sidebar
from globi.tools.visualization.views import (
    render_overview_page,
    render_raw_data_map_page,
    render_raw_data_summary_page,
    render_use_cases_page,
)

st.set_page_config(page_title="GLOBI Visualization", layout="wide")
st.title("GLOBI Visualization")
# update the icon of the webpage to be a globe

data_source = render_data_source_sidebar()
st.session_state["data_source"] = data_source


def _overview() -> None:
    render_overview_page()


def _raw_data_summary() -> None:
    ds = st.session_state.get("data_source")
    if ds is not None:
        render_raw_data_summary_page(ds)
    else:
        st.info(
            "Configure a data source in the sidebar (e.g. Local with an output directory) to view raw data."
        )


def _raw_data_map() -> None:
    ds = st.session_state.get("data_source")
    if ds is not None:
        render_raw_data_map_page(ds)
    else:
        st.info(
            "Configure a data source in the sidebar (e.g. Local with an output directory) to view raw data."
        )


def _use_cases() -> None:
    ds = st.session_state.get("data_source")
    if ds is not None:
        render_use_cases_page(ds)
    else:
        st.info(
            "Configure a data source in the sidebar (e.g. Local with an output directory) to run use cases."
        )


pg = st.navigation([
    st.Page(_overview, title="Overview"),
    st.Page(_raw_data_summary, title="Raw Data Summary"),
    st.Page(_raw_data_map, title="Raw Data Map"),
    st.Page(_use_cases, title="Use Cases"),
])
pg.run()
