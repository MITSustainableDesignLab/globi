## Simulation inputs and outputs

This page documents every input file required to run globi simulations (both single-building and batch/manifest), how to populate them, and the format of the output files produced.

---

### Input files overview

The table below summarizes all input files. Which files you need depends on whether you are running a single building or a batch via manifest.

| File                     | Single building | Batch (manifest) | Description                                        |
| ------------------------ | :-------------: | :--------------: | -------------------------------------------------- |
| `building.yml`           |    required     |        --        | single-building specification                      |
| `manifest.yml`           |       --        |     required     | experiment specification                           |
| `artifacts.yml`          |       --        |     required     | file paths for GIS, DB, weather, etc.              |
| `semantic-fields.yml`    |    required     |     required     | semantic field definitions and GIS column mappings |
| `component-map.yml`      |    required     |     required     | maps semantic fields to component selection rules  |
| `components-lib.db`      |    required     |     required     | SQLite component database                          |
| `buildings.parquet`      |       --        |     required     | GIS building footprints (GeoDataFrame)             |
| `gis-preprocessor.yml`   |       --        |     optional     | geometry validation and defaults                   |
| `hourly-data-config.yml` |       --        |     optional     | hourly output variable configuration               |
| `overheating-config.yml` |       --        |     optional     | overheating analysis thresholds                    |
| EPW weather file         |    required     |     required     | EnergyPlus weather data (URL or local path)        |

---

### Input file details

#### `building.yml` -- single building specification

Used by `make cli-native simulate` (or `make cli simulate`). Defines a single building's geometry, envelope, and the semantic context used to look up components.

**Required fields**:

| Field                    | Type        | Description                                                   |
| ------------------------ | ----------- | ------------------------------------------------------------- |
| `db_file`                | path        | path to the component database (SQLite)                       |
| `semantic_fields_file`   | path        | path to the semantic fields config                            |
| `component_map_file`     | path        | path to the component map config                              |
| `epwzip_file`            | path or URL | EPW weather file                                              |
| `semantic_field_context` | dict        | key-value pairs matching semantic field names to their values |

**Optional fields**:

| Field                   | Type  | Default  | Constraints | Description                         |
| ----------------------- | ----- | -------- | ----------- | ----------------------------------- |
| `length`                | float | 15.0     | >= 3.0      | long edge of the building [m]       |
| `width`                 | float | 15.0     | >= 3.0      | short edge of the building [m]      |
| `num_floors`            | int   | 2        | >= 1        | number of floors                    |
| `f2f_height`            | float | 3.0      | >= 0        | floor-to-floor height [m]           |
| `wwr`                   | float | 0.2      | 0.0 -- 1.0  | window-to-wall ratio                |
| `basement`              | str   | `"none"` | see below   | basement type                       |
| `attic`                 | str   | `"none"` | see below   | attic type                          |
| `exposed_basement_frac` | float | 0.25     | 0.0 -- 1.0  | fraction of basement exposed to air |

Valid values for `basement` and `attic`: `"none"`, `"unoccupied_unconditioned"`, `"unoccupied_conditioned"`, `"occupied_unconditioned"`, `"occupied_conditioned"`.

If `length < width`, they are automatically swapped so `length` is always the longer edge.

**Example** (`inputs/building.yml`):

