## Simulate a single building

This guide shows you how to run a single building simulation using the `globi` CLI. This is useful for testing configurations or running quick simulations without the full Hatchet workflow.

It assumes you have already completed the [setup guide](../getting-started/requirements.md), including:

- cloning the `globi` repo
- installing dependencies with `uv sync --all-extras --all-groups`

---

### Before you start

- **terminal location**: run commands from the repository root (the folder containing `Makefile` and `pyproject.toml`).
- **input files**: all input files (component database, semantic fields, component map, weather file) must be accessible and referenced correctly in your building configuration file.

!!! note

    the commands in this guide are the same for macOS, linux, and windows (using a unix‑like shell such as git bash or wsl).

---

### Step 1: Create a building configuration file

Create a YAML file that defines your building specification. The file must follow the `MinimalBuildingSpec` structure.

**Required fields**:

- `db_file`: path to the component database file (SQLite)
- `semantic_fields_file`: path to the semantic fields configuration file
- `component_map_file`: path to the component map configuration file
- `epwzip_file`: path or URL to the EPW weather file
- `semantic_field_context`: dictionary mapping semantic field names to their values

**Optional fields** (with defaults):

- `length`: length of the long edge of the building [m] (default: 15.0, minimum: 3.0)
- `width`: length of the short edge of the building [m] (default: 15.0, minimum: 3.0)
- `num_floors`: number of floors (default: 2, minimum: 1)
- `f2f_height`: floor-to-floor height [m] (default: 3.0, minimum: 0)
- `wwr`: window-to-wall ratio (default: 0.2, range: 0.0-1.0)
- `basement`: basement type (default: "none"). valid values: `"none"`, `"unoccupied_unconditioned"`, `"unoccupied_conditioned"`, `"occupied_unconditioned"`, `"occupied_conditioned"`
- `attic`: attic type (default: "none"). valid values: `"none"`, `"unoccupied_unconditioned"`, `"unoccupied_conditioned"`, `"occupied_unconditioned"`, `"occupied_conditioned"`
- `exposed_basement_frac`: fraction of basement exposed to air (default: 0.25, range: 0.0-1.0)

!!! note

    if `length` is less than `width`, they will be automatically swapped so that `length` is always the longer dimension.

**Example building configuration** (`inputs/building.yml`):

```yaml
db_file: inputs/components-lib.db
semantic_fields_file: inputs/semantic-fields.yml
component_map_file: inputs/component-map.yml
epwzip_file: https://climate.onebuilding.org/WMO_Region_4_USA/USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw
semantic_field_context:
  Region: TestRegion
  Typology: Office
  Age_bracket: Post_2000
  scenario: Baseline
length: 20.0
width: 15.0
num_floors: 3
f2f_height: 3.5
wwr: 0.3
basement: none
attic: none
exposed_basement_frac: 0.25
```

!!! warning

    all file paths in your building configuration should be relative to the repository root, or use absolute paths. ensure all referenced files (database, semantic fields, component map) exist and are accessible.

---

### Step 2: Run the simulation

Use the `make cli simulate` command to run a single building simulation:

```bash
make cli simulate -- --config inputs/building.yml --output-dir outputs
```

**Command options**:

- `--config {PATH}`: path to your building configuration YAML file (default: `inputs/building.yml`)
- `--output-dir {PATH}`: directory where simulation results will be saved (default: `outputs`)

If you use the default paths, you can simply run:

```bash
make cli simulate
```

!!! warning

    **critical**: you must include the two dashes `--` after `simulate` and before any options. this separator is required to pass arguments correctly to the underlying CLI command. if you forget it, the command will fail with an error.

---

### Step 3: Review the results

After the simulation completes, the CLI prints a summary of key results:

```text
--------------------------------
Results Summary
--------------------------------
End Uses [kWh/m2]
...
--------------------------------
Peak Demand [kW/m2]
...
--------------------------------
More detailed results and IDFs etc in outputs
```

**Output directory structure**:

```
outputs/
├── ep/              # EnergyPlus input/output files (IDF, EPW, etc.)
└── results/         # Processed simulation results
    ├── EnergyAndPeak.parquet
    ├── EnergyAndPeak.csv
    ├── EnergyAndPeak.xlsx
    └── ...          # Other result dataframes
```

**Result files**:

- **Parquet files**: efficient binary format for data analysis
- **CSV files**: human-readable tabular data
- **Excel files**: multi-sheet workbooks with organized results (only for `EnergyAndPeak` dataframe)

---

## Troubleshooting

### File not found errors

- **config file does not exist**

  - verify the path to your building configuration file is correct
  - ensure the file exists at the specified location
  - check that you're running the command from the repository root

- **referenced files not found**

  - verify all file paths in your building configuration are correct
  - ensure `db_file`, `semantic_fields_file`, `component_map_file`, and `epwzip_file` exist
  - check that paths are relative to the repository root or use absolute paths

### Validation errors

- **invalid semantic field context**

  - ensure all keys in `semantic_field_context` match field names defined in your `semantic_fields_file`
  - verify that values match the allowed options for each field

- **invalid building dimensions**

  - `length` and `width` must be at least 3.0 meters
  - `num_floors` must be at least 1
  - `wwr` must be between 0.0 and 1.0
  - `exposed_basement_frac` must be between 0.0 and 1.0

### Simulation errors

- **energyplus simulation failed**

  - check the `ep/` directory in your output folder for EnergyPlus error files
  - verify the weather file (`epwzip_file`) is valid and accessible
  - ensure the component database contains valid construction data

---

## Quick reference

### Essential commands

```bash
# run simulation with default paths (inputs/building.yml -> outputs/)
make cli simulate

# run simulation with custom config and output directory
make cli simulate -- --config inputs/my_building.yml --output-dir outputs/my_results

# run simulation with only custom output directory
make cli simulate -- --output-dir outputs/custom
```

### Building configuration file structure

```yaml
# required fields
db_file: path/to/components.db
semantic_fields_file: path/to/semantic-fields.yml
component_map_file: path/to/component-map.yml
epwzip_file: path/to/weather.epw # or URL
semantic_field_context:
  FieldName1: value1
  FieldName2: value2

# optional fields (with defaults)
length: 20.0 # default: 15.0
width: 15.0 # default: 15.0
num_floors: 3 # default: 2
f2f_height: 3.5 # default: 3.0
wwr: 0.3 # default: 0.2
basement: none # default: "none" (options: "none", "unoccupied_unconditioned", "unoccupied_conditioned", "occupied_unconditioned", "occupied_conditioned")
attic: none # default: "none" (options: "none", "unoccupied_unconditioned", "unoccupied_conditioned", "occupied_unconditioned", "occupied_conditioned")
exposed_basement_frac: 0.25 # default: 0.25
```

### Key file locations

- building configuration: `inputs/building.yml` (default)
- output directory: `outputs/` (default)
- component database: typically `inputs/components-lib.db` or `tests/data/components-lib.db`
- semantic fields: typically `inputs/semantic-fields.yml` or `tests/data/semantic-fields.yml`
- component map: typically `inputs/component-map.yml` or `tests/data/component-map.yml`
