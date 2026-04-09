## Visualization engine

The globi visualization engine is a Streamlit app for exploring and analyzing simulation results. It provides interactive charts, 3D building maps, and purpose-built analysis views for retrofit comparison, overheating assessment, and scenario comparison.

It assumes you have already completed the [setup guide](../getting-started/requirements.md) and have simulation results available either locally or in S3.

---

### Before you start

- **simulation results**: you need at least one completed simulation run with output parquet files (see [simulate a building](../run-simulations/simulate_building.md) or [simulation tasking](../run-simulations/simulation_tasking.md))
- **terminal location**: run commands from the repository root

---

### Starting the visualizer

=== "Native (local)"

    ```bash
    make viz-native
    ```

    This runs `streamlit run src/globi/tools/visualization/main.py` with the required environment files loaded. The app opens in your browser automatically.

=== "Docker"

    ```bash
    make viz
    ```

    This builds and starts the visualizer container via Docker Compose, including the `docker-compose.st.yml` configuration.

Once running, the app is available at the URL printed in the terminal (typically `http://localhost:8501`).

---

### Data sources

The sidebar lets you choose between two data sources:

#### Local

Point the app at a local directory containing simulation output folders. Each subfolder that contains `.pq` or `.parquet` files is treated as a separate run.

- **default directory**: `outputs`
- **optional**: place a `buildings.parquet` file in the `inputs/` directory with building location data (latitude, longitude, geometry) to enable 3D map visualizations

#### S3

Connect directly to your S3 experiment storage. The app lists available experiments and lets you pick a run name, version, and dataframe key.

**Required environment variables** (set in `.env.*.aws` and `.env.scythe.storage`):

- `SCYTHE_STORAGE_BUCKET`: the S3 bucket name
- `SCYTHE_STORAGE_BUCKET_PREFIX` (optional): prefix within the bucket

AWS credentials must be configured for S3 access.

---

### Pages

The app has three pages, accessible from the navigation menu.

---

#### Overview

The landing page. It describes the available data sources, how to use the app, and what file formats are expected. Use this as a reference when first opening the visualizer.

---

#### Raw Data Visualization

Explore the output of any individual simulation run. Select a run from the dropdown and the app loads the corresponding parquet file.

The behavior depends on the file format detected:

##### Results / EnergyAndPeak format

For files with the standard multi-index column structure (Measurement, Aggregation, Meter, Month), two tabs are available:

**Summary tab**:

| Chart                  | Description                                                       |
| ---------------------- | ----------------------------------------------------------------- |
| EUI histogram          | distribution of energy use intensity across buildings             |
| Peak demand histogram  | distribution of peak demand across buildings                      |
| End-use pie chart      | breakdown of energy by end use (heating, cooling, lighting, etc.) |
| Utilities pie chart    | breakdown of energy by fuel type (electricity, gas, etc.)         |
| Monthly EUI by end use | stacked bar chart showing monthly energy by end use               |
| Monthly EUI by utility | stacked bar chart showing monthly energy by fuel type             |

**Map tab**:

A 3D pydeck map showing buildings as extruded polygons. Requires building geometry data (either embedded in the parquet or from `inputs/buildings.parquet`). Color can be mapped to:

- EUI (energy use intensity)
- total energy
- peak demand per sqm
- total peak demand

##### Generic parquet format

For any other parquet file, the app provides:

- column selection with automatic numeric/categorical detection
- D3 histograms for numeric columns
- summary statistics grouped by a categorical column
- configurable value and category layers from the column structure

##### Export

All charts can be exported as:

- **CSV**: raw data behind the chart
- **HTML**: interactive standalone chart
- **PNG**: static image (requires Playwright: `playwright install chromium`)

---

#### Use Cases

Purpose-built analysis views for common workflows. Select the use case type from the sidebar.

---

##### Retrofit analysis

Compare energy, cost, and emissions across two or more scenarios (e.g. baseline vs. retrofit). Requires at least two runs loaded from the data source.

