# Batch runs with Hatchet (reference)

This page is the reference for batch runs. In a batch run, Docker workers simulate many buildings in parallel, and a local Hatchet server controls them. For a guided first run on sample data, follow [section B of the tutorial](tutorial.md#b-100-buildings-baseline). Use this page when you prepare a run on your own data.

Before you start, complete the [setup guide](../getting-started/requirements.md). Check that Docker Desktop is running. Run all commands from the repository root. On Windows, use Git Bash.

## How a batch run works

1. `submit manifest` reads your manifest, prepares the GIS file and makes one spec for each building.
2. `submit manifest` stores the specs and input files in the local S3 emulator (localstack). Then it starts a Hatchet workflow.
3. The fan-out worker divides the work into one task for each building. The simulation workers run the tasks in parallel. They try each failed task again, up to 2 times.
4. The fan-out worker combines the results into one table for each output (for example, `EnergyAndPeak`).
5. `get experiment` downloads a table into `outputs/`.

All of these steps run on your computer. To run in the cloud, see the note in [section B of the tutorial](tutorial.md#b-100-buildings-baseline).

---

## Step 1: Start the stack

```bash
make hatchet-token   # once per machine
make engine
```

- `make hatchet-token` starts the Hatchet server. It writes a client token into `.env.local.hatchet` and `.env.local.host.hatchet`, so you do not copy the token. Run it again only if you delete the Hatchet Docker volume.
- `make engine` builds the worker image (several minutes the first time). Then it starts Hatchet, localstack, 4 simulation workers and 1 fan-out worker. To start more workers, run `SIMULATIONS_REPLICAS=8 make engine`.

Check that all the containers are running:

```bash
docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml ps
```

Then open the Hatchet UI at <http://localhost:8888> (`admin@example.com` / `Admin123!!`). Check that the **Workers** page shows the simulation and fan-out workers.

## Step 2: Prepare your inputs

A run needs a **manifest**. The manifest points to an **artifacts** file, and the artifacts file points to the model files. To start, copy `examples/tutorial/manifest.yml` and `artifacts.yml` to `inputs/`. Then edit the copies.

**Manifest** (`inputs/manifest.yml`):

| Key                       | Required | Meaning                                                                                                                                                                                  |
| ------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                    | yes      | Experiment name. The run name is `<name>/<scenario>`                                                                                                                                     |
| `scenario`                | yes      | Value for the `Scenario` field of each building (for example, `Baseline`). Must be one of its options in `semantic-fields.yml`; see [Retrofit scenario](tutorial.md#c-retrofit-scenario) |
| `file_config`             | yes      | Path to the artifacts file                                                                                                                                                               |
| `gis_preprocessor_config` | no       | Preprocessing settings and defaults (e.g. `tests/data/e2e/gis-preprocessor.yml`)                                                                                                         |
| `overheating_config`      | no       | Turns on overheating metrics (e.g. `tests/data/e2e/overheating-config.yml`)                                                                                                              |
| `hourly_data_config`      | no       | Turns on hourly outputs (e.g. `tests/data/e2e/hourly-data-config.yml`)                                                                                                                   |

**Artifacts** (`inputs/artifacts.yml`):

| Key                    | Meaning                                                                                                                                          |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `gis_file`             | Building footprints (GeoJSON, Shapefile, ...) with one column per semantic field; see [What a GIS file needs](tutorial.md#what-a-gis-file-needs) |
| `db_file`              | Component library                                                                                                                                |
| `semantic_fields_file` | Semantic fields definition                                                                                                                       |
| `component_map_file`   | Component map                                                                                                                                    |
| `epwzip_file`          | Weather `.zip` (local path or URL); used for buildings without their own weather column                                                          |

For the full format of each file, see [Inputs and outputs](inputs_and_outputs.md).

All paths are relative to the repository root. `make cli` runs inside Docker, and Docker can only see `inputs/`, `outputs/`, `examples/` and `tests/data/e2e/`. Thus, keep your files in `inputs/`.

## Step 3: Submit

```bash
make cli submit manifest -- --path inputs/manifest.yml
```

Keep the `--` after `manifest`. It sends the options through `make` to the CLI. If you installed the Python environment on your computer, you can also use `make cli-native ...`.

| Option                                | Meaning                                                                                                                                                                                                                       |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--path`                              | The manifest (required)                                                                                                                                                                                                       |
| `--scenario NAME`                     | Override the manifest's scenario, e.g. `--scenario Retrofit`. Must be one of the options of the `Scenario` field                                                                                                              |
| `--max-sims N`                        | Simulate only N buildings, picked at random (good for a quick test)                                                                                                                                                           |
| `--epwzip-file PATH`                  | Override the artifacts file's weather zip                                                                                                                                                                                     |
| `--skip-model-constructability-check` | Skip the check that every building can be built from the component library                                                                                                                                                    |
| `--grid-run`                          | Dry run: instead of your GIS buildings, simulate one 12 m × 12 m test building per combination of semantic field values (up to `--max-sims`). Useful to check a component library. The run name is `<name>/dryrun/<scenario>` |

The submit command stops when the work is in the queue. It shows the run name and the version. For example:

```text
versioned_experiment:
  base_experiment:
    experiment: scythe_experiment_simulate_globi_building
    run_name: GloBI_Tutorial/Baseline
  version:
    major: 1
    minor: 0
    patch: 0
```

Each submit with the same name makes a new version (`v1.0.0`, `v1.1.0`, ...).

## Step 4: Watch progress

In the Hatchet UI (<http://localhost:8888>), open **Runs**. Your submission shows as a `scythe_scatter_gather` run, with one `scythe_experiment_simulate_globi_building` task for each building. To see the logs and errors of a task, click the task.

To see the logs in the terminal, run:

```bash
docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml logs -f simulations
```

## Step 5: Download results

When the run is complete, run:

```bash
make cli-native get experiment -- --run-name GloBI_Tutorial/Baseline
```

This command downloads the **latest** version of the run to `outputs/<run name>/v<version>/`:

```
outputs/GloBI_Tutorial/Baseline/v1.0.0/
├── EnergyAndPeak.pq      # always
├── EnergyAndPeak.xlsx    # always, for EnergyAndPeak
└── EnergyAndPeak.csv     # with --include-csv
```

Other tables, for example `BasicOverheating`, are saved as `.pq` only. For what each overheating table contains, see the [overheating metrics reference](../../reference/overheating_metrics.md).

| Option                | Meaning                                                                                                                   |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `--run-name`          | `<name>/<scenario>` from the submit output (required)                                                                     |
| `--version vX.Y.Z`    | A specific version instead of the latest, e.g. `--version v1.0.0`                                                         |
| `--dataframe-key KEY` | Which table to download (default `EnergyAndPeak`); see the [list of tables](tutorial.md#d-overheating-and-hourly-outputs) |
| `--output-dir DIR`    | Where to save (default `outputs`)                                                                                         |
| `--include-csv`       | Also write a CSV                                                                                                          |

## Step 6: Shut down

```bash
make down
```

`make down` stops all containers, including the results dashboard container. It keeps the images and volumes, so you keep the stored results and the Hatchet token. The next `make engine` starts faster.

To start again with no data, run the commands below. They delete all stored runs and make the token invalid:

```bash
docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml down -v
make hatchet-token
```

---

## Environment files

`make cli-native` loads `.env.<AWS_ENV>.aws`, `.env.<HATCHET_ENV>.hatchet`, `.env.scythe.fanouts` and `.env.scythe.storage`. By default, it uses the `local.host` files, for runs on your computer. The Docker containers use the `local` files. For the contents of each file, see [Environment files](../getting-started/requirements.md#environment-files).

## Troubleshooting

The [tutorial's troubleshooting section](tutorial.md#troubleshooting) covers the usual problems: Docker not running, ports in use, missing workers, memory, file paths and results downloads. Two more problems can occur with your own data:

??? problem "Submit fails with a semantic field or column error"

    **Cause:** the GIS file has no column for a semantic field, or the column has a different name (names are case-sensitive). Or the column contains a value that is not one of the field's options.

    **Fix:** read the error. It shows the field and the unexpected values. Correct the GIS file, or add the values to `semantic-fields.yml` and add matching components.

??? problem "`module not found`, or Python version errors with `make cli-native`"

    **Cause:** the Python environment on your computer is missing or old.

    **Fix:** run `make install` again. Check that `uv run python --version` shows 3.12 or newer.

## Quick reference

```bash
make hatchet-token                                         # once per machine
make engine                                                # start the stack
make cli submit manifest -- --path inputs/manifest.yml     # submit
make cli-native get experiment -- --run-name NAME/SCENARIO # download results
make down                                                  # stop the stack
```
