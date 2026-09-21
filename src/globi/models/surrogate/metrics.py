"""Metric utilities for surrogate model evaluation."""

from typing import cast

import numpy as np
import pandas as pd


def normalized_mean_bias_error(
    preds: pd.DataFrame, targets: pd.DataFrame
) -> np.ndarray:
    """Compute nMBE as mean residual divided by mean of true values.

    Residuals are defined as `true - predicted`. When the mean true value for a
    target is exactly zero, a denominator of `1` is used so nMBE reproduces MBE.

    Rows are matched positionally (like the sklearn metrics), since predictions
    typically carry a fresh RangeIndex while targets keep their feature MultiIndex.
    """
    true = targets.to_numpy(dtype=float)
    pred = preds[targets.columns].to_numpy(dtype=float)
    mean_residual = (true - pred).mean(axis=0)
    mean_true = true.mean(axis=0)
    denominator = np.where(mean_true != 0, mean_true, 1.0)
    return mean_residual / denominator


def compute_frame_metrics(preds: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    """Compute per-target regression metrics for a prediction/target frame pair.

    Returns a frame indexed by `target` with columns `metric` in
    {mae, rmse, r2, cvrmse, nmbe, mape}.
    """
    from sklearn.metrics import (
        mean_absolute_error,
        mean_absolute_percentage_error,
        mean_squared_error,
        r2_score,
    )

    mae = mean_absolute_error(targets, preds, multioutput="raw_values")
    mse = mean_squared_error(targets, preds, multioutput="raw_values")
    rmse = np.sqrt(mse)
    r2 = r2_score(targets, preds, multioutput="raw_values")
    cvrmse = rmse / np.abs(targets.mean(axis=0) + 1e-5)
    nmbe = normalized_mean_bias_error(preds=preds, targets=targets)
    mape = mean_absolute_percentage_error(
        targets + 1e-5,
        preds,
        multioutput="raw_values",
    )

    metrics = pd.DataFrame(
        {
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "cvrmse": cvrmse,
            "nmbe": nmbe,
            "mape": mape,
        },
    )
    metrics.columns.names = ["metric"]
    metrics.index.names = ["target"]

    return metrics


def fold_test_averages(metrics: pd.DataFrame) -> pd.Series:
    """Average the test-split metrics of a set of fold results over the folds.

    `metrics` is the frame returned by `TrainFoldSpec.compute_metrics` (global or
    strata) concatenated over folds: index levels include `sort_index` (the fold) and
    `iteration`; columns include a `split_segment` level.  The result is a series
    indexed by the remaining column levels plus `iteration`, as consumed by
    `ConvergenceThresholdsByTarget.run`.
    """
    return cast(
        pd.Series,
        metrics.xs("test", level="split_segment", axis=1)
        .groupby(level="iteration")
        .mean()
        .unstack(),
    )
