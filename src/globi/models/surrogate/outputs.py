"""Outputs for the surrogate model pipeline."""

from typing import Literal

from pydantic import BaseModel
from scythe.experiments import ExperimentRun
from scythe.scatter_gather import ScatterGatherResult

from globi.models.surrogate.training import TrainWithCVSpec


class CombineResultsResult(BaseModel):
    """The result of combining the results of the simulations."""

    incoming: ScatterGatherResult
    combined: ScatterGatherResult


# TODO: This should perhaps go somewhere else since it is generally useful.
class ExperimentRunWithRef(BaseModel):
    """An experiment run with a workflow run id."""

    run: ExperimentRun
    workflow_run_id: str


class StartTrainingResult(BaseModel):
    """The result of starting the training."""

    training_spec: TrainWithCVSpec
    experiment_run_with_ref: ExperimentRunWithRef


class TrainingEvaluationResult(BaseModel):
    """The result of evaluating the training."""

    converged: bool


class RecursionTransition(BaseModel):
    """The transition of the recursion."""

    reasoning: Literal["max_depth", "converged"] | None
    child_workflow_run_id: str | None
