"""Process Results.pq (MultiIndex) for D3 and dashboards."""

from __future__ import annotations

import json
import re
from textwrap import dedent
from typing import cast

import numpy as np
import pandas as pd

# Results values are per m² of conditioned area; multiply by this to get kWh / kW.
AREA_LEVEL = "feature.geometry.energy_model_conditioned_area"


def conditioned_area(df: pd.DataFrame) -> pd.Series:
    """Conditioned floor area (m²) per row, positionally indexed."""
    if AREA_LEVEL not in (df.index.names or []):
        # shortcut: without an area level, totals become sums of per-m² values; fine for old dryruns, not for portfolios.
        return pd.Series(1.0, index=range(len(df)))
    area = pd.to_numeric(df.index.get_level_values(AREA_LEVEL), errors="coerce")
    return pd.Series(area, index=range(len(df))).fillna(0.0)


def _total_kwh(section: pd.DataFrame, area: pd.Series) -> pd.Series:
    """Area-weighted total per column of a per-m² section (rows aligned positionally with area)."""
    return section.mul(area.to_numpy(), axis=0).sum()


def aggregate_by_measurement(df: pd.DataFrame) -> pd.DataFrame:
    """Sum across months; keep Measurement, Aggregation, Meter."""
    if not isinstance(df.columns, pd.MultiIndex):
        return df
    level_names = list(df.columns.names or [])
    if "Month" not in level_names:
        return df.copy()
    levels = [name for name in level_names if name != "Month"]
    return df.reset_index(drop=True).T.groupby(level=levels).sum().T


def _extract_monthly_timeseries(df: pd.DataFrame, aggregation: str) -> list[dict]:
    """Monthly timeseries for one aggregation (End Uses or Utilities). JSON-safe."""
    numeric_df = df.select_dtypes(include="number")
    if numeric_df.empty or not isinstance(numeric_df.columns, pd.MultiIndex):
        return []
    cols = numeric_df.columns
    if cols.names != ["Measurement", "Aggregation", "Meter", "Month"]:
        return []
    mask = (cols.get_level_values("Measurement") == "Energy") & (
        cols.get_level_values("Aggregation") == aggregation
    )
    subset = numeric_df.loc[:, mask]
    if subset.empty:
        return []
    data = []
    for meter in subset.columns.get_level_values("Meter").unique():
        for month in subset.columns.get_level_values("Month").unique():
            col_mask = (subset.columns.get_level_values("Meter") == meter) & (
                subset.columns.get_level_values("Month") == month
            )
            if col_mask.any():
                values = subset.loc[:, col_mask].iloc[:, 0]
                n = len(values)
                std = float(values.std(ddof=1)) if n > 1 else 0.0
                sem = std / (n**0.5) if n > 0 else 0.0
                half_width = 1.96 * sem
                mean_val = float(values.mean())
                data.append({
                    "month": int(month),
                    "meter": str(meter),
                    "avg": mean_val,
                    "min": float(values.min()),
                    "max": float(values.max()),
                    "ci_low": mean_val - half_width,
                    "ci_high": mean_val + half_width,
                })
    return data


def _compute_eui_and_peak(
    df: pd.DataFrame,
) -> tuple[list[float], list[float]]:
    """Per-building total eui and peak as lists (JSON-safe)."""
    numeric_df = df.select_dtypes(include="number")
    if numeric_df.empty or not isinstance(numeric_df.columns, pd.MultiIndex):
        return [], []
    cols = numeric_df.columns
    if cols.names != ["Measurement", "Aggregation", "Meter", "Month"]:
        return [], []
    energy_mask = (cols.get_level_values("Measurement") == "Energy") & (
        cols.get_level_values("Aggregation") == "End Uses"
    )
    energy_subset = numeric_df.loc[:, energy_mask]
    if energy_subset.empty:
        return [], []
    eui = energy_subset.sum(axis=1)
    peak_mask = (cols.get_level_values("Measurement") == "Peak") & (
        cols.get_level_values("Aggregation") == "Raw"
    )
    peak_subset = numeric_df.loc[:, peak_mask]
    if peak_subset.empty:
        return eui.dropna().tolist(), []
    peak = peak_subset.max(axis=1)
    return eui.dropna().tolist(), peak.dropna().tolist()


