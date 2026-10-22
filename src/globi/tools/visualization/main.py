"""Entry point for the GLOBI visualization app."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.sidebar import render_data_source_sidebar
from globi.tools.visualization.views import (
    render_compare_page,
    render_overheating_page,
    render_overview_page,
    render_raw_data_page,
)

st.set_page_config(
    page_title="GloBI results", page_icon=":material/public:", layout="wide"
)

data_source = render_data_source_sidebar()


def _with_data(render: Callable[[DataSource], None]) -> Callable[[], None]:
    """Page that needs a working data source; otherwise points to the sidebar."""

    def page() -> None:
        if data_source is None:
            st.info("Choose where your results are in the sidebar to get started.")
            return
        render(data_source)

    page.__name__ = render.__name__
    return page


explore = st.Page(
    _with_data(render_raw_data_page),
    title="Explore a run",
    icon=":material/search:",
    url_path="explore",
)
compare = st.Page(
    _with_data(render_compare_page),
    title="Compare scenarios",
    icon=":material/compare_arrows:",
    url_path="compare",
)
overheating = st.Page(
    _with_data(render_overheating_page),
    title="Overheating",
    icon=":material/thermostat:",
    url_path="overheating",
)
home = st.Page(
    lambda: render_overview_page(explore, compare, overheating),
    title="Start here",
    icon=":material/home:",
    url_path="start",
    default=True,
)

st.navigation({
    "": [home],
    "Results": [explore, compare, overheating],
}).run()
