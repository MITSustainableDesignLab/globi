"""Test commands for the GloBI CLI."""

from pathlib import Path

import click
import yaml


@click.group()
def tests():
    """Test commands for CI and development."""
    pass


@tests.command()
@click.option(
    "--manifest",
    type=click.Path(exists=True),
    default="tests/data/e2e/manifest.yml",
    help="Path to the manifest YAML file.",
)
@click.option(
    "--max-sims",
    type=int,
    default=2,
    help="Maximum number of simulations to run.",
)
@click.option(
    "--poll-interval",
    type=int,
    default=10,
    help="Seconds between status polls.",
)
@click.option(
    "--poll-timeout",
    type=int,
    default=300,
    help="Maximum seconds to wait for completion.",
)
def e2e(
    manifest: str,
    max_sims: int = 2,
    poll_interval: int = 10,
    poll_timeout: int = 300,
):
    """Run E2E experiment: allocate and poll for completion.

    Intended for CI; run with: make cli-native test e2e
    """
    import logging
    import sys
    import time

    from hatchet_sdk.clients.rest.models.v1_task_status import V1TaskStatus
    from scythe.hatchet import hatchet

    from globi.allocate import allocate_globi_experiment
    from globi.models.configs import GloBIExperimentSpec

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    manifest_path = Path(manifest)
    with open(manifest_path) as f:
        manifest_data = yaml.safe_load(f)
    config = GloBIExperimentSpec.model_validate(manifest_data)

    logger.info("Allocating experiment from %s (max_sims=%d)", manifest, max_sims)
    run, ref = allocate_globi_experiment(
        config,
        check_model_constructability=False,
        max_sims=max_sims,
    )
    workflow_run_id = ref.workflow_run_id
    logger.info("Experiment allocated, workflow_run_id=%s", workflow_run_id)

    deadline = time.monotonic() + poll_timeout
    while time.monotonic() < deadline:
        status = hatchet.runs.get_status(workflow_run_id)
        logger.info("Status: %s", status)

        if status == V1TaskStatus.COMPLETED:
            logger.info("Experiment completed successfully")
            run_name = run.versioned_experiment.base_experiment.run_name
            print(f"RUN_NAME={run_name}")
            sys.exit(0)
        if status in (V1TaskStatus.FAILED, V1TaskStatus.CANCELLED):
            logger.error("Experiment %s", status.value)
            sys.exit(1)

        time.sleep(poll_interval)

    logger.error("Experiment did not complete within %d seconds", poll_timeout)
    sys.exit(1)
