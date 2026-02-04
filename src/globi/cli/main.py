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
    "--max-tests",
    type=int,
    default=1000,
    help="Override the maximum number of tests in a grid run.",
    required=False,
)
def manifest(
    path: Path,
    scenario: str | None = None,
    skip_model_constructability_check: bool = False,
    grid_run: bool = False,
    epwzip_file: Path | None = None,
    max_tests: int = 1000,
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
        allocate_globi_dryrun(config, max_tests=max_tests)
    else:
        allocate_globi_experiment(config, not skip_model_constructability_check)


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
    config: Path = Path("inputs/building.yml"),
    output_dir: Path | None = Path("outputs"),
):
    """Simulate a GloBI building."""
    import pandas as pd

    from globi.models.tasks import MinimalBuildingSpec
    from globi.pipelines import simulate_globi_building_pipeline

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
            v.reset_index(drop=True).stack(
                level="Month", future_stack=True
            ).reset_index(level=0, drop=True).to_csv(rodir / f"{k}.csv")
            if k == "Results":
                with pd.ExcelWriter(rodir / "Results.xlsx") as writer:
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
        r.dataframes["Results"]
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
        r.dataframes["Results"]
        .Peak["Utilities"]
        .T.groupby(level=["Meter"])
        .sum()
        .T.reset_index(drop=True)
        .T[0]
        .rename("Peak Demand [kW/m2]")
    )
    print("--------------------------------")
    print("More detailed results and IDFs etc in", odir)


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
@click.option(
    "--include-csv",
    is_flag=True,
    help="Include the csv file in the output.",
    required=False,
)
def experiment(
    run_name: str,
    version: str | None = None,
    dataframe_key: str = "Results",
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

    if dataframe_key == "Results":
        print("Saving to excel...")
        with pd.ExcelWriter(output_key.with_suffix(".xlsx").as_posix()) as writer:
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