```yaml
db_file: inputs/components-lib.db
semantic_fields_file: inputs/semantic-fields.yml
component_map_file: inputs/component-map.yml
epwzip_file: "https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/MA_Massachusetts/USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023.zip"
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

---

#### `manifest.yml` -- experiment specification

Used by `make cli-native submit manifest` (or `make cli submit manifest`). Defines a batch experiment over a set of buildings. All referenced config files can be either inline YAML or file paths -- when a path is given, the file is loaded automatically.

| Field                     | Type                  | Required | Description                                            |
| ------------------------- | --------------------- | -------- | ------------------------------------------------------ |
| `name`                    | str                   | yes      | experiment/region name (used in `run_name`)            |
| `scenario`                | str                   | yes      | scenario identifier (e.g. `Baseline`, `Retrofit`)      |
| `file_config`             | path or inline        | yes      | path to `artifacts.yml` or inline file config          |
| `gis_preprocessor_config` | path or inline        | no       | path to `gis-preprocessor.yml` or inline config        |
| `hourly_data_config`      | path, inline, or null | no       | path to `hourly-data-config.yml`, or `null` to disable |
| `overheating_config`      | path, inline, or null | no       | path to `overheating-config.yml`, or `null` to disable |

**Example** (`inputs/manifest.yml`):

```yaml
name: TestRegion
scenario: Baseline
hourly_data_config: null
file_config: inputs/artifacts.yml
gis_preprocessor_config: inputs/gis-preprocessor.yml
```

**Example with overheating and hourly data enabled**:

```yaml
name: TestRegion
scenario: Baseline
hourly_data_config: inputs/hourly-data-config.yml
overheating_config: inputs/overheating-config.yml
file_config: inputs/artifacts.yml
gis_preprocessor_config: inputs/gis-preprocessor.yml
```

---

#### `artifacts.yml` -- file references

Points to the data files used during batch simulation. Referenced by `manifest.yml` via the `file_config` field.

| Field                  | Type        | Description                                            |
| ---------------------- | ----------- | ------------------------------------------------------ |
| `gis_file`             | path        | path to the buildings GeoDataFrame (parquet)           |
| `db_file`              | path        | path to the component database (SQLite)                |
| `semantic_fields_file` | path        | path to the semantic fields config                     |
| `component_map_file`   | path        | path to the component map config                       |
| `epwzip_file`          | path or URL | EPW weather file (or `null` to use nearest EPW lookup) |

**Example** (`inputs/artifacts.yml`):

```yaml
gis_file: inputs/buildings.parquet
db_file: inputs/components-lib.db
semantic_fields_file: inputs/semantic-fields.yml
epwzip_file: "https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/MA_Massachusetts/USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023.zip"
component_map_file: inputs/component-map.yml
```

---

#### `semantic-fields.yml` -- semantic field definitions

Defines the semantic fields (categorical variables) used to look up building components in the database, and maps GIS column names to building attributes.

| Field              | Type      | Description                                                               |
| ------------------ | --------- | ------------------------------------------------------------------------- |
| `Name`             | str       | model name                                                                |
| `Fields`           | list      | list of semantic field definitions                                        |
| `Fields[].Name`    | str       | field name (must match keys in `semantic_field_context` and component DB) |
| `Fields[].Options` | list[str] | allowed values for this field                                             |
| `Height_col`       | str       | GIS column name for building height                                       |
| `Num_Floors_col`   | str       | GIS column name for number of floors                                      |
| `Building_ID_col`  | str       | GIS column name for building ID                                           |
| `GFA_col`          | str       | GIS column name for gross floor area / footprint area                     |

**Example** (`inputs/semantic-fields.yml`):

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
Num_Floors_col: num_floors
Building_ID_col: building_id
GFA_col: footprint_area
```

The `Fields` entries define the categorical axes of the component database. Each building is assigned a value for each field (either from the GIS data or from `semantic_field_context`), and those values are used to select the appropriate envelope, HVAC, and other components.

---

#### `component-map.yml` -- component selection rules

Maps semantic fields to component types. Each component category has a `selector` that specifies which semantic fields are used to look up the matching entry in the component database.

The top-level structure has two sections:

- **Envelope**: construction and infiltration components
- **Operations**: space use, HVAC, and DHW components

**Example** (`inputs/component-map.yml`):

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

Each `source_fields` list names the semantic fields whose values are concatenated to form the lookup key in the component database. For example, an envelope lookup with `Region=TestRegion`, `Typology=Office`, `Scenario=Baseline`, `Age_bracket=Post_2000` would search for a matching entry in the database.

For more complex models, you can nest sub-components under each category. For example, envelope can be split into `Infiltration`, `Window`, and `Assemblies`, each with their own selector:

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

---

#### `components-lib.db` -- component database

