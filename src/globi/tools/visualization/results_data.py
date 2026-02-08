"""Process Results.pq (MultiIndex) for D3 and dashboards."""

from __future__ import annotations

import json
from textwrap import dedent

import pandas as pd


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
    end_uses_total: dict[str, float] = {}
    utilities_total: dict[str, float] = {}
    if "Energy" in (
        df_agg.columns.get_level_values(0)
        if isinstance(df_agg.columns, pd.MultiIndex)
        else []
    ):
        energy = df_agg["Energy"]
        if "End Uses" in energy.columns.get_level_values(0):
            eu = energy["End Uses"].sum()
            total = eu.sum()
            end_uses_total = {
                k: float(v) for k, v in eu.items() if total and v > total * 0.01
            }
        if "Utilities" in energy.columns.get_level_values(0):
            ut = energy["Utilities"].sum()
            total = ut.sum()
            utilities_total = {
                k: float(v) for k, v in ut.items() if total and v > total * 0.01
            }

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
