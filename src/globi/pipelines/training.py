"""The training pipeline."""

import tempfile
from datetime import timedelta
from pathlib import Path
from typing import cast

import boto3
import pandas as pd
import yaml
from hatchet_sdk import Context
from scythe.base import ExperimentInputSpec
from scythe.experiments import (
    BaseExperiment,
)
from scythe.hatchet import hatchet
from scythe.registry import ExperimentRegistry
from scythe.scatter_gather import RecursionMap, ScatterGatherResult, scatter_gather
from scythe.settings import ScytheStorageSettings
from scythe.utils.filesys import S3Url

from globi.models.surrogate.outputs import (
    CombineResultsResult,
    ExperimentRunWithRef,
    FinalizeResult,
    RecursionTransition,
    StartTrainingResult,
    TrainingEvaluationResult,
)
from globi.models.surrogate.sampling import SampleSpec
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
    context.log("Generating training samples...")
    sample_spec = SampleSpec(parent=spec, priors=spec.samplers)
    sample_df = sample_spec.populate_sample_df()
    context.log("Training samples generated.")

    # TODO: we shouldn't have to cast here, but the typing on `runnable` is not working as expected.
    input_validator = cast(
        type[ExperimentInputSpec], spec.runnable.input_validator_type
    )
    context.log("Converting training samples to specs...")
    specs = sample_spec.convert_to_specs(sample_df, input_validator)
    context.log("Training samples converted to specs.")

    # STEP 2: Simulate the simulations using scythe
    run_name = spec.subrun_name("sample")

    exp = BaseExperiment(
        runnable=spec.runnable,
        run_name=run_name,
        storage_settings=spec.storage_settings or ScytheStorageSettings(),
    )

    context.log("Allocating simulations...")
    run, ref = exp.allocate(
        specs,
        version="bumpmajor",
        recursion_map=spec.iteration.recursion,
    )
    context.log("Simulations allocated.")

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
    """Combine the results of the simulations.

    Specifically, this step is responsible for combining the results of the simulations
    of the previous iteration(s) with the results of the current iteration.  In other words,
    this is where we grow our simulation cache.
    """
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
        context.log("Combining results from previous iterations...")
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
            context.log(f"Combining results for key {key}...")
            old_df = pd.read_parquet(str(spec.data_uris.uris[key]))
            new_df = pd.read_parquet(str(results.uris[key]))
            combined_df = pd.concat([old_df, new_df], axis=0)
            uri = spec.format_combined_output_uri(key)
            combined_df.to_parquet(str(uri))
            context.log(f"Results for key {key} combined and saved to s3.")
            combined_results[key] = uri

    else:
        # TODO: consider copying these over to the `combined` folder anyways.
        context.log(
            "No previous iterations to combine results from, so using results from current iteration."
        )
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

    context.log("Scheduling training...")
    run_name = spec.subrun_name("train")
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
    context.log("Training scheduled.")

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
    strata_uri = results_output.uris["strata"]
    globals_uri = results_output.uris["global"]
    context.log("Reading strata results from s3...")
    results = pd.read_parquet(str(strata_uri))
    context.log("Strata results read from s3.")
    context.log("Reading global results from s3...")
    results_globals = pd.read_parquet(str(globals_uri))
    context.log("Global results read from s3.")

    fold_averages = cast(
        pd.Series,
        results.xs("test", level="split_segment", axis=1)
        .groupby(level="iteration")
        .mean()
        .unstack(),
    )
    # TODO: fold_averages and strata and globals should be saved to s3

    global_averages = cast(
        pd.Series,
        results_globals.xs("test", level="split_segment", axis=1)
        .groupby(level="iteration")
        .mean()
        .unstack(),
    )

    context.log("Running convergence criteria...")
    (
        convergence_all,
        _convergence_monitor_segment,
        _convergence_monitor_segment_and_target,
        _convergence,
    ) = spec.convergence_criteria.run(fold_averages)
    context.log("Convergence criteria run.")

    return TrainingEvaluationResult(
        converged=convergence_all,
        metrics={
            "global_averages": global_averages.reset_index().to_dict(orient="records"),
        },
    )


