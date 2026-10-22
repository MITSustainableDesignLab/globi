"""Compare scenarios against a baseline: energy, and optionally cost, emissions and payback."""

from __future__ import annotations

from typing import Any, cast

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from globi.tools.visualization.data_sources import DataSource
from globi.tools.visualization.plotting import (
    EnergyIntensityUnit,
    convert_eui_scenario_dict,
    create_building_map_deck,
    create_building_map_deck_from_cache,
    create_comparison_bar_d3_html,
    create_comparison_kde_d3_html,
    create_comparison_stacked_bar_d3_html,
    energy_intensity_axis_label,
    energy_intensity_factor,
)
from globi.tools.visualization.results_data import (
    apply_scenario_display_names,
    build_retrofit_map_df,
    extract_comparison_data,
    extract_retrofit_comparison_data,
    filter_mask,
    is_results_format,
    normalize_fuel_name,
    portfolio_kpis,
)
from globi.tools.visualization.utils import infer_rotated_rectangle_crs_hint
from globi.tools.visualization.views.common import (
    building_filters,
    eui_unit,
    eui_unit_suffix,
    fmt_energy,
    load_run,
    map_caption,
    map_crs_caption,
    ran,
    render_colormap_legend,
    resolve_map_crs,
    run_label,
    scenario_label,
    section_download,
    streamlit_theme,
)

# fuel labels matching simulation output (EnergyPlus Utilities meters)
_FUEL_LABELS = ("Electricity", "Natural Gas", "Fuel Oil", "Propane")
# placeholder defaults; users should replace them with local tariffs and grid factors
_DEFAULT_ENERGY_COSTS = (0.22, 0.05, 0.10, 0.08)
_DEFAULT_EMISSIONS = (0.4, 0.2, 0.27, 0.23)


def _build_eui_csv_for_display(
    comparison_data: dict, unit: EnergyIntensityUnit
) -> pd.DataFrame:
    """Build padded scenario columns from eui lists in display units."""
    eui = convert_eui_scenario_dict(comparison_data.get("eui_data", {}) or {}, unit)
    if not eui:
        return pd.DataFrame()
    max_len = max((len(v) for v in eui.values()), default=0)
    return pd.DataFrame({k: v + [None] * (max_len - len(v)) for k, v in eui.items()})


def _build_stacked_csv(comparison_data: dict, data_key: str) -> pd.DataFrame:
    """Build csv-friendly dataframe from stacked bar data."""
    data = comparison_data.get(data_key, {})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data).T.fillna(0)
    df.index.name = "scenario"
    return df.reset_index()


def _uniquify_display_names(run_ids, raw_names: dict[str, str]) -> dict[str, str]:
    """Build run_id -> unique display name mapping, appending (n) on collisions."""
    seen: dict[str, int] = {}
    out: dict[str, str] = {}
    for rid in run_ids:
        d = (raw_names.get(rid, rid) or "").strip() or rid
        if d in seen:
            seen[d] += 1
            d = f"{d} ({seen[d]})"
        else:
            seen[d] = 1
        out[rid] = d
    return out


def _pct_delta(value: float, base: float) -> str | None:
    return f"{(value - base) / base:+.0%}" if base else None


def _compact(v: float) -> str:
    """1234567 -> 1.2M, so big costs and emissions fit in a metric tile."""
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(v) >= div:
            return f"{v / div:,.1f}{unit}"
    return f"{v:,.0f}"


def _signed(v: float, prefix: str = "") -> str:
    return f"{'+' if v >= 0 else '-'}{prefix}{_compact(abs(v))}"


