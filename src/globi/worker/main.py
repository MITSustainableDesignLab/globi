"""Worker main script."""

from scythe.worker import ScytheWorkerConfig

from globi.pipelines import *  # noqa: F403
from globi.pipelines import iterative_training

conf = ScytheWorkerConfig()


def main():
    """Start the worker."""
    conf.start(additional_workflows=[iterative_training])


if __name__ == "__main__":
    main()
