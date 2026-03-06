"""Hatchet v1 workflows for progressive surrogate training.

Defines the progressive_training workflow which orchestrates:
1. Sample buildings from GIS + sample FlatModel params from Priors
2. Simulate all samples via Scythe experiment (parallel)
3. Combine results across iterations
4. Train surrogate with cross-validation via Scythe experiment (parallel)
5. Check convergence; if not converged, spawn next iteration
"""

import logging
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from hatchet_sdk import Context
from pydantic import BaseModel, Field
from scythe.experiments import BaseExperiment
from scythe.hatchet import hatchet
from scythe.scatter_gather import RecursionMap
from scythe.utils.filesys import fetch_uri

from globi.models.configs import GISPreprocessorColumnMap
from globi.models.sampling import Priors
from globi.models.surrogate import (
    SurrogateTrainingConfig,
    TrainFoldInputSpec,
)
from globi.surrogate.experiments import simulate_training_sample, train_cv_fold
from globi.surrogate.sampling import sample_training_specs

logger = logging.getLogger(__name__)


class ProgressiveTrainingInput(BaseModel):
    """Input for the progressive surrogate training workflow."""

    config_uri: str = Field(..., description="URI to SurrogateTrainingConfig YAML.")


progressive_training = hatchet.workflow(
    name="progressive_surrogate_training",
    input_validator=ProgressiveTrainingInput,
)


def _load_config(config_uri: str) -> SurrogateTrainingConfig:
    """Load SurrogateTrainingConfig from a URI."""
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = fetch_uri(config_uri, Path(tmpdir) / "config.yml")
        return SurrogateTrainingConfig.from_manifest(local_path)


def _load_priors(priors_file: Any) -> Priors:
    """Load Priors from a FileReference."""
    with tempfile.TemporaryDirectory() as tmpdir:
        if isinstance(priors_file, Path):
            local_path = priors_file
        else:
            local_path = fetch_uri(str(priors_file), Path(tmpdir) / "priors.yml")
        with open(local_path) as f:
            data = yaml.safe_load(f)
        return Priors.model_validate(data)


def _load_gis(
    gis_file: Any,
) -> tuple[gpd.GeoDataFrame, GISPreprocessorColumnMap]:
    """Load preprocessed GIS file and its column map."""
    with tempfile.TemporaryDirectory() as tmpdir:
        if isinstance(gis_file, Path):
            gis_dir = gis_file.parent
        else:
            gis_path = fetch_uri(str(gis_file), Path(tmpdir) / "globi_gdf.pq")
            gis_dir = gis_path.parent

        gdf = gpd.read_parquet(gis_dir / "globi_gdf.pq")
        colmap = GISPreprocessorColumnMap.from_manifest(
            gis_dir / "globi_column_output_map.yaml"
        )
        return gdf, colmap


