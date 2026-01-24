"""GloBI CLI."""

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
import click
import yaml

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
else:
    S3Client = object


@click.group()
def cli():
    """The GloBI CLI.

    Use this to create, manage, and submit GloBI experiments.
    """
    pass


@cli.group()
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
    help="The scenario to use for the experiment.",
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
    help="Dry run the experiment allocation by only testing semantic field combinations.",
)
@click.option(
    "--epwzip-file",
    type=click.Path(exists=True),
    help="The path to the EPWZip file to use for the experiment.",
    required=False,
)
def manifest(
    path: Path,
    scenario: str | None = None,
    skip_model_constructability_check: bool = False,
    grid_run: bool = False,
    epwzip_file: Path | None = None,
):
    """Submit a GloBI experiment from a manifest file."""
    import logging

    from globi.allocate import allocate_globi_dryrun, allocate_globi_experiment
    from globi.models import GloBIExperimentSpec

    logging.basicConfig(level=logging.INFO)

    with open(path) as f:
        manifest = yaml.safe_load(f)

    config = GloBIExperimentSpec.model_validate(manifest)

    if scenario:
        config.scenario = scenario

    if epwzip_file:
        config.file_config.epwzip_file = epwzip_file

    if grid_run:
        allocate_globi_dryrun(config)
    else:
        allocate_globi_experiment(config, not skip_model_constructability_check)


@submit.command()
def artifacts():
    """Submit a GloBI experiment from a set of artifacts."""
    print("NOT IMPLEMENTED YET")
    pass


@cli.command()
@click.option(
    "--config",
    type=click.Path(exists=True, dir_okay=False),
    help="The path to the manifest file which will be used to configure the building.",
    prompt="Manifest file path (.yml | .yaml)",
    required=True,
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False),
    required=False,
    help="The path to the directory to use for the simulation.",
    # prompt="Output directory path (optional)",
)
def simulate(config: Path, output_dir: str | None = None):
    """Simulate a GloBI building."""
    from globi.models import GloBIBuildingSpec
    from globi.pipelines import simulate_globi_building_pipeline

    with open(config) as f:
        manifest = yaml.safe_load(f)
    conf = GloBIBuildingSpec.model_validate(manifest)
    if output_dir is None:
        print("No output directory provided, results will not be saved.")
    with tempfile.TemporaryDirectory() as tempdir:
        odir = Path(output_dir or tempdir)
        odir.mkdir(parents=True, exist_ok=True)
        epodir = odir / "ep"
        epodir.mkdir(parents=True, exist_ok=True)
        rodir = odir / "results"
        rodir.mkdir(parents=True, exist_ok=True)
        r = simulate_globi_building_pipeline(conf, epodir)
        for k, v in r.dataframes.items():
            v.to_parquet(rodir / f"{k}.parquet")
            v.reset_index(drop=True).stack(
                level="Month", future_stack=True
            ).reset_index(level=0, drop=True).to_csv(rodir / f"{k}.csv")
    if not output_dir:
        # TODO: improve results summarization
        print("Results:")
        print(
            r.dataframes["Results"]
            .Energy.T.groupby(level=["Aggregation", "Meter"])
            .sum()
            .T.reset_index(drop=True)
            .T
        )


@cli.group()
def get():
    """Get a GloBI experiment from different sources."""
    pass


@get.command()
@click.option(
    "--run-name",
    type=str,
    help="The name of the run to get.",
    required=True,
    prompt="Run name",
)
@click.option(
    "--version",
    type=str,
    help="The version of the run to get.",
    required=False,
)
@click.option(
    "--dataframe-key",
    default="Results",
    type=str,
    help="The dataframe to get.",
    required=False,
)
@click.option(
    "--output-dir",
    default="outputs",
    type=click.Path(file_okay=False),
    required=False,
    help="The path to the directory to use for the simulation.",
)
def experiment(
    run_name: str,
    version: str | None = None,
    dataframe_key: str = "Results",
    output_dir: str = "outputs",
):
    """Get a GloBI experiment from a manifest file."""
    from scythe.experiments import BaseExperiment, SemVer
    from scythe.settings import ScytheStorageSettings

    from globi.pipelines import simulate_globi_building

    s3_client: S3Client = boto3.client("s3")
    s3_settings = ScytheStorageSettings()
    exp = BaseExperiment(experiment=simulate_globi_building, run_name=run_name)

    if not version:
        exp_version = exp.latest_version(s3_client, from_cache=False)
        if exp_version is None:
            msg = f"No version found for experiment {run_name}"
            raise ValueError(msg)
        sem_version = exp_version.version
    else:
        sem_version = SemVer.FromString(version)

    results_filekeys = exp.latest_results_for_version(sem_version)

    if dataframe_key not in results_filekeys:
        msg = f"Dataframe key {dataframe_key} not found in results."
        raise ValueError(msg)

    output_key = Path(output_dir) / run_name / str(sem_version) / f"{dataframe_key}.pq"

    output_key.parent.mkdir(parents=True, exist_ok=True)

    s3_client.download_file(
        Bucket=s3_settings.BUCKET,
        Key=results_filekeys[dataframe_key],
        Filename=output_key.as_posix(),
    )
    print(f"Downloaded to {output_key.as_posix()}")
