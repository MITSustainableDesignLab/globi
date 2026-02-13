"""GloBI CLI."""

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, cast

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


@cli.command()
@click.option(
    "--config",
    type=click.Path(exists=True, dir_okay=False),
    help="The path to the minimal building spec file which will be used to configure the building.",
    # prompt="Config file path (.yml | .yaml)",
    # required=True,
    default=Path("inputs/building.yml"),
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False),
    required=False,
    help="The path to the directory to use for the simulation.",
    default=Path("outputs"),
    # prompt="Output directory path (optional)",
)
def simulate(
    config: Path | str = Path("inputs/building.yml"),
    output_dir: Path | None = Path("outputs"),
):
    """Simulate a GloBI building."""
    import pandas as pd

    from globi.models.tasks import MinimalBuildingSpec
    from globi.pipelines import simulate_globi_building_pipeline

    if isinstance(config, str):
        config = Path(config)

    if not config.exists():
        msg = f"Config file {config} does not exist.  Either create it or use the --config option to specify a different path."
        raise FileNotFoundError(msg)
    with open(config) as f:
        manifest = yaml.safe_load(f)
    conf = MinimalBuildingSpec.model_validate(manifest).globi_spec

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
            # TODO: add excel outputs for overheating dataframes.
            if k == "EnergyAndPeak" or k == "Results":
                v.reset_index(drop=True).stack(
                    level="Month", future_stack=True
                ).reset_index(level=0, drop=True).to_csv(rodir / f"{k}.csv")
                with pd.ExcelWriter(rodir / "EnergyAndPeak.xlsx") as writer:
                    for measurement in v.columns.unique(level="Measurement"):
                        df0 = cast(pd.DataFrame, v[measurement])
                        for aggregation in df0.columns.unique(level="Aggregation"):
                            df1 = cast(pd.DataFrame, df0[aggregation])
                            label = f"{str(measurement).replace(' ', '')}_{str(aggregation).replace(' ', '')}"
                            df1.reset_index(drop=True).stack(
                                level="Month", future_stack=True
                            ).reset_index(level=0, drop=True).to_excel(
                                writer, sheet_name=label
                            )

    # TODO: improve results summarization
    print("--------------------------------")
    print("Results Summary")
    print("--------------------------------")
    end_uses = (
        r.dataframes["EnergyAndPeak"]
        .Energy["End Uses"]
        .T.groupby(level=["Meter"])
        .sum()
        .T.reset_index(drop=True)
        .T[0]
        .rename("End Uses [kWh/m2]")
    )
    print(end_uses)
    print("--------------------------------")
    print(
        r.dataframes["EnergyAndPeak"]
        .Peak["Utilities"]
        .T.groupby(level=["Meter"])
        .sum()
        .T.reset_index(drop=True)
        .T[0]
        .rename("Peak Demand [kW/m2]")
    )
    print("--------------------------------")
    # TODO: add printouts for overheating dataframes if present.
    print("More detailed results and IDFs etc in", odir)


@cli.group()
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
    default="EnergyAndPeak",
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
@click.option(
    "--include-csv",
    is_flag=True,
    help="Include the csv file in the output.",
    required=False,
)
def experiment(
    run_name: str,
    version: str | None = None,
    dataframe_key: str = "EnergyAndPeak",
    output_dir: str = "outputs",
    include_csv: bool = False,
):
    """Get a GloBI experiment from a manifest file."""
    import pandas as pd
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

    print(f"Downloading {results_filekeys[dataframe_key]} to {output_key.as_posix()}")
    s3_client.download_file(
        Bucket=s3_settings.BUCKET,
        Key=results_filekeys[dataframe_key],
        Filename=output_key.as_posix(),
    )
    print(f"Downloaded to {output_key.as_posix()}")

    df = pd.read_parquet(output_key.as_posix())
    if include_csv:
        print("Saving to csv...")
        df.reset_index(
            [c for c in df.index.names if c != "building_id"], drop=True
        ).to_csv(output_key.with_suffix(".csv").as_posix())

    if dataframe_key == "EnergyAndPeak" or dataframe_key == "Results":
        print("Saving to excel...")
        ixframe = df.index.to_frame(index=False)
        with pd.ExcelWriter(output_key.with_suffix(".xlsx").as_posix()) as writer:
            cols_for_feature_index = [
                c
                for c in ixframe.columns
                if c == "building_id" or "feature.semantic." in c
            ]
            ixframe[cols_for_feature_index].to_excel(writer, sheet_name="Feature Index")
            for measurement in df.columns.unique(level="Measurement"):
                df0 = cast(pd.DataFrame, df[measurement])
                for aggregation in df0.columns.unique(level="Aggregation"):
                    df1 = cast(pd.DataFrame, df0[aggregation])
                    label = f"{str(measurement).replace(' ', '')}_{str(aggregation).replace(' ', '')}"
                    df1.reset_index(
                        [c for c in df1.index.names if c != "building_id"], drop=True
                    ).to_excel(writer, sheet_name=label)

        print(f"Downloaded to {output_key.with_suffix('.xlsx').as_posix()}")


if __name__ == "__main__":
    cli()
