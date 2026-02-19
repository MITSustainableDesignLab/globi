"""Simulate command for the GloBI CLI."""

import tempfile
from pathlib import Path
from typing import cast

import click
import pandas as pd
import yaml


@click.command()
@click.option(
    "--config",
    type=click.Path(exists=True, dir_okay=False),
    help="The path to the minimal building spec file which will be used to configure the building.",
    default=Path("inputs/building.yml"),
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False),
    required=False,
    help="The path to the directory to use for the simulation.",
    default=Path("outputs"),
)
def simulate(
    config: Path | str = Path("inputs/building.yml"),
    output_dir: Path | None = Path("outputs"),
):
    """Simulate a GloBI building."""
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
    print("More detailed results and IDFs etc in", odir)