def _get_color_palette(n: int) -> list[str]:
    base = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    if n <= len(base):
        return base[:n]
    import colorsys

    return [
        f"rgb({int(r * 255)}, {int(g * 255)}, {int(b * 255)})"
        for i in range(n)
        for (r, g, b) in [colorsys.hsv_to_rgb(i / n, 0.7, 0.9)]
    ]


def _get_pastel_end_use_color(end_use: str) -> str:
    m = {
        "heating": "#ffb3ba",
        "cooling": "#bae1ff",
        "lighting": "#ffffba",
        "equipment": "#d3d3d3",
        "fans": "#d4b3ff",
        "pumps": "#baffc9",
        "domestic hot water": "#5b8bd9",
        "refrigeration": "#baffd4",
        "heat rejection": "#ffdfba",
    }
    key = end_use.lower()
    if key in m:
        return m[key]
    for k, v in m.items():
        if k in key or key in k:
            return v
    default = ["#ffb3ba", "#bae1ff", "#ffffba", "#d3d3d3", "#d4b3ff"]
    return default[hash(end_use) % len(default)]


def is_results_format(df: pd.DataFrame) -> bool:
    """True if df has Results.pq-style MultiIndex columns."""
    if not isinstance(df.columns, pd.MultiIndex):
        return False
    names = list(df.columns.names or [])
    return names == ["Measurement", "Aggregation", "Meter", "Month"]


def extract_d3_data(
    df: pd.DataFrame,
    region_name: str = "",
    scenario_name: str = "",
) -> dict:
    """Extract JSON-safe dict for D3 from Results.pq-style dataframe."""
    eui_list, peak_list = _compute_eui_and_peak(df)
    monthly_end_uses = _extract_monthly_timeseries(df, "End Uses")
    monthly_fuels = _extract_monthly_timeseries(df, "Utilities")
    end_use_meters = (
        sorted({r["meter"] for r in monthly_end_uses}) if monthly_end_uses else []
    )
    fuel_meters = sorted({r["meter"] for r in monthly_fuels}) if monthly_fuels else []
    end_use_colors = {m: _get_pastel_end_use_color(m) for m in end_use_meters}
    fuel_colors = dict(
        zip(fuel_meters, _get_color_palette(len(fuel_meters)), strict=True)
    )

    df_agg = aggregate_by_measurement(df)
    area = conditioned_area(df)
    end_uses_total: dict[str, float] = {}
    utilities_total: dict[str, float] = {}
    if "Energy" in (
        df_agg.columns.get_level_values(0)
        if isinstance(df_agg.columns, pd.MultiIndex)
        else []
    ):
        energy = df_agg["Energy"]
        if "End Uses" in energy.columns.get_level_values(0):
            eu = _total_kwh(cast(pd.DataFrame, energy["End Uses"]), area)
            end_uses_total = {str(k): float(v) for k, v in eu.items() if v > 0}
        if "Utilities" in energy.columns.get_level_values(0):
            ut = _total_kwh(cast(pd.DataFrame, energy["Utilities"]), area)
            utilities_total = {str(k): float(v) for k, v in ut.items() if v > 0}

    return {
        "region_name": region_name,
        "scenario_name": scenario_name,
        "eui": eui_list,
        "peak": peak_list,
        "monthly_end_uses": monthly_end_uses,
        "monthly_fuels": monthly_fuels,
        "end_use_meters": end_use_meters,
        "fuel_meters": fuel_meters,
        "end_use_colors": end_use_colors,
        "fuel_colors": fuel_colors,
        "end_uses_total": end_uses_total,
        "utilities_total": utilities_total,
    }