def _scenario_inputs(
    selected: list[str], with_costs: bool
) -> tuple[dict[str, str], dict[str, float], dict[str, dict], dict[str, dict]]:
    """Scenario names, system cost and per-scenario fuel prices / emission factors.

    Returns (names, system_costs_per_sqm, per_scenario_energy_costs,
    per_scenario_emissions), all keyed by run id.
    """
    labels = {r: scenario_label(r, selected) for r in selected}
    key = hash(tuple(selected))
    scen = pd.DataFrame({
        "Scenario": [labels[r] for r in selected],
        "Name in charts": [labels[r] for r in selected],
    })
    if with_costs:
        scen["System cost ($/m²)"] = 0.0
    edited = st.data_editor(
        scen,
        hide_index=True,
        disabled=["Scenario"],
        key=f"compare_scenarios_table_{key}_{with_costs}",
    )
    st.caption(
        "Rename scenarios for the charts."
        + (
            " System cost is the one-off cost per m² of floor area, used for payback."
            if with_costs
            else ""
        )
    )
    names = dict(zip(selected, edited["Name in charts"].astype(str), strict=True))
    syscost = (
        {
            r: float(v or 0.0)
            for r, v in zip(selected, edited["System cost ($/m²)"], strict=True)
        }
        if with_costs
        else {}
    )
    if not with_costs:
        return names, syscost, {}, {}

    def fuel_table(title: str, defaults: tuple[float, ...], tkey: str) -> dict:
        st.markdown(f"**{title}**")
        table = pd.DataFrame(
            [dict(zip(_FUEL_LABELS, defaults, strict=True)) for _ in selected],
            index=pd.Index([labels[r] for r in selected]),
        )
        edited = st.data_editor(table, key=f"{tkey}_{key}")
        return {
            r: {
                normalize_fuel_name(f): float(edited.loc[labels[r], f])
                for f in _FUEL_LABELS
            }
            for r in selected
        }

    col_cost, col_em = st.columns(2)
    with col_cost:
        costs = fuel_table(
            "Fuel prices ($/kWh)", _DEFAULT_ENERGY_COSTS, "compare_prices"
        )
    with col_em:
        emissions = fuel_table(
            "Emission factors (kg CO2/kWh)", _DEFAULT_EMISSIONS, "compare_emissions"
        )
    st.caption(
        "Placeholder values; replace them with your local tariffs and grid factors."
    )
    return names, syscost, costs, emissions


def _load_scenarios(
    data_source: DataSource, run_ids: list[str]
) -> dict[str, pd.DataFrame]:
    """Load runs in order, skipping (with a warning) any that can't be compared."""
    dfs: dict[str, pd.DataFrame] = {}
    for run_id in run_ids:
        try:
            df, _ = load_run(data_source, run_id)
        except Exception as exc:
            st.warning(f"Couldn't load {run_label(run_id)}: {exc}")
            continue
        if is_results_format(df):
            dfs[run_id] = df
        else:
            st.warning(f"{run_label(run_id)} has no energy results; skipped.")
    return dfs


def render_compare_page(data_source: DataSource) -> None:
    """Compare scenarios against a baseline: energy, and optionally cost, emissions and payback."""
    st.header("Compare scenarios")

    available_runs = data_source.list_available_runs()
    if len(available_runs) < 2:
        st.info("You need at least two runs to compare.")
        return

    col_runs, col_base = st.columns([3, 1])
    with col_runs:
        selected = st.multiselect(
            "Scenarios",
            options=available_runs,
            default=available_runs[:2],
            format_func=run_label,
            key="compare_runs",
        )
    if len(selected) < 2:
        st.info("Pick at least two scenarios.")
        return
    with col_base:
        baseline = st.selectbox(
            "Baseline",
            options=selected,
            format_func=lambda r: scenario_label(r, selected),
            help="Savings and changes are measured against this scenario.",
            key=f"compare_baseline_{hash(tuple(selected))}",
        )

    with_costs = st.toggle("Include costs and emissions", key="compare_costs")
    names, syscost, costs, emissions = _scenario_inputs(selected, with_costs)

    if not ran("Compare", "compare_go"):
        return

    dfs = _load_scenarios(
        data_source, [baseline, *(r for r in selected if r != baseline)]
    )
    if baseline not in dfs or len(dfs) < 2:
        st.error("Couldn't load enough scenarios (including the baseline) to compare.")
        return

    selections = building_filters(dfs[baseline])
    masks = {r: filter_mask(df, selections) for r, df in dfs.items()}
    if not all(m.any() for m in masks.values()):
        st.warning("No buildings match the filters in at least one scenario.")
        return
    views = {
        r: df if masks[r].all() else cast(pd.DataFrame, df[masks[r]])
        for r, df in dfs.items()
    }
    if selections:
        st.caption(
            f"Filtered to {masks[baseline].sum():,} of {len(masks[baseline]):,} "
            "baseline buildings"
        )
    display = _uniquify_display_names(list(dfs), names)
    base_n = int(masks[baseline].sum())
    mismatched = [
        f"{display[r]} ({int(m.sum()):,})"
        for r, m in masks.items()
        if m.sum() != base_n
    ]
    if mismatched:
        st.warning(
            f"These scenarios cover a different number of buildings than the baseline "
            f"({base_n:,}): {', '.join(mismatched)}. Totals aren't comparable; "
            "compare energy use intensity instead."
        )

    unit = eui_unit()
    with st.spinner("Comparing scenarios..."):
        if with_costs:
            data = extract_retrofit_comparison_data(
                views,
                per_scenario_energy_costs=costs,
                per_scenario_emissions=emissions,
                system_costs_per_sqm=syscost,
            )
        else:
            data = extract_comparison_data(views)
        data = apply_scenario_display_names(data, display)

    _render_scenario_kpis(views, display, data, baseline, unit)
    _render_comparison_charts(data, unit)
    _render_compare_map(
        {display[r]: (r, views[r]) for r in dfs},
        f"{selections!r}",
        costs,
        emissions,
        syscost,
        unit,
    )


