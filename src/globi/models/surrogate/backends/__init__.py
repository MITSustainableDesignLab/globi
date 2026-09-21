"""Backend implementations for surrogate model training."""

import sys

from globi.models.surrogate.backends.base import (
    SurrogateModelBackend,
    TrainedModelWithArtifacts,
    TrainingContext,
    preload_torch_runtime,
)

# On macOS, torch must be loaded before xgboost/lightgbm are *imported*, or torch ops
# deadlock on a second OpenMP runtime later on (see `preload_torch_runtime`).
if sys.platform == "darwin":
    preload_torch_runtime()
from globi.models.surrogate.backends.lgb import LGBBackend
from globi.models.surrogate.backends.nn import NNBackend
from globi.models.surrogate.backends.xgb import XGBBackend

MLBackend = XGBBackend | LGBBackend | NNBackend

__all__ = [
    "LGBBackend",
    "MLBackend",
    "NNBackend",
    "SurrogateModelBackend",
    "TrainedModelWithArtifacts",
    "TrainingContext",
    "XGBBackend",
    "preload_torch_runtime",
]