def normalize_fuel_name(name: str) -> str:
    """Normalize meter name for lookup: lowercase, spaces/dashes to underscore."""
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")


# keys used by the retrofit factor form in use_cases (normalize_fuel_name of each _FUEL_LABELS item)
_FORM_FACTOR_KEYS: frozenset[str] = frozenset(
    map(
        normalize_fuel_name,
        ("Electricity", "Natural Gas", "Fuel Oil", "Propane"),
    )
)


def resolve_fuel_factor_key(meter: str) -> str:
    """Map a Utilities column name to the key used in cost/emissions factor dicts.

    Output meters often differ from the form labels: e.g. EnergyPlus uses ``NaturalGas``
    (no space) which normalizes to ``naturalgas``, while the form keys use
    ``natural_gas`` from ``"Natural Gas"``. Without this, .get(fuel_key, 0) looks up
    the wrong string and all fuels can incorrectly get factor 0.
    """
    n = normalize_fuel_name(meter)
    if n in _FORM_FACTOR_KEYS:
        return n
    if n == "naturalgas" or n in ("ng", "natgas", "nat_gas"):
        return "natural_gas"
    if n == "electric":
        return "electricity"
    # "Fuel Oil" -> fuel_oil; EnergyPlus often uses "FuelOil" -> fueloil
    if n == "fueloil" or n.startswith("fuel_oil"):
        return "fuel_oil"
    if n == "lpg":
        return "propane"
    return n


def _get_utilities_kwh_by_fuel(df: pd.DataFrame) -> dict[str, float]:
    """Extract total kWh per fuel from Utilities aggregation."""
    ut = _get_per_building_utilities(df)
    if ut is None:
        return {}
    return {k: float(v) for k, v in ut.sum().items() if v > 0}


def _get_per_building_utilities(df: pd.DataFrame) -> pd.DataFrame | None:
    """Per-building kWh by fuel (per-m² values x conditioned area), indexed by building_id when present."""
    df_agg = aggregate_by_measurement(df)
    if not isinstance(df_agg.columns, pd.MultiIndex):
        return None
    if "Energy" not in df_agg.columns.get_level_values(0):
        return None
    energy = df_agg["Energy"]
    if "Utilities" not in energy.columns.get_level_values(0):
        return None
    ut = energy["Utilities"]
    result = cast(pd.DataFrame, pd.DataFrame(ut) if isinstance(ut, pd.Series) else ut)
    result = result.mul(conditioned_area(df).to_numpy(), axis=0)
    if "building_id" in (df.index.names or []):
        # map frames drop rows, so cost merges must go by id, not position
        result.index = pd.Index(
            df.index.get_level_values("building_id").astype(str), name="building_id"
        )
    return result


def _get_total_conditioned_area(df: pd.DataFrame) -> float:
    """Sum conditioned area (m²) across all buildings from index."""
    if AREA_LEVEL not in (df.index.names or []):
        return 0.0
    area = conditioned_area(df)
    return float(area[area > 0].sum())


def compute_per_building_cost_emissions(
    df: pd.DataFrame,
    energy_cost_factors: dict[str, float],
    emissions_factors: dict[str, float],
) -> pd.DataFrame:
    """Compute per-building energy cost and emissions from Utilities consumption.

    Returns DataFrame with building_id index and columns: energy_cost, emissions.
    """
    ut = _get_per_building_utilities(df)
    if ut is None or ut.empty:
        return pd.DataFrame()

    energy_cost = pd.Series(0.0, index=ut.index)
    emissions = pd.Series(0.0, index=ut.index)
    for meter in ut.columns:
        fuel_key = resolve_fuel_factor_key(meter)
        cost_factor = energy_cost_factors.get(fuel_key, 0.0)
        emissions_factor = emissions_factors.get(fuel_key, 0.0)
        energy_cost += ut[meter] * cost_factor
        emissions += ut[meter] * emissions_factor

    return pd.DataFrame({"energy_cost": energy_cost, "emissions": emissions})