def _render_scenario_kpis(
    views: dict[str, pd.DataFrame],
    names: dict[str, str],
    data: dict,
    baseline: str,
    unit: EnergyIntensityUnit,
) -> None:
    """One row of headline numbers per scenario, with changes against the baseline."""
    kpis = {r: portfolio_kpis(df) for r, df in views.items()}
    base_k, base_name = kpis[baseline], names[baseline]
    with_costs = "cost_totals" in data
    factor = energy_intensity_factor(unit)
    for run_id, k in kpis.items():
        name = names[run_id]
        is_base = run_id == baseline
        st.markdown(f"**{name}**" + (" · baseline" if is_base else ""))
        cols = st.columns(5 if with_costs else 2)
        cols[0].metric(
            "Energy use intensity",
            f"{k['eui'] * factor:,.0f} {eui_unit_suffix(unit)}",
            delta=None if is_base else _pct_delta(k["eui"], base_k["eui"]),
            delta_color="inverse",
        )
        cols[1].metric(
            "Annual energy",
            fmt_energy(k["energy"]),
            delta=None if is_base else _pct_delta(k["energy"], base_k["energy"]),
            delta_color="inverse",
        )
        if not with_costs:
            continue
        cost, base_cost = data["cost_totals"][name], data["cost_totals"][base_name]
        em = data["emissions_totals"][name] / 1000
        base_em = data["emissions_totals"][base_name] / 1000
        payback = data["payback_years"][name]
        cols[2].metric(
            "Energy cost ($/yr)",
            f"${_compact(cost)}",
            delta=None if is_base else _signed(cost - base_cost, "$"),
            delta_color="inverse",
        )
        cols[3].metric(
            "Emissions (t CO2/yr)",
            _compact(em),
            delta=None if is_base else _signed(em - base_em),
            delta_color="inverse",
        )
        cols[4].metric(
            "Payback (years)",
            "—" if is_base or payback is None else f"{payback:,.1f}",
            help="System cost / annual energy-cost savings vs the baseline. "
            "Enter a system cost per m² above to see it.",
        )


def _render_comparison_charts(data: dict, unit: EnergyIntensityUnit) -> None:
    """EUI distributions, end uses and fuels (share and absolute), cost and emissions."""
    theme = streamlit_theme()
    files: dict[str, str] = {}

    def chart(
        name: str, html: str, height: int, csv: pd.DataFrame | None = None
    ) -> None:
        components.html(html, height=height, scrolling=False)
        files[f"{name}.html"] = html
        if csv is not None and not csv.empty:
            files[f"{name}.csv"] = csv.to_csv(index=False)

    st.markdown("#### Energy use intensity across buildings")
    chart(
        "eui_distribution",
        create_comparison_kde_d3_html(data, theme=theme, eui_unit=unit),
        360,
        _build_eui_csv_for_display(data, unit),
    )

    for mode, heading in (
        ("share", "share of annual energy"),
        ("absolute", "kWh per year"),
    ):
        col_left, col_right = st.columns(2)
        extra: dict[str, Any] = (
            {}
            if mode == "share"
            else {"mode": "absolute", "value_label": "energy (kWh)"}
        )
        with col_left:
            st.markdown(f"#### End uses ({heading})")
            chart(
                f"end_uses_{mode}",
                create_comparison_stacked_bar_d3_html(
                    data,
                    "end_uses_data",
                    "end_use_colors",
                    "end uses",
                    theme=theme,
                    **extra,
                ),
                360,
                _build_stacked_csv(data, "end_uses_data"),
            )
        with col_right:
            st.markdown(f"#### Fuels ({heading})")
            chart(
                f"fuels_{mode}",
                create_comparison_stacked_bar_d3_html(
                    data, "utilities_data", "fuel_colors", "fuels", theme=theme, **extra
                ),
                360,
                _build_stacked_csv(data, "utilities_data"),
            )

    if data.get("cost_totals"):
        col_cost, col_em = st.columns(2)
        with col_cost:
            st.markdown("#### Annual energy cost")
            chart(
                "energy_cost",
                create_comparison_bar_d3_html(
                    data, "cost_totals", "energy cost", "$ per year", theme=theme
                ),
                200,
            )
        with col_em:
            st.markdown("#### Annual emissions")
            chart(
                "emissions",
                create_comparison_bar_d3_html(
                    data,
                    "emissions_totals",
                    "emissions",
                    "kg CO2 per year",
                    theme=theme,
                ),
                200,
            )
        files["costs_and_emissions.csv"] = (
            pd.DataFrame({
                "energy_cost_usd_per_yr": data["cost_totals"],
                "savings_usd_per_yr": data["annual_savings"],
                "emissions_kg_co2_per_yr": data["emissions_totals"],
                "system_cost_usd": data["capital_costs"],
                "payback_years": data["payback_years"],
            })
            .rename_axis("scenario")
            .to_csv()
        )
    section_download(files, "scenario_comparison", key="dl_compare")


