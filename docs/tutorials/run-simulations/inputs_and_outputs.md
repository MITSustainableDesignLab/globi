## Simulation inputs and outputs

This page is the reference for the input files that GloBI reads and the output files that it writes. For a guided run with working example files, see the [sample-buildings tutorial](tutorial.md).

---

### Input files overview

The files that you need depend on the type of run. The tutorial versions of all files are in `examples/tutorial/` and `tests/data/e2e/`.

| File                     | Single building | Batch run | Contents                                            |
| ------------------------ | :-------------: | :-------: | --------------------------------------------------- |
| `building.yml`           |    required     |    --     | One building and its semantic field values          |
| `manifest.yml`           |       --        | required  | The experiment and its configs                      |
| `artifacts.yml`          |       --        | required  | Paths to the GIS file, model files and weather file |
| `semantic-fields.yml`    |    required     | required  | Semantic fields and the names of GIS columns        |
| `component-map.yml`      |    required     | required  | Rules that select components from semantic fields   |
| `components-lib.db`      |    required     | required  | The component library (SQLite)                      |
| GIS file                 |       --        | required  | Building footprints and their attributes            |
| `gis-preprocessor.yml`   |       --        | optional  | Geometry checks and default values                  |
| `hourly-data-config.yml` |       --        | optional  | Hourly output variables                             |
| `overheating-config.yml` |       --        | optional  | Overheating thresholds                              |
| Weather file             |    required     | required  | A `.zip` with the `.epw` and `.ddy` files           |

---

### Input file details

#### `building.yml` -- single building specification