def build_retrofit_map_df(
    df: pd.DataFrame,
    energy_cost_factors: dict[str, float],
    emissions_factors: dict[str, float],
    system_cost_per_sqm: float = 0.0,
    cart_crs: str = "EPSG:3857",
) -> pd.DataFrame | None:
    """Build map-ready df with geometry and retrofit metrics (eui, energy_cost, emissions, etc)."""
    from globi.tools.visualization.utils import build_map_df_from_output

    geo_df = build_map_df_from_output(df, cart_crs=cart_crs)
    if geo_df is None:
        return None

    cost_em = compute_per_building_cost_emissions(
        df, energy_cost_factors, emissions_factors
    )
    if not cost_em.empty:
        cost_reset = cost_em.reset_index()
        bid_col = next(
            (c for c in cost_reset.columns if "building" in str(c).lower()),
            None,
        )
        if bid_col and bid_col in geo_df.columns:
            geo_df = geo_df.assign(**{bid_col: geo_df[bid_col].astype(str)})
            merged = geo_df.merge(
                cost_reset[[bid_col, "energy_cost", "emissions"]],
                on=bid_col,
                how="left",
            )
            geo_df = merged
            geo_df["energy_cost"] = geo_df["energy_cost"].fillna(0)
            geo_df["emissions"] = geo_df["emissions"].fillna(0)
        elif len(cost_em) == len(geo_df):
            geo_df["energy_cost"] = cost_em["energy_cost"].values
            geo_df["emissions"] = cost_em["emissions"].values
        else:
            geo_df["energy_cost"] = 0.0
            geo_df["emissions"] = 0.0
    else:
        geo_df["energy_cost"] = 0.0
        geo_df["emissions"] = 0.0

    if "conditioned_area" in geo_df.columns and system_cost_per_sqm:
        geo_df["capital_cost"] = geo_df["conditioned_area"] * system_cost_per_sqm
    else:
        geo_df["capital_cost"] = 0.0
    geo_df["total_cost"] = geo_df["energy_cost"] + geo_df["capital_cost"]
    return geo_df


def compute_retrofit_cost_emissions(
    dfs: dict[str, pd.DataFrame],
    per_scenario_energy_costs: dict[str, dict[str, float]],
    per_scenario_emissions: dict[str, dict[str, float]],
    system_costs_per_sqm: dict[str, float] | None = None,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]], dict[str, float]]:
    """Compute energy cost and emissions by scenario from Utilities consumption.

    Each scenario can have its own energy cost and emissions factors.

    Returns:
        cost_by_fuel: scenario -> fuel -> $ (annual energy cost)
        emissions_by_fuel: scenario -> fuel -> kg CO2
        capital_costs: scenario -> $ (system_cost_per_sqm * total area)
    """
    cost_by_fuel: dict[str, dict[str, float]] = {}
    emissions_by_fuel: dict[str, dict[str, float]] = {}
    capital_costs: dict[str, float] = {}

    for scenario_name, df in dfs.items():
        utilities = _get_utilities_kwh_by_fuel(df)
        energy_cost_factors = per_scenario_energy_costs.get(scenario_name, {})
        em_factors = per_scenario_emissions.get(scenario_name, {})
        cost_by_fuel[scenario_name] = {}
        emissions_by_fuel[scenario_name] = {}

        for meter, kwh in utilities.items():
            fuel_key = resolve_fuel_factor_key(meter)
            cost_factor = energy_cost_factors.get(fuel_key, 0.0)
            emissions_factor = em_factors.get(fuel_key, 0.0)
            cost_by_fuel[scenario_name][meter] = kwh * cost_factor
            emissions_by_fuel[scenario_name][meter] = kwh * emissions_factor

        if system_costs_per_sqm:
            cost_per_sqm = system_costs_per_sqm.get(scenario_name, 0.0)
            total_area = _get_total_conditioned_area(df)
            capital_costs[scenario_name] = cost_per_sqm * total_area

    return cost_by_fuel, emissions_by_fuel, capital_costs


