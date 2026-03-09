"""The training pipeline."""

import random
from datetime import timedelta
from pathlib import Path
from typing import cast

import pandas as pd
from hatchet_sdk import Context
from scythe.experiments import (
    BaseExperiment,
)
from scythe.hatchet import hatchet
from scythe.registry import ExperimentRegistry
from scythe.scatter_gather import RecursionMap, ScatterGatherResult, scatter_gather
from scythe.settings import ScytheStorageSettings
from scythe.utils.filesys import S3Url

from globi.models.surrogate.dummy import DummySimulationInput, dummy_simulation
from globi.models.surrogate.outputs import (
    CombineResultsResult,
    ExperimentRunWithRef,
    RecursionTransition,
    StartTrainingResult,
    TrainingEvaluationResult,
)
from globi.models.surrogate.training import (
    FoldResult,
    ProgressiveTrainingSpec,
    TrainFoldSpec,
    TrainWithCVSpec,
)


@ExperimentRegistry.Register(
    description="Train a regressor with cross-fold validation.",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(hours=1),
)
def train_regressor_with_cv_fold(
    input_spec: TrainFoldSpec, tempdir: Path
) -> FoldResult:
    """Train a regressor with cross-fold validation."""
    # DO TRAINING
    _model, (global_results, stratum_results), model_path = input_spec.train(tempdir)
    return FoldResult(
        regressor=model_path,
        dataframes={
            "global": global_results,
            "strata": stratum_results,
        },
    )


iterative_training = hatchet.workflow(
    name="iterative_training",
    description="Sample a collection of buliding simulations to then simulate and train a surrogate model.",
    input_validator=ProgressiveTrainingSpec,
)


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
            weather_file="some" if random.random() < 0.5 else "other",  # noqa: S311
            a=random.randint(-10, 10),  # noqa: S311
            b=random.randint(-10, 10),  # noqa: S311
            c=random.randint(-10, 10),  # noqa: S311
            experiment_id="placeholder",
            sort_index=i,
        )
        for i in range(1_000)
    ]

    # STEP 2: Simulate the simulations using scythe
    run_name = f"{spec.experiment_id}/sample"

    exp = BaseExperiment(
        runnable=spec.runnable,
        run_name=run_name,
        storage_settings=spec.storage_settings or ScytheStorageSettings(),
    )

    run, ref = exp.allocate(
        specs,
        version="bumpmajor",
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
    parents=[await_simulations],
)
def combine_results(
    spec: ProgressiveTrainingSpec, context: Context
) -> CombineResultsResult:
    """Combine the results of the simulations."""
    # TODO: major consider how we handle beyond-memory scale scenarios.
    # i.e. we probably need to refactor to allow lists of files that only the
    # main worker is responsible for combining.
    results = context.task_output(await_simulations)
    combined_results: dict[str, S3Url] = {}

    # TODO: in the old version, w removed constant columns from the data, i.e.:
    #     is_constant = (df.max(axis=0) - df.min(axis=0)).abs() < 1e-5
    #     df = df.loc[:, ~is_constant]
    # Should this sort of data cleaning be done here, or should it be done in the training task?
    # also, should we make sure to remove NaN?

    if spec.data_uris:
        shared_keys = set(spec.data_uris.uris.keys()) & set(results.uris.keys())
        old_keys_only = set(spec.data_uris.uris.keys()) - shared_keys
        new_keys_only = set(results.uris.keys()) - shared_keys
        # TODO: consider copying these over to the `combined` folder anyways.
        for key in old_keys_only:
            combined_results[key] = spec.data_uris.uris[key]
        for key in new_keys_only:
            combined_results[key] = results.uris[key]
        # TODO: refactor to use a threadpool executor?
        # For memory reasons, it might be a good idea to stay single threaded here.
        for key in shared_keys:
            old_df = pd.read_parquet(str(spec.data_uris.uris[key]))
            new_df = pd.read_parquet(str(results.uris[key]))
            combined_df = pd.concat([old_df, new_df], axis=0)
            uri = spec.format_combined_output_uri(key)
            combined_df.to_parquet(str(uri))
            combined_results[key] = uri

    else:
        # TODO: consider copying these over to the `combined` folder anyways.
        combined_results = results.uris

    return CombineResultsResult(
        incoming=results,
        combined=ScatterGatherResult(uris=combined_results),
    )


