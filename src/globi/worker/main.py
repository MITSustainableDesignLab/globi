"""Worker main script."""

from scythe.worker import ScytheWorkerConfig

from globi.pipelines import *  # noqa: F403

conf = ScytheWorkerConfig()


def main():
    """Main function for the worker."""
    conf.start()


if __name__ == "__main__":
    conf.start()