def extract_retrofit_comparison_data(
    dfs: dict[str, pd.DataFrame],
    region_name: str = "",
    per_scenario_energy_costs: dict[str, dict[str, float]] | None = None,
    per_scenario_emissions: dict[str, dict[str, float]] | None = None,
    system_costs_per_sqm: dict[str, float] | None = None,
) -> dict:
    """Extract comparison data with optional per-scenario cost and emissions.

    The first scenario in dfs is the baseline. With factors, adds annual energy
    cost ($/yr), emissions (kg CO2/yr), one-off capital cost ($), annual savings
    vs baseline ($/yr) and simple payback (years; None without savings or capital).
    """
    base = extract_comparison_data(dfs, region_name)

    if per_scenario_energy_costs or per_scenario_emissions:
        cost_by_fuel, emissions_by_fuel, capital = compute_retrofit_cost_emissions(
            dfs,
            per_scenario_energy_costs or {},
            per_scenario_emissions or {},
            system_costs_per_sqm,
        )
        base["cost_by_fuel"] = cost_by_fuel
        base["emissions_by_fuel"] = emissions_by_fuel
        base["capital_costs"] = capital
        # annual energy cost only: capital is one-off and is reported separately
        cost_totals = {s: sum(cf.values()) for s, cf in cost_by_fuel.items()}
        baseline = next(iter(dfs))
        savings = {s: cost_totals[baseline] - c for s, c in cost_totals.items()}
        base["baseline"] = baseline
        base["cost_totals"] = cost_totals
        base["emissions_totals"] = {
            s: sum(ef.values()) for s, ef in emissions_by_fuel.items()
        }
        base["annual_savings"] = savings
        base["payback_years"] = {
            s: (capital.get(s, 0.0) / savings[s])
            if savings[s] > 0 and capital.get(s)
            else None
            for s in dfs
        }

    return base


def extract_comparison_data(
    dfs: dict[str, pd.DataFrame],
    region_name: str = "",
) -> dict:
    """Extract comparison data for multiple scenarios. JSON-safe dict for D3.

    Parameters
    ----------
    dfs : dict[str, pd.DataFrame]
        mapping of scenario names to Results.pq-style dataframes
    region_name : str
        name of the region
    """
    eui_data: dict[str, list[float]] = {}
    peak_data: dict[str, list[float]] = {}
    end_uses_data: dict[str, dict[str, float]] = {}
    utilities_data: dict[str, dict[str, float]] = {}

    for scenario_name, df in dfs.items():
        eui, peak = _compute_eui_and_peak(df)
        eui_data[scenario_name] = eui
        peak_data[scenario_name] = peak

        df_agg = aggregate_by_measurement(df)
        if not isinstance(df_agg.columns, pd.MultiIndex):
            continue
        if "Energy" not in df_agg.columns.get_level_values(0):
            continue
        energy = df_agg["Energy"]
        area = conditioned_area(df)

        if "End Uses" in energy.columns.get_level_values(0):
            end_uses = _total_kwh(cast(pd.DataFrame, energy["End Uses"]), area)
            end_uses_data[scenario_name] = {
                str(k): float(v) for k, v in end_uses.items() if v > 0
            }

        if "Utilities" in energy.columns.get_level_values(0):
            utilities = _total_kwh(cast(pd.DataFrame, energy["Utilities"]), area)
            utilities_data[scenario_name] = {
                str(k): float(v) for k, v in utilities.items() if v > 0
            }

    # collect all unique meters for consistent colors
    all_end_uses = sorted({k for data in end_uses_data.values() for k in data})
    all_utilities = sorted({k for data in utilities_data.values() for k in data})

    end_use_colors = {eu: _get_pastel_end_use_color(eu) for eu in all_end_uses}
    fuel_colors = (
        dict(zip(all_utilities, _get_color_palette(len(all_utilities)), strict=True))
        if all_utilities
        else {}
    )

    return {
        "region_name": region_name,
        "scenarios": list(dfs.keys()),
        "eui_data": eui_data,
        "peak_data": peak_data,
        "end_uses_data": end_uses_data,
        "utilities_data": utilities_data,
        "end_use_colors": end_use_colors,
        "fuel_colors": fuel_colors,
    }


