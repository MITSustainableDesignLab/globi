"""Shared sidebar: data source config. Used by all pages in the multipage app."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from globi.tools.visualization.data_sources import (
    DataSource,
    S3ExperimentInfo,
    is_s3_storage_configured,
    list_s3_experiments,
)
from globi.tools.visualization.models import LocalDataSourceConfig, S3DataSourceConfig


def _friendly_s3_error(exc: Exception) -> str:
    """Return a user-friendly message for common S3/AWS errors."""
    msg = str(exc)
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
    return f"Failed to fetch experiments from S3: {msg}"


@st.cache_data(ttl=300, show_spinner="Fetching experiments from S3...")
def _fetch_s3_experiments() -> list[S3ExperimentInfo]:
    """Fetch available experiments from S3 with caching."""
    try:
        return list_s3_experiments()
    except ValueError as e:
        st.error(str(e))
        return []
    except Exception as e:
        st.error(_friendly_s3_error(e))
        return []


def _render_local_source() -> DataSource:
    """Render local data source controls."""
    base_dir = st.text_input("Output directory", value="outputs")
    return DataSource.from_config(LocalDataSourceConfig(base_dir=Path(base_dir)))


def _render_s3_source() -> DataSource | None:
    """Render S3 data source controls with experiment dropdown."""
    st.caption(
        "Requires SCYTHE_STORAGE_BUCKET (and optionally SCYTHE_STORAGE_BUCKET_PREFIX) "
        "in your environment, e.g. .env.scythe.storage."
    )

    if not is_s3_storage_configured():
        st.info("Set bucket in .env.scythe.storage to list experiments from S3.")
        st.markdown("**Manual entry:**")
        run_name = st.text_input("S3 run name", value="", key="s3_manual_run")
        version = st.text_input("Version (optional)", value="", key="s3_manual_version")
        dataframe_key = st.selectbox(
            "Dataframe",
            options=["Results", "EnergyAndPeak"],
            index=0,
            key="s3_manual_dataframe",
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
