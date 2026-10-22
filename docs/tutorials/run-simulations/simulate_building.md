# Simulate a single building

`globi simulate` builds and runs one building from a small config file. It does not need Hatchet or a batch setup. Thus, it is the fastest way to test a configuration. For a guided first run, see [section A of the tutorial](tutorial.md#a-one-building).

Before you start, complete the [setup guide](../getting-started/requirements.md). To run without Docker, also [install EnergyPlus](../getting-started/install-energyplus.md). Run all commands from the repository root. On Windows, use Git Bash.

---

## Step 1: Write a building config

The config describes one rectangular building. `examples/tutorial/building.yml` is a working example. Copy it to `inputs/`, then edit the copy:

```bash
mkdir -p inputs
cp examples/tutorial/building.yml inputs/building.yml
```

```yaml
db_file: tests/data/e2e/components-lib.db
semantic_fields_file: tests/data/e2e/semantic-fields.yml
component_map_file: tests/data/e2e/component-map.yml
epwzip_file: examples/tutorial/USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023.zip
semantic_field_context:
  Region: TestRegion
  Typology: Residential
  Age_bracket: Post_2000
  Scenario: Baseline
  Income: Low
length: 20.0
width: 15.0
num_floors: 2
f2f_height: 3.5
wwr: 0.3
basement: none
attic: none
exposed_basement_frac: 0.25
```

**Required fields:**

- `db_file`: the component library (SQLite).
- `semantic_fields_file`: the semantic fields definition.
- `component_map_file`: the component map.
- `epwzip_file`: a weather file (`.zip`) from [climate.onebuilding.org](https://climate.onebuilding.org), as a local path or a URL. The `.zip` must contain the `.epw` and `.ddy` files.
- `semantic_field_context`: one value for **each** field in the semantic fields file. Use the exact field name (case-sensitive, for example `Scenario`) and one of the listed options.

**Optional fields**:

| Field                   | Meaning                                | Default | Allowed                                                                                                        |
| ----------------------- | -------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `length`                | Long edge of the footprint [m]         | 15.0    | ≥ 3                                                                                                            |
| `width`                 | Short edge of the footprint [m]        | 15.0    | ≥ 3                                                                                                            |
| `num_floors`            | Number of floors                       | 2       | ≥ 1                                                                                                            |
| `f2f_height`            | Floor-to-floor height [m]              | 3.0     | ≥ 0                                                                                                            |
| `wwr`                   | Window-to-wall ratio                   | 0.2     | 0–1                                                                                                            |
| `basement`, `attic`     | Extra space type                       | `none`  | `none`, `unoccupied_unconditioned`, `unoccupied_conditioned`, `occupied_unconditioned`, `occupied_conditioned` |
| `exposed_basement_frac` | Fraction of basement wall above ground | 0.25    | 0–1                                                                                                            |

If `length` is smaller than `width`, GloBI swaps the two values. File paths are relative to the repository root. With `make cli` (Docker), the files must be in `inputs/`, `examples/` or `tests/data/e2e/`.

## Step 2: Run it

=== "Native (EnergyPlus installed)"

    ```bash
    make cli-native simulate -- --config inputs/building.yml --output-dir outputs/my-building
    ```

    Before the first run, also run `cp .env.local.host.hatchet.example .env.local.host.hatchet`. See [Install EnergyPlus](../getting-started/install-energyplus.md#step-3-check-that-it-works).

=== "Docker"

    ```bash
    make cli simulate -- --config inputs/building.yml --output-dir outputs/my-building
    ```

    The first run builds the worker image. This takes several minutes.

Options:

- `--config`: the building config (default `inputs/building.yml`).
- `--output-dir`: the folder for the results (default `outputs`).

Keep the `--` after `simulate`. It sends the options through `make` to the CLI.

## Step 3: Read the results

The command shows the end uses (kWh/m²), the peak demand (kW/m²) and the output folder:

```
outputs/my-building/
├── ep/          # EnergyPlus files (IDF, SQL, error files)
└── results/
    ├── EnergyAndPeak.parquet
    ├── EnergyAndPeak.csv
    └── EnergyAndPeak.xlsx    # one sheet per measurement and aggregation
```

`globi simulate` does not calculate overheating or hourly outputs. To get these outputs, use a batch run with an `overheating_config` or `hourly_data_config` in the manifest. See [section D of the tutorial](tutorial.md#d-overheating-and-hourly-outputs).

---

## Troubleshooting

Click a problem to see the cause and the fix.

??? problem "`Config file ... does not exist`"

    **Cause:** the `--config` path is wrong, or you ran the command outside the repository root.

    **Fix:** use `cd` to go to the folder that contains `Makefile`. Check the path with `ls inputs/building.yml`.

??? problem "Validation error in `semantic_field_context`"

    **Cause:** a field is missing or misspelled (names are case-sensitive), or its value is not one of its options.

    **Fix:** open the `semantic_fields_file`. Check that each `Name` under `Fields` is in `semantic_field_context`, with one of its `Options`.

??? problem "`Invalid weather path` or `NotAZipError`"

    **Cause:** `epwzip_file` does not point to a `.zip` file (for example, it points to an `.epw` file), or the file does not exist.

    **Fix:** use a `.zip` that contains the `.epw` and `.ddy` files. For example, use the bundled `examples/tutorial/USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023.zip`.

??? problem "EnergyPlus fails (`EnergyPlusProcessError`)"

    **Cause:** the generated model or the EnergyPlus installation has a problem.

    **Fix:**

    1. Find the `.err` file in `ep/` in the output folder. The lines that start with `** Severe **` or `** Fatal **` identify the problem.
    2. For native runs, check the installation with [Install EnergyPlus](../getting-started/install-energyplus.md#troubleshooting).
    3. Check that each component that the building needs exists. A missing component usually causes an earlier failure, with a component-not-found message.