def apply_scenario_display_names(
    comparison_data: dict,
    run_id_to_display_name: dict[str, str],
) -> dict:
    """Remap scenario keys in comparison_data to display names. Uniquifies duplicates.

    Renames the scenarios list, the baseline, and every dict keyed by scenario.
    """
    scenarios = comparison_data.get("scenarios", [])
    if not run_id_to_display_name or not scenarios:
        return comparison_data
    seen: dict[str, int] = {}
    run_id_to_final: dict[str, str] = {}
    for r in scenarios:
        d = (run_id_to_display_name.get(r, r) or "").strip() or r
        if d in seen:
            seen[d] += 1
            d = f"{d} ({seen[d]})"
        else:
            seen[d] = 1
        run_id_to_final[r] = d
    out: dict = {}
    for key, value in comparison_data.items():
        if key == "scenarios":
            out[key] = [run_id_to_final[r] for r in value]
        elif key == "baseline":
            out[key] = run_id_to_final.get(value, value)
        elif isinstance(value, dict) and value and set(value) <= set(scenarios):
            out[key] = {run_id_to_final[k]: v for k, v in value.items()}
        else:
            out[key] = value
    return out


def per_building_metrics(df: pd.DataFrame) -> pd.DataFrame | None:
    """One row per building (positional index) with energy metrics.

    Columns: building_id, area (m²), eui (kWh/m²), peak_per_sqm (kW/m²),
    total_energy (kWh), total_peak (kW), eui_<end use>.
    """
    if not is_results_format(df):
        return None
    cols = df.columns
    energy = df.loc[
        :,
        (cols.get_level_values(0) == "Energy")
        & (cols.get_level_values(1) == "End Uses"),
    ]
    peak = df.loc[
        :, (cols.get_level_values(0) == "Peak") & (cols.get_level_values(1) == "Raw")
    ]
    if energy.empty:
        return None
    names = list(df.index.names or [])
    ids = (
        df.index.get_level_values("building_id").astype(str)
        if "building_id" in names
        else pd.Index([str(i) for i in range(len(df))])
    )
    area = conditioned_area(df).to_numpy()
    eui = energy.sum(axis=1).to_numpy()
    peak_per_sqm = (
        peak.max(axis=1).to_numpy() if not peak.empty else np.full(len(df), np.nan)
    )
    out = pd.DataFrame({
        "building_id": ids,
        "area": area,
        "eui": eui,
        "peak_per_sqm": peak_per_sqm,
        "total_energy": eui * area,
        "total_peak": peak_per_sqm * area,
    })
    by_end_use = energy.T.groupby(level=2).sum().T
    for meter in by_end_use.columns:
        out[f"eui_{str(meter).lower().replace(' ', '_')}"] = by_end_use[
            meter
        ].to_numpy()
    return out


def portfolio_kpis(df: pd.DataFrame) -> dict[str, float]:
    """Headline numbers: buildings, floor area (m²), energy (kWh/yr), area-weighted EUI (kWh/m²/yr)."""
    m = per_building_metrics(df)
    if m is None or m.empty:
        return {"buildings": float(len(df)), "area": 0.0, "energy": 0.0, "eui": 0.0}
    area, energy = float(m["area"].sum()), float(m["total_energy"].sum())
    return {
        "buildings": float(len(m)),
        "area": area,
        "energy": energy,
        "eui": energy / area if area else 0.0,
    }