`globi simulate` reads this file. For all fields, defaults and an example, see [Simulate a single building](simulate_building.md#step-1-write-a-building-config).

---

#### `manifest.yml` -- experiment specification

`globi submit manifest` reads this file. For the keys, see [Batch runs: prepare your inputs](simulation_tasking.md#step-2-prepare-your-inputs).

Each config key (`file_config`, `gis_preprocessor_config`, `hourly_data_config`, `overheating_config`) accepts a file path or inline YAML. To turn off an optional config, set it to `null` or leave it out.

**Example** (`examples/tutorial/manifest-overheating.yml`):

```yaml
name: GloBI_Tutorial_Overheating
scenario: Baseline
hourly_data_config: tests/data/e2e/hourly-data-config.yml
file_config: examples/tutorial/artifacts.yml
gis_preprocessor_config: tests/data/e2e/gis-preprocessor.yml
overheating_config: tests/data/e2e/overheating-config.yml
```

---

#### `artifacts.yml` -- file references

The `file_config` key of the manifest points to this file. For the keys, see [Batch runs: prepare your inputs](simulation_tasking.md#step-2-prepare-your-inputs).

If `epwzip_file` is `null` and the GIS file has no weather column, GloBI uses the closest TMYx weather file to each building.

**Example** (`examples/tutorial/artifacts.yml`):

```yaml
gis_file: examples/tutorial/buildings-100.geojson
db_file: tests/data/e2e/components-lib.db
semantic_fields_file: tests/data/e2e/semantic-fields.yml
epwzip_file: examples/tutorial/USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023.zip
component_map_file: tests/data/e2e/component-map.yml
```

---

#### `semantic-fields.yml` -- semantic field definitions

This file defines the semantic fields and names the GIS columns that hold building attributes.

| Key                            | Type   | Required  | Contents                                                                   |
| ------------------------------ | ------ | --------- | -------------------------------------------------------------------------- |
| `Name`                         | str    | yes       | Model name                                                                 |
| `Fields`                       | list   | yes       | The semantic fields                                                        |
| `Fields[].Name`                | str    | yes       | Field name. It must match the GIS column and `semantic_field_context` keys |
| `Fields[].Options`             | list   | yes       | Allowed values of a categorical field                                      |
| `Fields[].Min`, `Fields[].Max` | number | yes       | Allowed range of a numeric field (instead of `Options`)                    |
| `Building_ID_col`              | str    | yes       | GIS column with the building ID                                            |
| `Height_col`                   | str    | one of    | GIS column with the building height [m]                                    |
| `Num_Floors_col`               | str    | these two | GIS column with the number of floors                                       |
| `WWR_col`                      | str    | no        | GIS column with the window-to-wall ratio                                   |
| `Basement_col`, `Attic_col`    | str    | no        | GIS columns with the basement and attic types                              |
| `Exposed_Basement_Frac_col`    | str    | no        | GIS column with the exposed basement fraction                              |
| `Weather_File_col`             | str    | no        | GIS column with a weather file for each building                           |
| `GFA_col`                      | str    | no        | Accepted, but GloBI does not use it                                        |

**Example** (`tests/data/e2e/semantic-fields.yml`):

```yaml
Name: Test Region Model
Fields:
  - Name: Region
    Options:
      - TestRegion
  - Name: Typology
    Options:
      - Office
      - School
      - Residential
      - Hospital
      - Hotel
  - Name: Age_bracket
    Options:
      - Pre_1980
      - 1980_to_2000
      - Post_2000
  - Name: Income
    Options:
      - Low
      - High
  - Name: Scenario
    Options:
      - Baseline
      - Retrofit

Height_col: height
Num_Floors_col: num_storeys
Building_ID_col: id
```

Each building gets one value for each field: from the GIS file in a batch run, or from `semantic_field_context` in a single-building run. The component map uses these values to select components.

---

#### `component-map.yml` -- component selection rules

The component map assigns a `selector` to each component. The `source_fields` of a selector list the semantic fields that build the component name.

The file has two top-level sections:

- **Envelope**: constructions, windows and infiltration.
- **Operations**: space use, HVAC and domestic hot water (DHW).

**Example** (`tests/data/e2e/component-map.yml`):

```yaml
Envelope:
  selector:
    source_fields:
      - Region
      - Typology
      - Scenario
      - Age_bracket

Operations:
  SpaceUse:
    selector:
      source_fields:
        - Region
        - Typology
        - Income
        - Scenario
  HVAC:
    selector:
      source_fields:
        - Region
        - Typology
        - Scenario
        - Age_bracket
  DHW:
    selector:
      source_fields:
        - Region
        - Typology
```

GloBI joins the field values with `_` to make the component name. For example, a residential, post-2000 building in the Baseline scenario gets the `Envelope` record `TestRegion_Residential_Baseline_Post_2000`. The record must exist in the component library.

For a more detailed model, give each sub-component its own selector. In the example below, `Envelope` has separate selectors for `Infiltration`, `Window` and `Assemblies`. The `suffix` key adds `_<suffix>` to the end of the name, for example `..._Main`.

```yaml
Envelope:
  Infiltration:
    selector:
      source_fields:
        - Region
        - TypologySpaceUse
        - Weatherization
      suffix: Main
  Window:
    selector:
      source_fields:
        - Region
  Assemblies:
    selector:
      source_fields:
        - Region
        - TypologySpaceUse
        - Age_bracket

Operations:
  SpaceUse:
    Occupancy:
      selector:
        source_fields:
          - Region
          - TypologySpaceUse
    Lighting:
      selector:
        source_fields:
          - Region
          - TypologySpaceUse
          - Lighting
    Equipment:
      selector:
        source_fields:
          - Region
          - TypologySpaceUse
    Thermostat:
      selector:
        source_fields:
          - Region
          - TypologySpaceUse
          - Thermostat
    WaterUse:
      selector:
        source_fields:
          - Region
          - TypologySpaceUse
  HVAC:
    ConditioningSystems:
      Heating:
        selector:
          source_fields:
            - Region
            - Heating
      Cooling:
        selector:
          source_fields:
            - Region
            - Cooling
    Ventilation:
      selector:
        source_fields:
          - Region
          - TypologyVentilation
          - Weatherization
  DHW:
    selector:
      source_fields:
        - Region
        - DHW
```

To edit the component map in a browser, see [Tutorial: edit the model in sbem-ui](edit-components.md#step-6-component-map).

---

#### `components-lib.db` -- component library

The component library is a SQLite database with the component records: materials, constructions, windows, HVAC systems, schedules and more. Single-building runs and batch runs use the same file.

The database has one table for each component type:

- **Envelope**: `ConstructionMaterial`, `ConstructionAssembly`, `ConstructionAssemblyLayer`, `GlazingConstructionSimple`, `Infiltration`, `Envelope`, `EnvelopeAssembly`
- **Operations**: `Occupancy`, `Lighting`, `Equipment`, `Thermostat`, `WaterUse`, `SpaceUse`, `ThermalSystem`, `ConditioningSystems`, `HVAC`, `Ventilation`, `DHW`, `Operations`
- **Schedules**: `Day`, `Week`, `Year`
- **Zone**: `Zone`

The component map selects top-level records by name, for example `TestRegion_Office_Baseline_Post_2000`. To edit records in a browser, see [Tutorial: edit the model in sbem-ui](edit-components.md#step-7-component-library).

---

#### GIS file -- building footprints

The GIS file holds one row for each building: a footprint polygon and its attributes. GloBI reads any format that GeoPandas reads, for example GeoJSON, GeoParquet or Shapefile. For the required columns, see [What a GIS file needs](tutorial.md#what-a-gis-file-needs).

!!! note

    `tests/data/e2e/buildings.parquet` is a GeoJSON file, despite its name.

In a batch run, `--scenario` sets the `Scenario` column of all buildings. The value must be one of the options of the `Scenario` field.

---

#### `gis-preprocessor.yml` -- geometry checks and defaults

This file controls how GloBI checks and prepares the GIS file. All keys are optional.

| Key                             | Type        | Default                | Contents                                           |
| ------------------------------- | ----------- | ---------------------- | -------------------------------------------------- |
| `cart_crs`                      | str         | `EPSG:3857`            | Cartesian CRS for geometry operations              |
| `min_building_area`             | float       | 10.0                   | Minimum footprint area [m²]                        |
| `min_edge_length`               | float       | 3.0                    | Minimum edge length [m]                            |
| `max_edge_length`               | float       | 1000.0                 | Maximum edge length [m]                            |
| `neighbor_threshold`            | float       | 100.0                  | Distance to search for neighbor buildings [m]      |
| `f2f_height`                    | float       | 3.0                    | Floor-to-floor height [m]                          |
| `min_building_height`           | float       | 3.0                    | Minimum building height [m]                        |
| `max_building_height`           | float       | 300.0                  | Maximum building height [m]                        |
| `min_num_floors`                | int         | 1                      | Minimum number of floors                           |
| `max_num_floors`                | int         | 125                    | Maximum number of floors                           |
| `default_wwr`                   | float       | 0.2                    | Window-to-wall ratio if the GIS file has none      |
| `default_num_floors`            | int         | 2                      | Number of floors if the GIS file has none          |
| `default_basement`              | str         | `none`                 | Basement type if the GIS file has none             |
| `default_attic`                 | str         | `none`                 | Attic type if the GIS file has none                |
| `default_exposed_basement_frac` | float       | 0.25                   | Exposed basement fraction if the GIS file has none |
| `epw_query`                     | str or null | `"source in ['tmyx']"` | Filter for the closest weather file lookup         |

GloBI ignores other keys. Set the weather file in `artifacts.yml`, not in this file.

**Example** (`tests/data/e2e/gis-preprocessor.yml`, shortened):

```yaml
cart_crs: EPSG:3857
min_building_area: 10.0
neighbor_threshold: 100.0
f2f_height: 3.0
default_wwr: 0.2
default_num_floors: 2
epw_query: source in ['tmyx']
```

---

#### `hourly-data-config.yml` -- hourly output configuration

This file selects the hourly EnergyPlus variables to report. To turn it on, set `hourly_data_config` in the manifest. Each variable becomes a separate result table.

| Key           | Type      | Contents                                                       |
| ------------- | --------- | -------------------------------------------------------------- |
| `data`        | list[str] | Variables to report (see the list below)                       |
| `output_mode` | str       | `dataframes-and-filerefs`, `dataframes-only` or `fileref-only` |

The available variables are:

- `Zone Mean Air Temperature`
- `Zone Air Relative Humidity`
- `Zone Mean Radiant Temperature`
- `Site Outdoor Air Drybulb Temperature`

**Example** (`tests/data/e2e/hourly-data-config.yml`):

```yaml
data:
  - "Zone Mean Air Temperature"
  - "Zone Air Relative Humidity"

output_mode: dataframes-and-filerefs
```

---

#### `overheating-config.yml` -- overheating analysis configuration

This file sets the overheating thresholds. To turn it on, set `overheating_config` in the manifest. The run then produces the overheating tables. For their contents, see the [overheating metrics reference](../../reference/overheating_metrics.md).

| Key                   | Type | Contents                                        |
| --------------------- | ---- | ----------------------------------------------- |
| `heat_thresholds`     | list | Temperatures [°C] for heat exceedance           |
| `cold_thresholds`     | list | Temperatures [°C] for cold exceedance           |
| `heat_index_criteria` | dict | Hour limits for the heat index categories       |
| `thermal_comfort`     | dict | Thermal comfort assumptions (`met`, `clo`, `v`) |

**Example** (`tests/data/e2e/overheating-config.yml`):

```yaml
heat_thresholds:
  - threshold: 26.0
  - threshold: 30.0
  - threshold: 35.0
cold_thresholds:
  - threshold: 10.0
  - threshold: 5.0
heat_index_criteria:
  extreme_danger_hours: null
  danger_or_worse_hours: null
  caution_or_worse_hours: null
thermal_comfort:
  met: 1.1
  clo: 0.5
  v: 0.1
```

---

### How inputs relate to each other

Single building:

```
building.yml
├── db_file ──────────────► components-lib.db
├── semantic_fields_file ─► semantic-fields.yml
├── component_map_file ───► component-map.yml
└── epwzip_file ──────────► weather file (.zip, local path or URL)
```

Batch run:

```
manifest.yml
├── file_config ──────────────────► artifacts.yml
│                                   ├── gis_file ──────────────► GIS file
│                                   ├── db_file ───────────────► components-lib.db
│                                   ├── semantic_fields_file ──► semantic-fields.yml
│                                   ├── component_map_file ────► component-map.yml
│                                   └── epwzip_file ───────────► weather file
├── gis_preprocessor_config ──────► gis-preprocessor.yml
├── hourly_data_config (optional) ► hourly-data-config.yml
└── overheating_config (optional) ► overheating-config.yml
```

!!! warning

    Write all file paths relative to the repository root, or as absolute paths. For runs with `make cli` (Docker), keep your files under `inputs/`: the container only sees `inputs/`, `outputs/`, `examples/` and `tests/data/e2e/`.

---

### Output files

#### Single building output

`globi simulate` writes these files to the output folder:

```
<output-dir>/
├── ep/
│   └── eplus_simulation/
│       ├── Minimal.idf              # generated EnergyPlus model
│       └── {hash}/                  # one EnergyPlus run
│           ├── Minimal.idf
│           ├── *.epw                # weather file used
│           ├── eplusout.sql         # all results (SQLite)
│           ├── eplusout.csv         # output variables
│           ├── eplusmtr.csv         # meter outputs
│           ├── eplustbl.csv         # tabular summary report
│           ├── eplusout.err         # warnings and errors
│           └── ...                  # other EnergyPlus files
└── results/
    ├── EnergyAndPeak.parquet        # main results
    ├── EnergyAndPeak.csv            # one row for each month
    └── EnergyAndPeak.xlsx           # one sheet for each measurement and aggregation
```

#### Batch run output

`globi get experiment` downloads one result table for each call:

```
outputs/
└── {run_name}/
    └── v{version}/
        ├── EnergyAndPeak.pq         # always
        ├── EnergyAndPeak.xlsx       # for EnergyAndPeak only
        └── EnergyAndPeak.csv        # only with --include-csv
```

To download another table, add `--dataframe-key`. Other tables are saved as `.pq` only. For the list of overheating and hourly tables, see [section D of the tutorial](tutorial.md#d-overheating-and-hourly-outputs).

---

#### `EnergyAndPeak` table format

`EnergyAndPeak` is the main output. Its columns have four levels:

| Level | Name        | Values                                                                                                                                      |
| ----- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 0     | Measurement | `Energy`, `Peak`                                                                                                                            |
| 1     | Aggregation | `Raw`, `End Uses`, `Utilities`                                                                                                              |
| 2     | Meter       | End uses (`Lighting`, `Equipment`, `Domestic Hot Water`, `Heating`, `Cooling`) and fuels (`Electricity`, `NaturalGas`, `ChilledWater`, ...) |
| 3     | Month       | `1` to `12`                                                                                                                                 |

In a batch run, the row index has `building_id` and the building features, for example `feature.semantic.Typology` and `feature.geometry.long_edge`.

**Units**: energy in kWh/m², peak in kW/m².

**CSV format**: the CSV file has one row for each month. The header has four rows, one for each column level:

```
Measurement  Energy    Energy     Energy              ...
Aggregation  Raw       Raw        Raw                 ...
Meter        Lighting  Equipment  Domestic Hot Water  ...
Month
1            1.588     1.860      1.397               ...
2            1.434     1.680      1.260               ...
```

**Excel format**: the workbook has one sheet for each measurement and aggregation:

- `Energy_Raw`, `Energy_EndUses`, `Energy_Utilities`
- `Peak_Raw`, `Peak_Utilities`
- `Feature Index`: building IDs and semantic field values (batch runs only)

---

#### EnergyPlus raw outputs

The `ep/` folder has the EnergyPlus files of a single-building run. The most useful files are:

| File                           | Contents                                                    |
| ------------------------------ | ----------------------------------------------------------- |
| `Minimal.idf`                  | The generated EnergyPlus model                              |
| `*.epw`                        | The weather file used                                       |
| `eplusout.err`                 | Warnings and errors. Read it first if a run fails           |
| `eplusout.sql`                 | All results in one SQLite database                          |
| `eplusout.csv`                 | Output variables (temperatures, humidity, energy in joules) |
| `eplusmtr.csv`                 | Meter outputs (energy by fuel type)                         |
| `eplustbl.csv`, `eplustbl.htm` | Tabular summary report (annual totals, end uses)            |
| `epluszsz.csv`                 | Zone sizing data (design loads, mass flows)                 |
| `eplusout.eso`                 | EnergyPlus standard output (text)                           |
| `*.eio`, `*.rdd`, `*.mdd`      | Variable dictionaries and metadata                          |

---

### Quick reference

#### Minimal single-building setup

```
inputs/
├── building.yml
├── components-lib.db
├── semantic-fields.yml
├── component-map.yml
└── <weather>.zip
```

#### Minimal batch setup

```
inputs/
├── manifest.yml
├── artifacts.yml
├── buildings.geojson          # GIS file
├── components-lib.db
├── semantic-fields.yml
├── component-map.yml
├── <weather>.zip
└── gis-preprocessor.yml       # optional
```

#### Batch run with hourly data and overheating

Add these files to the minimal batch setup, and set their keys in the manifest:

```
inputs/
├── hourly-data-config.yml
└── overheating-config.yml
```