@iterative_training.task(
    name="iterative_training.start_training",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(hours=1),
    parents=[combine_results],
)
def start_training(
    spec: ProgressiveTrainingSpec, context: Context
) -> StartTrainingResult:
    """Start the training."""
    results = context.task_output(combine_results)

    train_spec = TrainWithCVSpec(
        parent=spec,
        data_uris=results.combined,  # TODO: should configure which results to use
    )

    # Alternatively, one task per fold-column combination?
    specs = train_spec.schedule

    run_name = f"{spec.experiment_id}/train"
    exp = BaseExperiment(
        runnable=train_regressor_with_cv_fold,
        run_name=run_name,
        storage_settings=spec.storage_settings or ScytheStorageSettings(),
    )
    run, ref = exp.allocate(
        specs,
        version="bumpmajor",  # There is normally only ever one training round per parent minor version, except during replays etc
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


@iterative_training.task(
    name="iterative_training.evaluate_training",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(minutes=5),
    parents=[await_training],
)
def evaluate_training(
    spec: ProgressiveTrainingSpec, context: Context
) -> TrainingEvaluationResult:
    """Evaluate the training."""
    results_output = context.task_output(await_training)
    strata = results_output.uris["strata"]
    _globals = results_output.uris["global"]
    results = pd.read_parquet(str(strata))

    fold_averages = cast(
        pd.Series,
        results.xs("test", level="split_segment", axis=1)
        .groupby(level="iteration")
        .mean()
        .unstack(),
    )
    # TODO: fold_averages and strata and globals should be saved to s3

    (
        convergence_all,
        _convergence_monitor_segment,
        _convergence_monitor_segment_and_target,
        _convergence,
    ) = spec.convergence_criteria.run(fold_averages)

    return TrainingEvaluationResult(converged=convergence_all)


@iterative_training.task(
    name="iterative_training.transition_recursion",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(minutes=5),
    parents=[evaluate_training, combine_results],
)
def transition_recursion(
    spec: ProgressiveTrainingSpec, context: Context
) -> RecursionTransition:
    """Transition the recursion."""
    results = context.task_output(evaluate_training)
    if results.converged:
        # create child
        return RecursionTransition(reasoning="converged", child_workflow_run_id=None)
    if spec.iteration.at_max_iters:
        return RecursionTransition(reasoning="max_depth", child_workflow_run_id=None)

    # start_training_output = context.task_output(start_training)
    combine_results_output = context.task_output(combine_results)

    next_spec = spec.model_copy(deep=True)
    next_spec.iteration.current_iter += 1
    next_spec.data_uris = combine_results_output.combined
    exp = BaseExperiment(
        runnable=iterative_training,
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


# TODO: Final training stage? or should we save models along the way.

if __name__ == "__main__":
    from pydantic import HttpUrl
    from scythe.settings import ScytheStorageSettings

    from globi.models.surrogate.configs.pipeline import (
        ConvergenceThresholds,
        ConvergenceThresholdsByTarget,
        IterationSpec,
        StratificationSpec,
    )

    base_run_name = "test-experiment"
    progressive_training_spec = ProgressiveTrainingSpec(
        runnable=dummy_simulation,
        sort_index=0,
        experiment_id="placeholder",
        gis_uri=HttpUrl("https://example.com/gis.parquet"),
        stratification=StratificationSpec(
            field="weather_file",
            sampling="equal",
            aliases=["feature.weather.file"],
        ),
        iteration=IterationSpec(
            max_iters=3,
        ),
        convergence_criteria=ConvergenceThresholdsByTarget(
            thresholds={
                "*": ConvergenceThresholds(r2=0.975),
            },
        ),
        storage_settings=ScytheStorageSettings(),
        data_uris=None,
        base_run_name=base_run_name,
    )

    exp = BaseExperiment(
        runnable=iterative_training,
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
