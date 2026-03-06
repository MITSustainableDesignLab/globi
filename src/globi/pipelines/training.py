"""The training pipeline."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from hatchet_sdk import Context
from pydantic import BaseModel, HttpUrl
from scythe.base import ExperimentOutputSpec
from scythe.experiments import (
    BaseExperiment,
    ExperimentRun,
    SemVer,
    VersionedExperiment,
)
from scythe.hatchet import hatchet
from scythe.registry import ExperimentRegistry
from scythe.scatter_gather import RecursionMap, ScatterGatherResult, scatter_gather

from globi.models.surrogate.dummy import DummySimulationInput, dummy_simulation
from globi.models.surrogate.training import SampleSpec, TrainFoldSpec, TrainWithCVSpec


class FoldResult(ExperimentOutputSpec):
    """The output for a fold."""

    pass


@ExperimentRegistry.Register(
    description="Train a regressor with cross-fold validation.",
)
def train_regressor_with_cv_fold(
    input_spec: TrainFoldSpec, tempdir: Path
) -> FoldResult:
    """Train a regressor with cross-fold validation."""
    # DO TRAINING

    return FoldResult()


class ExperimentMetadata(BaseModel):
    """Metadata about an experiment."""

    workflow_run_id: str
    run_id: str
    run_name: str
    version: SemVer
    datetime: datetime


class CombineResultsResult(BaseModel):
    """The result of combining the results of the simulations."""

    scatter_gather_result: ScatterGatherResult
    combined_scatter_gather_result: ScatterGatherResult


iterative_training = hatchet.workflow(
    name="iterative_training",
    description="Sample a collection of buliding simulations to then simulate and train a surrogate model.",
    input_validator=SampleSpec,
)


@iterative_training.task(
    name="iterative_training.create_simulations",
    schedule_timeout=timedelta(minutes=30),
    execution_timeout=timedelta(minutes=10),
)
def create_simulations(spec: SampleSpec, context: Context) -> ExperimentMetadata:
    """Create the simulations."""
    # STEP 1: Generate the training samples, allocate simulations
    specs = [
        DummySimulationInput(
            a=i,
            b=i,
            experiment_id="placeholder",
            sort_index=i,
        )
        for i in range(10)
    ]

    # STEP 2: Simulate the simulations using scythe
    root_run_name = spec.progressive_training_spec.experiment_id
    run_name = f"{root_run_name}/sample"

    exp = BaseExperiment(
        # TODO: replace with simulate_globi_flat_building
        experiment=dummy_simulation,  # TODO: add configurability to switch between simulations.
        run_name=run_name,
        storage_settings=spec.progressive_training_spec.storage_settings,
    )

    run, ref = exp.allocate(
        specs,
        version="bumpmajor",  # TODO: bump minor if not the first iteration.
        recursion_map=spec.progressive_training_spec.iteration.recursion,
    )

    run_name = run.versioned_experiment.base_experiment.run_name
    if not run_name:
        msg = "Run name is required."
        raise ValueError(msg)
    run_id = run.experiment_id

    return ExperimentMetadata(
        workflow_run_id=ref.workflow_run_id,
        run_id=run_id,
        run_name=run_name,
        version=run.versioned_experiment.version,
        datetime=run.timestamp,
    )


@iterative_training.task(
    name="iterative_training.await_simulations",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(hours=5),
    parents=[create_simulations],
)
async def await_simulations(spec: SampleSpec, context: Context) -> ScatterGatherResult:
    """Await the simulations."""
    parent_output = context.task_output(create_simulations)
    workflow_run_id = parent_output.workflow_run_id
    context.log("Awaiting simulations...")
    results = await scatter_gather.aio_get_result(workflow_run_id)
    context.log("Simulations completed.")

    return results


@iterative_training.task(
    name="iterative_training.combine_results",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(hours=1),
    parents=[await_simulations, create_simulations],
)
async def combine_results(spec: SampleSpec, context: Context) -> CombineResultsResult:
    """Combine the results of the simulations."""
    results = context.task_output(await_simulations)
    run_info = context.task_output(create_simulations)
    # TODO: kind of annoying have to reconstruct the run object here; necessary because the base experiment is not serializable.
    _run = ExperimentRun(
        versioned_experiment=VersionedExperiment(
            base_experiment=BaseExperiment(
                experiment=dummy_simulation,  # TODO: replace with simulate_globi_flat_building
                run_name=run_info.run_name,
                storage_settings=spec.progressive_training_spec.storage_settings,
            ),
            version=run_info.version,
        ),
        timestamp=run_info.datetime,
    )
    # files = run.list_results_files()
    # TODO: configure which files to store/combine via input spec.
    return CombineResultsResult(
        scatter_gather_result=results,
        combined_scatter_gather_result=results,
    )


class StartTrainingResult(BaseModel):
    """The result of starting the training."""

    training_spec: TrainWithCVSpec
    experiment_metadata: ExperimentMetadata


@iterative_training.task(
    name="iterative_training.start_training",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(hours=1),
    parents=[combine_results],
)
async def start_training(spec: SampleSpec, context: Context) -> StartTrainingResult:
    """Start the training."""
    results = context.task_output(combine_results)

    train_spec = TrainWithCVSpec(
        progressive_training_spec=spec.progressive_training_spec,
        progressive_training_iteration_ix=spec.progressive_training_iteration_ix,
        data_uri=results.combined_scatter_gather_result.uris[
            "main_result"
        ],  # TODO: should be configure which result to use
        stage_type="train",
    )

    # TODO: create the training specs and then allocate the experiment

    specs = train_spec.schedule

    root_run_name = spec.progressive_training_spec.experiment_id
    run_name = f"{root_run_name}/train"
    exp = BaseExperiment(
        experiment=train_regressor_with_cv_fold,
        run_name=run_name,
        storage_settings=spec.progressive_training_spec.storage_settings,
    )
    run, ref = exp.allocate(
        specs,
        version="bumpmajor",  # TODO: bump minor if not the first iteration.
        recursion_map=RecursionMap(
            factor=2,
            max_depth=0,
        ),
    )

    if not run.versioned_experiment.base_experiment.run_name:
        msg = "Run name is required."
        raise ValueError(msg)

    return StartTrainingResult(
        training_spec=train_spec,
        experiment_metadata=ExperimentMetadata(
            workflow_run_id=ref.workflow_run_id,
            run_id=run.experiment_id,
            run_name=run.versioned_experiment.base_experiment.run_name,
            version=run.versioned_experiment.version,
            datetime=run.timestamp,
        ),
    )


@iterative_training.task(
    name="iterative_training.await_training",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(hours=5),
    parents=[start_training],
)
async def await_training(spec: SampleSpec, context: Context) -> ScatterGatherResult:
    """Await the training."""
    parent_output = context.task_output(start_training)
    workflow_run_id = parent_output.experiment_metadata.workflow_run_id
    context.log("Awaiting training...")
    results = await scatter_gather.aio_get_result(workflow_run_id)
    context.log("Training completed.")

    return results


class TrainingEvaluationResult(BaseModel):
    """The result of evaluating the training."""

    converged: bool


class RecursionTransition(BaseModel):
    """The transition of the recursion."""

    reasoning: Literal["max_depth", "converged"] | None
    child_workflow_run_id: str | None


@iterative_training.task(
    name="iterative_training.evaluate_training",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(minutes=5),
    parents=[await_training],
)
async def evaluate_training(
    spec: SampleSpec, context: Context
) -> TrainingEvaluationResult:
    """Evaluate the training."""
    _results = context.task_output(await_training)
    return TrainingEvaluationResult(converged=True)


@iterative_training.task(
    name="iterative_training.transition_recursion",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(minutes=5),
    parents=[evaluate_training, start_training],
)
async def transition_recursion(
    spec: SampleSpec, context: Context
) -> RecursionTransition:
    """Transition the recursion."""
    results = context.task_output(evaluate_training)
    if results.converged:
        # create child
        return RecursionTransition(reasoning="converged", child_workflow_run_id=None)
    if (
        spec.progressive_training_iteration_ix + 1
        >= spec.progressive_training_spec.iteration.max_iters
    ):
        return RecursionTransition(reasoning="max_depth", child_workflow_run_id=None)

    start_training_output = context.task_output(start_training)

    sample_spec = SampleSpec(
        progressive_training_spec=spec.progressive_training_spec,
        progressive_training_iteration_ix=spec.progressive_training_iteration_ix + 1,
        data_uri=start_training_output.training_spec.data_uri,
        stage_type="sample",
    )

    ref = await iterative_training.aio_run_no_wait(
        sample_spec,
    )
    return RecursionTransition(
        reasoning=None, child_workflow_run_id=ref.workflow_run_id
    )


if __name__ == "__main__":
    from scythe.settings import ScytheStorageSettings

    from globi.models.surrogate.training import ProgressiveTrainingSpec

    progressive_training_spec = ProgressiveTrainingSpec(
        experiment_id="test-experiment",
        gis_uri=HttpUrl("https://example.com/gis.parquet"),
        storage_settings=ScytheStorageSettings(),
    )
    spec = SampleSpec(
        progressive_training_spec=progressive_training_spec,
        progressive_training_iteration_ix=0,
        data_uri=None,
        stage_type="sample",
    )
    result = iterative_training.run(spec)
    print(result)
