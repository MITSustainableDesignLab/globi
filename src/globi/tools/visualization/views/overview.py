"""Overview/landing page for the visualization app."""

from __future__ import annotations

import streamlit as st


def render_overview_page() -> None:
    """Render the overview page with usage and file pointers."""
    st.subheader("Overview")

    st.markdown("""
    Use the **sidebar** to choose a data source and open:
    - **Raw Data Visualization** - explore run outputs (EUI, peak, end uses, 3D map).
    - **Use Cases** - run retrofit, overheating, and scenario-comparison analyses.
    """)

    st.markdown("### Data source")

    st.markdown("""
    - **Local**: Point to an output directory (default `outputs`). The app looks for run subdirs
      containing parquet files (e.g. `Results.pq`). For the map, building locations are read from
      `inputs/buildings.parquet` if present.
    - **S3**: Enter an experiment **run name** (and optional **version**). Data is downloaded from
      S3 and cached under the configured cache directory.
    """)

    st.markdown("### Running the visualizer")

    st.markdown("""
    - **Local (Streamlit only)**: `make viz-native` or
      `uv run streamlit run src/globi/tools/visualization/main.py`
    - **Docker**: `make viz` (uses docker compose; ensure env files and AWS/Hatchet config are set).
    """)

    st.markdown("### Required files (local)")

    st.markdown("""
    - **Output directory** (e.g. `outputs`): run subdirectories, each with at least one `.pq` file.
    - **Building locations** (optional): `inputs/buildings.parquet` for 3D map and geo-based views.
    """)
