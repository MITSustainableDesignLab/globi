"""Backend implementations for surrogate model training."""

from globi.models.surrogate.backends.base import (
    SurrogateModelBackend,
    TrainedModelWithArtifacts,
    TrainingContext,
)
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
]
