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
    """
    mean_residual = cast(pd.Series, (targets - preds).mean(axis=0))
    mean_true = cast(pd.Series, targets.mean(axis=0))
    denominator = mean_true.where(mean_true != 0, other=1.0)
    return (mean_residual / denominator).to_numpy(dtype=float)
