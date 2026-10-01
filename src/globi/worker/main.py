"""Worker main script."""

import logging

from scythe.worker import ScytheWorkerConfig

from globi.pipelines import *  # noqa: F403
from globi.pipelines import iterative_training

conf = ScytheWorkerConfig()


def main():
    """Start the worker."""
    logging.basicConfig(level=logging.INFO)
    # only orchestrator (fan) workers should pick up iterative_training steps; leaf
    # workers would otherwise hold a slot while e.g. await_simulations waits.
    conf.start(additional_workflows=[iterative_training] if conf.DOES_FAN else [])


if __name__ == "__main__":
    main()