A SQLite database containing building component definitions (materials, assemblies, glazing, HVAC systems, schedules, etc.). This database is populated separately and is referenced by both single-building and batch simulations.

The database uses a Prisma-managed schema with tables including:

- **Envelope**: `ConstructionMaterial`, `ConstructionAssembly`, `ConstructionAssemblyLayer`, `GlazingConstructionSimple`, `Infiltration`, `Envelope`, `EnvelopeAssembly`
- **Operations**: `Occupancy`, `Lighting`, `Equipment`, `Thermostat`, `WaterUse`, `SpaceUse`, `ThermalSystem`, `ConditioningSystems`, `HVAC`, `Ventilation`, `DHW`, `Operations`
- **Schedule**: `Day`, `Week`, `Year`
- **Zone**: `Zone`

Component records are keyed by concatenated semantic field values (e.g. `TestRegion_Office_Baseline_Post_2000`).

---

#### `buildings.parquet` -- building footprints

A GeoParquet file containing building footprint geometries and attributes for batch simulations. Each row represents one building.

**Required columns** (column names are defined in `semantic-fields.yml`):

| Column (from semantic-fields)              | Description                             |
| ------------------------------------------ | --------------------------------------- |
| building ID column (`Building_ID_col`)     | unique building identifier              |
| height column (`Height_col`)               | building height [m]                     |
| number of floors column (`Num_Floors_col`) | number of floors                        |
| GFA column (`GFA_col`)                     | gross floor area or footprint area [m2] |
| geometry                                   | building footprint polygon              |

Additionally, the parquet must contain columns for each semantic field defined in `semantic-fields.yml` that the GIS preprocessor needs to assign to each building (e.g. `Typology`, `Age_bracket`, etc.). Fields not present in the GIS data can be set via the `scenario` field in the manifest.

---

#### `gis-preprocessor.yml` -- geometry validation and defaults

Controls how GIS building data is validated and preprocessed before simulation. All fields are optional with sensible defaults.

| Field                           | Type         | Default                | Description                                   |
| ------------------------------- | ------------ | ---------------------- | --------------------------------------------- |
| `cart_crs`                      | str          | `EPSG:3857`            | cartesian CRS for geometry operations         |
| `min_building_area`             | float        | 10.0                   | minimum building footprint area [m2]          |
| `min_edge_length`               | float        | 3.0                    | minimum edge length [m]                       |
| `max_edge_length`               | float        | 1000.0                 | maximum edge length [m]                       |
| `neighbor_threshold`            | float        | 100.0                  | distance threshold for neighbor detection [m] |
| `f2f_height`                    | float        | 3.0                    | floor-to-floor height [m]                     |
| `min_building_height`           | float        | 3.0                    | minimum building height [m]                   |
| `max_building_height`           | float        | 300.0                  | maximum building height [m]                   |
| `min_num_floors`                | int          | 1                      | minimum number of floors                      |
| `max_num_floors`                | int          | 125                    | maximum number of floors                      |
| `default_wwr`                   | float        | 0.2                    | default window-to-wall ratio                  |
| `default_num_floors`            | int          | 2                      | default number of floors when missing         |
| `default_basement`              | str          | `"none"`               | default basement type                         |
| `default_attic`                 | str          | `"none"`               | default attic type                            |
| `default_exposed_basement_frac` | float        | 0.25                   | default exposed basement fraction             |
| `epwzip_file`                   | path or null | null                   | override EPW file for all buildings           |
| `epw_query`                     | str or null  | `"source in ['tmyx']"` | filter for closest EPW lookup                 |

**Example** (`inputs/gis-preprocessor.yml`):

```yaml
cart_crs: EPSG:4326
min_building_area: 10.0
min_edge_length: 3.0
max_edge_length: 1000.0
neighbor_threshold: 100.0
f2f_height: 3.0
min_building_height: 3.0
max_building_height: 300.0
min_num_floors: 1
max_num_floors: 125
default_wwr: 0.2
default_num_floors: 2
default_basement: none
default_attic: none
default_exposed_basement_frac: 0.25
epwzip_file: null
epw_query: source in ['tmyx']
```

