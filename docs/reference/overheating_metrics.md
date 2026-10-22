# Overheating analysis metrics reference

This page describes the overheating metrics that `epinterface.analysis.overheating` calculates from the hourly EnergyPlus SQL output. GloBI calculates these metrics only when the manifest has an `overheating_config` (see [section D of the tutorial](../tutorials/run-simulations/tutorial.md#d-overheating-and-hourly-outputs)).

All series must have **8760 hourly timesteps** per year. The functions use arrays with shape **(zones, timesteps)** and raise an error for other shapes.

## Output tables

The postprocessor `overheating_results_postprocess` returns an `OverheatingAnalysisResults` object. GloBI saves four of its tables:

| GloBI dataframe key        | Attribute            | Function                                      | Columns                            |
| -------------------------- | -------------------- | --------------------------------------------- | ---------------------------------- |
| **BasicOverheating**       | `basic_oh`           | `calculate_basic_overheating_stats`           | `Total Hours [hr]`                 |
| **ExceedanceDegreeHours**  | `edh`                | `calculate_edh`                               | `EDH [degC-hr]`                    |
| **HeatIndexCategories**    | `hi`                 | `calculate_hi_categories`                     | `… [hr]`, one per category         |
| **ConsecutiveExceedances** | `consecutive_e_zone` | `calculate_consecutive_hours_above_threshold` | `Streak [hr]`, `Integral [deg-hr]` |

The results object also has a fifth table, `zone_at_risk` (from `compute_zone_at_risk`). GloBI does not save it.

In GloBI outputs, each table also has the feature index of the building (`building_id`, `feature.semantic.*`, ...) in front of the index levels below. GloBI saves `ConsecutiveExceedances` only if at least one streak occurs.

## Inputs

- $T_{\mathrm{db},z,t}$: zone dry-bulb air temperature (°C), from _Zone Mean Air Temperature_.
- $\mathrm{RH}_{z,t}$: zone relative humidity (%), from _Zone Air Relative Humidity_.
- $T_{\mathrm{r},z,t}$: mean radiant temperature (°C), from _Zone Mean Radiant Temperature_. Only EDH uses this input.
- Thresholds: `heat_thresholds` and `cold_thresholds` in the overheating config. The defaults are 26, 30 and 35 °C (heat) and 10 and 5 °C (cold).

The zone weights $w_z$ are the zone floor areas. The functions normalize the weights so that they sum to 1: $\tilde{w}_z = w_z / \sum_j w_j$.

---

## 1. BasicOverheating (`calculate_basic_overheating_stats`)

**What it measures:** the number of hours with a **dry-bulb** temperature above a **heat** threshold (overheating) or below a **cold** threshold (underheating). This metric does not correct for humidity or radiant temperature.

### Per-threshold, per-zone hour counts

For each heat threshold $T^{\mathrm{heat}}_k$ and each zone $z$:

$$H^{\mathrm{over}}_{k,z} = \sum_{t=0}^{8759} \mathbf{1}\bigl[T_{\mathrm{db},z,t} > T^{\mathrm{heat}}_k\bigr].$$

For each cold threshold $T^{\mathrm{cold}}_\ell$ and each zone $z$:

$$H^{\mathrm{under}}_{\ell,z} = \sum_{t=0}^{8759} \mathbf{1}\bigl[T_{\mathrm{db},z,t} < T^{\mathrm{cold}}_\ell\bigr].$$

These are the **zone-level** values: one hour count for each threshold and zone.

### Building-level aggregates (same thresholds)

For each **overheat** threshold $T^{\mathrm{heat}}_k$:

| Group column         | Formula or rule                                                                                                                                                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Any Zone**         | $\sum_t \mathbf{1}\bigl[\exists z: T_{\mathrm{db},z,t} > T^{\mathrm{heat}}_k\bigr]$: the hours in which **at least one** zone is above the threshold.                                                                           |
| **Zone Weighted**    | $\sum_z \tilde{w}_z\, H^{\mathrm{over}}_{k,z}$: the **weighted average of the zone hour counts**. It is not the number of hours in which the weighted mean dry-bulb temperature is above $T$.                                   |
| **Worst Zone**       | $\max_z H^{\mathrm{over}}_{k,z}$: the largest zone hour count for the threshold.                                                                                                                                                |
| **Equally Weighted** | The row **mean** over all zone columns plus **Any Zone**, **Zone Weighted** and **Worst Zone**. Thus it is not equal to $\frac{1}{N}\sum_z H^{\mathrm{over}}_{k,z}$, unless the three aggregate columns are equal to that mean. |

The same four groups apply to the **underheat** thresholds, with $T_{\mathrm{db},z,t} < T^{\mathrm{cold}}_\ell$ and the zone counts $H^{\mathrm{under}}_{\ell,z}$.

### Output shape and meaning

- **Index levels:** `Polarity` (`Overheat` | `Underheat`), `Threshold [degC]`, `Aggregation Unit` (`Building` | `Zone`), `Group`.
- **Column:** `Total Hours [hr]`.
- **Building** rows: the four groups above (Any Zone, Zone Weighted, Worst Zone, Equally Weighted).
- **Zone** rows: one row for each zone, with the zone name in `Group`. The value is the hour count $H^{\mathrm{over}}_{k,z}$ or $H^{\mathrm{under}}_{\ell,z}$.

**Interpretation:** this is the simplest view of overheating and underheating. It counts the hours that are outside the dry-bulb limits, and gives several ways to combine the zones into one building value.

---

## 2. ExceedanceDegreeHours (`calculate_edh`)

**What it measures:** **exceedance degree-hours (EDH)** of the **Standard Effective Temperature (SET)**, not of the dry-bulb temperature. `pythermalcomfort.models.set_tmp` calculates SET for each hour from $T_{\mathrm{db}}$, $T_{\mathrm{r}}$ and $\mathrm{RH}$. It also uses the `ThermalComfortAssumptions` of the config: metabolic rate `met` (default 1.1), clothing `clo` (default 0.5) and air speed `v` (default 0.1 m/s).

$\mathrm{SET}_{z,t}$ is the SET for zone $z$ at hour $t$ (°C).

### Hot side (overheat)

For each heat threshold $T^{\mathrm{heat}}_k$ and zone $z$:

$$\mathrm{EDH}^{\mathrm{hot}}_{k,z} = \sum_{t=0}^{8759} \max\bigl(0,\, \mathrm{SET}_{z,t} - T^{\mathrm{heat}}_k\bigr).$$

Unit: **°C·h** (degree-hours). Each hour adds the positive part of $\mathrm{SET} - T$, and the sum covers the full year.

### Cold side (underheat)

For each cold threshold $T^{\mathrm{cold}}_\ell$ and zone $z$:

$$\mathrm{EDH}^{\mathrm{cold}}_{\ell,z} = \sum_{t=0}^{8759} \max\bigl(0,\, T^{\mathrm{cold}}_\ell - \mathrm{SET}_{z,t}\bigr).$$

### Building-level aggregates

For the **Overheat** thresholds:

- **Zone Weighted:** $\sum_z \tilde{w}_z\, \mathrm{EDH}^{\mathrm{hot}}_{k,z}$.
- **Worst Zone:** $\max_z \mathrm{EDH}^{\mathrm{hot}}_{k,z}$.

For the **Underheat** thresholds:

- **Zone Weighted:** $\sum_z \tilde{w}_z\, \mathrm{EDH}^{\mathrm{cold}}_{\ell,z}$.
- **Worst Zone:** $\max_z \mathrm{EDH}^{\mathrm{cold}}_{\ell,z}$.

### Output shape and meaning

- **Index levels:** `Polarity` (`Overheat` | `Underheat`), `Threshold [degC]`, `Aggregation Unit` (`Building` | `Zone`), `Group`.
- **Column:** `EDH [degC-hr]`.
- **Zone** rows: the EDH of each zone for each threshold.
- **Building** rows: only Zone Weighted and Worst Zone.

**Interpretation:** EDH increases with both the **magnitude** and the **duration** of discomfort beyond a threshold. It does not only count hours. It uses the same threshold temperatures as the config, but applies them to **SET**, not to the dry-bulb temperature.

---

## 3. HeatIndexCategories (`calculate_hi_categories`)

**What it measures:** the apparent temperature from the **Rothfusz regression** (heat index in **°F**), sorted into the **NOAA** categories. The table counts the **hours in each category** with several aggregation rules.

### Step A — Heat index in °F

For each zone $z$ and hour $t$, the function converts the dry-bulb temperature to Fahrenheit: $T_{\mathrm{f}} = T_{\mathrm{db}} \cdot \frac{9}{5} + 32$. $\mathrm{RH}_{z,t}$ is in percent (0–100):

$$
\begin{aligned}
\mathrm{HI}_{z,t} &= -42.379 + 2.04901523\, T_{\mathrm{f}} + 10.14333127\, \mathrm{RH} \\
&\quad - 0.22475541\, T_{\mathrm{f}}\, \mathrm{RH} - 6.83783\times 10^{-3}\, T_{\mathrm{f}}^2 - 5.481717\times 10^{-2}\, \mathrm{RH}^2 \\
&\quad + 1.22874\times 10^{-3}\, T_{\mathrm{f}}^2 \mathrm{RH} + 8.5282\times 10^{-4}\, T_{\mathrm{f}}\, \mathrm{RH}^2 - 1.99\times 10^{-6}\, T_{\mathrm{f}}^2 \mathrm{RH}^2 .
\end{aligned}
$$

### Step B — Category index (NOAA, by $\mathrm{HI}$ in °F)

| Category        | Rule (heat index °F)        |
| --------------- | --------------------------- |
| Extreme Danger  | $\mathrm{HI} \ge 130$       |
| Danger          | $105 \le \mathrm{HI} < 130$ |
| Extreme Caution | $90 \le \mathrm{HI} < 105$  |
| Caution         | $80 \le \mathrm{HI} < 90$   |
| Normal          | $\mathrm{HI} < 80$          |

Each zone-hour gets one category.

### Step C — Building-level “Zone Weighted” series

The building heat index for each hour is the **weighted mean** of $\mathrm{HI}_{z,t}$ over the zones:

$$\overline{\mathrm{HI}}_t = \sum_z \tilde{w}_z\, \mathrm{HI}_{z,t}.$$

The function sorts this series into the same categories. The result is the **Zone Weighted** row: the hour count for each category.

### Step D — Other building-level series

- **Modal per Timestep:** for each hour $t$, the function takes the **modal** category over the zones. If two or more modes tie, it takes the mode with the **largest category index**, which is the most severe (see `cat_index_map`). Then it counts the hours in each category.
- **Worst per Timestep:** for each hour $t$, the function takes the **maximum** category index over the zones (the most severe category). Then it counts the hours in each category.

### Step E — Zone-level block

For each zone $z$, the function counts the hours (of 8760) in each category.

### Output shape and meaning

- **Index levels:** `Aggregation Unit` (`Building` | `Zone`), `Group`.
- **Columns:** one for each category: `Extreme Danger [hr]`, `Danger [hr]`, `Extreme Caution [hr]`, `Caution [hr]`, `Normal [hr]`.
- **Building** rows: three groups: **Modal per Timestep**, **Worst per Timestep** and **Zone Weighted**. For each of these rows, the categories sum to **8760**.
- **Zone** rows: one row for each zone, with the zone name in `Group`.

**Interpretation:** the heat index is a **humidity-adjusted** discomfort index, in the NOAA °F form. **Zone Weighted** gives one combined heat index for each hour. **Worst per Timestep** and **Modal per Timestep** show how often the building is in a bad category when you look at all zones in each hour.

---

## 4. ConsecutiveExceedances (`consecutive_e_zone` / `calculate_consecutive_hours_above_threshold`)

**What it measures:** each **maximal run** of consecutive hours with $T_{\mathrm{db},z,t} > T^{\mathrm{heat}}_k$, for each heat threshold. For each cold threshold, each **maximal run** with $T_{\mathrm{db},z,t} < T^{\mathrm{cold}}_\ell$. This metric uses **only the dry-bulb temperature**, as BasicOverheating does (EDH uses SET).

### Run detection

The hourly excess for overheating at threshold $T^{\mathrm{heat}}_k$ is:

$$\Delta^{\mathrm{over}}_{k,z,t} = T_{\mathrm{db},z,t} - T^{\mathrm{heat}}_k.$$

An hour is part of an **overheat streak** if $\Delta^{\mathrm{over}}_{k,z,t} > 0$ (strictly above the threshold). Consecutive hours with this property make one run. The run stops when $\Delta^{\mathrm{over}}_{k,z,t} \le 0$ or when the year ends.

For underheating at $T^{\mathrm{cold}}_\ell$:

$$\Delta^{\mathrm{under}}_{\ell,z,t} = T^{\mathrm{cold}}_\ell - T_{\mathrm{db},z,t}.$$

An hour is part of an **underheat streak** if $\Delta^{\mathrm{under}}_{\ell,z,t} > 0$ (strictly below the threshold). The runs are the maximal sets of consecutive hours with this property.

### Per-run quantities

For each run $r$ of length $L_r$ (hours):

- **Streak length** $L_r$: the number of hours in the run (`Streak [hr]`).
- **Integral** of the run: $\sum_{t \in \mathrm{run}\,r} \Delta_{k,z,t}$, where $\Delta$ is $\Delta^{\mathrm{over}}$ or $\Delta^{\mathrm{under}}$. Unit: **°C·h** (`Integral [deg-hr]`). For a constant excess $\delta$ over the run, the integral is $L_r \cdot \delta$.

The runs are in **time order** for each threshold and zone. The function makes one column for each run, then stacks the columns and removes the empty values. Thus the table has **one row for each run**. To get the longest streak of a zone, aggregate the rows yourself.

### Output shape and meaning

- **Index levels:** `Polarity` (`Overheat` | `Underheat`), `Threshold [degC]`, `Zone`, and `Streak Index` (the number of the run in the year: `00000`, `00001`, …).
- **Columns:** `Streak [hr]`, `Integral [deg-hr]`.
- **No building-level aggregation:** the table has only zone and threshold rows. It does not use the zone weights.

**Interpretation:** **BasicOverheating** counts **how many** hours are outside a limit. This table shows **how those hours are grouped**: long continuous warm periods or many short ones. The **integral** also shows **how far** $T_{\mathrm{db}}$ is past the threshold during each run.

**Downstream use:** if a threshold in `OverheatingAnalysisConfig` has `streak_failure` or `integrated_streak_failure`, `compute_zone_at_risk` uses this table to flag zones. It counts the runs longer than a limit, or sums the integrals of the long runs.

---

## Relationship between the four outputs

| Aspect           | BasicOverheating           | ExceedanceDegreeHours      | HeatIndexCategories | ConsecutiveExceedances                |
| ---------------- | -------------------------- | -------------------------- | ------------------- | ------------------------------------- |
| Primary variable | Dry bulb $T_{\mathrm{db}}$ | SET                        | Rothfusz HI (°F)    | Dry bulb $T_{\mathrm{db}}$            |
| Threshold use    | Config heat/cold °C        | Config heat/cold °C on SET | Fixed HI °F bands   | Config heat/cold °C                   |
| Unit             | Hours (counts)             | °C·h (EDH)                 | Hours per category  | Hours per run + °C·h per run integral |
| Building rollups | Yes                        | Yes                        | Yes                 | No                                    |
