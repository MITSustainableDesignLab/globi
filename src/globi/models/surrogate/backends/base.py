"""Core backend abstractions for surrogate model training."""

import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, Field
from scythe.utils.filesys import FileReference, fetch_uri

from globi.models.surrogate.transforms import PrepDataResult, Transformers, predict


@dataclass(frozen=True)
class TrainingContext:
    """Runtime context shared by all model backends."""

    prepped_data: PrepDataResult
    tempdir: Path


@dataclass(frozen=True)
class TrainedModel:
    """A trained model with a regressor and transforms."""

    model_object: Any
    transformers: Transformers


@dataclass(frozen=True)
class TrainedArtifacts:
    """Artifacts for a trained model."""

    regressor_path: Path
    transforms_path: Path


@dataclass(frozen=True)
class TrainedModelWithArtifacts:
    """Model artifacts emitted by backend training."""

    trained_model: TrainedModel
    artifacts: TrainedArtifacts


ML_MODEL_CACHE: dict[str, dict[FileReference, Any]] = {}
ML_TRANSFORMS_CACHE: dict[FileReference, Transformers] = {}


class SurrogateModelBackend(BaseModel, ABC):
    """Base interface for model-specific training and loading."""

    ml_backend: Any = Field(
        ...,
        description="The discriminator for selecting a model backend.",
    )

    @abstractmethod
    def train(self, context: TrainingContext) -> TrainedModel:
        """Train the model and serialize artifacts."""

    def train_and_save(self, context: TrainingContext) -> TrainedModelWithArtifacts:
        """Train the model and save the artifacts."""
        trained_model = self.train(context)
        artifacts = TrainedArtifacts(
            regressor_path=self.save_model(trained_model.model_object, context.tempdir),
            transforms_path=self.save_transforms(
                trained_model.transformers, context.tempdir
            ),
        )
        return TrainedModelWithArtifacts(trained_model, artifacts)

    @abstractmethod
    def save_model(self, model_object: Any, output_dir: Path) -> Path:
        """Serialize backend-specific model artifacts to disk."""

    @classmethod
    @abstractmethod
    def load_model(cls, regressor_path: Path) -> Any:
        """Load backend-specific model artifacts from disk."""

    def load_model_from_cache(self, model_ref: FileReference) -> Any:
        """Load a model from the cache."""
        if self.ml_backend not in ML_MODEL_CACHE:
            ML_MODEL_CACHE[self.ml_backend] = {}
        if model_ref in ML_MODEL_CACHE[self.ml_backend]:
            return ML_MODEL_CACHE[self.ml_backend][model_ref]

        if isinstance(model_ref, Path):
            model = self.load_model(model_ref)
            ML_MODEL_CACHE[self.ml_backend][model_ref] = model
            return model
        else:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                local_model_path = fetch_uri(
                    model_ref,
                    tmp_path
                    / Path("model.bin").with_suffix(Path(str(model_ref)).suffix),
                )
                model = self.load_model(local_model_path)
                ML_MODEL_CACHE[self.ml_backend][model_ref] = model
                return model

    @classmethod
    @abstractmethod
    def make_raw_predict_fn(
        cls,
        model_object: Any,
    ) -> Callable[[pd.DataFrame, list[str]], np.ndarray]:
        """Bind a backend-specific raw prediction callable.

        The signature of the raw prediction callable is:
        def raw_pred_fn(x: pd.DataFrame, col_order: list[str]) -> np.ndarray:
            ...
        """

    def save_transforms(self, transformers: Transformers, output_dir: Path) -> Path:
        """Save transforms in a backend-agnostic way."""
        transforms_path = output_dir / "transforms.yml"
        with open(transforms_path, "w") as f:
            yaml.dump(
                transformers.model_dump(mode="json"), f, indent=2, sort_keys=False
            )
        return transforms_path

    @classmethod
    def load_transforms(cls, transforms_ref: FileReference) -> Transformers:
        """Load transforms from a backend-agnostic way."""
        if transforms_ref in ML_TRANSFORMS_CACHE:
            return ML_TRANSFORMS_CACHE[transforms_ref]
        if isinstance(transforms_ref, Path):
            transformers = Transformers.model_validate(transforms_ref)
            ML_TRANSFORMS_CACHE[transforms_ref] = transformers
            return transformers
        else:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp) / "transforms.yml"
                local_transforms_path = fetch_uri(transforms_ref, tmp_path)
                with open(local_transforms_path) as f:
                    transformers_yaml = yaml.safe_load(f)
                transformers = Transformers.model_validate(transformers_yaml)
                ML_TRANSFORMS_CACHE[transforms_ref] = transformers
                return transformers

    @classmethod
    def build_predict_fn(
        cls, *, model_object: Any, transformers: Transformers
    ) -> Callable[[pd.DataFrame], pd.DataFrame]:
        """Create a dataframe-level prediction callable from raw backend prediction."""
        raw_pred = cls.make_raw_predict_fn(model_object)
        return lambda x: predict(x, conf=transformers, pred_fn=raw_pred)
