"""Submit commands for the GloBI CLI."""

from pathlib import Path

import click
import yaml


@click.group()
def submit():
    """Submit a GloBI experiment from different sources."""
    pass


@submit.command()
@click.option(
    "--path",
    type=click.Path(exists=True),
    help="The path to the manifest file which will be used to configure the experiment.",
    prompt="Manifest file path (.yml)",
)
@click.option(
    "--scenario",
    type=str,
    help="Override the scenario listed in the manifest file with the provided scenario.",
    required=False,
)
@click.option(
    "--skip-model-constructability-check",
    is_flag=True,
    help="Skip the model constructability check.",
    required=False,
)
@click.option(
    "--grid-run",
    is_flag=True,
    help="Dry run the experiment allocation by only simulating semantic field combinations.",
)
@click.option(
    "--epwzip-file",
    type=click.Path(exists=True),
    help="Override the EPWZip file listed in the manifest file with the provided EPWZip file.",
    required=False,
)
@click.option(
    "--max-sims",
    type=int,
    help="Override the maximum number of simulations to run.",
    required=False,
)
def manifest(
    path: Path,
    scenario: str | None = None,
    skip_model_constructability_check: bool = False,
    grid_run: bool = False,
    epwzip_file: Path | None = None,
    max_sims: int | None = None,
):
    """Submit a GloBI experiment from a manifest file."""
    import logging

    from globi.allocate import allocate_globi_dryrun, allocate_globi_experiment
    from globi.models.configs import GloBIExperimentSpec

    logging.basicConfig(level=logging.INFO)

    with open(path) as f:
        manifest = yaml.safe_load(f)

    config = GloBIExperimentSpec.model_validate(manifest)

    if scenario:
        config.scenario = scenario

    if epwzip_file:
        config.file_config.epwzip_file = epwzip_file

    if grid_run:
        allocate_globi_dryrun(config, max_tests=max_sims)
    else:
        allocate_globi_experiment(
            config,
            check_model_constructability=not skip_model_constructability_check,
            max_sims=max_sims,
        )
