# Overheating analysis metrics reference

This document describes the **core metrics** produced by `epinterface.analysis.overheating` from hourly EnergyPlus SQL outputs. All series assume **8760 hourly timesteps** per year and zone-major arrays with shape **(zones, timesteps)**.

The postprocessor (`overheating_results_postprocess`) builds **four** result tables on `OverheatingAnalysisResults`:

| Logical output            | Attribute            | Implementing function                         | Typical columns                    |
| ------------------------- | -------------------- | --------------------------------------------- | ---------------------------------- |
| **BasicOverheating**      | _(in `basic_oh`)_    | `calculate_basic_overheating_stats`           | `Total Hours [hr]`                 |
| **ExceedanceDegreeHours** | _(in `edh`)_         | `calculate_edh`                               | `EDH [degC-hr]`                    |
| **HeatIndexCategories**   | _(in `hi`)_          | `calculate_hi_categories`                     | `… [hr]` per category              |
| **ConsecutiveStreaks**    | `consecutive_e_zone` | `calculate_consecutive_hours_above_threshold` | `Streak [hr]`, `Integral [deg-hr]` |

Shared inputs:

- $T_{\mathrm{db},z,t}$: zone dry-bulb air temperature (°C), from _Zone Mean Air Temperature_.
- $\mathrm{RH}_{z,t}$: zone relative humidity (%), from _Zone Air Relative Humidity_.
- For EDH only: $T_{\mathrm{r},z,t}$: mean radiant temperature (°C), from _Zone Mean Radiant Temperature_.

Zone weights $w_z$ are **normalized** to sum to 1: $\tilde{w}_z = w_z / \sum_j w_j$.

---

## 1. BasicOverheating (`calculate_basic_overheating_stats`)

**What it measures:** Counts of hours where **dry-bulb** temperature is above a **heat** threshold (overheating) or below a **cold** threshold (underheating). No humidity or radiant correction.

### Per-threshold, per-zone hour counts

For each configured heat threshold $T^{\mathrm{heat}}_k$ and each zone $z$:

$$H^{\mathrm{over}}_{k,z} = \sum_{t=0}^{8759} \mathbf{1}\bigl[T_{\mathrm{db},z,t} > T^{\mathrm{heat}}_k\bigr].$$

For each configured cold threshold $T^{\mathrm{cold}}_\ell$ and each zone $z$:

$$H^{\mathrm{under}}_{\ell,z} = \sum_{t=0}^{8759} \mathbf{1}\bigl[T_{\mathrm{db},z,t} < T^{\mathrm{cold}}_\ell\bigr].$$

These are the **zone-level** values: one integer hour count per (threshold, zone).

### Building-level aggregates (same thresholds)

For **overheat** thresholds $T^{\mathrm{heat}}_k$:

| Group column         | Formula / rule                                                                                                                                                                                                                                                                |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Any Zone**         | $\sum_t \mathbf{1}\bigl[\exists z: T_{\mathrm{db},z,t} > T^{\mathrm{heat}}_k\bigr]$ — hours in which **at least one** zone exceeds the threshold.                                                                                                                             |
| **Zone Weighted**    | $\sum_z \tilde{w}_z\, H^{\mathrm{over}}_{k,z}$ — **weighted average of the per-zone hour counts** (not “hours where weighted-mean dry-bulb exceeds $T$”).                                                                                                                     |
| **Worst Zone**       | For each $k$, $\max_z H^{\mathrm{over}}_{k,z}$ — largest zone count for that threshold.                                                                                                                                                                                       |
| **Equally Weighted** | Row-wise **mean** over all columns present when this column is built: each **zone** column plus **Any Zone**, **Zone Weighted**, and **Worst Zone**. So it is **not** the same as $\frac{1}{N}\sum_z H^{\mathrm{over}}_{k,z}$ unless those aggregate columns match that mean. |

The same four groups apply to **underheat** thresholds using $T_{\mathrm{db},z,t} < T^{\mathrm{cold}}_\ell$ and the analogous zone sums $H^{\mathrm{under}}_{\ell,z}$.

### Output shape and meaning

- **Index levels:** `Polarity` (`Overheat` | `Underheat`), `Threshold [degC]`, `Aggregation Unit` (`Building` | `Zone`), `Group`.
- **Column:** `Total Hours [hr]`.
- **Building** rows: the four groups above (Any Zone, Zone Weighted, Worst Zone, Equally Weighted).
- **Zone** rows: one value per zone name in `Group` — raw exceedance hour counts $H^{\mathrm{over}}_{k,z}$ or $H^{\mathrm{under}}_{\ell,z}$.

**Interpretation:** This is the simplest overheating/underheating view: **binary hourly violations** of dry-bulb limits, with several ways to roll zones up to a single building number.

---

## 2. ExceedanceDegreeHours (`calculate_edh`)

