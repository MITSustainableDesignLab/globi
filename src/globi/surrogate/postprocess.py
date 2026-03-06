"""Result aggregation and convergence checking for surrogate training."""

import logging
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from scythe.experiments import BaseExperiment
from scythe.utils.filesys import fetch_uri

from globi.models.surrogate import ConvergenceThresholds, Metrics

logger = logging.getLogger(__name__)


def combine_simulation_results(
    previous_features: pd.DataFrame,
    previous_other_dfs: dict[str, pd.DataFrame],
    new_experiment: BaseExperiment,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Fetch new simulation results and combine with previous data.

    Args:
        previous_features: DataFrame from prior iterations, or None for first iteration.
        previous_other_dfs: Dictionary of other dataframes from prior iterations, or None for first iteration.
        new_experiment: Scythe experiment with latest simulation results.

    Returns:
        Tuple of (features_df, other_dfs) with all iterations' data.
    """
    latest_results = new_experiment.latest_results
    if latest_results is None:
        msg = "No results found for simulation experiment."
        raise RuntimeError(msg)

    features_df: pd.DataFrame | None = None
    other_dfs: dict[str, pd.DataFrame] = {}

    for key, uri in latest_results.items():
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = fetch_uri(uri, Path(tmpdir) / f"{key}.pq")
            df = pd.read_parquet(local_path)
            key_lower = key.lower()
            if "feature" in key_lower:
                features_df = df
            else:
                other_dfs[key] = df

    if previous_features is not None:
        features_df = (
            pd.concat([previous_features, features_df])
            if features_df is not None
            else previous_features
        )
    for key, df in other_dfs.items():
        if key in previous_other_dfs:
            other_dfs[key] = pd.concat([previous_other_dfs[key], df])
        else:
            other_dfs[key] = df

    # logger.info(
    #     f"Combined dataset: {len(combined)} rows "
    #     f"({len(new_data)} new, {len(previous_data) if previous_data is not None else 0} previous)"
    # )
    return features_df, other_dfs


def aggregate_fold_metrics(
    fold_experiment: BaseExperiment,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate per-fold metrics into global and stratum summaries.

    Args:
        fold_experiment: Scythe experiment with CV fold results.

    Returns:
        Tuple of (global_metrics_df, stratum_metrics_df) averaged across folds.
    """
    latest_results = fold_experiment.latest_results
    if latest_results is None:
        msg = "No results found for training experiment."
        raise RuntimeError(msg)

    global_dfs: list[pd.DataFrame] = []
    stratum_dfs: list[pd.DataFrame] = []

    for key, uri in latest_results.items():
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = fetch_uri(uri, Path(tmpdir) / f"{key}.pq")
            df = pd.read_parquet(local_path)
            key_lower = key.lower()
            if "global" in key_lower:
                global_dfs.append(df)
            elif "stratum" in key_lower:
                stratum_dfs.append(df)

    global_metrics = (
        pd.concat(global_dfs, ignore_index=True) if global_dfs else pd.DataFrame()
    )
    stratum_metrics = (
        pd.concat(stratum_dfs, ignore_index=True) if stratum_dfs else pd.DataFrame()
    )

    return global_metrics, stratum_metrics


def check_convergence(
    metrics_df: pd.DataFrame,
    thresholds: ConvergenceThresholds,
) -> bool:
    """Check if training has converged based on averaged metrics.

    Args:
        metrics_df: DataFrame with columns for metric values (mae, rmse, etc.).
        thresholds: Convergence thresholds to check against.

    Returns:
        True if all specified thresholds are met.
    """
    numeric_cols = metrics_df.select_dtypes(include="number").columns
    avg_metrics: dict[str, Any] = metrics_df[numeric_cols].mean().to_dict()
    metrics = Metrics(**avg_metrics)
    return thresholds.check(metrics)
