"""Run the surrogate training pipeline in-process, without Hatchet or S3.

Each function mirrors one task of the ``iterative_training`` hatchet workflow in
``globi.pipelines.training``:

==========================  ==================================
hatchet task                local equivalent
==========================  ==================================
create_simulations          :func:`sample_training_specs` + :func:`simulate_specs_locally`
await_simulations           (synchronous)
combine_results             :func:`combine_with_previous`
start/await_training        :func:`train_folds_locally`
evaluate_training           :func:`train_folds_locally` (fold averages + convergence)
transition_recursion        :func:`run_local_iterative_training` (the loop)
finalize                    :func:`run_local_iterative_training` (``summary.yml``)
==========================  ==================================
"""

import hashlib
import json
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
import pandas as pd
import yaml
from scythe.base import ExperimentInputSpec
from scythe.utils.results import transpose_dataframe_dict
from tqdm import tqdm

from globi.models.surrogate.inference import ReferencedMLBackend, SurrogateEnsemble
from globi.models.surrogate.metrics import fold_test_averages
from globi.models.surrogate.pipeline import ProgressiveTrainingSpec
from globi.models.surrogate.sampling import SampleSpec
from globi.models.surrogate.training import TrainFoldSpec
from globi.validation.env import ensure_local_hatchet_env

logger = logging.getLogger(__name__)

# fields that vary between otherwise-identical specs and must not affect the cache key
_CACHE_KEY_EXCLUDED_FIELDS = frozenset({
    "experiment_id",
    "sort_index",
    "workflow_run_id",
    "root_workflow_run_id",
    "storage_settings",
})

# spec fields that reference input files: keyed by their *contents*, so editing the
# component library / semantic fields / component map invalidates cached results.
_CACHE_KEY_FILE_FIELDS = (
    "db_file",
    "semantic_fields_file",
    "component_map_file",
    "epwzip_file",
)


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #


@cache
def _file_sha1(path: str, size: int, mtime_ns: int) -> str:
    """Content hash of a local file, memoised on (path, size, mtime)."""
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()  # noqa: S324 - not used for security


def _file_fingerprint(ref: object) -> object:
    """Replace a local file path by a content hash; leave urls / missing paths as-is."""
    if not isinstance(ref, str):
        return ref
    path = Path(ref)
    if not path.is_file():
        return ref
    st = path.stat()
    return f"sha1:{_file_sha1(str(path.resolve()), st.st_size, st.st_mtime_ns)}"


