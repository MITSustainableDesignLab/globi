# Results dashboard: setup and reference

How to run the dashboard and how it computes what it shows. For a walk-through of the pages, see [Using the dashboard](using-the-dashboard.md). The code lives in `src/globi/tools/visualization/`.

## Running it

| Command                                                      | What it does                                                                                                              |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| `make viz-native`                                            | Runs on your machine. Loads `.env.$(AWS_ENV).aws` (default `local.host`, i.e. the local stack) and `.env.scythe.storage`. |
| `make viz`                                                   | Runs in Docker, with `src/globi/tools/visualization/config.toml` as the Streamlit config.                                 |
| `uv run streamlit run src/globi/tools/visualization/main.py` | Runs directly; you set the environment variables yourself.                                                                |

The dashboard is served at <http://localhost:8501>. Both Streamlit configs (`.streamlit/config.toml` for native runs, the one above for Docker) set `toolbarMode = "viewer"`, which hides Streamlit's developer toolbar from users.

## Pages

| Page                  | Code                 | What it does                                                                                        |
| --------------------- | -------------------- | --------------------------------------------------------------------------------------------------- |
| **Start here**        | `views/overview.py`  | Steps, page links and a glossary                                                                    |
| **Explore a run**     | `views/raw_data.py`  | Headline numbers, then Charts / Map / Buildings for one run; a generic view for other parquet files |
| **Compare scenarios** | `views/compare.py`   | Baseline vs other runs: headline changes, payback, comparison charts, map                           |
| **Overheating**       | `views/use_cases.py` | Portfolio / Map / Priority list / Correlations from the overheating tables                          |

Shared widgets (filters, headline numbers, run labels, downloads, the map legend and captions) are in `views/common.py`. The sidebar (data source, Refresh, Settings) is in `sidebar.py`.

## Settings

The sidebar's **Settings** box holds two settings that apply to every page:

- **Energy intensity units**: kWh/m² or kBTU/ft² for EUI everywhere (headline numbers, charts, map colours, tables).
- **Map coordinate system**: the projected CRS of the footprints. **Automatic** (default) uses `infer_rotated_rectangle_crs_hint`, which tries a list of common CRSs on a sample of footprints and picks the one that places them cleanly. Users can pick a CRS from that list or type any EPSG code under **Other…**. Each map's caption says which CRS it used.

## Units

Result tables store energy per m² of conditioned floor area (`feature.geometry.energy_model_conditioned_area`). The dashboard shows:

- **EUI (kWh/m²)**: per building as stored; across buildings, weighted by area, i.e. total energy / total floor area.
- **Totals (kWh, $, kg CO2)**: per-m² values × conditioned area, then summed. Pies, stacked bars and the cost and emissions figures all use these area-weighted totals.
- **Peak (kW/m²)**: the highest monthly peak across meters.

## Costs, emissions and payback

On **Compare scenarios**, the first scenario after reordering is the chosen baseline. Then:

- **Annual energy cost and emissions** = kWh per fuel × that scenario's price and emission factor for the fuel. Meter names (e.g. `NaturalGas`) are matched to the table's fuels by `resolve_fuel_factor_key`. Fuels without a factor count as zero.
- **System cost** = the scenario's $/m² × its total floor area. It's a one-off cost and is never added to annual figures.
- **Annual savings** = baseline annual energy cost − scenario annual energy cost.
- **Payback** = system cost / annual savings. It's left empty when there are no savings or no system cost.

Map costs are per building (kWh × price), matched to buildings by `building_id`.

## Overheating

The Overheating page reads up to four tables per run: `BasicOverheating` (hours above a threshold), `ExceedanceDegreeHours` (EDH), `HeatIndexCategories` and `ConsecutiveExceedances`. The [Overheating metrics reference](../../reference/overheating_metrics.md) defines each table, its groups (Any Zone, Zone Weighted, Worst Zone, Equally Weighted) and its formulas. The page:

- offers the thresholds found in the data, and the **Zone Weighted** and **Worst Zone** groups (shown as "All rooms" and "Hottest room");
- builds every per-building table once per run, threshold and room setting (cached). Table reads, the threshold list and the building-level rows of each table are also cached per file;
- draws only the selected section (Portfolio, Map, Priority list or Correlations), because Streamlit tabs would compute all four on every interaction;
- applies the sidebar filters by `building_id` to every per-building table, then recomputes the threshold summaries from the filtered buildings.

Summary statistics (median, P90, share of buildings) are per building and not weighted by floor area, except **Floor area overheating** and the floor-area histograms.

## Filters

The _Filter buildings_ list is built from the run's `feature.*` index levels that have more than one value.

- Numeric levels get a range slider in 5% steps.
- Categorical levels with up to 50 values get a multi-select.
- The list is ordered floor area, age-like attributes (`age`, `year`, `vintage`, `built`), other `feature.semantic.*` fields, then the rest. Shading masks and orientation are left out.
- Floor area and the first age-like attribute are selected by default.

On **Compare scenarios** the filters come from the baseline run and are applied to every scenario by attribute.