@iterative_training.task(
    name="iterative_training.transition_recursion",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(minutes=5),
    parents=[evaluate_training, combine_results, await_training],
)
def transition_recursion(
    spec: ProgressiveTrainingSpec, context: Context
) -> RecursionTransition:
    """Transition the recursion."""
    results = context.task_output(evaluate_training)
    if results.converged:
        context.log("Converged! Time to wrap up... no more recursion.")
        return RecursionTransition(reasoning="converged", child_workflow_run_id=None)
    if spec.iteration.at_max_iters:
        context.log(
            "Not converged, but we're at the max number of iterations. Time to wrap up... no more recursion."
        )
        return RecursionTransition(reasoning="max_depth", child_workflow_run_id=None)

    await_training_output = context.task_output(await_training)
    # start_training_output = context.task_output(start_training)
    combine_results_output = context.task_output(combine_results)

    context.log(
        "Not converged, but we have more iterations to try. Time to continue recursion..."
    )
    next_spec = spec.model_copy(deep=True)
    next_spec.iteration.current_iter += 1
    next_spec.data_uris = combine_results_output.combined
    next_spec.metrics_uris.append(await_training_output)
    next_spec.previous_experiment_ids.append(spec.experiment_id)
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
    context.log("Recursion transitioned.")
    return RecursionTransition(
        reasoning=None, child_workflow_run_id=ref.workflow_run_id
    )


@iterative_training.task(
    name="iterative_training.finalize",
    schedule_timeout=timedelta(hours=5),
    execution_timeout=timedelta(minutes=30),
    parents=[transition_recursion, await_training, combine_results],
    # skip_if=[
    #     # TODO: maybe we should just run every time?
    #     ParentCondition(
    #         parent=transition_recursion,
    #         expression="output.reasoning == null",
    #     )
    # ],
)
def finalize(spec: ProgressiveTrainingSpec, context: Context) -> FinalizeResult:
    """Run when training has exited the loop (converged, max depth, or other reason). Saves final models and artifacts."""
    # TODO: save the final model?
    transition = context.task_output(transition_recursion)
    context.log(f"Training finished. Finalizing: {transition.reasoning}")

    context.log("Fetching metrics from all iterations...")
    await_training_output = context.task_output(await_training)
    metrics_uris = [*spec.metrics_uris, await_training_output]
    metrics_by_key: dict[str, list[pd.DataFrame]] = {}
    for i, metrics_uri in enumerate(metrics_uris):
        context.log(f"\tFetching metrics from iteration {i}...")
        for key in metrics_uri.uris:
            context.log(f"\t\tFetching metrics for key {key} from iteration {i}...")
            if key not in metrics_by_key:
                metrics_by_key[key] = []
            metrics_by_key[key].append(pd.read_parquet(str(metrics_uri.uris[key])))
    context.log("Combining metrics from all iterations...")
    combined_metrics = {
        key: pd.concat(metrics, axis=0) for key, metrics in metrics_by_key.items()
    }
    combined_metrics_uris = {
        key: spec.format_metrics_output_uri(key) for key in combined_metrics
    }
    context.log("Saving combined metrics to s3...")
    for key, metrics in combined_metrics.items():
        context.log(f"\tSaving metrics for key {key} to s3...")
        metrics.to_parquet(str(combined_metrics_uris[key]))
    context.log("Final metrics saved to s3.")

    # Get the simulation data outputs from all steps and this step
    combine_results_output = context.task_output(combine_results)

    # Get the experiment ids from all steps and this step
    experiment_ids = [*spec.previous_experiment_ids, spec.experiment_id]

    # TODO: save final models, or return them a little more directly?

    result = FinalizeResult(
        reasoning=transition.reasoning,
        data_uris=combine_results_output.combined.uris,
        metrics_uris=combined_metrics_uris,
        experiment_ids=experiment_ids,
    )

    s3_client = boto3.client("s3")
    summary_manifest_uri = spec.format_summary_manifest_key()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "summary.yml"
        with open(temp_path, "w") as f:
            yaml.dump(result.model_dump(mode="json"), f, indent=2, sort_keys=False)
        if spec.storage_settings is None:
            msg = (
                "Storage settings are not set, so we can't upload the summary manifest."
            )
            raise ValueError(msg)
        s3_client.upload_file(
            temp_path.as_posix(), spec.storage_settings.BUCKET, summary_manifest_uri
        )
    return result