# attributes that are never useful as filters
_FILTER_EXCLUDE = re.compile(r"shading_mask|orientation|occupied_area")
_AGE_NAME = re.compile(r"(^|[._])(age|year|vintage|built)", re.IGNORECASE)
_SIZE_NAME = re.compile(r"(^|[._])size", re.IGNORECASE)


def filter_candidates(df: pd.DataFrame, max_categories: int = 50) -> list[str]:
    """Index levels users can filter by: feature.* levels with more than one value.

    Ordered size, age, other semantic fields, then the rest; categorical levels
    with more than max_categories values are left out.
    """
    out = []
    for name in df.index.names or []:
        if not str(name).startswith("feature.") or _FILTER_EXCLUDE.search(str(name)):
            continue
        values = df.index.get_level_values(name)
        n = values.nunique()
        is_numeric = pd.api.types.is_numeric_dtype(
            values
        ) and not pd.api.types.is_bool_dtype(values)
        if n > 1 and (is_numeric or n <= max_categories):
            out.append(str(name))

    def rank(name: str) -> tuple[int, str]:
        last = name.rsplit(".", 1)[-1]
        if name == AREA_LEVEL or _SIZE_NAME.search(last):
            return (0, name)
        if _AGE_NAME.search(last):
            return (1, name)
        # semantic fields (typology, systems, ...) mean more to users than geometry
        return (2 if name.startswith("feature.semantic.") else 3, name)

    return sorted(out, key=rank)


def default_filters(candidates: list[str]) -> list[str]:
    """Floor area and the first age-like attribute, when present."""
    size = [c for c in candidates if c == AREA_LEVEL]
    age = [c for c in candidates if _AGE_NAME.search(c.rsplit(".", 1)[-1])][:1]
    return size + age


def filter_label(name: str) -> str:
    """Readable label for an index level, e.g. feature.semantic.Age_bracket -> Age bracket."""
    if name == AREA_LEVEL:
        return "Floor area (m²)"
    return name.rsplit(".", 1)[-1].replace("_", " ").capitalize()


def filter_mask(df: pd.DataFrame, selections: dict[str, tuple | list]) -> np.ndarray:
    """Rows matching every selection: (low, high) for numeric levels, allowed values otherwise.

    Levels missing from df are ignored, so one set of filters can be applied to several scenarios.
    """
    mask = np.ones(len(df), dtype=bool)
    names = set(df.index.names or [])
    for name, sel in selections.items():
        if name not in names:
            continue
        values = df.index.get_level_values(name)
        if isinstance(sel, tuple):
            num = pd.to_numeric(values, errors="coerce")
            mask &= (num >= sel[0]) & (num <= sel[1])
        elif sel:
            mask &= values.isin(list(sel))
    return mask


