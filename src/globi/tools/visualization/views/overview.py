"""Start page: what the app is for, where to go, and what the numbers mean."""

from __future__ import annotations

import streamlit as st
from streamlit.navigation.page import StreamlitPage

_GLOSSARY = {
    "Energy use intensity (EUI)": "Energy a building uses in a year per m² of floor "
    "area (kWh/m²). Lets you compare buildings of different sizes.",
    "Annual energy": "Total energy used in a year (kWh, MWh or GWh).",
    "Peak demand": "Highest power a building draws in the year, per m² (kW/m²); "
    "drives grid and equipment sizing.",
    "Floor area": "Conditioned (heated or cooled) floor area of the building model.",
    "Baseline": "The scenario others are compared against, usually today's buildings.",
    "Payback": "Years for energy-cost savings to repay the one-off capital cost.",
    "Overheating hours": "Hours in a year a building is above a chosen temperature.",
}


def render_overview_page(
    explore: StreamlitPage, compare: StreamlitPage, overheating: StreamlitPage
) -> None:
    """Short guide with links to each page and a glossary."""
    st.header("GloBI results")
    st.markdown(
        "Explore simulated energy use for a building stock, compare retrofit "
        "scenarios, and find buildings at risk of overheating."
    )

    st.markdown("**1.** Choose where your results are in the sidebar.")
    st.markdown("**2.** Open a page:")
    st.page_link(explore, label="Explore a run: charts, map and a table of buildings")
    st.page_link(compare, label="Compare scenarios: savings, costs and payback")
    st.page_link(
        overheating, label="Overheating: hours above a temperature, by building"
    )
    st.markdown("**3.** Narrow down with *Filter buildings* in the sidebar.")

    st.caption(
        "Willingness-to-pay, adoption and emissions analyses live in a separate "
        "project, [globi-use-cases](https://github.com/daryaguettler/globi-use-cases)."
    )

    with st.expander("What the numbers mean"):
        for term, meaning in _GLOSSARY.items():
            st.markdown(f"**{term}**: {meaning}")
