"""Shared sidebar: data source config. Used by all pages in the multipage app."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.models import (
    DataSourceConfig,
    LocalDataSourceConfig,
    S3DataSourceConfig,
)

_STORE = "Simulation store"
_FOLDER = "Folder on this computer"


def _friendly_s3_error(exc: Exception) -> str:
    """Return a user-friendly message for common S3/AWS errors."""
    msg = str(exc)
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if "Could not connect to the endpoint URL" in msg:
        return (
            f"Can't reach the simulation store at {endpoint or 'AWS'}. "
            "If you run simulations locally, start the local stack with `make engine` "
            "and press Refresh."
        )
    if "BUCKET" in msg and "Field required" in msg:
        return (
            "The simulation store isn't configured (SCYTHE_STORAGE_BUCKET is not set). "
            "Start the app with `make viz-native`, which loads .env.scythe.storage."
        )
    if "NoSuchBucket" in msg:
        return "The configured bucket doesn't exist in the simulation store."
    if "SignatureDoesNotMatch" in msg:
        return (
            "AWS credentials are invalid or expired. "
            "Please check your AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, "
            "or re-run 'aws configure' to set up valid credentials."
        )
    if "InvalidAccessKeyId" in msg:
        return "AWS access key not recognized. Check that AWS_ACCESS_KEY_ID is correct."
    if "ExpiredToken" in msg:
        return (
            "AWS session token has expired. "
            "Refresh your credentials (e.g. re-run 'aws sso login' or get new temporary credentials)."
        )
    if "NoCredentialsError" in msg or "Unable to locate credentials" in msg:
        return (
            "No AWS credentials found. "
            "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or run 'aws configure'."
        )
    if "AccessDenied" in msg:
        return (
            "Access denied to the S3 bucket. "
            "Ensure your AWS credentials have permission to access the configured bucket."
        )
    return f"Failed to read the simulation store: {msg}"


@st.cache_resource(max_entries=4, show_spinner=False)
def _data_source(config: DataSourceConfig) -> DataSource:
    """One data source per config, kept across reruns so its loaded runs stay in memory."""
    return DataSource.from_config(config)


def _store_label() -> str | None:
    """Which store is in use; None when no bucket is configured (an error explains that)."""
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    bucket = os.environ.get("SCYTHE_STORAGE_BUCKET")
    if not bucket:
        return None
    if endpoint and (
        "localhost" in endpoint or "127.0.0.1" in endpoint or "://aws:" in endpoint
    ):
        return f"Local store · {endpoint}"
    return f"AWS S3 · {bucket}" if not endpoint else f"S3 · {endpoint}"


_OTHER_CRS = "Other…"


def _render_settings() -> None:
    """Units and map coordinate system, set once for every page."""
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    from globi.tools.visualization.plotting import pick_energy_intensity_unit
    from globi.tools.visualization.utils import MAP_POLYGON_CRS_OPTIONS
    from globi.tools.visualization.views.common import AUTO_CRS, CRS_CHOICE_KEY

    with st.expander("Settings"):
        pick_energy_intensity_unit()
        options = [AUTO_CRS, *MAP_POLYGON_CRS_OPTIONS, _OTHER_CRS]
        choice = st.selectbox(
            "Map coordinate system",
            options=options,
            format_func=lambda o: "Automatic (guess from the data)"
            if o == AUTO_CRS
            else o,
            key="map_crs_select",
            help="The projected coordinate system the buildings were prepared in "
            "(cart_crs in the run config). Result files don't record it, so by default "
            "it is guessed from the footprints. Change it if buildings look misplaced.",
        )
        if choice == _OTHER_CRS:
            value = st.text_input("EPSG code", value="EPSG:3857", key="map_crs_other")
            try:
                CRS.from_user_input(value)
                choice = value
            except CRSError:
                st.error(f"'{value}' is not a known coordinate system.")
                choice = AUTO_CRS
        st.session_state[CRS_CHOICE_KEY] = choice


def render_data_source_sidebar() -> DataSource | None:
    """Render data source controls in sidebar.

    Returns DataSource or None if invalid configuration.
    """
    with st.sidebar:
        st.markdown("### Data source")
        source_type = st.radio(
            "Where are the results?",
            options=[_STORE, _FOLDER],
            index=0,
            help="Simulation store: results uploaded by GloBI runs (local stack or AWS). "
            "Folder: run folders already on this computer.",
        )

        config: DataSourceConfig
        if source_type == _FOLDER:
            base_dir = st.text_input(
                "Folder",
                value="outputs",
                help="Folder containing run folders, each with an EnergyAndPeak.pq file.",
            )
            config = LocalDataSourceConfig(base_dir=Path(base_dir))
        else:
            if label := _store_label():
                st.badge(label, color="gray")
            config = S3DataSourceConfig()

        if st.button("Refresh", help="Look again for new runs and reload data."):
            st.cache_resource.clear()
            st.cache_data.clear()

        _render_settings()

        try:
            data_source = _data_source(config)
            with st.spinner("Looking for runs..."):
                data_source.list_available_runs()
        except Exception as e:
            st.error(_friendly_s3_error(e) if source_type == _STORE else str(e))
            return None
        return data_source