---

#### `hourly-data-config.yml` -- hourly output configuration

Configures which hourly EnergyPlus output variables to report. When enabled (by setting `hourly_data_config` in the manifest), the simulation produces additional per-building time series dataframes.

| Field         | Type      | Description                                                               |
| ------------- | --------- | ------------------------------------------------------------------------- |
| `data`        | list[str] | EnergyPlus output variable names to report                                |
| `output_mode` | str       | one of `"dataframes-and-filerefs"`, `"fileref-only"`, `"dataframes-only"` |

Available hourly variables include (among others):

- `"Zone Mean Air Temperature"`
- `"Zone Air Relative Humidity"`

**Example** (`inputs/hourly-data-config.yml`):

```yaml
data:
  - "Zone Mean Air Temperature"
  - "Zone Air Relative Humidity"

output_mode: dataframes-and-filerefs
```

---

#### `overheating-config.yml` -- overheating analysis configuration

Configures overheating analysis thresholds. When enabled (by setting `overheating_config` in the manifest), the simulation produces `BasicOverheating.pq` and related dataframes.

| Field                 | Type | Description                                         |
| --------------------- | ---- | --------------------------------------------------- |
| `heat_thresholds`     | list | temperature thresholds for heat exceedance analysis |
| `cold_thresholds`     | list | temperature thresholds for cold exceedance analysis |
| `heat_index_criteria` | dict | heat index hour limits (set to `null` to skip)      |
| `thermal_comfort`     | dict | thermal comfort parameters (met, clo, v)            |

**Example** (`inputs/overheating-config.yml`):

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

For a **single building** simulation, the relationship is straightforward:

```
building.yml
├── db_file ──────────────► components-lib.db
├── semantic_fields_file ─► semantic-fields.yml
├── component_map_file ───► component-map.yml
└── epwzip_file ──────────► weather file (URL or local)
```

For a **batch** (manifest) simulation, the chain is:

```
manifest.yml
├── file_config ──────────────────► artifacts.yml
│                                   ├── gis_file ──────────────► buildings.parquet
│                                   ├── db_file ───────────────► components-lib.db
│                                   ├── semantic_fields_file ──► semantic-fields.yml
│                                   ├── component_map_file ────► component-map.yml
│                                   └── epwzip_file ───────────► weather file
├── gis_preprocessor_config ──────► gis-preprocessor.yml
├── hourly_data_config (optional) ► hourly-data-config.yml
└── overheating_config (optional) ► overheating-config.yml
```

!!! warning

    all file paths in your configs should be relative to the repository root, or use absolute paths. for dockerized runs (`make cli`), all input files must be located under the `inputs/` directory.

---

### Output files

#### Single building output

Running `make cli-native simulate` produces the following directory structure:

```
outputs/
├── ep/                              # EnergyPlus working directory
│   └── eplus_simulation/
│       └── {hash}/                  # simulation run (hash of the IDF)
│           ├── Minimal.idf          # generated EnergyPlus model
│           ├── *.epw                # weather file used
│           ├── eplusout.csv         # hourly outputs
│           ├── eplusmtr.csv         # meter outputs
│           ├── eplustbl.csv         # tabular summary report
│           ├── epluszsz.csv         # zone sizing data
│           └── ...                  # other EnergyPlus artifacts
└── results/
    ├── EnergyAndPeak.parquet        # main results (parquet)
    ├── EnergyAndPeak.csv            # flattened CSV export
    └── EnergyAndPeak.xlsx           # multi-sheet Excel workbook
```

#### Batch simulation output (from S3)

Running `make cli-native get experiment` downloads results to:

```
outputs/
└── {run_name}/
    └── {version}/
        ├── EnergyAndPeak.pq         # main results (parquet)
        ├── EnergyAndPeak.csv        # CSV export (auto-generated)
        └── EnergyAndPeak.xlsx       # Excel workbook (auto-generated)
```

When hourly data or overheating analysis is enabled, additional dataframes are stored in S3 and can be fetched by specifying `--dataframe-key`:

- `BasicOverheating` -- overheating hours per building
- `ExceedanceDegreeHours` -- degree hours above each threshold
- `HeatIndexCategories` -- heat index classification hours
- `ConsecutiveExceedances` -- consecutive exceedance periods
- `HourlyData.Zone_Mean_Air_Temperature` -- hourly zone temperatures
- `HourlyData.Zone_Air_Relative_Humidity` -- hourly zone humidity

---

#### `EnergyAndPeak` dataframe format

This is the primary output. It uses a multi-index column structure with four levels:

| Level | Name        | Values                                                                                                                         |
| ----- | ----------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 0     | Measurement | `Energy`, `Peak`                                                                                                               |
| 1     | Aggregation | `Raw`, `End Uses`, `Utilities`                                                                                                 |
| 2     | Meter       | `Lighting`, `Equipment`, `Domestic Hot Water`, `Heating`, `Cooling`, `ChilledWater`, `Coal`, `Electricity`, `NaturalGas`, etc. |
| 3     | Month       | `1` through `12`                                                                                                               |

**Index** (for batch runs): a multi-index containing `building_id` and all semantic field feature columns (e.g. `feature.semantic.Typology`, `feature.semantic.Age_bracket`).

**Units**:

- Energy values are in **kWh/m2**
- Peak values are in **kW/m2**

**CSV format** (flattened):

The CSV export stacks the Month level, producing one row per month. The header is four rows deep (one per column level):

```
                  Energy  Energy  Energy  ...  Peak    Peak    ...
                  Raw     Raw     Raw     ...  Raw     Raw     ...
                  Lighting Equipment DHW  ...  Lighting Equipment ...
Month
1                 1.588   1.860   0.432   ...  0.0065  0.0076  ...
2                 1.434   1.680   0.390   ...  0.0065  0.0076  ...
...
12                1.416   1.860   0.432   ...  0.0174  0.0076  ...
```

**Excel format**:

The Excel workbook contains one sheet per Measurement+Aggregation combination:

- `Energy_Raw` -- raw energy by meter and month
- `Energy_EndUses` -- energy grouped by end use
- `Energy_Utilities` -- energy grouped by utility/fuel type
- `Peak_Raw` -- raw peak by meter and month
- `Peak_EndUses` -- peak grouped by end use
- `Peak_Utilities` -- peak grouped by utility/fuel type
- `Feature Index` -- building IDs and semantic field values (batch runs only)

---

#### EnergyPlus raw outputs

The `ep/` directory contains the raw EnergyPlus simulation artifacts for each run. Key files:

| File                      | Description                                                            |
| ------------------------- | ---------------------------------------------------------------------- |
| `Minimal.idf`             | the generated EnergyPlus input file                                    |
| `*.epw`                   | the weather file used                                                  |
| `eplusout.csv`            | all hourly output variables (temperatures, humidity, energy in Joules) |
| `eplusmtr.csv`            | meter-level outputs (energy by fuel type, hourly/monthly)              |
| `eplustbl.csv`            | tabular summary report (annual totals, end-use breakdown)              |
| `epluszsz.csv`            | zone sizing data (design loads, mass flows)                            |
| `eplusout.eso`            | EnergyPlus standard output (binary)                                    |
| `*.eio`, `*.rdd`, `*.mdd` | variable dictionaries and metadata                                     |

---

### Quick reference

#### Minimal single-building setup

```
inputs/
├── building.yml
├── components-lib.db
├── semantic-fields.yml
└── component-map.yml
```

#### Minimal batch setup

```
inputs/
├── manifest.yml
├── artifacts.yml
├── buildings.parquet
├── components-lib.db
├── semantic-fields.yml
├── component-map.yml
└── gis-preprocessor.yml        # optional
```

#### Batch with hourly data and overheating

```
inputs/
├── manifest.yml
├── artifacts.yml
├── buildings.parquet
├── components-lib.db
├── semantic-fields.yml
├── component-map.yml
├── gis-preprocessor.yml
├── hourly-data-config.yml
└── overheating-config.yml
```