**What it measures:** **Exceedance degree-hours (EDH)** using **Standard Effective Temperature (SET)** from `pythermalcomfort.models.set_tmp`, not raw dry-bulb. Inputs per timestep are $T_{\mathrm{db}}$, $T_{\mathrm{r}}$, $\mathrm{RH}$, plus global assumptions `ThermalComfortAssumptions`: metabolic rate MET, clothing CLO, and air speed $v$.

Let $\mathrm{SET}_{z,t}$ be the SET returned for zone $z$ at hour $t$ (°C).

### Hot side (overheat)

For each heat threshold $T^{\mathrm{heat}}_k$ and zone $z$:

$$\mathrm{EDH}^{\mathrm{hot}}_{k,z} = \sum_{t=0}^{8759} \max\bigl(0,\, \mathrm{SET}_{z,t} - T^{\mathrm{heat}}_k\bigr).$$

Units: **°C·h** (degree-hours): each hour contributes the positive part of $\mathrm{SET} - T$ in °C, summed over the year.

### Cold side (underheat)

For each cold threshold $T^{\mathrm{cold}}_\ell$ and zone $z$:

$$\mathrm{EDH}^{\mathrm{cold}}_{\ell,z} = \sum_{t=0}^{8759} \max\bigl(0,\, T^{\mathrm{cold}}_\ell - \mathrm{SET}_{z,t}\bigr).$$

### Building-level aggregates

For **Overheat** thresholds:

- **Zone Weighted:** $\sum_z \tilde{w}_z\, \mathrm{EDH}^{\mathrm{hot}}_{k,z}$.
- **Worst Zone:** $\max_z \mathrm{EDH}^{\mathrm{hot}}_{k,z}$.

For **Underheat** thresholds:

- **Zone Weighted:** $\sum_z \tilde{w}_z\, \mathrm{EDH}^{\mathrm{cold}}_{\ell,z}$.
- **Worst Zone:** $\max_z \mathrm{EDH}^{\mathrm{cold}}_{\ell,z}$.

### Output shape and meaning

- **Index levels:** `Polarity` (`Overheat` | `Underheat`), `Threshold [degC]`, `Aggregation Unit` (`Building` | `Zone`), `Group`.
- **Column:** `EDH [degC-hr]`.
- **Zone** rows: per-zone EDH for each threshold.
- **Building** rows: Zone Weighted and Worst Zone only.

**Interpretation:** EDH rewards **magnitude and duration** of discomfort beyond a SET threshold (not just counting hours above/below). Same threshold temperatures as in config, but applied to **SET** instead of dry-bulb.

---

## 3. HeatIndexCategories (`calculate_hi_categories`)

**What it measures:** Apparent temperature via the **Rothfusz regression** (heat index in **°F**), then bins into **NOAA** categories. Counts **hours per category** under several aggregation rules.

### Step A — Heat index in °F

For each zone $z$ and hour $t$, dry-bulb is converted to Fahrenheit: $T_{\mathrm{f}} = T_{\mathrm{db}} \cdot \frac{9}{5} + 32$. With $\mathrm{RH}_{z,t}$ as percent (0–100 scale as used in the regression):

$$
\begin{aligned}
\mathrm{HI}_{z,t} &= -42.379 + 2.04901523\, T_{\mathrm{f}} + 10.14333127\, \mathrm{RH} \\
&\quad - 0.22475541\, T_{\mathrm{f}}\, \mathrm{RH} - 6.83783\times 10^{-3}\, T_{\mathrm{f}}^2 - 5.481717\times 10^{-2}\, \mathrm{RH}^2 \\
&\quad + 1.22874\times 10^{-3}\, T_{\mathrm{f}}^2 \mathrm{RH} + 8.5282\times 10^{-4}\, T_{\mathrm{f}}\, \mathrm{RH}^2 - 1.99\times 10^{-6}\, T_{\mathrm{f}}^2 \mathrm{RH}^2 .
\end{aligned}
$$

### Step B — Category index (NOAA, by $\mathrm{HI}$ in °F)

| Category        | Rule (heat index °F)          |
| --------------- | ----------------------------- |
| Extreme Danger  | $\mathrm{HI} \ge 130$         |
| Danger          | $105 \le \mathrm{HI} \le 129$ |
| Extreme Caution | $90 \le \mathrm{HI} \le 104$  |
| Caution         | $80 \le \mathrm{HI} \le 89$   |
| Normal          | $\mathrm{HI} < 80$            |

Each zone-hour is assigned one category.

### Step C — Building-level “Zone Weighted” series

A **single** building heat index per hour is the **weighted mean** of $\mathrm{HI}_{z,t}$ across zones:

$$\overline{\mathrm{HI}}_t = \sum_z \tilde{w}_z\, \mathrm{HI}_{z,t}.$$

That scalar series is categorized with the same thresholds → **Zone Weighted** hour counts per category (column group name in the building block).

### Step D — Other building-level series

- **Modal per Timestep:** For each hour $t$, take the **modal** category across zones; if multiple modes tie, the implementation picks the mode with the **largest numeric category index** (see `cat_index_map`: Extreme Danger is “worst”). Then count hours per category over the year.
- **Worst per Timestep:** For each hour $t$, take the **maximum** category index among zones (most severe category present). Count hours per category.