def create_results_d3_html(data: dict, title: str = "results summary") -> str:
    """Build D3 HTML for eui/peak histograms and end use / utility pies from extract_d3_data output."""
    data_json = json.dumps(data, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.75rem; background: #f9fafb; color: #111827; }}
          h1 {{ font-size: 1.1rem; margin: 0 0 0.75rem 0; }}
          .layout {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }}
          .card {{ background: #fff; border-radius: 0.75rem; padding: 0.75rem 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb; }}
          .card h2 {{ font-size: 0.95rem; margin: 0 0 0.5rem 0; }}
          .chart {{ width: 100%; height: 240px; }}
          .axis-label {{ fill: #4b5563; font-size: 11px; }}
          .tooltip {{ position: absolute; background: #111827; color: #e5e7eb; padding: 0.35rem 0.55rem; border-radius: 0.5rem; font-size: 0.75rem; pointer-events: none; z-index: 1000; }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <h1>{title}</h1>
        <div class="layout">
          <div class="card"><h2>EUI distribution</h2><div id="eui-hist" class="chart"></div></div>
          <div class="card"><h2>Peak distribution</h2><div id="peak-hist" class="chart"></div></div>
          <div class="card"><h2>End uses</h2><div id="end-use-pie" class="chart"></div></div>
          <div class="card"><h2>Utilities</h2><div id="util-pie" class="chart"></div></div>
        </div>
        <script>
          const d = {data_json};
          const tooltip = d3.select("body").append("div").attr("class", "tooltip").style("opacity", 0);

          function hist(containerId, values, label) {{
            const el = document.getElementById(containerId);
            if (!el || !values.length) {{ el && (el.innerHTML = "no data"); return; }}
            d3.select(el).selectAll("*").remove();
            const width = el.clientWidth || 280;
            const height = 240;
            const margin = {{ top: 16, right: 16, bottom: 36, left: 44 }};
            const x = d3.scaleLinear().domain(d3.extent(values)).nice().range([margin.left, width - margin.right]);
            const bins = d3.bin().domain(x.domain()).thresholds(25)(values);
            const y = d3.scaleLinear().domain([0, d3.max(bins, b => b.length) || 1]).nice().range([height - margin.bottom, margin.top]);
            const svg = d3.select(el).append("svg").attr("width", width).attr("height", height);
            svg.selectAll("rect").data(bins).enter().append("rect")
              .attr("x", d => x(d.x0)).attr("y", d => y(d.length))
              .attr("width", d => Math.max(0, x(d.x1) - x(d.x0) - 1)).attr("height", d => y(0) - y(d.length))
              .attr("fill", "#4f46e5").attr("opacity", 0.85)
              .on("mouseover", (ev, d) => {{ tooltip.style("opacity", 1).html("range: [" + d3.format(",.2f")(d.x0) + ", " + d3.format(",.2f")(d.x1) + ") count: " + d.length).style("left", (ev.pageX + 10) + "px").style("top", (ev.pageY - 28) + "px"); }})
              .on("mouseout", () => tooltip.style("opacity", 0));
            svg.append("g").attr("transform", "translate(0," + (height - margin.bottom) + ")").call(d3.axisBottom(x).ticks(6));
            svg.append("g").attr("transform", "translate(" + margin.left + ",0)").call(d3.axisLeft(y).ticks(5));
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle").attr("x", width/2).attr("y", height - 8).text(label);
          }}

          function pie(containerId, obj, colors) {{
            const el = document.getElementById(containerId);
            if (!el) return;
            const entries = Object.entries(obj).filter(([k,v]) => v > 0);
            if (!entries.length) {{ el.innerHTML = "no data"; return; }}
            d3.select(el).selectAll("*").remove();
            const width = Math.min(el.clientWidth || 280, 280);
            const height = 240;
            const radius = Math.min(width, height) / 2 - 24;
            const data = entries.map(([label, value]) => ({{ label, value }}));
            const color = d3.scaleOrdinal().domain(data.map(d => d.label)).range(data.map(d => colors[d.label] || "#94a3b8"));
            const pie = d3.pie().value(d => d.value).sort(null);
            const arc = d3.arc().innerRadius(0).outerRadius(radius);
            const svg = d3.select(el).append("svg").attr("width", width).attr("height", height);
            const g = svg.append("g").attr("transform", "translate(" + width/2 + "," + height/2 + ")");
            g.selectAll("path").data(pie(data)).enter().append("path").attr("d", arc).attr("fill", d => color(d.data.label)).attr("stroke", "#fff").attr("stroke-width", 1)
              .on("mouseover", (ev, d) => {{ tooltip.style("opacity", 1).html(d.data.label + ": " + d3.format(",.2f")(d.data.value)).style("left", (ev.pageX + 10) + "px").style("top", (ev.pageY - 28) + "px"); }})
              .on("mouseout", () => tooltip.style("opacity", 0));
          }}

          hist("eui-hist", d.eui || [], "EUI");
          hist("peak-hist", d.peak || [], "Peak");
          pie("end-use-pie", d.end_uses_total || {{}}, d.end_use_colors || {{}});
          pie("util-pie", d.utilities_total || {{}}, d.fuel_colors || {{}});
        </script>
      </body>
    </html>
    """
    return dedent(html)
