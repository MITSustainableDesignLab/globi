"""Orchestrate a configured local training + validation run.

This is what the ``globi tests surrogate-local`` / ``surrogate-validate`` commands
call; it glues :mod:`config`, :mod:`context`, :mod:`local_runner` and
:mod:`validate` together and decides the on-disk layout::

    <workdir>/
        holdout.json                  buildings reserved for validation (energyplus)
                                      + the fingerprint of the settings that chose them
        context.parquet               training context (energyplus)
        sim_cache/                    per-spec simulation cache (shared)
        training/<backend>/           run_local_iterative_training output
            training_spec.yml
        validation/<backend>/         validate_surrogate output
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, cast

import geopandas as gpd
import pandas as pd
import yaml
from scythe.base import ExperimentInputSpec

from globi.models.configs import GISPreprocessorColumnMap, GloBIExperimentSpec
from globi.models.surrogate.backends import MLBackend
from globi.models.surrogate.inference import SurrogateEnsemble
from globi.models.surrogate.pipeline import IterationSpec, ProgressiveTrainingSpec
from globi.pipelines.gis import preprocess_gis_file
from globi.validation.config import LocalValidationConfig
from globi.validation.context import (
    build_training_context,
    build_training_spec,
    default_priors_from_semantic_fields,
)
from globi.validation.env import ensure_local_hatchet_env
from globi.validation.local_runner import (
    LocalIterativeResult,
    run_local_iterative_training,
    sample_training_specs,
    simulate_specs_locally,
)
from globi.validation.validate import (
    ValidationResult,
    deterministic_specs,
    validate_surrogate,
)

logger = logging.getLogger(__name__)

#: iteration offset used to draw the dummy-mode "ground truth" from a different seed
DUMMY_HOLDOUT_ITER = 1000


def load_config(path: Path) -> LocalValidationConfig:
    """Load a `LocalValidationConfig` yaml and prepare the process for local execution."""
    ensure_local_hatchet_env()
    import globi.pipelines  # noqa: F401 - registers runnables

    return LocalValidationConfig.from_manifest(path)


# --------------------------------------------------------------------------- #
# Spec construction
# --------------------------------------------------------------------------- #


def _load_manifest(config: LocalValidationConfig) -> GloBIExperimentSpec:
    if config.manifest is None:
        msg = "`manifest` is required in energyplus mode."
        raise ValueError(msg)
    return GloBIExperimentSpec.from_manifest(config.manifest)


# preprocessed GIS frames by manifest path: the hold-out, the training context and the
# ground truth all need the same frame, so preprocess once per process.
_PREPROCESSED: dict[str, tuple[gpd.GeoDataFrame, GISPreprocessorColumnMap]] = {}


def _preprocessed(
    config: LocalValidationConfig, manifest: GloBIExperimentSpec
) -> tuple[gpd.GeoDataFrame, GISPreprocessorColumnMap]:
    key = str(config.manifest)
    if key not in _PREPROCESSED:
        _PREPROCESSED[key] = preprocess_gis_file(
            manifest.gis_preprocessor_config,
            manifest.file_config,
            scenario=manifest.scenario,
        )
    return _PREPROCESSED[key]


def _sha1_of_files(*paths: Path) -> str:
    h = hashlib.sha1()  # noqa: S324 - not used for security
    for path in paths:
        h.update(path.read_bytes())
    return h.hexdigest()


def _holdout_fingerprint(
    config: LocalValidationConfig, manifest: GloBIExperimentSpec
) -> dict[str, Any]:
    """Everything that determines which buildings get held out (and the context)."""
    return {
        "seed": config.seed,
        "n_test": config.n_test,
        "manifest": str(config.manifest),
        "scenario": manifest.scenario,
        "inputs_sha1": _sha1_of_files(
            manifest.file_config.gis_file, manifest.file_config.semantic_fields_file
        ),
    }


def _holdout_ids(
    config: LocalValidationConfig, manifest: GloBIExperimentSpec
) -> list[str]:
    """Pick (or reload) the buildings reserved for validation.

    The hold-out is chosen once, when the training context is built, and pinned in
    `holdout.json` together with the settings that chose it.  Re-choosing it later
    (e.g. after changing `n_test` or the GIS file) would let buildings that are in the
    training context leak into the validation set, so a mismatch is an error rather than a
    rebuild.
    """
    fingerprint = _holdout_fingerprint(config, manifest)
    if config.holdout_path.exists():
        stored = json.loads(config.holdout_path.read_text())
        stale = {
            k: (stored.get(k), v) for k, v in fingerprint.items() if stored.get(k) != v
        }
        if stale:
            details = ", ".join(
                f"{k}: {old!r} -> {new!r}" for k, (old, new) in stale.items()
            )
            msg = (
                f"{config.holdout_path} was built with different settings ({details}); "
                "use a new `workdir` (or delete this one) rather than mixing hold-outs."
            )
            raise ValueError(msg)
        return stored["ids"]

    _, ids = deterministic_specs(
        manifest,
        n=config.n_test,
        seed=config.seed,
        preprocessed=_preprocessed(config, manifest),
    )
    config.workdir.mkdir(parents=True, exist_ok=True)
    config.holdout_path.write_text(json.dumps({**fingerprint, "ids": ids}, indent=2))
    logger.info("Held out %d buildings for validation.", len(ids))
    return ids


def build_spec(
    config: LocalValidationConfig, backend: MLBackend
) -> ProgressiveTrainingSpec:
    """Build the training spec for one backend according to `config.mode`."""
    if config.mode == "dummy":
        with open(config.dummy_training_spec) as f:
            base = ProgressiveTrainingSpec.model_validate({
                **yaml.safe_load(f),
                "storage_settings": None,
            })
        return base.model_copy(
            update={
                "ml_backend": backend,
                "iteration": IterationSpec(
                    n_per_iter=config.n_per_iter,
                    min_per_stratum=config.min_per_stratum,
                    max_iters=config.max_iters,
                    recursion=base.iteration.recursion,
                ),
                "cross_val": base.cross_val.model_copy(
                    update={"n_folds": config.n_folds}
                ),
            }
        )

    manifest = _load_manifest(config)
    holdout = _holdout_ids(config, manifest)
    if not config.context_path.exists():
        context = build_training_context(
            manifest.gis_preprocessor_config,
            manifest.file_config,
            scenario=manifest.scenario,
            exclude_building_ids=holdout,
            preprocessed=_preprocessed(config, manifest),
        )
        context.to_parquet(config.context_path)
        logger.info(
            "Wrote training context (%d buildings) to %s",
            len(context),
            config.context_path,
        )
    return build_training_spec(
        manifest,
        context_path=config.context_path,
        ml_backend=backend,
        priors=default_priors_from_semantic_fields(
            manifest.file_config.semantic_fields_file,
            fixed_basement_attic=config.fixed_basement_attic,
        ),
        n_per_iter=config.n_per_iter,
        min_per_stratum=config.min_per_stratum,
        max_iters=config.max_iters,
        n_folds=config.n_folds,
        targets_globs=config.targets_globs,
        exclude_columns=config.exclude_columns,
        thresholds=config.thresholds,
        base_run_name=f"local-surrogate-{backend.ml_backend}",
    )


# --------------------------------------------------------------------------- #
# Training
# --------------------------------------------------------------------------- #


def run_training(
    config: LocalValidationConfig, backend_names: list[str] | None = None
) -> dict[str, LocalIterativeResult]:
    """Train one surrogate per selected backend; returns results keyed by backend name."""
    results: dict[str, LocalIterativeResult] = {}
    for backend in config.selected_backends(backend_names):
        spec = build_spec(config, backend)
        out_dir = config.backend_dir(backend)
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "training_spec.yml", "w") as f:
            yaml.dump(spec.model_dump(mode="json"), f, indent=2, sort_keys=False)
        logger.info("Training %s surrogate -> %s", backend.ml_backend, out_dir)
        results[backend.ml_backend] = run_local_iterative_training(
            spec,
            out_dir,
            n_workers=config.n_workers,
            seed=config.seed,
            sim_cache_dir=config.sim_cache_dir,
        )
    return results


def load_trained_ensemble(
    config: LocalValidationConfig, backend: MLBackend
) -> SurrogateEnsemble:
    """Reload the surrogate a previous `run_training` wrote for `backend`."""
    summary_path = config.backend_dir(backend) / "summary.yml"
    if not summary_path.exists():
        msg = f"No trained {backend.ml_backend} surrogate at {summary_path}; run `surrogate-local` first."
        raise FileNotFoundError(msg)
    return SurrogateEnsemble.from_training_summary(summary_path, backend)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def ground_truth_specs(
    config: LocalValidationConfig,
) -> tuple[Any, list[ExperimentInputSpec]]:
    """The runnable and specs for the deterministic (ground truth) set."""
    if config.mode == "dummy":
        # a fresh draw from the priors with a seed no training iteration uses
        spec = build_spec(config, config.backends[0]).model_copy(
            update={
                "iteration": IterationSpec(
                    n_per_iter=config.n_test,
                    min_per_stratum=1,
                    current_iter=DUMMY_HOLDOUT_ITER,
                )
            }
        )
        return spec.runnable, sample_training_specs(spec, seed=config.seed)

    from globi.pipelines.simulations import simulate_globi_building

    manifest = _load_manifest(config)
    holdout = _holdout_ids(config, manifest)
    specs, _ = deterministic_specs(
        manifest,
        n=None,
        building_ids=holdout,
        preprocessed=_preprocessed(config, manifest),
    )
    return simulate_globi_building, cast(list[ExperimentInputSpec], specs)


def simulate_ground_truth(config: LocalValidationConfig) -> dict[str, pd.DataFrame]:
    """Simulate (or load from cache) the deterministic ground-truth set."""
    runnable, specs = ground_truth_specs(config)
    logger.info("Simulating %d ground-truth buildings...", len(specs))
    return simulate_specs_locally(
        runnable, specs, cache_dir=config.sim_cache_dir, n_workers=config.n_workers
    )


def run_validations(
    config: LocalValidationConfig, backend_names: list[str] | None = None
) -> dict[str, ValidationResult]:
    """Validate every selected (already trained) backend against the ground truth."""
    ground_truth = simulate_ground_truth(config)
    results: dict[str, ValidationResult] = {}
    for backend in config.selected_backends(backend_names):
        ensemble = load_trained_ensemble(config, backend)
        out_dir = config.validation_dir / backend.ml_backend
        logger.info("Validating %s surrogate -> %s", backend.ml_backend, out_dir)
        results[backend.ml_backend] = validate_surrogate(
            ensemble, ground_truth, out_dir=out_dir
        )
    return results


def summarize_validations(results: dict[str, ValidationResult]) -> pd.DataFrame:
    """One row per (backend, target) with the headline metrics and stock error."""
    rows = []
    for name, r in results.items():
        g = r.metrics_global["all"]
        stock = r.aggregate.loc[("all", "all")]
        for target in g.index:
            rows.append({
                "backend": name,
                "target": target,
                "r2": g.loc[target, "r2"],
                "cvrmse": g.loc[target, "cvrmse"],
                "nmbe": g.loc[target, "nmbe"],
                "mae": g.loc[target, "mae"],
                "stock_pct_error": stock.loc[target, "pct_error"],
            })
    return pd.DataFrame(rows).set_index(["backend", "target"])
