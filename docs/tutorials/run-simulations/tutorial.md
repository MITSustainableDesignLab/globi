# Tutorial: run GloBI on sample buildings

This tutorial shows the main ways to run GloBI. First you run one building. Then you run batches on a fixed sample of **100 buildings**. Each section is independent, so you can go directly to the section you need.

## Which steps do you need?

Find your goal in the table. Do only the setup that the table lists, then go to the sections for your goal.

| Your goal                        | [Setup guide](../getting-started/requirements.md) | Also install                                                                   | Then do                                                                                                                                |
| -------------------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| Run one building, without Docker | Steps 2–5 (skip Docker)                           | [EnergyPlus](../getting-started/install-energyplus.md)                         | [A](#a-one-building), **Native** tab                                                                                                   |
| Run one building, with Docker    | Steps 1–5                                         | –                                                                              | [A](#a-one-building), **Docker** tab                                                                                                   |
| Run batches of buildings         | Steps 1–5                                         | –                                                                              | [B](#b-100-buildings-baseline), then any of [C](#c-retrofit-scenario), [D](#d-overheating-and-hourly-outputs), [E](#e-explore-results) |
| Change the model and rerun       | Steps 1–5                                         | Node.js and sbem-ui (see [that tutorial](edit-components.md#before-you-start)) | A or B first, then [edit the model](edit-components.md)                                                                                |

Batch runs always need Docker, also when EnergyPlus is installed on your computer. The workers run in Docker containers.

## What's on this page

| Section                                                                | What you run                          | Needs                           |
| ---------------------------------------------------------------------- | ------------------------------------- | ------------------------------- |
| [A. One building](#a-one-building)                                     | `globi simulate`                      | Native EnergyPlus **or** Docker |
| [B. 100 buildings](#b-100-buildings-baseline)                          | Batch run on the local stack          | Docker                          |
| [C. Retrofit scenario](#c-retrofit-scenario)                           | Same buildings, `Retrofit` components | Docker                          |
| [D. Overheating and hourly outputs](#d-overheating-and-hourly-outputs) | Extra result tables                   | Docker                          |
| [E. Explore results](#e-explore-results)                               | Results dashboard                     | Python (or Docker)              |

Run all commands from the repository root.

!!! note "Windows: use Git Bash"

    Run all commands on this page in **Git Bash**. Do not use PowerShell or Command Prompt. The `make` targets call `bash` scripts, and commands such as `cp` and `mkdir -p` are only available in Git Bash. The commands are the same on macOS, Linux and Windows, unless a tab shows a difference. If `make` is not found, see [Troubleshooting make on Windows](../getting-started/requirements.md#troubleshooting-make-on-windows).

## The sample inputs

All sample inputs are in `examples/tutorial/`:

| File                                       | What it is                                                                                          |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `buildings-100.geojson`                    | 100 footprints with semantic attributes (48 residential, 31 office, 10 school, 6 hotel, 5 hospital) |
| `artifacts.yml`                            | Points to the GIS file, component library, semantic fields, component map and weather file          |
| `manifest.yml`                             | The 100-building experiment (`GloBI_Tutorial`, scenario `Baseline`)                                 |
| `manifest-overheating.yml`                 | Same buildings, with overheating metrics and hourly outputs turned on                               |
| `building.yml`                             | One building, for `globi simulate`                                                                  |
| `USA_MA_Boston-Logan...TMYx.2009-2023.zip` | Weather file (Boston TMYx), used by all the configs above                                           |
| `sbem-project/`                            | Template for [editing the model in sbem-ui](edit-components.md)                                     |

The buildings are in a synthetic test region and use Boston weather. The component library, semantic fields and component map are the same files as the test data in `tests/data/e2e/`.

### What a GIS file needs

| Item                     | Requirement                                                                                                                                        | In the tutorial                                            |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Geometry                 | Polygons, in WGS84 or the `cart_crs` of the preprocessor config                                                                                    | WGS84 polygons                                             |
| Semantic fields          | One column for each field in `semantic-fields.yml`, with values from its `Options`                                                                 | `Region`, `Typology`, `Age_bracket`, `Income`, `Scenario`  |
| Building ID              | The column that `Building_ID_col` names                                                                                                            | `id`                                                       |
| Height or floors         | At least one: the columns that `Height_col` and `Num_Floors_col` name                                                                              | `height`, `num_storeys`                                    |
| Other columns (optional) | Columns that `WWR_col`, `Basement_col`, `Attic_col`, `Exposed_Basement_Frac_col` name. Missing values use the defaults in the preprocessor config. | None (defaults from `tests/data/e2e/gis-preprocessor.yml`) |
| Weather file             | First match: the `Weather_File_col` column, then `epwzip_file` in `artifacts.yml`, then the closest TMYx file                                      | `epwzip_file` (the bundled zip)                            |

For all keys of `semantic-fields.yml` and the preprocessor config, see [Inputs and outputs](inputs_and_outputs.md).

---

## A. One building

This section simulates the building in `examples/tutorial/building.yml`. To compare results, change `Typology`, `Scenario`, `num_floors` or other values, and run the command again.

=== "Native (EnergyPlus installed)"

    ```bash
    cp .env.local.host.hatchet.example .env.local.host.hatchet   # first time only
    make cli-native simulate -- --config examples/tutorial/building.yml --output-dir outputs/tutorial
    ```

=== "Docker"

    ```bash
    make cli simulate -- --config examples/tutorial/building.yml --output-dir outputs/tutorial
    ```

    The first run builds the worker image. This takes several minutes.

The command prints the end uses and the peak demand per m². The outputs are:

```
outputs/tutorial/
├── ep/        # EnergyPlus files (IDF, SQL, error files)
└── results/
    ├── EnergyAndPeak.parquet
    ├── EnergyAndPeak.csv
    └── EnergyAndPeak.xlsx
```

!!! note

    For overheating and hourly outputs, use section D. `globi simulate` ignores the overheating and hourly settings.

---

## B. 100 buildings (Baseline)

A batch run uses a Hatchet server and workers that run in Docker on your computer. The workers exchange files through a local S3 emulator (localstack, at `localhost:4566`). `get experiment` copies the results into `outputs/`. The [batch runs reference](simulation_tasking.md) explains each step in detail.

!!! note "Local by default, cloud if you set it up"

    This tutorial runs everything on your computer. You do not need an AWS account, and GloBI uploads nothing. The local env files send all S3 calls to localstack with dummy credentials. Check that `.env` contains `AWS_ENV=local` and `HATCHET_ENV=local` (the defaults from `.env.example`). Localstack keeps the results between restarts, until you delete its Docker volume.

    You can also run the same workflow in the cloud, but you must set it up yourself. You need an AWS account with an S3 bucket, a Hatchet instance, and workers that run the GloBI image. For the deployment that the lab uses, see `infra/`. External users cannot use the lab's bucket and workers. When you have these, do the steps that follow:

    1. Add `.env.<name>.aws` and `.env.<name>.hatchet` files with your credentials.
    2. Set `AWS_ENV=<name>` and `HATCHET_ENV=<name>` in `.env`.
    3. Put your bucket name in `.env.scythe.storage`.

1. **Start the stack** (the first run takes several minutes):

   ```bash
   make hatchet-token   # once per machine: starts Hatchet and writes a token into .env.local.hatchet and .env.local.host.hatchet
   make engine          # starts localstack, 4 simulation workers and 1 fan-out worker
   ```

   Run `make hatchet-token` first, because `make engine` does not create the token. Run `make hatchet-token` again only if you delete the Hatchet Docker volume (e.g. `docker compose down -v`).

   To monitor progress, open the Hatchet UI at <http://localhost:8888> (`admin@example.com` / `Admin123!!`).

2. **Submit the experiment**:

   ```bash
   make cli submit manifest -- --path examples/tutorial/manifest.yml
   ```

   To try the run on a few buildings first, add `--max-sims 5`. GloBI then selects 5 buildings at random.

   The submit command does these steps:

   - It preprocesses the GIS file and makes one spec for each building.
   - It stores the specs in the local S3 emulator and starts a Hatchet scatter-gather workflow.
   - The fan-out worker splits the specs into one task for each building.
   - The simulation workers run the tasks in parallel. Each task is retried up to 2 times.
   - The fan-out worker combines the results into one table.

   In the Hatchet UI, you can see how the tasks spread across the workers.

   To run more buildings at the same time, start more simulation workers: `SIMULATIONS_REPLICAS=8 make engine`.

3. **Download the results** when the run is complete (a few minutes with 4 workers):

   ```bash
   make cli-native get experiment -- --run-name GloBI_Tutorial/Baseline
   ```

   This command writes `outputs/GloBI_Tutorial/Baseline/v<version>/EnergyAndPeak.pq` and `.xlsx`.

   Each submit with the same name creates a new version. `get experiment` downloads the **latest** version. Thus, if you submit a `--max-sims 5` test run later, that run replaces the 100-building run as "latest". To get a specific version, add `--version v1.0.0`. To also get a CSV file, add `--include-csv`.

---

## C. Retrofit scenario

Run the same 100 buildings with the `Retrofit` scenario:

```bash
make cli submit manifest -- --path examples/tutorial/manifest.yml --scenario Retrofit
make cli-native get experiment -- --run-name GloBI_Tutorial/Retrofit
```

The results go into `outputs/GloBI_Tutorial/Retrofit/`, next to the Baseline results. You can compare the two scenarios in section E.

`--scenario Retrofit` works because the model defines the scenario in advance:

1. `Scenario` is a semantic field. Its options in `semantic-fields.yml` are `Baseline` and `Retrofit`.
2. The component map uses `Scenario` to select the `Envelope`, `SpaceUse` and `HVAC` components.
3. The component library has a record for each scenario, for example `TestRegion_Residential_Low_Baseline` and `TestRegion_Residential_Low_Retrofit`.

`--scenario` only sets the value of the `Scenario` field for every building. The value must be one of the options of that field. Other values fail at submit with an error like `Field 'Scenario' has values which are not in the allowed options`.

To add a scenario (for example `DeepRetrofit`), add it as an option of `Scenario` and create its components. See [Tutorial: edit the model in sbem-ui](edit-components.md), steps 5–7.

---

## D. Overheating and hourly outputs

`manifest-overheating.yml` adds two settings to the baseline manifest:

```yaml
hourly_data_config: tests/data/e2e/hourly-data-config.yml # hourly zone temperature and humidity
overheating_config: tests/data/e2e/overheating-config.yml # thresholds for overheating metrics
```

```bash
make cli submit manifest -- --path examples/tutorial/manifest-overheating.yml
make cli-native get experiment -- --run-name GloBI_Tutorial_Overheating/Baseline
make cli-native get experiment -- --run-name GloBI_Tutorial_Overheating/Baseline --dataframe-key BasicOverheating
```

This run gives the extra result tables that follow. To download a table, use its name as `--dataframe-key`.

| Key                                                                       | Contents                                                         |
| ------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `BasicOverheating`                                                        | Summary heat and cold exceedance metrics per building and zone   |
| `ExceedanceDegreeHours`                                                   | Exceedance degree-hours for each threshold                       |
| `HeatIndexCategories`                                                     | Time spent in each heat-index category                           |
| `ConsecutiveExceedances`                                                  | Streaks of consecutive exceedance (only present if any occurred) |
| `HourlyData.ZoneMeanAirTemperature`, `HourlyData.ZoneAirRelativeHumidity` | Hourly series per building                                       |

To change the thresholds, edit `tests/data/e2e/overheating-config.yml`. You can also copy the file and point the manifest to your copy.

For the formulas and thresholds behind each table, see the [overheating metrics reference](../../reference/overheating_metrics.md).

---

## E. Explore results

Start the results dashboard:

```bash
make viz-native     # or: make viz (Docker)
```

Open <http://localhost:8501> and keep **Simulation store** as the source. When the stack runs, the dashboard lists all runs in the stack, so you do not need `get experiment` first. Runs that you downloaded into `outputs/` are also under **Folder on this computer**. Then:

- **Explore a run**: Select `Baseline (v1.0.0) · GloBI_Tutorial` to see EUI, peak, end uses, the 3D map and a table of buildings.
- **Compare scenarios**: Select the `Baseline` and `Retrofit` runs to see the savings. To see the payback, turn on costs and emissions.
- **Overheating**: Select the `GloBI_Tutorial_Overheating` run.

[Using the results dashboard](../results-dashboard/using-the-dashboard.md) shows each page with screenshots.

---

## Next: edit the model

You can change the semantic fields, the component map and the components (constructions, lighting, setpoints, ...) of these buildings, and then run them again. See [Tutorial: edit the model in sbem-ui](edit-components.md).

---

## Clean up

```bash
make down
```

## Troubleshooting

Click a problem to see the cause and the fix. For Windows `make` problems, see [Troubleshooting make on Windows](../getting-started/requirements.md#troubleshooting-make-on-windows). For native EnergyPlus problems, see [Install EnergyPlus](../getting-started/install-energyplus.md#troubleshooting).

### Starting the stack

??? problem "`Cannot connect to the Docker daemon` or `docker: command not found`"

    **Cause:** Docker Desktop is not running, or you opened the terminal before you installed Docker.

    **Fix:**

    1. Start Docker Desktop. Wait until it shows **Engine running**.
    2. Open a new terminal and run `docker info`.

??? problem "`Bind for 0.0.0.0:8888 failed: port is already allocated` (or 7077, 4566, 8501)"

    **Cause:** another program or an old container uses that port.

    **Fix:**

    1. Find the container: `docker ps --format '{{.Names}} {{.Ports}}'`.
    2. Stop the old GloBI stack with `make down`, or stop the other container with `docker stop <name>`.
    3. If no container uses the port, find the program and close it. Use `lsof -i :8888` on macOS/Linux, or `netstat -ano | grep 8888` in Git Bash.

??? problem "`make engine` fails with `image ... already exists`"

    **Cause:** Docker builds the same image for several services at the same time, and the builds conflict. This occurs on macOS.

    **Fix:** run `make engine` again.

??? problem "Workers do not appear in the Hatchet UI, or tasks stay queued"

    **Cause:** usually, the workers started with a missing or old Hatchet token. For example, you ran `make engine` before `make hatchet-token`, or Docker created the Hatchet volume again.

    **Fix:**

    1. Look at the worker logs: `docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml logs simulations | tail -20`.
    2. Create a new token and restart the stack:

        ```bash
        make hatchet-token
        make down
        make engine
        ```

    3. Reload the **Workers** page in the Hatchet UI. The page must show the simulation and fan-out workers.

??? problem "Workers stop with exit code 137, or the computer becomes very slow"

    **Cause:** Docker does not have sufficient memory.

    **Fix:** give Docker more memory (Docker Desktop → **Settings → Resources**, 8 GB or more), or start fewer workers: `SIMULATIONS_REPLICAS=2 make engine`.

### Submitting a run

??? problem "`Config file ... does not exist` or `No such file or directory` with `make cli`"

    **Cause:** `make cli` runs inside Docker. The container only sees `inputs/`, `outputs/`, `examples/` and `tests/data/e2e/`. Files in other folders, and absolute paths on your computer, do not exist inside the container.

    **Fix:** move your files into `inputs/`. Use paths relative to the repository root, e.g. `--path inputs/my-manifest.yml`. Paths *inside* your manifest and artifacts files must also obey this rule.

??? problem "Semantic field error: a value is not one of the allowed options"

    **Cause:** a cell in the GIS file (e.g. `Typology = Warehouse`) is not an option of that field in `semantic-fields.yml`, or a required column is missing.

    **Fix:**

    1. Read the error. It names the field, the incorrect values and the allowed options.
    2. Correct the GIS file. Alternatively, add the value to the field's `Options` in `semantic-fields.yml` **and** add matching components (see the next item).
    3. Check that the column names are exactly the same as the field names, including case (`Scenario`, not `scenario`).

??? problem "Model constructability check fails"

    **Cause:** before GloBI submits a run, it checks that each combination of semantic field values maps to components in `components-lib.db`. If a combination has no component, all buildings with that combination fail.

    **Fix:** add the missing components to the component library, or remove the unused option from `semantic-fields.yml`. `--skip-model-constructability-check` only skips the check. The buildings with missing components still fail.

??? problem "Weather file errors (`Invalid weather path`, `NotAZipError`, download fails)"

    **Cause:** the `epwzip_file` in your config is not a `.zip`, does not exist, or is a URL that GloBI cannot reach. The tutorial configs use the bundled `examples/tutorial/USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023.zip`, so they do not download a file.

    **Fix:** for your own runs, do these steps:

    1. Download the `.zip` for your location from [climate.onebuilding.org](https://climate.onebuilding.org).
    2. Save the file in `inputs/`.
    3. Set `epwzip_file: inputs/<file>.zip` in `artifacts.yml` (or `building.yml`).

    The zip must contain the `.epw` and `.ddy` files.

### Getting results

??? problem "`Dataframe key EnergyAndPeak not found in results`"

    **Cause:** the run is not complete yet, or you asked for a table that this run does not make (e.g. `BasicOverheating` on a baseline run).

    **Fix:**

    1. Open the Hatchet UI (<http://localhost:8888>) → **Runs**. Wait until the `scythe_scatter_gather` run is complete. With 4 workers, 100 buildings take a few minutes.
    2. Run `get experiment` again.
    3. If the run is complete, compare the key with the table in [section D](#d-overheating-and-hourly-outputs).

??? problem "`Version must start with 'v'`"

    **Cause:** version names start with `v`.

    **Fix:** use `--version v1.2.0`, not `--version 1.2.0`. The submit command prints the version (`major`, `minor`, `patch`). The version is also part of the output folder name.

??? problem "The results only have 5 buildings, not 100"

    **Cause:** `get experiment` downloads the latest version, and a later `--max-sims 5` test run is now the latest version.

    **Fix:** download the 100-building run by its version, e.g. `--version v1.0.0`. Each version has its own folder in `outputs/GloBI_Tutorial/Baseline/`.

??? problem "Code or config changes have no effect on `make cli` or the workers"

    **Cause:** the Docker image contains a copy of the code from the time of the build.

    **Fix:** rebuild and restart with `make engine`. Docker mounts the input files in `inputs/` and `examples/`, so changes to these files apply without a rebuild.

### Dashboard

??? problem "No runs listed"

    **Cause:** with **Simulation store**, the stack is not running. With **Folder on this computer**, the folder does not contain run folders.

    **Fix:** start the stack with `make engine`, then click **Refresh** in the sidebar. For a folder, run `get experiment` first, and check that the folder is `outputs`.

??? problem "The map is empty or in the wrong place"

    **Cause:** the building footprints use the projection that `cart_crs` sets in the run config. The result files do not record this projection, so the dashboard guesses it from the footprints.

    **Fix:** in the sidebar, open **Settings** and pick the run's `cart_crs` under **Map coordinate system** (use **Other…** to type any EPSG code).

??? problem "Overheating: `No runs with overheating results`"

    **Cause:** the run has no `BasicOverheating` table. With **Folder on this computer**, `get experiment` only downloads `EnergyAndPeak` by default.

    **Fix:** use **Simulation store**, which gets the table automatically. Alternatively, run `make cli-native get experiment -- --run-name GloBI_Tutorial_Overheating/Baseline --dataframe-key BasicOverheating` and reload the page.

See [Using the results dashboard](../results-dashboard/using-the-dashboard.md#troubleshooting) for more information.