### Step E — Zone-level block

For each zone $z$, count how many of the 8760 hours fall in each category. Columns are the five category names with suffix ` [hr]`.

### Output shape and meaning

- **Index:** `Aggregation Unit` (`Building` | `Zone`), optional `Group` for building sub-rows.
- **Building** section: three rows — **Modal per Timestep**, **Worst per Timestep**, **Zone Weighted** — each with five columns `Normal [hr]`, `Caution [hr]`, …, `Extreme Danger [hr]`. Row sums over categories are **8760** for each of these three methods.
- **Zone** section: per-zone hour counts per category (same column names).

**Interpretation:** Heat index is a **humidity-adjusted** discomfort index in original NOAA °F form. **Zone Weighted** summarizes one blended HI per hour; **Worst** and **Modal** describe how often the building appears “bad” when you look at all zones each hour in different ways.

---

## 4. ConsecutiveStreaks (`consecutive_e_zone` / `calculate_consecutive_hours_above_threshold`)

**What it measures:** For each heat threshold, every **maximal run** of consecutive hours with $T_{\mathrm{db},z,t} > T^{\mathrm{heat}}_k$. For each cold threshold, every **maximal run** with $T_{\mathrm{db},z,t} < T^{\mathrm{cold}}_\ell$. Uses **dry-bulb only** (same as basic hours, unlike EDH/SET).

### Run detection

Define the hourly “excess” for overheating at threshold $T^{\mathrm{heat}}_k$:

$$\Delta^{\mathrm{over}}_{k,z,t} = T_{\mathrm{db},z,t} - T^{\mathrm{heat}}_k.$$

A timestep belongs to an **overheat streak** if $\Delta^{\mathrm{over}}_{k,z,t} > 0$ (strictly above threshold). Contiguous hours with that property form one run; the run ends when $\Delta^{\mathrm{over}}_{k,z,t} \le 0$ or the year ends.

For underheating at $T^{\mathrm{cold}}_\ell$:

$$\Delta^{\mathrm{under}}_{\ell,z,t} = T^{\mathrm{cold}}_\ell - T_{\mathrm{db},z,t}.$$

A timestep belongs to an **underheat streak** if $\Delta^{\mathrm{under}}_{\ell,z,t} > 0$ (strictly below threshold). Runs are maximal contiguous segments where this holds.

### Per-run quantities

For each run $r$ of length $L_r$ (hours):

- **Streak length** $L_r$: number of hours in that run (reported as `Streak [hr]`).
- **Integral** for that run: $\sum_{t \in \mathrm{run}\,r} \Delta_{k,z,t}$ where $\Delta$ is $\Delta^{\mathrm{over}}$ or $\Delta^{\mathrm{under}}$ as appropriate. Units **°C·h** (`Integral [deg-hr]`). For a constant excess $\delta$ over the whole run, integral $= L_r \cdot \delta$.

Runs are listed in **time order** for that (threshold, zone) slice. If a zone has $R$ distinct runs in the year, there are up to $R$ non-NaN streak columns before stacking; after the function **stacks** streak indices and **drops NaNs**, you get **one row per run** (not one row per zone with a single “max streak” unless you aggregate yourself).

### Output shape and meaning

- **Index levels:** `Polarity` (`Overheat` | `Underheat`), `Threshold [degC]`, `Zone`, and `Streak Index` (which run in the year: `00000`, `00001`, …).
- **Columns:** `Streak [hr]`, `Integral [deg-hr]`.
- **No building-level aggregation:** this table is **zone- and threshold-only**. Weights are not applied here.

**Interpretation:** Unlike **BasicOverheating**, which only totals **how many** hours exceed a limit, this table captures **how those hours cluster** — long unbroken warm spells vs many short ones — and the **integral** weights **how far** $T_{\mathrm{db}}$ sits on the wrong side of the threshold during each spell.

**Downstream use:** If `OverheatingAnalysisConfig` sets `streak_failure` or `integrated_streak_failure` on a threshold, `compute_zone_at_risk` uses this table to flag zones (count of runs longer than a limit, or sum of integrals for long runs).

---

## Relationship between the four outputs

| Aspect           | BasicOverheating           | ExceedanceDegreeHours      | HeatIndexCategories | ConsecutiveStreaks                    |
| ---------------- | -------------------------- | -------------------------- | ------------------- | ------------------------------------- |
| Primary variable | Dry bulb $T_{\mathrm{db}}$ | SET                        | Rothfusz HI (°F)    | Dry bulb $T_{\mathrm{db}}$            |
| Threshold use    | Config heat/cold °C        | Config heat/cold °C on SET | Fixed HI °F bands   | Config heat/cold °C                   |
| Unit             | Hours (counts)             | °C·h (EDH)                 | Hours per category  | Hours per run + °C·h per run integral |
| Building rollups | Yes                        | Yes                        | Yes                 | No                                    |