def spec_cache_key(spec: ExperimentInputSpec) -> str:
    """A content hash of a spec, independent of its position in an experiment.

    Local input files are hashed by content, not path.
    """
    payload = spec.model_dump(mode="json", exclude=set(_CACHE_KEY_EXCLUDED_FIELDS))
    for name in _CACHE_KEY_FILE_FIELDS:
        if name in payload:
            payload[name] = _file_fingerprint(payload[name])
    return hashlib.sha1(  # noqa: S324 - not used for security
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def run_spec_locally(
    runnable_name: str, spec_json: dict[str, Any]
) -> dict[str, pd.DataFrame]:
    """Execute one registered experiment in this process and return its dataframes.

    Safe to call from a freshly spawned worker process: it sets up the hatchet env,
    imports the pipelines (which registers the runnables), and re-validates the spec.
    """
    ensure_local_hatchet_env()
    from scythe.registry import ExperimentRegistry

    import globi.pipelines  # noqa: F401 - registers runnables

    runnable = ExperimentRegistry.get_runnable(runnable_name)
    spec = runnable.input_validator_type.model_validate(spec_json)  # pyright: ignore [reportAttributeAccessIssue]
    output = runnable.mock_run(input=spec)  # pyright: ignore [reportAttributeAccessIssue]
    return {k: v for k, v in output.dataframes.items() if isinstance(v, pd.DataFrame)}


def _cache_paths(cache_dir: Path, runnable_name: str, key: str) -> Path:
    return cache_dir / runnable_name / key


def _read_cached(spec_dir: Path) -> dict[str, pd.DataFrame] | None:
    manifest = spec_dir / "keys.json"
    if not manifest.exists():
        return None
    keys: list[str] = json.loads(manifest.read_text())
    return {k: pd.read_parquet(spec_dir / f"{k}.parquet") for k in keys}


def _write_cached(spec_dir: Path, dfs: dict[str, pd.DataFrame]) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    for k, df in dfs.items():
        df.to_parquet(spec_dir / f"{k}.parquet")
    (spec_dir / "keys.json").write_text(json.dumps(sorted(dfs)))


def simulate_specs_locally(
    runnable: Any,
    specs: list[ExperimentInputSpec],
    *,
    cache_dir: Path,
    n_workers: int = 1,
) -> dict[str, pd.DataFrame]:
    """Simulate specs in-process (optionally in parallel) with a per-spec parquet cache.

    Args:
        runnable: A scythe-registered standalone (e.g. `simulate_globi_building`).
        specs: The input specs.  Order is preserved in the gathered output.
        cache_dir: Root of the cache; results live at `cache_dir/<runnable>/<hash>/`.
        n_workers: Number of worker processes for uncached specs (1 = in-process).

    Returns:
        The per-key concatenation of every spec's result frames, exactly as scythe's
        gather would produce them.
    """
    runnable_name: str = runnable.name
    keys = [spec_cache_key(spec) for spec in specs]
    results: dict[int, dict[str, pd.DataFrame]] = {}
    pending: list[int] = []
    for i, key in enumerate(keys):
        cached = _read_cached(_cache_paths(cache_dir, runnable_name, key))
        if cached is not None:
            results[i] = cached
        else:
            pending.append(i)
    logger.info(
        "%d/%d specs cached; simulating %d.", len(results), len(specs), len(pending)
    )

    def _run_and_cache(i: int) -> dict[str, pd.DataFrame]:
        dfs = run_spec_locally(runnable_name, specs[i].model_dump(mode="json"))
        _write_cached(_cache_paths(cache_dir, runnable_name, keys[i]), dfs)
        return dfs

    if pending:
        # The first miss runs in-process so shared caches (e.g. the downloaded EPW)
        # are warm before fanning out.
        first, *rest = pending
        results[first] = _run_and_cache(first)
        if n_workers <= 1 or not rest:
            for i in tqdm(rest, desc=f"Simulating ({runnable_name})"):
                results[i] = _run_and_cache(i)
        else:
            ctx = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as pool:
                futures = {
                    pool.submit(
                        run_spec_locally,
                        runnable_name,
                        specs[i].model_dump(mode="json"),
                    ): i
                    for i in rest
                }
                for fut in tqdm(
                    as_completed(futures),
                    total=len(futures),
                    desc=f"Simulating ({runnable_name}, {n_workers} workers)",
                ):
                    i = futures[fut]
                    dfs = fut.result()
                    _write_cached(_cache_paths(cache_dir, runnable_name, keys[i]), dfs)
                    results[i] = dfs

    ordered = [results[i] for i in range(len(specs))]
    return transpose_dataframe_dict(ordered)


# --------------------------------------------------------------------------- #
# Sampling / combining
# --------------------------------------------------------------------------- #


def sample_training_specs(
    spec: ProgressiveTrainingSpec, *, seed: int | None = None
) -> list[ExperimentInputSpec]:
    """Draw this iteration's training samples and convert them to simulation specs.

    Mirrors step 1 of `iterative_training.create_simulations`.  The sampler's own RNG
    is seeded by `spec.iteration.current_iter`; `seed` additionally pins numpy's global
    RNG, which some `GloBIBuildingSpec` validators draw from.
    """
    sample_spec = SampleSpec(parent=spec, priors=spec.samplers)
    sample_df = sample_spec.populate_sample_df()
    if seed is not None:
        np.random.seed(seed + spec.iteration.current_iter)
    input_validator = cast(
        type[ExperimentInputSpec], spec.runnable.input_validator_type
    )
    return sample_spec.convert_to_specs(sample_df, input_validator)


def combine_with_previous(
    previous: dict[str, Path] | None,
    incoming: dict[str, pd.DataFrame],
    out_dir: Path,
) -> dict[str, Path]:
    """Grow the simulation cache: concat new results onto previous iterations' parquets.

    Mirrors `iterative_training.combine_results`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    combined: dict[str, Path] = {}
    previous = previous or {}
    for key in set(previous) | set(incoming):
        parts: list[pd.DataFrame] = []
        if key in previous:
            parts.append(pd.read_parquet(previous[key]))
        if key in incoming:
            parts.append(incoming[key])
        df = pd.concat(parts, axis=0) if len(parts) > 1 else parts[0]
        path = out_dir / f"{key}.parquet"
        df.to_parquet(path)
        combined[key] = path
    return combined


# --------------------------------------------------------------------------- #
# Training
# --------------------------------------------------------------------------- #


@dataclass
class LocalTrainingResult:
    """Everything one training round produces, with artifacts on local disk."""

    fold_models: list[ReferencedMLBackend]
    global_metrics: pd.DataFrame
    strata_metrics: pd.DataFrame
    fold_averages: pd.Series
    global_averages: pd.Series
    converged: bool
    data_paths: dict[str, Path]

    @property
    def test_metrics_table(self) -> pd.DataFrame:
        """Fold-averaged test metrics as a (target x metric) table."""
        s = self.global_averages
        table = s.unstack(level="metric") if "metric" in s.index.names else s.to_frame()
        return cast(pd.DataFrame, table)


def train_folds_locally(
    spec: ProgressiveTrainingSpec,
    data_paths: dict[str, Path],
    models_dir: Path,
) -> LocalTrainingResult:
    """Train one model per cross-validation fold and evaluate convergence.

    Mirrors `start_training` + `await_training` + `evaluate_training`.
    """
    fold_models: list[ReferencedMLBackend] = []
    global_frames: list[pd.DataFrame] = []
    strata_frames: list[pd.DataFrame] = []
    for i in range(spec.cross_val.n_folds):
        fold_dir = models_dir / f"fold_{i}"
        fold_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Training fold %d/%d...", i + 1, spec.cross_val.n_folds)
        fold_spec = TrainFoldSpec(
            experiment_id="placeholder",
            sort_index=i,
            data_uris=dict(data_paths),
            parent=spec,
        )
        trained = fold_spec.train(fold_dir)
        fold_models.append(
            ReferencedMLBackend(
                regressor=trained.artifacts.artifacts.regressor_path,
                transforms=trained.artifacts.artifacts.transforms_path,
                ml_backend=spec.ml_backend,
            )
        )
        global_frames.append(trained.global_metrics)
        strata_frames.append(trained.stratum_metrics)

    global_metrics = pd.concat(global_frames, axis=0)
    strata_metrics = pd.concat(strata_frames, axis=0)
    fold_averages = fold_test_averages(strata_metrics)
    global_averages = fold_test_averages(global_metrics)
    converged, *_ = spec.convergence_criteria.run(fold_averages)

    return LocalTrainingResult(
        fold_models=fold_models,
        global_metrics=global_metrics,
        strata_metrics=strata_metrics,
        fold_averages=fold_averages,
        global_averages=global_averages,
        converged=bool(converged),
        data_paths=data_paths,
    )


# --------------------------------------------------------------------------- #
# The outer loop
# --------------------------------------------------------------------------- #

StopReason = Literal["converged", "max_depth"]


@dataclass
class LocalIterativeResult:
    """The outcome of a local iterative training run."""

    reasoning: StopReason
    iterations: list[LocalTrainingResult] = field(default_factory=list)
    workdir: Path = Path()

    @property
    def final(self) -> LocalTrainingResult:
        """The last training round."""
        return self.iterations[-1]

    @property
    def fold_models(self) -> list[ReferencedMLBackend]:
        """The fold models from the last training round."""
        return self.final.fold_models

    @property
    def ensemble(self) -> SurrogateEnsemble:
        """The trained surrogate (the last round's fold models)."""
        return SurrogateEnsemble(models=self.fold_models)

    @property
    def summary_path(self) -> Path:
        """Where `summary.yml` was written."""
        return self.workdir / "summary.yml"


def run_local_iterative_training(
    spec: ProgressiveTrainingSpec,
    workdir: Path,
    *,
    n_workers: int = 1,
    seed: int | None = 0,
    sim_cache_dir: Path | None = None,
) -> LocalIterativeResult:
    """Run the whole sample -> simulate -> train -> evaluate loop locally.

    Layout of `workdir`::

        iter_000/
            specs.parquet         the sampled training specs (this iteration only)
            data/<key>.parquet    combined simulation results (all iterations so far)
            models/fold_<i>/      regressor + transforms.yml per fold
            metrics/{global,strata}.parquet
        summary.yml

    Args:
        spec: The training spec; `iteration.current_iter` is the starting iteration.
        workdir: Output directory.
        n_workers: Worker processes for simulation.
        seed: Seed for numpy's global RNG (see `sample_training_specs`).
        sim_cache_dir: Per-spec simulation cache (default: `workdir / "sim_cache"`).
    """
    workdir.mkdir(parents=True, exist_ok=True)
    cache_dir = sim_cache_dir or (workdir / "sim_cache")
    result = LocalIterativeResult(reasoning="max_depth", workdir=workdir)
    previous_data: dict[str, Path] | None = None
    all_global: list[pd.DataFrame] = []
    all_strata: list[pd.DataFrame] = []

    current = spec.iteration.current_iter
    while True:
        iter_spec = spec.model_copy(
            update={
                "iteration": spec.iteration.model_copy(update={"current_iter": current})
            }
        )
        iter_dir = workdir / f"iter_{current:03d}"
        logger.info("=== Iteration %d ===", current)

        iter_dir.mkdir(parents=True, exist_ok=True)
        specs = sample_training_specs(iter_spec, seed=seed)
        pd.DataFrame([s.model_dump(mode="json") for s in specs]).to_parquet(
            iter_dir / "specs.parquet"
        )
        incoming = simulate_specs_locally(
            iter_spec.runnable, specs, cache_dir=cache_dir, n_workers=n_workers
        )
        data_paths = combine_with_previous(previous_data, incoming, iter_dir / "data")

        training = train_folds_locally(iter_spec, data_paths, iter_dir / "models")
        metrics_dir = iter_dir / "metrics"
        metrics_dir.mkdir(exist_ok=True)
        training.global_metrics.to_parquet(metrics_dir / "global.parquet")
        training.strata_metrics.to_parquet(metrics_dir / "strata.parquet")
        all_global.append(training.global_metrics)
        all_strata.append(training.strata_metrics)
        result.iterations.append(training)
        logger.info(
            "Iteration %d test metrics:\n%s", current, training.test_metrics_table
        )

        if training.converged:
            result.reasoning = "converged"
            break
        if iter_spec.iteration.at_max_iters:
            result.reasoning = "max_depth"
            break
        previous_data = data_paths
        current += 1

    # mirrors `finalize`: combined metrics across iterations + a summary manifest
    combined_dir = workdir / "combined_metrics"
    combined_dir.mkdir(exist_ok=True)
    pd.concat(all_global, axis=0).to_parquet(combined_dir / "global.parquet")
    pd.concat(all_strata, axis=0).to_parquet(combined_dir / "strata.parquet")
    summary = {
        "reasoning": result.reasoning,
        "ml_backend": spec.ml_backend.ml_backend,
        "n_iterations": len(result.iterations),
        "data_paths": {k: str(v) for k, v in result.final.data_paths.items()},
        "fold_models": [
            {"regressor": str(m.regressor), "transforms": str(m.transforms)}
            for m in result.fold_models
        ],
        "test_metrics_by_iteration": [
            {
                "iteration": i,
                "converged": it.converged,
                "metrics": _series_to_records(it.global_averages),
            }
            for i, it in enumerate(result.iterations)
        ],
    }
    with open(result.summary_path, "w") as f:
        yaml.dump(summary, f, indent=2, sort_keys=False)
    return result


def _series_to_records(s: pd.Series) -> list[dict[str, Any]]:
    names = [str(n) for n in s.index.names]
    return [
        {**dict(zip(names, cast(tuple, idx), strict=True)), "value": float(v)}
        for idx, v in s.items()
    ]
