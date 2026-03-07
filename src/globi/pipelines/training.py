"""The training pipeline."""

from datetime import timedelta
from pathlib import Path
from typing import Literal

from hatchet_sdk import Context
from pydantic import BaseModel, HttpUrl
from scythe.base import ExperimentOutputSpec
from scythe.experiments import (
    BaseExperiment,
    ExperimentRun,
)
from scythe.hatchet import hatchet
from scythe.registry import ExperimentRegistry
from scythe.scatter_gather import RecursionMap, ScatterGatherResult, scatter_gather

from globi.models.surrogate.dummy import DummySimulationInput, dummy_simulation
from globi.models.surrogate.training import (
    IterationSpec,
    ProgressiveTrainingSpec,
    TrainFoldSpec,
    TrainWithCVSpec,
)


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


class CombineResultsResult(BaseModel):
    """The result of combining the results of the simulations."""

    scatter_gather_result: ScatterGatherResult
    combined_scatter_gather_result: ScatterGatherResult


iterative_training = hatchet.workflow(
    name="iterative_training",
    description="Sample a collection of buliding simulations to then simulate and train a surrogate model.",
    input_validator=ProgressiveTrainingSpec,
)


class ExperimentRunWithRef(BaseModel):
    """An experiment run with a workflow run id."""

    run: ExperimentRun
    workflow_run_id: str


@iterative_training.task(
    name="iterative_training.create_simulations",
    schedule_timeout=timedelta(minutes=30),
    execution_timeout=timedelta(minutes=10),
)
def create_simulations(
    spec: ProgressiveTrainingSpec, context: Context
) -> ExperimentRunWithRef:
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
    run_name = f"{spec.experiment_id}/sample"

    exp = BaseExperiment(
        # TODO: replace with simulate_globi_flat_building
        experiment=dummy_simulation,  # TODO: add configurability to switch between simulations.
        run_name=run_name,
        storage_settings=spec.storage_settings or ScytheStorageSettings(),
    )

    run, ref = exp.allocate(
        specs,
        version="bumpmajor",  # TODO: bump minor if not the first iteration; actually, not necessary since root experiment takes care of this
        recursion_map=spec.iteration.recursion,
    )

    run_name = run.versioned_experiment.base_experiment.run_name
    if not run_name:
        msg = "Run name is required."
        raise ValueError(msg)

    return ExperimentRunWithRef(
        run=run,
        workflow_run_id=ref.workflow_run_id,
    )


@iterative_training.task(
    name="iterative_training.await_simulations",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(hours=5),
    parents=[create_simulations],
)
async def await_simulations(
    spec: ProgressiveTrainingSpec, context: Context
) -> ScatterGatherResult:
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
async def combine_results(
    spec: ProgressiveTrainingSpec, context: Context
) -> CombineResultsResult:
    """Combine the results of the simulations."""
    results = context.task_output(await_simulations)
    run_info = context.task_output(create_simulations)
    # TODO: kind of annoying have to reconstruct the run object here; necessary because the base experiment is not serializable.
    _run = run_info.run
    # files = run.list_results_files()
    # TODO: configure which files to store/combine via input spec.
    return CombineResultsResult(
        scatter_gather_result=results,
        combined_scatter_gather_result=results,
    )


class StartTrainingResult(BaseModel):
    """The result of starting the training."""

    training_spec: TrainWithCVSpec
    experiment_run_with_ref: ExperimentRunWithRef


@iterative_training.task(
    name="iterative_training.start_training",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(hours=1),
    parents=[combine_results],
)
async def start_training(
    spec: ProgressiveTrainingSpec, context: Context
) -> StartTrainingResult:
    """Start the training."""
    results = context.task_output(combine_results)

    train_spec = TrainWithCVSpec(
        parent=spec,
        data_uri=results.combined_scatter_gather_result.uris[
            "main_result"
        ],  # TODO: should be configure which result to use
    )

    # TODO: create the training specs and then allocate the experiment

    specs = train_spec.schedule

    run_name = f"{spec.experiment_id}/train"
    exp = BaseExperiment(
        experiment=train_regressor_with_cv_fold,
        run_name=run_name,
        storage_settings=spec.storage_settings or ScytheStorageSettings(),
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
        experiment_run_with_ref=ExperimentRunWithRef(
            run=run,
            workflow_run_id=ref.workflow_run_id,
        ),
    )


@iterative_training.task(
    name="iterative_training.await_training",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(hours=5),
    parents=[start_training],
)
async def await_training(
    spec: ProgressiveTrainingSpec, context: Context
) -> ScatterGatherResult:
    """Await the training."""
    parent_output = context.task_output(start_training)
    workflow_run_id = parent_output.experiment_run_with_ref.workflow_run_id
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
    spec: ProgressiveTrainingSpec, context: Context
) -> TrainingEvaluationResult:
    """Evaluate the training."""
    _results = context.task_output(await_training)
    return TrainingEvaluationResult(converged=False)


@iterative_training.task(
    name="iterative_training.transition_recursion",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(minutes=5),
    parents=[evaluate_training, start_training],
)
async def transition_recursion(
    spec: ProgressiveTrainingSpec, context: Context
) -> RecursionTransition:
    """Transition the recursion."""
    results = context.task_output(evaluate_training)
    if results.converged:
        # create child
        return RecursionTransition(reasoning="converged", child_workflow_run_id=None)
    if spec.iteration.at_max_iters:
        return RecursionTransition(reasoning="max_depth", child_workflow_run_id=None)

    start_training_output = context.task_output(start_training)

    next_spec = spec.model_copy(deep=True)
    next_spec.iteration.current_iter += 1
    next_spec.data_uri = (
        start_training_output.training_spec.data_uri
    )  # or could be from combined
    exp = BaseExperiment(
        experiment=iterative_training,
        run_name=f"{next_spec.base_run_name}",
        storage_settings=spec.storage_settings or ScytheStorageSettings(),
    )
    _run, ref = exp.allocate(
        next_spec,
        version="bumpminor",
        recursion_map=RecursionMap(
            factor=2,
            max_depth=0,
        ),
    )
    return RecursionTransition(
        reasoning=None, child_workflow_run_id=ref.workflow_run_id
    )


if __name__ == "__main__":
    from scythe.settings import ScytheStorageSettings

    from globi.models.surrogate.training import ProgressiveTrainingSpec

    base_run_name = "test-experiment"
    progressive_training_spec = ProgressiveTrainingSpec(
        sort_index=0,
        experiment_id="placeholder",
        gis_uri=HttpUrl("https://example.com/gis.parquet"),
        iteration=IterationSpec(
            max_iters=4,
        ),
        storage_settings=ScytheStorageSettings(),
        data_uri=None,
        base_run_name=base_run_name,
    )

    exp = BaseExperiment(
        experiment=iterative_training,
        run_name="test-experiment",
    )

    run, ref = exp.allocate(
        progressive_training_spec,
        version="bumpmajor",
        recursion_map=RecursionMap(
            factor=2,
            max_depth=0,
        ),
    )
    import yaml

    print(yaml.dump(run.model_dump(mode="json"), indent=2, sort_keys=False))
    # result = iterative_training.run(spec)
    # print(result)