@progressive_training.task(execution_timeout=timedelta(hours=12))
async def sample_and_simulate(
    input: ProgressiveTrainingInput,
    ctx: Context,
) -> dict[str, Any]:
    """Sample from GIS + Priors, allocate Scythe simulation experiment, await results."""
    config = _load_config(input.config_uri)
    priors = _load_priors(config.priors_file)
    gis_gdf, colmap = _load_gis(config.gis_file)

    sim_experiment = BaseExperiment(
        experiment=simulate_training_sample,
        run_name=f"{config.name}/simulate",
    )
    existing_versions = sim_experiment.list_versions()
    iteration = len(existing_versions)

    n = config.iteration.n_init if iteration == 0 else config.iteration.n_per_iter
    logger.info(f"Iteration {iteration}: sampling {n} training specs.")

    generator = np.random.default_rng(seed=42 + iteration)
    specs = sample_training_specs(
        gis_gdf=gis_gdf,
        colmap=colmap,
        priors=priors,
        n=n,
        generator=generator,
    )

    branching_factor = max(1, min(100, len(specs) // 50))
    run, ref = sim_experiment.allocate(
        specs,
        version="bumppatch",
        recursion_map=RecursionMap(factor=branching_factor, max_depth=1),
    )

    await ref.aio_result()

    combined_uri = (
        f"s3://{sim_experiment.storage_settings.BUCKET}/"
        f"{sim_experiment.prefix}/combined_data.pq"
    )

    return {
        "iteration": iteration,
        "sim_version": str(run.version),
        "combined_data_uri": combined_uri,
    }


@progressive_training.task(
    parents=[sample_and_simulate],
    execution_timeout=timedelta(hours=6),
)
async def train_with_cv(
    input: ProgressiveTrainingInput,
    ctx: Context,
) -> dict[str, Any]:
    """Allocate Scythe CV training experiment and await results."""
    config = _load_config(input.config_uri)
    parent_output = ctx.task_output(sample_and_simulate)
    combined_data_uri = parent_output["combined_data_uri"]

    with tempfile.TemporaryDirectory() as tmpdir:
        local_data = fetch_uri(combined_data_uri, Path(tmpdir) / "data.pq")
        data = pd.read_parquet(local_data)

    feature_columns = [
        c
        for c in data.columns
        if c not in ("weather_file_id",) and not c.startswith("target.")
    ]
    target_columns = [c for c in data.columns if c.startswith("target.")]

    n_folds = config.cv.n_folds
    fold_specs: list[TrainFoldInputSpec] = []
    for fold_ix in range(n_folds):
        fold_specs.append(
            TrainFoldInputSpec(
                experiment_id=f"train_fold_{fold_ix}",
                sort_index=fold_ix,
                data_uri=combined_data_uri,
                fold_index=fold_ix,
                n_folds=n_folds,
                hyperparameters=config.hyperparameters,
                feature_columns=feature_columns,
                target_columns=target_columns,
            )
        )

    train_experiment = BaseExperiment[TrainFoldInputSpec, Any](
        experiment=train_cv_fold,
        run_name=f"{config.name}/train",
    )
    run, ref = train_experiment.allocate(
        fold_specs,
        version="bumppatch",
        recursion_map=RecursionMap(factor=n_folds, max_depth=0),
    )

    await ref.result()

    return {
        "train_version": str(run.version),
        "iteration": parent_output["iteration"],
    }


@progressive_training.task(
    parents=[train_with_cv],
    execution_timeout=timedelta(minutes=10),
)
async def check_convergence_and_iterate(
    input: ProgressiveTrainingInput,
    ctx: Context,
) -> dict[str, Any]:
    """Check convergence and optionally spawn next iteration."""
    config = _load_config(input.config_uri)
    parent_output = ctx.task_output(train_with_cv)
    iteration = parent_output["iteration"]

    train_experiment = BaseExperiment[TrainFoldInputSpec, Any](
        experiment=train_cv_fold,
        run_name=f"{config.name}/train",
    )
    latest_results = train_experiment.latest_results
    global_metrics_key = next(
        (
            k
            for k in (latest_results or {})
            if "GlobalMetrics" in k or "global" in k.lower()
        ),
        None,
    )

    converged = False
    if global_metrics_key and latest_results:
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_path = fetch_uri(
                latest_results[global_metrics_key],
                Path(tmpdir) / "metrics.pq",
            )
            metrics_df = pd.read_parquet(metrics_path)

        from globi.models.surrogate import Metrics

        avg_row = metrics_df.select_dtypes(include="number").mean()
        avg_metrics = Metrics(
            mae=avg_row.get("mae", float("inf")),
            rmse=avg_row.get("rmse", float("inf")),
            mape=avg_row.get("mape", float("inf")),
            r_squared=avg_row.get("r_squared", 0.0),
            cvrmse=avg_row.get("cvrmse", float("inf")),
            target="average",
            fold=-1,
            stratum=None,
        )
        converged = config.convergence.check(avg_metrics)

        logger.info(
            f"Iteration {iteration}: converged={converged}, "
            f"metrics={avg_metrics.model_dump()}"
        )

    at_max_iters = (iteration + 1) >= config.iteration.max_iters

    if converged:
        logger.info(f"Training converged at iteration {iteration}.")
        return {"converged": True, "iteration": iteration}

    if at_max_iters:
        logger.info(
            f"Max iterations ({config.iteration.max_iters}) reached "
            f"without convergence."
        )
        return {"converged": False, "iteration": iteration, "max_iters_reached": True}

    logger.info(f"Spawning iteration {iteration + 1}...")
    await progressive_training.aio_run(input)

    return {"converged": False, "iteration": iteration, "next_spawned": True}