**Configuration** (sidebar):

- select baseline and retrofit scenario(s)
- enter per-scenario energy costs ($/kWh per fuel type)
- enter per-scenario emissions factors (kgCO2/kWh per fuel type)
- enter system costs per sqm ($/m2) for each scenario
- assign display names to each scenario

**Visualizations**:

| Chart                | Description                                                            |
| -------------------- | ---------------------------------------------------------------------- |
| EUI KDE plot         | kernel density estimate comparing EUI distributions across scenarios   |
| End-use stacked bars | energy breakdown by end use, per scenario                              |
| Fuel stacked bars    | energy breakdown by fuel type, per scenario                            |
| Cost bar chart       | total energy cost by scenario                                          |
| Emissions bar chart  | total emissions by scenario                                            |
| 3D building map      | buildings colored by selected metric (EUI, peak, percent change, etc.) |

The map supports switching between metrics and adjusting elevation scale, radius, and view parameters (zoom, pitch, bearing).

---

##### Overheating analysis

Visualize overheating risk across buildings on a 3D map. Requires that the simulation produced a `BasicOverheating.pq` file (enabled via hourly data configuration in the manifest).

**Configuration** (sidebar):

- temperature threshold: 26, 30, or 35 degrees C
- aggregation method: zone-weighted average or worst zone

**Visualization**:

- 3D pydeck map with buildings colored by overheating hours above the selected threshold
- configurable elevation scale and view parameters
- hover tooltips showing building-level overheating details

!!! note

    if the selected run does not contain a `BasicOverheating.pq` file, the overheating use case will not be available. make sure hourly data output is enabled in your simulation configuration.

---

##### Scenario comparison

A lightweight comparison between two or more scenarios without cost/emissions data. Useful for quickly comparing energy profiles across different simulation configurations.

**Configuration** (sidebar):

- select the scenarios to compare
- assign display names

**Visualizations**:

| Chart                | Description                              |
| -------------------- | ---------------------------------------- |
| EUI KDE plot         | distribution comparison across scenarios |
| End-use stacked bars | energy by end use per scenario           |
| Fuel stacked bars    | energy by fuel type per scenario         |

---

### Supported data formats

| File                       | Structure                                                   | Used by                                 |
| -------------------------- | ----------------------------------------------------------- | --------------------------------------- |
| `EnergyAndPeak.pq`         | multi-index columns: Measurement, Aggregation, Meter, Month | raw data, retrofit, scenario comparison |
| `Results.pq`               | same structure as EnergyAndPeak (legacy name)               | raw data, retrofit, scenario comparison |
| `BasicOverheating.pq`      | overheating hours per building per zone                     | overheating analysis                    |
| generic `.pq` / `.parquet` | any flat or index-flattened parquet                         | raw data (generic mode)                 |
| `buildings.parquet`        | building locations with lat/lon and geometry                | 3D map views                            |

---

### Troubleshooting

- **no runs found**: ensure your output directory contains subfolders with `.pq` or `.parquet` files. the app scans recursively for these.

- **map not showing**: 3D maps require building geometry data. either the parquet file must contain `latitude`, `longitude`, and `rotated_rectangle` columns, or you must have an `inputs/buildings.parquet` file with this data that can be joined on `building_id`.

- **PNG export fails**: PNG export uses Playwright for headless browser rendering. install it with:

  ```bash
  playwright install chromium
  ```

- **S3 connection errors**: verify your AWS credentials are configured and the environment variables `SCYTHE_STORAGE_BUCKET` (and optionally `SCYTHE_STORAGE_BUCKET_PREFIX`) are set in your env files.

- **streamlit not found**: re-sync dependencies:

  ```bash
  uv sync --all-extras --all-groups
  ```

---

### Quick reference

```bash
# start visualizer locally
make viz-native

# start visualizer via docker
make viz

# stop all docker services (including visualizer)
make down
```
