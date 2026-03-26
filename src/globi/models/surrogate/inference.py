"""Inference utilities for the surrogate model pipeline."""

import pandas as pd
from pydantic import BaseModel, Field
from scythe.utils.filesys import FileReference

from globi.models.surrogate.backends import MLBackend


class ReferencedMLBackend(BaseModel):
    """A model backend with referenced regressor and transforms."""

    regressor: FileReference
    transforms: FileReference
    ml_backend: MLBackend = Field(
        ..., description="The ml backend for the model.", discriminator="ml_backend"
    )

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        """Predict the targets for the given features."""
        model = self.ml_backend.load_model_from_cache(self.regressor)
        transforms = self.ml_backend.load_transforms(self.transforms)
        pred_fn = self.ml_backend.build_predict_fn(
            model_object=model, transformers=transforms
        )
        return pred_fn(features)