@st.cache_data(show_spinner="Building map data...", max_entries=8)
def _cached_retrofit_map(
    cache_key: str,
    cart_crs: str,
    ec_items: tuple,
    em_items: tuple,
    system_cost_per_sqm: float,
    _view: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict] | None] | None:
    """Map frame (with per-building cost and emissions) and its geometry, cached per scenario."""
    from globi.tools.visualization.utils import build_map_features_from_df

    map_df = build_retrofit_map_df(
        _view,
        dict(ec_items),
        dict(em_items),
        system_cost_per_sqm=system_cost_per_sqm,
        cart_crs=cart_crs,
    )
    if map_df is None or map_df.empty:
        return None
    return map_df, build_map_features_from_df(map_df, cart_crs=cart_crs, value_col=None)


@st.fragment
def _render_compare_map(
    scenarios: dict[str, tuple[str, pd.DataFrame]],
    selections_key: str,
    costs: dict[str, dict],
    emissions: dict[str, dict],
    syscost: dict[str, float],
    unit: EnergyIntensityUnit,
) -> None:
    """Map of one scenario, coloured by an energy (or, with costs on, cost) measure."""
    st.markdown("#### Map")
    metrics = [
        ("eui", "greens", energy_intensity_axis_label(unit)),
        ("total_energy", "viridis", "Annual energy (kWh)"),
        ("peak_per_sqm", "reds", "Peak per m² (kW/m²)"),
        ("total_peak", "plasma", "Peak (kW)"),
    ]
    if costs:
        metrics += [
            ("energy_cost", "reds", "Annual energy cost ($/yr)"),
            ("emissions", "reds", "Emissions (kg CO2/yr)"),
            ("capital_cost", "plasma", "System cost ($)"),
        ]
    col_s, col_m = st.columns(2)
    name = col_s.selectbox(
        "Scenario", options=list(scenarios), key="compare_map_scenario"
    )
    value_col, cmap, metric_label = col_m.selectbox(
        "Colour by",
        options=metrics,
        format_func=lambda x: x[2],
        key="compare_map_metric",
    )

    run_id, view = scenarios[name]
    hint = infer_rotated_rectangle_crs_hint(view.iloc[: min(300, len(view))])
    cart_crs = resolve_map_crs(hint)
    cached = _cached_retrofit_map(
        f"{run_id}|{selections_key}",
        cart_crs,
        tuple(sorted(costs.get(run_id, {}).items())),
        tuple(sorted(emissions.get(run_id, {}).items())),
        syscost.get(run_id, 0.0),
        view,
    )
    if cached is None:
        st.info(
            "No building footprints could be placed on the map. Check the "
            "map coordinate system under Settings in the sidebar."
        )
        return
    map_df, geometry = cached
    if geometry is not None and len(geometry) == len(map_df):
        result = create_building_map_deck_from_cache(
            geometry,
            map_df,
            value_col=value_col,
            cmap=cmap,
            eui_unit=unit,
            value_label=metric_label,
        )
    else:
        result = create_building_map_deck(
            map_df,
            cart_crs=cart_crs,
            value_col=value_col,
            cmap=cmap,
            eui_unit=unit,
            value_label=metric_label,
        )
    if result is None:
        st.info("Could not build the map.")
        return
    deck, n_features, value_stats = result
    st.pydeck_chart(deck)
    map_caption(n_features)
    map_crs_caption(hint, cart_crs)
    if value_stats:
        render_colormap_legend(metric_label, value_stats, cmap)
