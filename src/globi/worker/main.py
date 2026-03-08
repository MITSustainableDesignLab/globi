"""Worker main script."""

from scythe.hatchet import hatchet
from scythe.registry import ExperimentRegistry
from scythe.scatter_gather import scatter_gather
from scythe.worker import ScytheWorkerConfig

from globi.pipelines import *  # noqa: F403
from globi.pipelines import iterative_training

conf = ScytheWorkerConfig()


def main():
    """Main function for the worker."""
    # TODO: this is required since scythe does not allow registering extra tasks/workflows at the moment.
    worker = hatchet.worker(
        name=conf.computed_name,
        slots=conf.computed_slots,
        durable_slots=conf.computed_durable_slots,
        labels=conf.labels,
    )
    workflows = ([scatter_gather] if conf.DOES_FAN else []) + (
        ExperimentRegistry.experiments() if conf.DOES_LEAF else []
    )
    for workflow in workflows:
        worker.register_workflow(workflow)
    if conf.DOES_FAN:
        worker.register_workflow(iterative_training)
    worker.start()

    # conf.start()


if __name__ == "__main__":
    main()
