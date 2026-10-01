"""Configuration for a local surrogate training + validation run."""

from pathlib import Path
from typing import Literal

from pydantic import Field

from globi.models.base import BaseConfig
from globi.models.surrogate.backends import MLBackend
from globi.models.surrogate.pipeline import ConvergenceThresholds
from globi.validation.context import (
    DEFAULT_EXCLUDED_FEATURE_COLUMNS,
    DEFAULT_TARGET_GLOBS,
)


class LocalValidationConfig(BaseConfig):
    """Everything needed to train small surrogates locally and validate them.

    Two modes:

    - ``energyplus``: sample buildings from the GIS data in ``manifest``, fill in
      semantic fields / geometry knobs from priors, simulate with EnergyPlus, train;
      validate against a held-out set of buildings simulated exactly as the GIS data
      defines them.
    - ``dummy``: the same loop on the analytic ``dummy_simulation`` runnable
      (``dummy_training_spec``), which runs in seconds and needs no EnergyPlus.
    """

    mode: Literal["energyplus", "dummy"] = Field(
        default="energyplus", description="Which simulator drives the loop."
    )
    workdir: Path = Field(
        default=Path("outputs/surrogate-local"),
        description="Root output directory (training/, validation/, sim_cache/ ...).",
    )
    seed: int = Field(
        default=0, description="Seed for sampling and hold-out selection."
    )
    n_workers: int = Field(
        default=1, ge=1, description="Worker processes for simulation (1 = in-process)."
    )
    backends: list[MLBackend] = Field(
        ...,
        description="ML backends to train, one surrogate per entry (discriminated on `ml_backend`).",
    )

    # ---- energyplus mode -------------------------------------------------
    manifest: Path | None = Field(
        default=None,
        description="GloBIExperimentSpec yaml describing the building stock (energyplus mode).",
    )
    n_per_iter: int | list[int] = Field(
        default=32, description="Training samples per iteration."
    )
    min_per_stratum: int = Field(default=8, description="Min samples per stratum.")
    max_iters: int = Field(default=1, ge=1, description="Max outer iterations.")
    n_folds: int = Field(default=4, ge=2, description="Cross-validation folds.")
    targets_globs: list[str] = Field(
        default_factory=lambda: list(DEFAULT_TARGET_GLOBS),
        description="Globs selecting regression targets from the flattened result columns.",
    )
    exclude_columns: list[str] = Field(
        default_factory=lambda: sorted(DEFAULT_EXCLUDED_FEATURE_COLUMNS),
        description="Index columns that must not become features.",
    )
    thresholds: dict[str, ConvergenceThresholds] = Field(
        default_factory=lambda: {"*": ConvergenceThresholds(r2=0.95)},
        description="Convergence thresholds by target glob.",
    )
    fixed_basement_attic: bool = Field(
        default=True,
        description="Pin basement/attic priors to 'none' (deterministic spec validators).",
    )
    n_test: int = Field(
        default=8, ge=1, description="Held-out deterministic buildings to validate on."
    )

    # ---- dummy mode ------------------------------------------------------
    dummy_training_spec: Path = Field(
        default=Path("tests/data/dummy_training/training.yml"),
        description="ProgressiveTrainingSpec yaml for the dummy runnable (dummy mode).",
    )

    @property
    def training_dir(self) -> Path:
        """Where per-backend training runs live."""
        return self.workdir / "training"

    @property
    def validation_dir(self) -> Path:
        """Where per-backend validation outputs live."""
        return self.workdir / "validation"

    @property
    def sim_cache_dir(self) -> Path:
        """Simulation cache shared by training and validation."""
        return self.workdir / "sim_cache"

    @property
    def holdout_path(self) -> Path:
        """The held-out building ids plus the fingerprint of the settings that chose them."""
        return self.workdir / "holdout.json"

    @property
    def context_path(self) -> Path:
        """The training context parquet."""
        return self.workdir / "context.parquet"

    def backend_dir(self, backend: MLBackend) -> Path:
        """Training output dir for a backend."""
        return self.training_dir / backend.ml_backend

    def selected_backends(self, names: list[str] | None) -> list[MLBackend]:
        """Filter configured backends by name (all if `names` is empty/None)."""
        if not names:
            return list(self.backends)
        chosen = [b for b in self.backends if b.ml_backend in names]
        missing = set(names) - {b.ml_backend for b in chosen}
        if missing:
            msg = f"Backends {sorted(missing)} are not configured; available: {[b.ml_backend for b in self.backends]}"
            raise ValueError(msg)
        return chosen
