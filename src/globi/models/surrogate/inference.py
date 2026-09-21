"""Applying a trained surrogate.

A training run (``iterative_training`` on hatchet, or
``globi.validation.local_runner`` in-process) produces one regressor + transforms pair
per cross-validation fold.  :class:`SurrogateEnsemble` is *the* surrogate: it holds
those fold models and predicts with their mean.

Features are the same frame the trainer saw, i.e. the result index a simulation of the
building would carry (`ExperimentInputSpec.make_multiindex`: every scalar spec field
plus `computed_features`).  :func:`features_from_specs` builds that frame from specs
alone, so a building can be predicted without ever being simulated.
"""

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Self, cast

import pandas as pd
import yaml
from pydantic import BaseModel, Field, TypeAdapter
from scythe.base import ExperimentInputSpec
from scythe.utils.filesys import FileReference

from globi.models.surrogate.backends import MLBackend
from globi.models.surrogate.transforms import Transformers

logger = logging.getLogger(__name__)

#: Index column holding the conditioned floor area the intensity targets (kWh/m²) are
#: normalized by.
AREA_COLUMN = "feature.geometry.energy_model_conditioned_area"

#: Prefix of the semantic-field feature columns (`feature.semantic.<Name>`).
SEMANTIC_PREFIX = "feature.semantic."

_FILE_REFERENCE = TypeAdapter(FileReference)


def file_reference(ref: str | Path) -> FileReference:
    """Validate a uri or path into scythe's `FileReference` (S3Url / HttpUrl / Path)."""
    text = str(ref)
    return _FILE_REFERENCE.validate_python(text if "://" in text else Path(text))


def features_from_specs(specs: Iterable[ExperimentInputSpec]) -> pd.DataFrame:
    """The feature frame a simulation of each spec would carry as its result index.

    One row per spec, columns = every index-able spec field plus `computed_features`,
    exactly as `TrainFoldSpec` saw them (no simulation involved).
    """
    rows = [
        spec.make_multiindex(n_rows=1, include_sort_subindex=False).to_frame(
            index=False
        )
        for spec in specs
    ]
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, axis=0, ignore_index=True)


class ReferencedMLBackend(BaseModel):
    """A model backend with referenced regressor and transforms."""

    regressor: FileReference
    transforms: FileReference
    ml_backend: MLBackend = Field(
        ..., description="The ml backend for the model.", discriminator="ml_backend"
    )

    def load_transforms(self) -> Transformers:
        """The (cached) transforms this model was trained with."""
        return self.ml_backend.load_transforms(self.transforms)

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        """Predict the targets for the given features.

        The result carries a fresh RangeIndex regardless of `features`' index.
        """
        model = self.ml_backend.load_model_from_cache(self.regressor)
        transforms = self.load_transforms()
        pred_fn = self.ml_backend.build_predict_fn(
            model_object=model, transformers=transforms
        )
        return pred_fn(features)


class SurrogateEnsemble(BaseModel):
    """The fold models of one training run; predictions are their mean."""

    models: list[ReferencedMLBackend] = Field(..., min_length=1)

    # ---- construction ------------------------------------------------------

    @classmethod
    def from_pairs(
        cls, pairs: Iterable[tuple[str | Path, str | Path]], backend: MLBackend
    ) -> Self:
        """Build from `(regressor, transforms)` references and the backend they use."""
        models = [
            ReferencedMLBackend(
                regressor=file_reference(regressor),
                transforms=file_reference(transforms),
                ml_backend=backend,
            )
            for regressor, transforms in pairs
        ]
        if not models:
            msg = "No fold models given."
            raise ValueError(msg)
        return cls(models=models)

    @classmethod
    def from_training_summary(cls, path: str | Path, backend: MLBackend) -> Self:
        """From the `summary.yml` a local `run_local_iterative_training` writes."""
        summary = yaml.safe_load(Path(path).read_text())
        pairs = [(m["regressor"], m["transforms"]) for m in summary["fold_models"]]
        ensemble = cls.from_pairs(pairs, backend)
        logger.info("Loaded %d fold models from %s", len(ensemble.models), path)
        return ensemble

    @classmethod
    def from_file_refs(cls, path: str | Path, backend: MLBackend) -> Self:
        """From the `result_file_refs` parquet (local or s3) of a hatchet training subrun.

        Its `regressor` / `transforms` columns hold one artifact pair per fold.
        """
        refs = pd.read_parquet(str(path))
        missing = {"regressor", "transforms"} - set(refs.columns)
        if missing:
            msg = (
                f"{path} has no {sorted(missing)} column(s); expected a "
                "result_file_refs parquet from a training subrun."
            )
            raise ValueError(msg)
        pairs = list(zip(refs["regressor"], refs["transforms"], strict=True))
        ensemble = cls.from_pairs(pairs, backend)
        logger.info("Loaded %d fold models from %s", len(ensemble.models), path)
        return ensemble

    @classmethod
    def load(cls, source: str | Path, backend: MLBackend) -> Self:
        """Dispatch on the source: a `summary.yml` or a `result_file_refs` parquet."""
        if str(source).endswith((".yml", ".yaml")):
            return cls.from_training_summary(source, backend)
        return cls.from_file_refs(source, backend)

    # ---- metadata ----------------------------------------------------------

    @property
    def transforms(self) -> Transformers:
        """The transforms of the first fold (all folds share features and targets)."""
        return self.models[0].load_transforms()

    @property
    def targets(self) -> list[str]:
        """The target columns the ensemble predicts."""
        return list(self.transforms.y.targets)

    @property
    def features(self) -> list[str]:
        """The feature columns the ensemble consumes."""
        return list(self.transforms.x.features)

    # ---- prediction --------------------------------------------------------

    def predict_per_fold(self, features: pd.DataFrame) -> list[pd.DataFrame]:
        """One prediction frame per fold model, each indexed like `features`."""
        x = features.reset_index(drop=True)
        return [m.predict(x).set_index(features.index) for m in self.models]

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        """The ensemble (fold-mean) prediction, indexed like `features`."""
        per_fold = self.predict_per_fold(features)
        return cast(pd.DataFrame, sum(per_fold) / len(per_fold))

    def predict_specs(self, specs: Iterable[ExperimentInputSpec]) -> pd.DataFrame:
        """Predict buildings straight from their specs, without simulating them."""
        return self.predict(features_from_specs(specs))

    def unseen_categories(self, features: pd.DataFrame) -> dict[str, set]:
        """Categorical values in `features` that no fold model was trained on.

        Predictions for such rows extrapolate: index encoding maps an unseen value to
        whatever code the encoder assigns it.
        """
        unseen: dict[str, set] = {}
        for m in self.models:
            for col, cats in m.load_transforms().x.cat_map.items():
                if col not in features.columns:
                    continue
                extra = set(features[col].unique()) - set(cats)
                if extra:
                    unseen.setdefault(col, set()).update(extra)
        return unseen
