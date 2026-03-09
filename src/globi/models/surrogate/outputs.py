"""Outputs for the surrogate model pipeline."""

from typing import Literal

from pydantic import BaseModel
from scythe.experiments import ExperimentRun
from scythe.scatter_gather import ScatterGatherResult
from scythe.utils.filesys import S3Url

from globi.models.surrogate.training import TrainWithCVSpec


class CombineResultsResult(BaseModel):
    """The result of combining the results of the simulations."""

    incoming: ScatterGatherResult
    combined: ScatterGatherResult


# TODO: This should perhaps go somewhere else since it is generally useful.
# (most likely into scythe itself)
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
    # TODO: possibly get rid of this since we have nice combined outputs already.
    metrics: dict


class RecursionTransition(BaseModel):
    """The transition of the recursion."""

    reasoning: Literal["max_depth", "converged"] | None
    child_workflow_run_id: str | None


class FinalizeResult(BaseModel):
    """The result of finalizing the training."""

    reasoning: Literal["max_depth", "converged"] | None
    data_uris: dict[str, S3Url]
    metrics_uris: dict[str, S3Url]
    experiment_ids: list[str]
