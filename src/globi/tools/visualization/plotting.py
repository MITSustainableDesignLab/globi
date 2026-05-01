"""Plotting utilities for D3 and Pydeck visualizations."""

from __future__ import annotations

import contextlib
import json
import math
from itertools import pairwise
from textwrap import dedent
from typing import Any, Literal

import pandas as pd
import pydeck as pdk
from shapely import wkt as shapely_wkt
from shapely.geometry import MultiPolygon, Polygon

from .models import Building3DConfig
from .utils import (
    LAT_COL,
    LON_COL,
    ROTATED_RECTANGLE_COL,
    MapMetricColumn,
    build_map_df_from_output,
    build_map_features_from_df,
    sanitize_for_json,
    transform_rotated_rectangle_to_latlon,
)

Theme = Literal["light", "dark"]

# energy intensity: stored internally as kWh/m²; optional display as kBTU/ft²
EnergyIntensityUnit = Literal["kwh_m2", "kbtu_sqft"]
# 1 kWh = 3600000 J; 1 ISO BTU = 1055.05585262 J -> kBTU per kWh = 3.412141633...
_KWH_TO_KBTU = 3.412141633
_SQFT_PER_SQM = 10.76391041670972
KWH_PER_SQM_TO_KBTU_PER_SQFT = _KWH_TO_KBTU / _SQFT_PER_SQM

_CARTO_POSITRON = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"


def energy_intensity_factor(unit: EnergyIntensityUnit) -> float:
    """Scale from kwh/m² to display unit (1.0 or kbtu/ft² per kwh/m²)."""
    return KWH_PER_SQM_TO_KBTU_PER_SQFT if unit == "kbtu_sqft" else 1.0


def convert_energy_intensity_values(
    values: list[float], unit: EnergyIntensityUnit
) -> list[float]:
    """Return new list of intensity values in the requested display unit."""
    f = energy_intensity_factor(unit)
    if f == 1.0:
        return list(values)
    return [float(v) * f for v in values]


def energy_intensity_axis_label(unit: EnergyIntensityUnit) -> str:
    """Axis or legend label for eui in the selected unit."""
    return "EUI (kBTU/ft²)" if unit == "kbtu_sqft" else "EUI (kWh/m²)"


def convert_eui_scenario_dict(
    eui_data: dict[str, list[float]], unit: EnergyIntensityUnit
) -> dict[str, list[float]]:
    """per-scenario eui lists scaled to display unit."""
    if unit == "kwh_m2":
        return {k: list(v) for k, v in eui_data.items()}
    f = energy_intensity_factor(unit)
    return {k: [float(x) * f for x in v] for k, v in eui_data.items()}


def scale_monthly_eui_records(
    records: list[dict], unit: EnergyIntensityUnit
) -> list[dict]:
    """Clone monthly eui records with avg/ci scaled to display unit."""
    f = energy_intensity_factor(unit)
    if f == 1.0:
        return [dict(r) for r in records]
    out: list[dict] = []
    for r in records:
        d = dict(r)
        for key in ("avg", "ci_low", "ci_high"):
            if key in d and d[key] is not None:
                with contextlib.suppress(TypeError, ValueError):
                    d[key] = float(d[key]) * f
        out.append(d)
    return out


def pick_energy_intensity_unit() -> EnergyIntensityUnit:
    """Shared session key so unit choice is consistent across viz pages."""
    try:
        import streamlit as st
    except ImportError:
        return "kwh_m2"
    choice = st.radio(
        "Energy intensity units",
        ["kWh/m²", "kBTU/ft²"],
        horizontal=True,
        key="globi_energy_intensity_unit",
        help="Applies to EUI (per-unit-floor-area) charts and map coloring.",
    )
    return "kbtu_sqft" if choice == "kBTU/ft²" else "kwh_m2"


def _maybe_scale_eui_column_for_display(
    df: pd.DataFrame,
    value_col: MapMetricColumn,
    eui_unit: EnergyIntensityUnit,
) -> pd.DataFrame:
    if value_col != "eui" or eui_unit == "kwh_m2" or "eui" not in df.columns:
        return df
    out = df.copy()
    f = energy_intensity_factor(eui_unit)
    out["eui"] = out["eui"].astype(float) * f
    return out


def _theme_colors(theme: Theme) -> dict[str, str]:
    if theme == "dark":
        return {
            "bg": "#0e1117",
            "text": "#fafafa",
            "axis": "#9ca3af",
            "axis_line": "#374151",
            "card_bg": "#1e1e1e",
            "card_border": "#374151",
            "placeholder": "#9ca3af",
            "pie_stroke": "#374151",
            "color_scheme": "dark",
        }
    return {
        "bg": "#f9fafb",
        "text": "#111827",
        "axis": "#4b5563",
        "axis_line": "#e5e7eb",
        "card_bg": "#ffffff",
        "card_border": "#e5e7eb",
        "placeholder": "#6b7280",
        "pie_stroke": "#ffffff",
        "color_scheme": "light",
    }


def _theme_colors_d3_embedded(theme: Theme) -> dict[str, str]:
    """Palette for D3 iframes; overlays Streamlit ``theme.*`` when running in Streamlit."""
    c = dict(_theme_colors(theme))
    try:
        import streamlit as st

        bg_key = (
            "theme.dark.backgroundColor"
            if theme == "dark"
            else "theme.light.backgroundColor"
        )
        bg = st.get_option(bg_key) or st.get_option("theme.backgroundColor")
        if isinstance(bg, str) and bg.startswith("#") and len(bg) >= 4:
            c["bg"] = bg
        tx_key = "theme.dark.textColor" if theme == "dark" else "theme.light.textColor"
        tx = st.get_option(tx_key) or st.get_option("theme.textColor")
        if isinstance(tx, str) and tx.startswith("#") and len(tx) >= 4:
            c["text"] = tx
        sec_key = (
            "theme.dark.secondaryBackgroundColor"
            if theme == "dark"
            else "theme.light.secondaryBackgroundColor"
        )
        sec = st.get_option(sec_key) or st.get_option("theme.secondaryBackgroundColor")
        if isinstance(sec, str) and sec.startswith("#") and len(sec) >= 4:
            c["card_bg"] = sec
    except Exception:  # noqa: S110
        pass
    return c


def create_raw_data_d3_html(
    df: pd.DataFrame,
    value_column: str | tuple[str, ...],
    category_column: str | tuple[str, ...] | None = None,
    title: str = "raw data summary",
    theme: Theme = "light",
) -> str:
    """Build a small d3 dashboard for a single numeric column. Uses string keys for JSON."""
    c = _theme_colors_d3_embedded(theme)
    cols = [value_column] + ([category_column] if category_column else [])
    subset = pd.DataFrame(df[cols].copy())
    subset.columns = ["value"] + (["category"] if category_column else [])
    safe_df = sanitize_for_json(subset)
    records = safe_df.to_dict(orient="records")
    value_label = str(value_column)

    payload = {
        "rows": records,
        "value_column": "value",
        "category_column": "category" if category_column else None,
        "value_label": value_label,
    }
    data_json = json.dumps(payload, ensure_ascii=False)

    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          html, body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            padding: 0.75rem;
            color-scheme: {c["color_scheme"]};
            background-color: {c["bg"]};
            color: {c["text"]};
          }}
          h1 {{
            font-size: 1.1rem;
            margin: 0 0 0.75rem 0;
          }}
          .layout {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 1rem;
          }}
          .card {{
            background: {c["card_bg"]};
            border-radius: 0.75rem;
            padding: 0.75rem 1rem 1rem;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
            border: 1px solid {c["card_border"]};
          }}
          .card h2 {{
            font-size: 0.95rem;
            margin: 0 0 0.5rem 0;
          }}
          .chart {{
            width: 100%;
            height: 260px;
          }}
          .axis-label {{
            fill: {c["axis"]};
            font-size: 11px;
          }}
          .axis text {{
            fill: {c["axis"]};
            font-size: 10px;
          }}
          .axis line,
          .axis path {{
            stroke: {c["axis_line"]};
          }}
          .placeholder-text {{
            color: {c["placeholder"]};
          }}
          .tooltip {{
            position: absolute;
            background: #111827;
            color: #e5e7eb;
            padding: 0.35rem 0.55rem;
            border-radius: 0.5rem;
            font-size: 0.75rem;
            pointer-events: none;
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
            border: 1px solid #1f2937;
            z-index: 1000;
          }}
          .bar {{
            fill: #4f46e5;
            opacity: 0.85;
          }}
          .bar:hover {{
            opacity: 1;
          }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <h1>{title}</h1>
        <div class="layout">
          <div class="card">
            <h2>distribution</h2>
            <div id="histogram" class="chart"></div>
          </div>
          <div class="card">
            <h2>summary</h2>
            <div id="summary" style="font-size: 0.85rem; line-height: 1.7;"></div>
          </div>
          <div class="card">
            <h2>by category</h2>
            <div id="by-category" class="chart"></div>
          </div>
        </div>
        <script>
          const payload = {data_json};
          const valueKey = payload.value_column;
          const categoryKey = payload.category_column;
          const valueLabel = payload.value_label || valueKey;
          const rows = payload.rows || [];

          const numeric = rows
            .map(r => +r[valueKey])
            .filter(v => Number.isFinite(v));

          const tooltip = d3.select("body")
            .append("div")
            .attr("class", "tooltip")
            .style("opacity", 0);

          function renderSummary() {{
            const container = d3.select("#summary");
            if (!numeric.length) {{
              container.text("no numeric data available");
              return;
            }}
            const fmt = d3.format(",.2f");
            const min = d3.min(numeric);
            const max = d3.max(numeric);
            const mean = d3.mean(numeric);
            const median = d3.median(numeric);

            container.html(`
              <div><strong>count:</strong> ${{numeric.length}}</div>
              <div><strong>mean:</strong> ${{fmt(mean)}}</div>
              <div><strong>median:</strong> ${{fmt(median)}}</div>
              <div><strong>min:</strong> ${{fmt(min)}}</div>
              <div><strong>max:</strong> ${{fmt(max)}}</div>
            `);
          }}

          function renderHistogram() {{
            const container = document.getElementById("histogram");
            const width = container.clientWidth || 360;
            const height = 260;
            const margin = {{top: 16, right: 16, bottom: 40, left: 52}};

            d3.select(container).selectAll("*").remove();

            if (!numeric.length) {{
              d3.select(container)
                .append("div")
                .attr("class", "placeholder-text")
                .style("padding", "0.5rem")
                .text("no numeric data available");
              return;
            }}

            const svg = d3.select(container)
              .append("svg")
              .attr("width", width)
              .attr("height", height);

            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;

            const g = svg.append("g")
              .attr("transform", "translate(" + margin.left + "," + margin.top + ")");

            const x = d3.scaleLinear()
              .domain(d3.extent(numeric))
              .nice()
              .range([0, chartWidth]);

            const bins = d3.bin()
              .domain(x.domain())
              .thresholds(25)(numeric);

            const y = d3.scaleLinear()
              .domain([0, d3.max(bins, d => d.length) || 1])
              .nice()
              .range([chartHeight, 0]);

            g.append("g")
              .attr("class", "x axis")
              .attr("transform", "translate(0," + chartHeight + ")")
              .call(d3.axisBottom(x).ticks(6));

            g.append("g")
              .attr("class", "y axis")
              .call(d3.axisLeft(y).ticks(5));

            g.selectAll("rect")
              .data(bins)
              .enter()
              .append("rect")
              .attr("class", "bar")
              .attr("x", d => x(d.x0))
              .attr("y", d => y(d.length))
              .attr("width", d => Math.max(0, x(d.x1) - x(d.x0) - 1))
              .attr("height", d => chartHeight - y(d.length))
              .on("mouseover", (event, d) => {{
                tooltip
                  .style("opacity", 1)
                  .html(
                    "range: [" + d3.format(",.2f")(d.x0) + ", " + d3.format(",.2f")(d.x1) + ")<br/>" +
                    "count: " + d.length
                  )
                  .style("left", (event.pageX + 10) + "px")
                  .style("top", (event.pageY - 28) + "px");
              }})
              .on("mousemove", (event) => {{
                tooltip
                  .style("left", (event.pageX + 10) + "px")
                  .style("top", (event.pageY - 28) + "px");
              }})
              .on("mouseout", () => {{
                tooltip.style("opacity", 0);
              }});

            svg.append("text")
              .attr("class", "axis-label")
              .attr("text-anchor", "middle")
              .attr("x", margin.left + chartWidth / 2)
              .attr("y", height - 8)
              .text(valueLabel);

            svg.append("text")
              .attr("class", "axis-label")
              .attr("text-anchor", "middle")
              .attr("transform", "rotate(-90)")
              .attr("x", -(margin.top + chartHeight / 2))
              .attr("y", 16)
              .text("count");
          }}

          function renderByCategory() {{
            const container = document.getElementById("by-category");
            const width = container.clientWidth || 360;
            const height = 260;
            const margin = {{top: 16, right: 16, bottom: 80, left: 52}};

            d3.select(container).selectAll("*").remove();

            if (!categoryKey) {{
              d3.select(container)
                .append("div")
                .attr("class", "placeholder-text")
                .style("padding", "0.5rem")
                .text("select a category column in the app to see grouped values.");
              return;
            }}

            const grouped = d3.rollups(
              rows,
              v => d3.mean(v, d => +d[valueKey]),
              d => d[categoryKey]
            ).map(([key, val]) => ({{ key, value: val }}));

            if (!grouped.length) {{
              d3.select(container)
                .append("div")
                .attr("class", "placeholder-text")
                .style("padding", "0.5rem")
                .text("no grouped data available.");
              return;
            }}

            grouped.sort((a, b) => d3.descending(a.value, b.value));

            const svg = d3.select(container)
              .append("svg")
              .attr("width", width)
              .attr("height", height);

            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;

            const g = svg.append("g")
              .attr("transform", "translate(" + margin.left + "," + margin.top + ")");

            const x = d3.scaleBand()
              .domain(grouped.map(d => d.key))
              .range([0, chartWidth])
              .padding(0.15);

            const y = d3.scaleLinear()
              .domain([0, d3.max(grouped, d => d.value) || 1])
              .nice()
              .range([chartHeight, 0]);

            g.append("g")
              .attr("class", "x axis")
              .attr("transform", "translate(0," + chartHeight + ")")
              .call(d3.axisBottom(x))
              .selectAll("text")
              .style("text-anchor", "end")
              .attr("dx", "-0.35em")
              .attr("dy", "0.1em")
              .attr("transform", "rotate(-40)");

            g.append("g")
              .attr("class", "y axis")
              .call(d3.axisLeft(y).ticks(5));

            g.selectAll("rect")
              .data(grouped)
              .enter()
              .append("rect")
              .attr("class", "bar")
              .attr("x", d => x(d.key))
              .attr("y", d => y(d.value))
              .attr("width", x.bandwidth())
              .attr("height", d => chartHeight - y(d.value))
              .on("mouseover", (event, d) => {{
                tooltip
                  .style("opacity", 1)
                  .html(
                    "<strong>" + d.key + "</strong><br/>" +
                    d3.format(",.2f")(d.value)
                  )
                  .style("left", (event.pageX + 10) + "px")
                  .style("top", (event.pageY - 28) + "px");
              }})
              .on("mousemove", (event) => {{
                tooltip
                  .style("left", (event.pageX + 10) + "px")
                  .style("top", (event.pageY - 28) + "px");
              }})
              .on("mouseout", () => {{
                tooltip.style("opacity", 0);
              }});

            svg.append("text")
              .attr("class", "axis-label")
              .attr("text-anchor", "middle")
              .attr("x", margin.left + chartWidth / 2)
              .attr("y", height - 8)
              .text(categoryKey);

            svg.append("text")
              .attr("class", "axis-label")
              .attr("text-anchor", "middle")
              .attr("transform", "rotate(-90)")
              .attr("x", -(margin.top + chartHeight / 2))
              .attr("y", 16)
              .text("mean " + valueLabel);
          }}

          renderSummary();
          renderHistogram();
          renderByCategory();
        </script>
      </body>
    </html>
    """

    return dedent(html)


def create_histogram_d3_html(
    values: list[float],
    title: str,
    x_label: str,
    theme: Theme = "light",
    *,
    bin_edges: list[float] | None = None,
    counts: list[int] | None = None,
    bar_colors: list[str] | None = None,
    annotation_values: list[dict] | None = None,
    y_label: str = "count",
    selected_range: tuple[float, float] | None = None,
    wide_layout: bool = False,
) -> str:
    """Build a histogram d3 card.

    If bin_edges, counts, and bar_colors (same length as counts) are set, draws
    those bins instead of auto d3.bin (keeps kde overlay on values).

    annotation_values: optional list of dicts like [{"value": 25.3, "label": "median", "color": "#374151"}]
    to draw vertical reference lines on the chart.

    wide_layout: use tighter margins, more x ticks, and less side padding (geography brush column).
    """
    c = _theme_colors_d3_embedded(theme)
    # shorter svg height = larger chartWidth/chartHeight ratio (wider-looking plot in the same iframe)
    chart_css_h = "335px" if wide_layout else "280px"
    body_pad = "0.5rem 0.28rem" if wide_layout else "0.5rem"
    payload = {
        "values": values,
        "title": title,
        "x_label": x_label,
        "bin_edges": bin_edges,
        "counts": counts,
        "bar_colors": bar_colors,
        "annotation_values": annotation_values,
        "y_label": y_label,
        "selected_range": list(selected_range) if selected_range is not None else None,
        "wide_layout": wide_layout,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: {body_pad}; color-scheme: {c["color_scheme"]}; background: {c["bg"]}; color: {c["text"]}; }}
          .chart {{ width: 100%; height: {chart_css_h}; min-width: 0; box-sizing: border-box; overflow: visible; }}
          svg {{ display: block; overflow: visible; max-width: 100%; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .axis text {{ fill: {c["axis"]}; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
          .tooltip {{
            position: absolute;
            background: #111827;
            color: #e5e7eb;
            padding: 0.35rem 0.55rem;
            border-radius: 0.5rem;
            font-size: 0.75rem;
            pointer-events: none;
            z-index: 1000;
          }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="hist" class="chart"></div>
        <script>
          const payload = {data_json};
          const values = payload.values || [];
          const container = document.getElementById("hist");
          const tooltip = d3.select("body").append("div").attr("class", "tooltip").style("opacity", 0);
          if (!values.length) {{
            container.innerHTML = "<span style=\\"color: {c["placeholder"]}\\">no data available</span>";
          }} else {{
            const width = container.clientWidth || 360;
            const wide = !!payload.wide_layout;
            const height = wide ? 335 : 280;
            const margin = wide
              ? {{ top: 12, right: 6, bottom: 78, left: 40 }}
              : {{ top: 12, right: 10, bottom: 68, left: 44 }};
            const xTickCount = wide ? 11 : 6;
            const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;
            const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
            const pe = payload.bin_edges;
            const pc = payload.counts;
            const pcol = payload.bar_colors;
            let x;
            let bins;
            if (pe && pc && pe.length === pc.length + 1 && pc.length > 0) {{
              const xDom = [d3.min(pe), d3.max(pe)];
              x = d3.scaleLinear().domain(xDom).nice().range([0, chartWidth]);
              bins = pc.map((cnt, i) => ({{ x0: pe[i], x1: pe[i + 1], length: cnt }}));
            }} else {{
              x = d3.scaleLinear().domain(d3.extent(values)).nice().range([0, chartWidth]);
              bins = d3.bin().domain(x.domain()).thresholds(25)(values);
            }}
            const y = d3.scaleLinear().domain([0, d3.max(bins, d => d.length) || 1]).nice().range([chartHeight, 0]);
            const xSpan = Math.abs(x.domain()[1] - x.domain()[0]);
            const xTickFmt = (xSpan >= 500 || Math.abs(x.domain()[1]) >= 1000 || Math.abs(x.domain()[0]) >= 1000)
              ? d3.format(".3~s") : d3.format(",.2f");
            const yMax = d3.max(bins, d => d.length) || 1;
            const yTickFmt = yMax >= 1000
              ? d3.format(".3~s")
              : (yMax < 10 ? d3.format(".2f") : d3.format(",.0f"));
            g.append("g").attr("transform", "translate(0," + chartHeight + ")")
              .call(d3.axisBottom(x).ticks(xTickCount).tickFormat(xTickFmt))
              .selectAll("text")
                .attr("transform", "rotate(-22)")
                .style("text-anchor", "end")
                .attr("font-size", "10px")
                .attr("dx", "-0.35em")
                .attr("dy", "0.35em");
            g.append("g").call(d3.axisLeft(y).ticks(5).tickFormat(yTickFmt));
            // selection band
            const sr = payload.selected_range;
            const hasSelection = sr && sr.length === 2 && sr[0] !== null && sr[1] !== null;
            if (hasSelection) {{
              const bx0 = Math.max(x(sr[0]), 0);
              const bx1 = Math.min(x(sr[1]), chartWidth);
              g.append("rect")
                .attr("x", bx0).attr("y", 0)
                .attr("width", Math.max(0, bx1 - bx0)).attr("height", chartHeight)
                .attr("fill", "#3b82f6").attr("opacity", 0.10).attr("pointer-events", "none");
              g.append("line").attr("x1", bx0).attr("x2", bx0).attr("y1", 0).attr("y2", chartHeight)
                .attr("stroke", "#3b82f6").attr("stroke-width", 1.5).attr("stroke-dasharray", "4,3");
              g.append("line").attr("x1", bx1).attr("x2", bx1).attr("y1", 0).attr("y2", chartHeight)
                .attr("stroke", "#3b82f6").attr("stroke-width", 1.5).attr("stroke-dasharray", "4,3");
            }}
            g.selectAll("rect.bar")
              .data(bins)
              .enter()
              .append("rect")
              .attr("class", "bar")
              .attr("x", d => x(d.x0))
              .attr("y", d => y(d.length))
              .attr("width", d => Math.max(0, x(d.x1) - x(d.x0) - 1))
              .attr("height", d => chartHeight - y(d.length))
              .attr("fill", (d, i) => (pcol && pcol.length === bins.length ? pcol[i] : "#4f46e5"))
              .attr("opacity", d => hasSelection ? (d.x1 > sr[0] && d.x0 < sr[1] ? 0.85 : 0.18) : 0.85)
              .on("mouseover", (event, d) => {{
                tooltip.style("opacity", 1)
                  .html("range: [" + d3.format(",.2f")(d.x0) + ", " + d3.format(",.2f")(d.x1) + ")<br/>" + (payload.y_label || "count") + ": " + d3.format(",.1f")(d.length))
                  .style("left", (event.pageX + 10) + "px")
                  .style("top", (event.pageY - 28) + "px");
              }})
              .on("mouseout", () => tooltip.style("opacity", 0));

            // kde overlay
            const kdeBandwidth = (x.domain()[1] - x.domain()[0]) / 40 || 1;
            const kdeX = d3.range(x.domain()[0], x.domain()[1], (x.domain()[1] - x.domain()[0]) / 200);
            const kernel = v => Math.exp(-0.5 * v * v) / Math.sqrt(2 * Math.PI);
            const kdeY = kdeX.map(xv => {{
              let sum = 0;
              values.forEach(v => {{
                sum += kernel((xv - v) / kdeBandwidth);
              }});
              return sum / (values.length * kdeBandwidth);
            }});
            const kdeScale = d3.scaleLinear()
              .domain([0, d3.max(kdeY) || 1])
              .range([chartHeight, 0]);
            const kdeLine = d3.line()
              .x((d, i) => x(kdeX[i]))
              .y(d => kdeScale(d))
              .curve(d3.curveBasis);
            g.append("path")
              .datum(kdeY)
              .attr("fill", "none")
              .attr("stroke", (pcol && pcol.length) ? "#9a3412" : "#ef4444")
              .attr("stroke-width", 2)
              .attr("d", kdeLine);
            // annotation vertical lines
            const annots = payload.annotation_values || [];
            annots.forEach(a => {{
              if (a.value == null) return;
              const ax = x(a.value);
              if (ax < 0 || ax > chartWidth) return;
              g.append("line")
                .attr("x1", ax).attr("x2", ax)
                .attr("y1", 0).attr("y2", chartHeight)
                .attr("stroke", a.color || "#374151")
                .attr("stroke-width", 1.5)
                .attr("stroke-dasharray", "4,3");
              g.append("text")
                .attr("x", ax + 4).attr("y", 10)
                .attr("fill", a.color || "#374151")
                .attr("font-size", "10px")
                .text(a.label || "");
            }});
            svg.append("text")
              .attr("class", "axis-label")
              .attr("text-anchor", "middle")
              .attr("x", margin.left + chartWidth / 2)
              .attr("y", height - 6)
              .attr("dominant-baseline", "alphabetic")
              .text(payload.x_label || "");
            svg.append("text")
              .attr("class", "axis-label")
              .attr("text-anchor", "middle")
              .attr("transform", "rotate(-90)")
              .attr("x", -(margin.top + chartHeight / 2))
              .attr("y", 16)
              .text(payload.y_label || "count");
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_binned_bar_d3_html(
    bin_edges: list[float],
    heights: list[float],
    *,
    title: str,
    x_label: str,
    y_label: str,
    theme: Theme = "light",
    bar_color: str = "#059669",
    bar_colors: list[str] | None = None,
) -> str:
    """Bar chart from precomputed histogram bins (e.g. weighted by floor area)."""
    c = _theme_colors_d3_embedded(theme)
    payload = {
        "edges": bin_edges,
        "heights": heights,
        "title": title,
        "x_label": x_label,
        "y_label": y_label,
        "bar_color": bar_color,
        "bar_colors": bar_colors,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; color-scheme: {c["color_scheme"]}; background: {c["bg"]}; color: {c["text"]}; }}
          .chart {{ width: 100%; height: 260px; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .axis text {{ fill: {c["axis"]}; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
          .tooltip {{
            position: absolute;
            background: #111827;
            color: #e5e7eb;
            padding: 0.35rem 0.55rem;
            border-radius: 0.5rem;
            font-size: 0.75rem;
            pointer-events: none;
            z-index: 1000;
          }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="bbar" class="chart"></div>
        <script>
          const payload = {data_json};
          const edges = payload.edges || [];
          const heights = payload.heights || [];
          const container = document.getElementById("bbar");
          const tooltip = d3.select("body").append("div").attr("class", "tooltip").style("opacity", 0);
          const n = heights.length;
          if (!edges.length || n + 1 !== edges.length || !n) {{
            container.innerHTML = "<span style=\\"color: {c["placeholder"]}\\">no data available</span>";
          }} else {{
            const width = container.clientWidth || 360;
            const height = 260;
            const margin = {{ top: 16, right: 16, bottom: 40, left: 56 }};
            const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;
            const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
            const x0 = d3.min(edges);
            const x1 = d3.max(edges);
            const x = d3.scaleLinear().domain([x0, x1]).nice().range([0, chartWidth]);
            const yMax = d3.max(heights) || 1;
            const y = d3.scaleLinear().domain([0, yMax]).nice().range([chartHeight, 0]);
            g.append("g").attr("transform", "translate(0," + chartHeight + ")").call(d3.axisBottom(x).ticks(6));
            g.append("g").call(d3.axisLeft(y).ticks(5));
            const bc = payload.bar_color || "#059669";
            const bcols = payload.bar_colors;
            for (let i = 0; i < n; i++) {{
              const xa = x(edges[i]);
              const xb = x(edges[i + 1]);
              const w = Math.max(0, xb - xa - 1);
              const h = heights[i];
              const fill = (bcols && bcols.length === n) ? bcols[i] : bc;
              g.append("rect")
                .attr("x", xa)
                .attr("y", y(h))
                .attr("width", w)
                .attr("height", chartHeight - y(h))
                .attr("fill", fill)
                .attr("opacity", 0.85)
                .on("mouseover", (event) => {{
                  tooltip.style("opacity", 1)
                    .html("range: [" + d3.format(",.2f")(edges[i]) + ", " + d3.format(",.2f")(edges[i+1]) + ")<br/>" + (payload.y_label || "value") + ": " + d3.format(",.1f")(h))
                    .style("left", (event.pageX + 10) + "px")
                    .style("top", (event.pageY - 28) + "px");
                }})
                .on("mouseout", () => tooltip.style("opacity", 0));
            }}
            svg.append("text")
              .attr("class", "axis-label")
              .attr("text-anchor", "middle")
              .attr("x", margin.left + chartWidth / 2)
              .attr("y", height - 8)
              .text(payload.x_label || "");
            svg.append("text")
              .attr("class", "axis-label")
              .attr("text-anchor", "middle")
              .attr("transform", "rotate(-90)")
              .attr("x", -(margin.top + chartHeight / 2))
              .attr("y", 16)
              .text(payload.y_label || "");
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_line_chart_d3_html(
    x: list[float],
    y: list[float],
    title: str,
    x_label: str,
    y_label: str,
    theme: Theme = "light",
) -> str:
    """Simple single-series line chart."""
    c = _theme_colors_d3_embedded(theme)
    points = [{"x": float(a), "y": float(b)} for a, b in zip(x, y, strict=False)]
    payload = {"points": points, "title": title, "x_label": x_label, "y_label": y_label}
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; color-scheme: {c["color_scheme"]}; background: {c["bg"]}; color: {c["text"]}; }}
          .chart {{ width: 100%; height: 280px; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .axis text {{ fill: {c["axis"]}; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="linec" class="chart"></div>
        <script>
          const payload = {data_json};
          const pts = payload.points || [];
          const container = document.getElementById("linec");
          if (!pts.length) {{
            container.innerHTML = "<span style=\\"color: {c["placeholder"]}\\">no data</span>";
          }} else {{
            const width = container.clientWidth || 400;
            const height = 280;
            const margin = {{ top: 16, right: 16, bottom: 44, left: 56 }};
            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;
            const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
            const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
            const x = d3.scaleLinear().domain(d3.extent(pts, d => d.x)).nice().range([0, chartWidth]);
            const yMin = d3.min(pts, d => d.y);
            const yMax = d3.max(pts, d => d.y);
            let y0 = yMin, y1 = yMax;
            if (y0 === y1) {{
              const p = Math.abs(y0) * 0.05 + 1e-6;
              y0 -= p;
              y1 += p;
            }}
            const y = d3.scaleLinear().domain([y0, y1]).nice().range([chartHeight, 0]);
            g.append("g").attr("transform", "translate(0," + chartHeight + ")").call(d3.axisBottom(x));
            g.append("g").call(d3.axisLeft(y));
            const line = d3.line().x(d => x(d.x)).y(d => y(d.y)).curve(d3.curveMonotoneX);
            g.append("path").datum(pts).attr("fill", "none").attr("stroke", "#4f46e5").attr("stroke-width", 2).attr("d", line);
            g.selectAll("circle.pt").data(pts).enter().append("circle").attr("class", "pt")
              .attr("cx", d => x(d.x)).attr("cy", d => y(d.y)).attr("r", 3).attr("fill", "#4f46e5");
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("x", margin.left + chartWidth / 2).attr("y", height - 8).text(payload.x_label || "");
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("transform", "rotate(-90)").attr("x", -(margin.top + chartHeight / 2)).attr("y", 14)
              .text(payload.y_label || "");
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_scatter_d3_html(
    x: list[float],
    y: list[float],
    labels: list[str],
    title: str,
    x_label: str,
    y_label: str,
    theme: Theme = "light",
    max_points: int = 4000,
    *,
    hline: float | None = None,
    vline: float | None = None,
    quadrant_labels: dict[str, str] | None = None,
) -> str:
    """Scatter plot with building id in tooltip; subsamples if too many points.

    hline: optional horizontal reference line (e.g. mean EUI).
    vline: optional vertical reference line (e.g. mean EDH).
    quadrant_labels: optional dict mapping quadrant keys ("tl","tr","bl","br") to label strings.
    """
    c = _theme_colors_d3_embedded(theme)
    n_raw = min(len(x), len(y), len(labels))
    if n_raw == 0:
        pts_data: list[dict] = []
    else:
        step = max(1, (n_raw + max_points - 1) // max_points)
        idx = list(range(0, n_raw, step))
        pts_data = [
            {"x": float(x[i]), "y": float(y[i]), "id": str(labels[i])} for i in idx
        ]
    payload = {
        "points": pts_data,
        "title": title,
        "x_label": x_label,
        "y_label": y_label,
        "sampled": n_raw > len(pts_data) if n_raw else False,
        "n_total": n_raw,
        "hline": hline,
        "vline": vline,
        "quadrant_labels": quadrant_labels or {},
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; color-scheme: {c["color_scheme"]}; background: {c["bg"]}; color: {c["text"]}; }}
          .chart {{ width: 100%; height: 480px; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .axis text {{ fill: {c["axis"]}; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
          .tip {{
            position: absolute; background: #111827; color: #e5e7eb; padding: 0.35rem 0.55rem;
            border-radius: 0.35rem; font-size: 0.72rem; pointer-events: none; z-index: 1000;
          }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="scat" class="chart"></div>
        <script>
          const payload = {data_json};
          const pts = payload.points || [];
          const container = document.getElementById("scat");
          const tip = d3.select("body").append("div").attr("class", "tip").style("opacity", 0);
          if (!pts.length) {{
            container.innerHTML = "<span style=\\"color: {c["placeholder"]}\\">no data</span>";
          }} else {{
            const width = container.clientWidth || 600;
            const height = 480;
            const margin = {{ top: 16, right: 20, bottom: 64, left: 64 }};
            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;
            const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
            const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
            const x = d3.scaleLinear().domain(d3.extent(pts, d => d.x)).nice().range([0, chartWidth]);
            const y = d3.scaleLinear().domain(d3.extent(pts, d => d.y)).nice().range([chartHeight, 0]);
            g.append("g").attr("transform", "translate(0," + chartHeight + ")")
              .call(d3.axisBottom(x))
              .selectAll("text")
                .attr("transform", "rotate(-35)")
                .style("text-anchor", "end")
                .attr("dx", "-0.5em")
                .attr("dy", "0.15em");
            g.append("g").call(d3.axisLeft(y));
            // quadrant reference lines
            const ql = payload.quadrant_labels || {{}};
            if (payload.vline != null) {{
              const vx = x(payload.vline);
              g.append("line").attr("x1", vx).attr("x2", vx).attr("y1", 0).attr("y2", chartHeight)
                .attr("stroke", "{c["axis"]}").attr("stroke-width", 1).attr("stroke-dasharray", "5,4");
            }}
            if (payload.hline != null) {{
              const hy = y(payload.hline);
              g.append("line").attr("x1", 0).attr("x2", chartWidth).attr("y1", hy).attr("y2", hy)
                .attr("stroke", "{c["axis"]}").attr("stroke-width", 1).attr("stroke-dasharray", "5,4");
            }}
            // quadrant labels
            const qpad = 6;
            const qFontSize = "10px";
            if (ql.bl) g.append("text").attr("x", qpad).attr("y", chartHeight - qpad)
              .attr("font-size", qFontSize).attr("fill", "{c["placeholder"]}").text(ql.bl);
            if (ql.br) g.append("text").attr("x", chartWidth - qpad).attr("y", chartHeight - qpad)
              .attr("text-anchor", "end").attr("font-size", qFontSize).attr("fill", "{c["placeholder"]}").text(ql.br);
            if (ql.tl) g.append("text").attr("x", qpad).attr("y", qpad + 10)
              .attr("font-size", qFontSize).attr("fill", "{c["placeholder"]}").text(ql.tl);
            if (ql.tr) g.append("text").attr("x", chartWidth - qpad).attr("y", qpad + 10)
              .attr("text-anchor", "end").attr("font-size", qFontSize).attr("fill", "{c["placeholder"]}").text(ql.tr);
            g.selectAll("circle").data(pts).enter().append("circle")
              .attr("cx", d => x(d.x)).attr("cy", d => y(d.y)).attr("r", 3)
              .attr("fill", "#dc2626").attr("opacity", 0.45)
              .on("mouseover", (event, d) => {{
                tip.style("opacity", 1).html(d.id + "<br/>" + d.x.toFixed(3) + ", " + d.y.toFixed(3))
                  .style("left", (event.pageX + 12) + "px").style("top", (event.pageY - 24) + "px");
              }})
              .on("mouseout", () => tip.style("opacity", 0));
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("x", margin.left + chartWidth / 2).attr("y", height - 4).text(payload.x_label || "");
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("transform", "rotate(-90)").attr("x", -(margin.top + chartHeight / 2)).attr("y", 16)
              .text(payload.y_label || "");
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_overheating_threshold_fan_d3_html(
    thresholds: list[float],
    lines: list[dict[str, Any]],
    mean_values: list[float] | None,
    *,
    title: str,
    y_label: str,
    theme: Theme = "light",
) -> str:
    """Multi-line chart: one series per building across thresholds + optional mean curve."""
    c = _theme_colors_d3_embedded(theme)
    payload = {
        "thresholds": [float(t) for t in thresholds],
        "lines": lines,
        "mean": mean_values,
        "title": title,
        "y_label": y_label,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>{_comparison_pane_css(c)}</style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="fan" class="chart" style="height:320px;"></div>
        <script>
          const payload = {data_json};
          const th = payload.thresholds || [];
          const lines = payload.lines || [];
          const meanV = payload.mean;
          const container = document.getElementById("fan");
          if (!th.length || !lines.length) {{
            container.innerHTML = '<span class="placeholder-text">no data</span>';
          }} else {{
            const width = container.clientWidth || 640;
            const height = 320;
            const margin = {{ top: 14, right: 18, bottom: 42, left: 56 }};
            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;
            const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
            const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
            let yMin = Infinity, yMax = -Infinity;
            lines.forEach(L => {{
              (L.values || []).forEach(v => {{
                if (v != null && v === v) {{ yMin = Math.min(yMin, v); yMax = Math.max(yMax, v); }}
              }});
            }});
            if (meanV) {{
              meanV.forEach(v => {{ if (v != null && v === v) {{ yMin = Math.min(yMin, v); yMax = Math.max(yMax, v); }} }});
            }}
            if (!isFinite(yMin) || yMax <= yMin) {{ yMin = 0; yMax = 1; }}
            const x = d3.scaleLinear().domain(d3.extent(th)).range([0, chartWidth]);
            const y = d3.scaleLinear().domain([yMin, yMax]).nice().range([chartHeight, 0]);
            const lineGen = d3.line()
              .defined((d, i) => d != null && d === d)
              .x((d, i) => x(th[i]))
              .y(d => y(d))
              .curve(d3.curveMonotoneX);
            lines.forEach(L => {{
              g.append("path")
                .datum(L.values)
                .attr("fill", "none")
                .attr("stroke", "#fb923c")
                .attr("stroke-width", 1.2)
                .attr("opacity", 0.2)
                .attr("d", lineGen);
            }});
            if (meanV && meanV.length === th.length) {{
              g.append("path")
                .datum(meanV)
                .attr("fill", "none")
                .attr("stroke", "#dc2626")
                .attr("stroke-width", 2.8)
                .attr("d", lineGen);
            }}
            g.append("g").attr("transform", "translate(0," + chartHeight + ")").call(d3.axisBottom(x).ticks(6));
            g.append("g").call(d3.axisLeft(y).ticks(5));
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("x", margin.left + chartWidth / 2).attr("y", height - 6)
              .text("threshold (°C)");
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("transform", "rotate(-90)").attr("x", -(margin.top + chartHeight / 2)).attr("y", 14)
              .text(payload.y_label || "");
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_trellis_scatter_d3_html(
    panels: list[dict[str, Any]],
    *,
    y_label: str,
    theme: Theme = "light",
) -> str:
    """Small-multiples scatter: each panel y vs EDH (same y axis label)."""
    c = _theme_colors_d3_embedded(theme)
    payload = {"panels": panels, "y_label": y_label}
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>morphology vs EDH</title>
        <style>{_comparison_pane_css(c)}</style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
        <style>
          .trellis-grid {{ display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }}
          .trellis-cell {{ flex: 1 1 300px; min-width: 260px; max-width: 480px; }}
          .trellis-cell h3 {{ font-size: 0.75rem; margin: 0 0 4px 0; color: {c["text"]}; }}
          .trellis-svg {{ width: 100%; height: 260px; }}
        </style>
      </head>
      <body>
        <div id="trellis" class="trellis-grid"></div>
        <script>
          const payload = {data_json};
          const panels = payload.panels || [];
          const root = document.getElementById("trellis");
          const yLabel = payload.y_label || "EDH";
          panels.forEach((panel, pi) => {{
            const pts = panel.points || [];
            const xLabel = panel.x_label || "x";
            const cell = document.createElement("div");
            cell.className = "trellis-cell";
            const h = document.createElement("h3");
            h.textContent = panel.title || ("panel " + (pi + 1));
            cell.appendChild(h);
            const div = document.createElement("div");
            div.className = "trellis-svg";
            cell.appendChild(div);
            root.appendChild(cell);
            if (!pts.length) {{
              div.innerHTML = '<span class="placeholder-text">no data</span>';
              return;
            }}
            const w = div.clientWidth || 280;
            const hgt = 260;
            const margin = {{ top: 10, right: 12, bottom: 64, left: 46 }};
            const cw = w - margin.left - margin.right;
            const ch = hgt - margin.top - margin.bottom;
            const svg = d3.select(div).append("svg").attr("width", w).attr("height", hgt);
            const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
            const x = d3.scaleLinear().domain(d3.extent(pts, d => d.x)).nice().range([0, cw]);
            const y = d3.scaleLinear().domain(d3.extent(pts, d => d.y)).nice().range([ch, 0]);
            g.append("g").attr("transform", "translate(0," + ch + ")")
              .call(d3.axisBottom(x).ticks(4))
              .selectAll("text")
                .attr("transform", "rotate(-35)")
                .style("text-anchor", "end")
                .attr("dx", "-0.5em")
                .attr("dy", "0.15em");
            g.append("g").call(d3.axisLeft(y).ticks(4));
            g.selectAll("circle").data(pts).enter().append("circle")
              .attr("cx", d => x(d.x)).attr("cy", d => y(d.y)).attr("r", 2.5)
              .attr("fill", "#ea580c").attr("opacity", 0.55);
            svg.append("text").attr("fill", "{c["axis"]}").attr("font-size", "10px")
              .attr("x", margin.left + cw / 2).attr("y", hgt - 4).attr("text-anchor", "middle").text(xLabel);
            svg.append("text").attr("fill", "{c["axis"]}").attr("font-size", "10px")
              .attr("transform", "rotate(-90)").attr("x", -(margin.top + ch / 2)).attr("y", 14)
              .attr("text-anchor", "middle").text(yLabel);
          }});
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_ratio_hotspot_scatter_d3_html(
    x: list[float],
    y: list[float],
    ratio: list[float],
    labels: list[str],
    *,
    title: str,
    x_label: str,
    y_label: str,
    theme: Theme = "light",
) -> str:
    """Scatter: x vs y with point color from ratio (blue low imbalance → red high)."""
    c = _theme_colors_d3_embedded(theme)
    pts = [
        {"x": float(a), "y": float(b), "r": float(r), "id": str(lab)}
        for a, b, r, lab in zip(x, y, ratio, labels, strict=False)
        if a == a and b == b and r == r
    ]
    payload = {"points": pts, "title": title, "x_label": x_label, "y_label": y_label}
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; color-scheme: {c["color_scheme"]};
            background: {c["bg"]}; color: {c["text"]}; }}
          .chart {{ width: 100%; height: 360px; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .axis text {{ fill: {c["axis"]}; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="rhs" class="chart"></div>
        <script>
          const payload = {data_json};
          const pts = payload.points || [];
          const container = document.getElementById("rhs");
          if (!pts.length) {{
            container.innerHTML = "<span style=\\"color:{c["placeholder"]}\\">no data</span>";
          }} else {{
            const width = container.clientWidth || 400;
            const height = 360;
            const margin = {{ top: 16, right: 16, bottom: 44, left: 52 }};
            const cw = width - margin.left - margin.right;
            const ch = height - margin.top - margin.bottom;
            const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
            const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
            const x = d3.scaleLinear().domain(d3.extent(pts, d => d.x)).nice().range([0, cw]);
            const y = d3.scaleLinear().domain(d3.extent(pts, d => d.y)).nice().range([ch, 0]);
            g.append("g").attr("transform", "translate(0," + ch + ")").call(d3.axisBottom(x));
            g.append("g").call(d3.axisLeft(y));
            g.selectAll("circle").data(pts).enter().append("circle")
              .attr("cx", d => x(d.x)).attr("cy", d => y(d.y)).attr("r", 4)
              .attr("fill", d => d3.interpolateRdYlBu(1 - Math.min(1, Math.max(0, (d.r - 1) / 12))))
              .attr("opacity", 0.85);
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("x", margin.left + cw / 2).attr("y", height - 8).text(payload.x_label || "");
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("transform", "rotate(-90)").attr("x", -(margin.top + ch / 2)).attr("y", 14)
              .text(payload.y_label || "");
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_warm_scatter_d3_html(
    x: list[float],
    y: list[float],
    labels: list[str],
    *,
    title: str,
    x_label: str,
    y_label: str,
    theme: Theme = "light",
) -> str:
    """Scatter with warm (yellow-orange-red) fill by y rank."""
    c = _theme_colors_d3_embedded(theme)
    n_raw = min(len(x), len(y), len(labels))
    pts_data = [
        {"x": float(x[i]), "y": float(y[i]), "id": str(labels[i])}
        for i in range(n_raw)
        if x[i] == x[i] and y[i] == y[i]
    ]
    payload = {
        "points": pts_data,
        "x_label": x_label,
        "y_label": y_label,
        "title": title,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; color-scheme: {c["color_scheme"]};
            background: {c["bg"]}; color: {c["text"]}; }}
          .chart {{ width: 100%; height: 380px; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .axis text {{ fill: {c["axis"]}; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
          .tip {{ position: absolute; background: #111827; color: #e5e7eb; padding: 0.35rem 0.5rem;
            border-radius: 0.35rem; font-size: 0.72rem; pointer-events: none; z-index: 1000; }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="ws" class="chart"></div>
        <script>
          const payload = {data_json};
          const pts = payload.points || [];
          const tip = d3.select("body").append("div").attr("class", "tip").style("opacity", 0);
          const container = document.getElementById("ws");
          if (!pts.length) {{
            container.innerHTML = "<span style=\\"color:{c["placeholder"]}\\">no data</span>";
          }} else {{
            const width = container.clientWidth || 480;
            const height = 380;
            const margin = {{ top: 16, right: 16, bottom: 44, left: 56 }};
            const cw = width - margin.left - margin.right;
            const ch = height - margin.top - margin.bottom;
            const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
            const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
            const yExtent = d3.extent(pts, d => d.y);
            const fillScale = d3.scaleSequential(d3.interpolateYlOrRd).domain(yExtent);
            const x = d3.scaleLinear().domain(d3.extent(pts, d => d.x)).nice().range([0, cw]);
            const y = d3.scaleLinear().domain(yExtent).nice().range([ch, 0]);
            g.append("g").attr("transform", "translate(0," + ch + ")").call(d3.axisBottom(x));
            g.append("g").call(d3.axisLeft(y));
            g.selectAll("circle").data(pts).enter().append("circle")
              .attr("cx", d => x(d.x)).attr("cy", d => y(d.y)).attr("r", 3.5)
              .attr("fill", d => fillScale(d.y)).attr("opacity", 0.75)
              .on("mouseover", (ev, d) => {{
                tip.style("opacity", 1).html(d.id + "<br/>" + d.x.toFixed(1) + " hr, " + d.y.toFixed(0) + " °C·hr")
                  .style("left", (ev.pageX + 12) + "px").style("top", (ev.pageY - 24) + "px");
              }})
              .on("mouseout", () => tip.style("opacity", 0));
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("x", margin.left + cw / 2).attr("y", height - 8).text(payload.x_label || "");
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("transform", "rotate(-90)").attr("x", -(margin.top + ch / 2)).attr("y", 14)
              .text(payload.y_label || "");
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_pie_d3_html(
    values: dict[str, float],
    title: str,
    colors: dict[str, str] | None = None,
    theme: Theme = "light",
) -> str:
    """Build a pie d3 card."""
    c = _theme_colors_d3_embedded(theme)
    payload = {"values": values, "title": title, "colors": colors or {}}
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; color-scheme: {c["color_scheme"]}; background: {c["bg"]}; color: {c["text"]}; }}
          .chart {{ width: 100%; height: 240px; }}
          .legend {{ display: flex; flex-wrap: wrap; gap: 0.5rem; font-size: 0.75rem; margin-top: 0.5rem; }}
          .legend-item {{ display: flex; align-items: center; gap: 0.4rem; }}
          .legend-color {{ width: 12px; height: 12px; border-radius: 2px; }}
          .tooltip {{
            position: absolute;
            background: #111827;
            color: #e5e7eb;
            padding: 0.35rem 0.55rem;
            border-radius: 0.5rem;
            font-size: 0.75rem;
            pointer-events: none;
            z-index: 1000;
          }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="pie" class="chart"></div>
        <div id="legend" class="legend"></div>
        <script>
          const payload = {data_json};
          const entries = Object.entries(payload.values || {{}}).filter(([k, v]) => v > 0);
          const container = document.getElementById("pie");
          const legend = document.getElementById("legend");
          const tooltip = d3.select("body").append("div").attr("class", "tooltip").style("opacity", 0);
          if (!entries.length) {{
            container.innerHTML = "<span style=\\"color: " + "{c["placeholder"]}" + "\\">no data available</span>";
          }} else {{
            const width = Math.min(container.clientWidth || 280, 280);
            const height = 260;
            const radius = Math.min(width, height) / 2 - 20;
            const data = entries.map(([label, value]) => ({{ label, value }}));
            const color = d3.scaleOrdinal()
              .domain(data.map(d => d.label))
              .range(data.map(d => payload.colors[d.label] || "#94a3b8"));
            const pie = d3.pie().value(d => d.value).sort(null);
            const arc = d3.arc().innerRadius(0).outerRadius(radius);
            const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
            const g = svg.append("g").attr("transform", "translate(" + width / 2 + "," + height / 2 + ")");
            const strokeColor = "{c["pie_stroke"]}";
            g.selectAll("path")
              .data(pie(data))
              .enter()
              .append("path")
              .attr("d", arc)
              .attr("fill", d => color(d.data.label))
              .attr("stroke", strokeColor)
              .attr("stroke-width", 1)
              .on("mouseover", (event, d) => {{
                const total = d3.sum(data, i => i.value) || 1;
                const pct = (d.data.value / total) * 100;
                tooltip.style("opacity", 1)
                  .html("<strong>" + d.data.label + "</strong><br/>" + d3.format(",.0f")(d.data.value) + " kWh<br/>" + d3.format(".1f")(pct) + "%")
                  .style("left", (event.pageX + 10) + "px")
                  .style("top", (event.pageY - 28) + "px");
              }})
              .on("mouseout", () => tooltip.style("opacity", 0));

            data.forEach(d => {{
              const item = document.createElement("div");
              item.className = "legend-item";
              item.innerHTML = '<div class="legend-color" style="background:' + color(d.label) + '"></div><span>' + d.label + '</span>';
              legend.appendChild(item);
            }});
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def _comparison_pane_css(c: dict[str, str]) -> str:
    """Shared CSS for comparison pane HTML pages."""
    return f"""
          html, body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            padding: 0.5rem 0.75rem;
            color-scheme: {c["color_scheme"]};
            background: {c["bg"]};
            color: {c["text"]};
            overflow: hidden;
          }}
          .chart {{
            width: 100%;
            height: 280px;
          }}
          .axis-label {{
            fill: {c["axis"]};
            font-size: 11px;
          }}
          .axis text {{
            fill: {c["axis"]};
            font-size: 10px;
          }}
          .axis line,
          .axis path {{
            stroke: {c["axis_line"]};
          }}
          .placeholder-text {{
            color: {c["placeholder"]};
            padding: 0.5rem;
          }}
          .tooltip {{
            position: absolute;
            background: #111827;
            color: #e5e7eb;
            padding: 0.35rem 0.55rem;
            border-radius: 0.5rem;
            font-size: 0.75rem;
            pointer-events: none;
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
            border: 1px solid #1f2937;
            z-index: 1000;
          }}
          .legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            font-size: 0.75rem;
            margin-top: 0.25rem;
          }}
          .legend-item {{
            display: flex;
            align-items: center;
            gap: 0.4rem;
          }}
          .legend-color {{
            width: 12px;
            height: 12px;
            border-radius: 2px;
          }}
    """


def create_comparison_kde_d3_html(
    data: dict,
    theme: Theme = "light",
    *,
    eui_unit: EnergyIntensityUnit = "kwh_m2",
) -> str:
    """Build a standalone D3 KDE pane comparing EUI distributions across scenarios.

    Expects output from results_data.extract_comparison_data.
    """
    c = _theme_colors_d3_embedded(theme)
    raw_eui: dict[str, list[float]] = data.get("eui_data", {}) or {}
    eui_payload = convert_eui_scenario_dict(raw_eui, eui_unit)
    x_axis_title = energy_intensity_axis_label(eui_unit)
    payload = {
        "scenarios": data.get("scenarios", []),
        "eui_data": eui_payload,
        "x_axis_title": x_axis_title,
    }
    data_json = json.dumps(payload, ensure_ascii=False)

    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>EUI comparison</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>{_comparison_pane_css(c)}</style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="chart" class="chart"></div>
        <div id="legend" class="legend"></div>
        <script>
          const payload = {data_json};
          const scenarios = payload.scenarios || [];
          const eui = payload.eui_data || {{}};
          const xAxisTitle = payload.x_axis_title || "EUI (kWh/m²)";
          const scenarioColors = d3.scaleOrdinal(d3.schemeTableau10).domain(scenarios);
          const tooltip = d3.select("body").append("div").attr("class", "tooltip").style("opacity", 0);

          const container = document.getElementById("chart");
          const legendEl = document.getElementById("legend");
          const hasData = scenarios.some(s => eui[s] && eui[s].length > 0);

          if (!hasData) {{
            container.innerHTML = '<span class="placeholder-text">no EUI data available</span>';
          }} else {{
            const width = container.clientWidth || 600;
            const height = 280;
            const margin = {{ top: 16, right: 20, bottom: 40, left: 52 }};
            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;

            const svg = d3.select(container)
              .append("svg")
              .attr("width", width)
              .attr("height", height);

            const g = svg.append("g")
              .attr("transform", "translate(" + margin.left + "," + margin.top + ")");

            let allVals = [];
            scenarios.forEach(s => {{ if (eui[s]) allVals = allVals.concat(eui[s]); }});
            const ext = d3.extent(allVals);
            const x = d3.scaleLinear().domain(ext).nice().range([0, chartWidth]);

            function kde(kernel, thresholds, values) {{
              return thresholds.map(t => [t, d3.mean(values, v => kernel(t - v))]);
            }}
            function epanechnikov(bandwidth) {{
              return x => Math.abs(x /= bandwidth) <= 1 ? 0.75 * (1 - x * x) / bandwidth : 0;
            }}

            const thresholds = x.ticks(100);
            let yMax = 0;
            const kdeData = {{}};
            scenarios.forEach(s => {{
              if (!eui[s] || !eui[s].length) return;
              const bw = (ext[1] - ext[0]) / 30 || 1;
              kdeData[s] = kde(epanechnikov(bw), thresholds, eui[s]);
              const localMax = d3.max(kdeData[s], d => d[1]) || 0;
              if (localMax > yMax) yMax = localMax;
            }});

            const y = d3.scaleLinear().domain([0, yMax]).nice().range([chartHeight, 0]);

            g.append("g")
              .attr("class", "axis")
              .attr("transform", "translate(0," + chartHeight + ")")
              .call(d3.axisBottom(x).ticks(8));
            g.append("g")
              .attr("class", "axis")
              .call(d3.axisLeft(y).ticks(5));

            const line = d3.line().x(d => x(d[0])).y(d => y(d[1])).curve(d3.curveBasis);
            const area = d3.area().x(d => x(d[0])).y0(chartHeight).y1(d => y(d[1])).curve(d3.curveBasis);

            scenarios.forEach(s => {{
              if (!kdeData[s]) return;
              const color = scenarioColors(s);
              g.append("path").datum(kdeData[s]).attr("fill", color).attr("opacity", 0.12).attr("d", area);
              g.append("path").datum(kdeData[s]).attr("fill", "none").attr("stroke", color).attr("stroke-width", 2.5).attr("opacity", 0.85).attr("d", line);
            }});

            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("x", margin.left + chartWidth / 2).attr("y", height - 6)
              .text(xAxisTitle);
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("transform", "rotate(-90)")
              .attr("x", -(margin.top + chartHeight / 2)).attr("y", 16)
              .text("density");

            scenarios.forEach(s => {{
              if (!kdeData[s]) return;
              const item = document.createElement("div");
              item.className = "legend-item";
              item.innerHTML = '<div class="legend-color" style="background:' + scenarioColors(s) + '"></div><span>' + s + '</span>';
              legendEl.appendChild(item);
            }});
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_comparison_stacked_bar_d3_html(
    data: dict,
    data_key: str,
    color_key: str,
    title: str = "comparison",
    theme: Theme = "light",
    mode: Literal["percent", "absolute"] = "percent",
    value_label: str | None = None,
) -> str:
    """Build a standalone D3 stacked horizontal bar pane.

    Expects output from results_data.extract_comparison_data.
    Use data_key/color_key to select which sub-dict to render,
    e.g. ("end_uses_data", "end_use_colors") or ("utilities_data", "fuel_colors").

    mode="percent" normalizes each row to 100% (default).
    mode="absolute" plots raw summed values; pass value_label for x-axis units
    (defaults to "energy").
    """
    c = _theme_colors_d3_embedded(theme)
    payload = {
        "scenarios": data.get("scenarios", []),
        "values": data.get(data_key, {}),
        "colors": data.get(color_key, {}),
        "mode": mode,
        "value_label": value_label
        or ("percentage (%)" if mode == "percent" else "energy"),
    }
    data_json = json.dumps(payload, ensure_ascii=False)

    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>{_comparison_pane_css(c)}</style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="chart" class="chart"></div>
        <div id="legend" class="legend"></div>
        <script>
          const payload = {data_json};
          const scenarios = payload.scenarios || [];
          const rawData = payload.values || {{}};
          const colorMap = payload.colors || {{}};
          const mode = payload.mode || "percent";
          const valueLabel = payload.value_label || (mode === "percent" ? "percentage (%)" : "energy");
          const tooltip = d3.select("body").append("div").attr("class", "tooltip").style("opacity", 0);

          const container = document.getElementById("chart");
          const legendEl = document.getElementById("legend");

          if (!Object.keys(rawData).length) {{
            container.innerHTML = '<span class="placeholder-text">no data available</span>';
          }} else {{
            const allCats = new Set();
            Object.values(rawData).forEach(obj => {{
              Object.keys(obj).forEach(k => allCats.add(k));
            }});
            const categories = Array.from(allCats).sort();

            const rows = [];
            scenarios.forEach(s => {{
              if (!rawData[s]) return;
              const total = d3.sum(categories, c => rawData[s][c] || 0);
              if (total <= 0) return;
              const row = {{ scenario: s }};
              categories.forEach(c => {{
                const raw = rawData[s][c] || 0;
                row[c] = mode === "percent" ? (raw / total) * 100 : raw;
              }});
              rows.push(row);
            }});

            if (!rows.length) {{
              container.innerHTML = '<span class="placeholder-text">no data available</span>';
            }} else {{
              const width = container.clientWidth || 400;
              const height = 280;
              function measureLabelWidth(text) {{
                const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
                svg.setAttribute("style", "position:absolute;visibility:hidden;pointer-events:none;");
                const el = svg.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "text"));
                el.setAttribute("font-size", "10px");
                el.textContent = text;
                container.appendChild(svg);
                const w = el.getComputedTextLength();
                container.removeChild(svg);
                return w;
              }}
              const maxLabelWidth = Math.max(0, ...rows.map(r => measureLabelWidth(r.scenario)));
              const leftMargin = Math.max(60, maxLabelWidth + 24);
              const margin = {{ top: 16, right: 20, bottom: 40, left: leftMargin }};
              const chartWidth = width - margin.left - margin.right;
              const chartHeight = height - margin.top - margin.bottom;

              const svg = d3.select(container)
                .append("svg")
                .attr("width", width)
                .attr("height", height);

              const g = svg.append("g")
                .attr("transform", "translate(" + margin.left + "," + margin.top + ")");

              const y = d3.scaleBand()
                .domain(rows.map(r => r.scenario))
                .range([0, chartHeight])
                .padding(0.25);

              const xMax = mode === "percent"
                ? 100
                : (d3.max(rows, r => d3.sum(categories, c => r[c] || 0)) || 0);
              const x = d3.scaleLinear().domain([0, xMax]).nice().range([0, chartWidth]);

              const stack = d3.stack().keys(categories).value((d, key) => d[key] || 0);
              const series = stack(rows);

              const valueFmt = mode === "percent"
                ? (v => d3.format(".1f")(v) + "%")
                : (v => d3.format(",.3~s")(v));

              const color = d3.scaleOrdinal()
                .domain(categories)
                .range(categories.map(c => colorMap[c] || "#94a3b8"));

              g.selectAll("g.layer")
                .data(series)
                .enter()
                .append("g")
                .attr("class", "layer")
                .attr("fill", d => color(d.key))
                .selectAll("rect")
                .data(d => d.map(v => ({{ ...v, key: d.key }})))
                .enter()
                .append("rect")
                .attr("y", d => y(d.data.scenario))
                .attr("x", d => x(d[0]))
                .attr("width", d => Math.max(0, x(d[1]) - x(d[0])))
                .attr("height", y.bandwidth())
                .attr("opacity", 0.85)
                .on("mouseover", (event, d) => {{
                  tooltip.style("opacity", 1)
                    .html("<strong>" + d.key + "</strong><br/>" + valueFmt(d.data[d.key]))
                    .style("left", (event.pageX + 10) + "px")
                    .style("top", (event.pageY - 28) + "px");
                }})
                .on("mousemove", (event) => {{
                  tooltip
                    .style("left", (event.pageX + 10) + "px")
                    .style("top", (event.pageY - 28) + "px");
                }})
                .on("mouseout", () => {{
                  tooltip.style("opacity", 0);
                }});

              const tickFmt = mode === "percent"
                ? (d => d + "%")
                : d3.format(",.2~s");
              g.append("g")
                .attr("class", "axis")
                .attr("transform", "translate(0," + chartHeight + ")")
                .call(d3.axisBottom(x).ticks(5).tickFormat(tickFmt));
              g.append("g")
                .attr("class", "axis")
                .call(d3.axisLeft(y));

              svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
                .attr("x", margin.left + chartWidth / 2).attr("y", height - 6)
                .text(valueLabel);

              categories.forEach(c => {{
                const item = document.createElement("div");
                item.className = "legend-item";
                item.innerHTML = '<div class="legend-color" style="background:' + color(c) + '"></div><span>' + c + '</span>';
                legendEl.appendChild(item);
              }});
            }}
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


_METRIC_GROUP_INTERPOLATORS = {
    "Basic": "interpolateReds",
    "EDH": "interpolateYlOrRd",
    "HeatIndex": "interpolateOrRd",
}
_METRIC_GROUP_UNITS = {
    "Basic": "hr",
    "EDH": "degC-hr",
    "HeatIndex": "hr",
}
_METRIC_GROUP_CSS_GRADIENTS = {
    "Basic": "linear-gradient(to right, #fff5f0, #fb6a4a, #a50f15)",
    "EDH": "linear-gradient(to right, #ffffcc, #fd8d3c, #bd0026)",
    "HeatIndex": "linear-gradient(to right, #fff7ec, #fc8d59, #7f0000)",
}


def _classify_metric_group(col_name: str) -> str:
    """Map a column name like 'Basic 25.0C' to its metric group key."""
    if col_name.startswith("Basic"):
        return "Basic"
    if col_name.startswith("EDH"):
        return "EDH"
    return "HeatIndex"


def create_overheating_heatmap_d3_html(
    df: pd.DataFrame,
    row_col: str = "statistic",
    theme: Theme = "light",
) -> str:
    """Build D3 heatmap of summary stats x overheating metrics.

    Each metric group (Basic, EDH, HeatIndex) gets its own color palette and
    is independently normalized, since they have different units.
    """
    c = _theme_colors_d3_embedded(theme)
    value_cols = [
        col
        for col in df.columns
        if col != row_col and pd.api.types.is_numeric_dtype(df[col])
    ]
    if not value_cols:
        return "<div class='placeholder-text'>no numeric columns</div>"

    rows = df[row_col].astype(str).tolist()
    values = df[value_cols].fillna(0).values.tolist()

    # per-group normalization: all columns in a group share the same max
    col_groups = [_classify_metric_group(vc) for vc in value_cols]
    group_maxes: dict[str, float] = {}
    for vc, grp in zip(value_cols, col_groups, strict=True):
        mx = float(df[vc].max())
        group_maxes[grp] = max(group_maxes.get(grp, 0), mx)
    # map each column to its group max
    col_maxes = [max(group_maxes.get(grp, 1), 1e-9) for grp in col_groups]
    # map each column to its interpolator name
    col_interps = [
        _METRIC_GROUP_INTERPOLATORS.get(grp, "d3.interpolateReds") for grp in col_groups
    ]

    payload = {
        "rows": rows,
        "cols": value_cols,
        "values": values,
        "col_maxes": col_maxes,
        "col_interps": col_interps,
    }
    data_json = json.dumps(payload, ensure_ascii=False)

    # build legend html: one gradient bar per group present
    seen_groups = dict.fromkeys(col_groups)
    legend_parts: list[str] = []
    for grp in seen_groups:
        gradient = _METRIC_GROUP_CSS_GRADIENTS.get(
            grp, _METRIC_GROUP_CSS_GRADIENTS["Basic"]
        )
        unit = _METRIC_GROUP_UNITS.get(grp, "")
        mx = group_maxes.get(grp, 0)
        legend_parts.append(
            f'<div style="display:flex;align-items:center;gap:6px;margin-right:18px;">'
            f'<span style="font-size:11px;font-weight:600;">{grp}</span>'
            f'<span style="font-size:10px;color:{c["axis"]}">0</span>'
            f'<div style="width:60px;height:10px;border-radius:3px;background:{gradient};'
            f'border:1px solid {c["axis_line"]};"></div>'
            f'<span style="font-size:10px;color:{c["axis"]}">{mx:,.1f} {unit}</span>'
            f"</div>"
        )
    legend_html_str = "".join(legend_parts)

    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>Overheating summary heatmap</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>{_comparison_pane_css(c)}</style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="chart" class="chart"></div>
        <div id="legend" class="legend" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;padding-top:4px;">
          {legend_html_str}
        </div>
        <script>
          const payload = {data_json};
          const rows = payload.rows || [];
          const cols = payload.cols || [];
          const values = payload.values || [];
          const colMaxes = payload.col_maxes || [];
          const colInterps = payload.col_interps || [];
          const tooltip = d3.select("body").append("div").attr("class", "tooltip").style("opacity", 0);

          const interpMap = {{
            "interpolateReds": d3.interpolateReds,
            "interpolateYlOrRd": d3.interpolateYlOrRd,
            "interpolateOrRd": d3.interpolateOrRd,
          }};
          const colorScales = cols.map((c, j) =>
            d3.scaleSequential(interpMap[colInterps[j]] || d3.interpolateReds)
              .domain([0, colMaxes[j] || 1])
          );

          const container = document.getElementById("chart");
          if (!rows.length || !cols.length) {{
            container.innerHTML = '<span class="placeholder-text">no data</span>';
          }} else {{
            const width = container.clientWidth || 560;
            const bottomMargin = 130;
            const height = Math.max(280, rows.length * 50 + 16 + bottomMargin);
            const leftMargin = 64;
            const topMargin = 16;
            const chartWidth = width - leftMargin - 40;
            const chartHeight = height - topMargin - bottomMargin;

            const x = d3.scaleBand()
              .domain(cols)
              .range([0, chartWidth])
              .paddingInner(0.08);
            const y = d3.scaleBand()
              .domain(rows)
              .range([0, chartHeight])
              .paddingInner(0.12);

            const svg = d3.select(container)
              .append("svg")
              .attr("width", width)
              .attr("height", height);

            const g = svg.append("g")
              .attr("transform", "translate(" + leftMargin + "," + topMargin + ")");

            rows.forEach((r, i) => {{
              cols.forEach((c, j) => {{
                const v = values[i]?.[j] ?? 0;
                g.append("rect")
                  .attr("x", x(c))
                  .attr("y", y(r))
                  .attr("width", x.bandwidth())
                  .attr("height", y.bandwidth())
                  .attr("fill", colorScales[j](v))
                  .attr("rx", 3)
                  .attr("stroke", "#e5e7eb")
                  .attr("stroke-width", 0.5)
                  .on("mouseover", (ev) => {{
                    tooltip.style("opacity", 1)
                      .html(r + " / " + c + ": " + d3.format(",.2f")(v))
                      .style("left", (ev.pageX + 10) + "px")
                      .style("top", (ev.pageY - 28) + "px");
                  }})
                  .on("mouseout", () => tooltip.style("opacity", 0));

                g.append("text")
                  .attr("x", x(c) + x.bandwidth() / 2)
                  .attr("y", y(r) + y.bandwidth() / 2)
                  .attr("text-anchor", "middle")
                  .attr("dominant-baseline", "central")
                  .attr("font-size", "11px")
                  .attr("fill", v / (colMaxes[j] || 1) > 0.6 ? "#fff" : "{c["text"]}")
                  .text(d3.format(",.1f")(v));
              }});
            }});

            g.append("g")
              .attr("class", "axis")
              .attr("transform", "translate(0," + chartHeight + ")")
              .call(d3.axisBottom(x).tickSize(0))
              .selectAll("text")
              .attr("transform", "rotate(-40)")
              .attr("dx", "-0.6em")
              .attr("dy", "0.25em")
              .style("text-anchor", "end")
              .style("font-size", "10px");

            g.append("g")
              .attr("class", "axis")
              .call(d3.axisLeft(y).tickSize(0));
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_comparison_bar_d3_html(
    data: dict,
    value_key: str,
    title: str = "comparison",
    value_label: str = "value",
    theme: Theme = "light",
) -> str:
    """Build a simple horizontal bar chart for scenario totals (e.g. cost, emissions).

    Expects data with "scenarios" list and value_key dict (scenario -> number).
    """
    c = _theme_colors_d3_embedded(theme)
    scenarios = data.get("scenarios", [])
    values = data.get(value_key, {})
    rows = [{"scenario": s, "value": values.get(s, 0)} for s in scenarios]
    payload = {"rows": rows, "value_label": value_label}
    data_json = json.dumps(payload, ensure_ascii=False)

    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>{_comparison_pane_css(c)}</style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="chart" class="chart"></div>
        <script>
          const payload = {data_json};
          const rows = payload.rows || [];
          const valueLabel = payload.value_label || "value";
          const tooltip = d3.select("body").append("div").attr("class", "tooltip").style("opacity", 0);

          const container = document.getElementById("chart");
          if (!rows.length) {{
            container.innerHTML = '<span class="placeholder-text">no data available</span>';
          }} else {{
            const width = container.clientWidth || 400;
            const height = Math.max(120, rows.length * 36);
            function measureLabelWidth(text) {{
              const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
              svg.setAttribute("style", "position:absolute;visibility:hidden;pointer-events:none;");
              const el = svg.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "text"));
              el.setAttribute("font-size", "10px");
              el.textContent = text;
              container.appendChild(svg);
              const w = el.getComputedTextLength();
              container.removeChild(svg);
              return w;
            }}
            const maxLabelWidth = Math.max(0, ...rows.map(d => measureLabelWidth(d.scenario)));
            const leftMargin = Math.max(60, maxLabelWidth + 24);
            const margin = {{ top: 16, right: 20, bottom: 40, left: leftMargin }};
            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;

            const maxVal = d3.max(rows, d => d.value) || 1;
            const x = d3.scaleLinear().domain([0, maxVal * 1.05]).range([0, chartWidth]);
            const y = d3.scaleBand()
              .domain(rows.map(d => d.scenario))
              .range([0, chartHeight])
              .padding(0.25);

            const svg = d3.select(container)
              .append("svg")
              .attr("width", width)
              .attr("height", height);
            const g = svg.append("g")
              .attr("transform", "translate(" + margin.left + "," + margin.top + ")");

            g.selectAll("rect")
              .data(rows)
              .enter()
              .append("rect")
              .attr("y", d => y(d.scenario))
              .attr("x", 0)
              .attr("width", d => x(d.value))
              .attr("height", y.bandwidth())
              .attr("fill", "#4f46e5")
              .attr("opacity", 0.85)
              .on("mouseover", (ev, d) => {{
                tooltip.style("opacity", 1)
                  .html(d.scenario + ": " + d3.format(",.2f")(d.value))
                  .style("left", (ev.pageX + 10) + "px")
                  .style("top", (ev.pageY - 28) + "px");
              }})
              .on("mouseout", () => tooltip.style("opacity", 0));

            g.append("g")
              .attr("class", "axis")
              .attr("transform", "translate(0," + chartHeight + ")")
              .call(d3.axisBottom(x).ticks(6));
            g.append("g")
              .attr("class", "axis")
              .call(d3.axisLeft(y));

            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
              .attr("x", margin.left + chartWidth / 2).attr("y", height - 6)
              .text(valueLabel);
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_monthly_timeseries_d3_html(
    records: list[dict],
    meters: list[str],
    colors: dict[str, str],
    title: str,
    y_label: str,
    theme: Theme = "light",
) -> str:
    """Build a monthly timeseries d3 card with legend."""
    c = _theme_colors_d3_embedded(theme)
    payload = {
        "records": records,
        "meters": meters,
        "colors": colors,
        "title": title,
        "y_label": y_label,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; color-scheme: {c["color_scheme"]}; background: {c["bg"]}; color: {c["text"]}; }}
          .chart {{ width: 100%; height: 300px; }}
          .legend {{ display: flex; flex-wrap: wrap; gap: 0.5rem; font-size: 0.75rem; margin-top: 0.5rem; }}
          .legend-item {{ display: flex; align-items: center; gap: 0.4rem; }}
          .legend-color {{ width: 12px; height: 12px; border-radius: 2px; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .axis text {{ fill: {c["axis"]}; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
          .tooltip {{
            position: absolute;
            background: #111827;
            color: #e5e7eb;
            padding: 0.35rem 0.55rem;
            border-radius: 0.5rem;
            font-size: 0.75rem;
            pointer-events: none;
            z-index: 1000;
          }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="chart" class="chart"></div>
        <div id="legend" class="legend"></div>
        <script>
          const payload = {data_json};
          const data = payload.records || [];
          const meters = payload.meters || [];
          const colors = payload.colors || {{}};
          const monthNames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
          const container = document.getElementById("chart");
          const legend = document.getElementById("legend");
          const tooltip = d3.select("body").append("div").attr("class", "tooltip").style("opacity", 0);
          if (!data.length) {{
            container.innerHTML = "<span style=\\"color: {c["placeholder"]}\\">no data available</span>";
          }} else {{
            const width = container.clientWidth || 480;
            const height = 300;
            const margin = {{ top: 20, right: 20, bottom: 40, left: 52 }};
            const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;
            const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
            const x = d3.scaleBand().domain(d3.range(1, 13)).range([0, chartWidth]).padding(0.1);
            const y = d3.scaleLinear()
              .domain([0, d3.max(data, d => d.avg) || 1])
              .nice()
              .range([chartHeight, 0]);
            const area = d3.area()
              .x(d => x(d.month) + x.bandwidth() / 2)
              .y0(d => y(d.ci_low))
              .y1(d => y(d.ci_high))
              .curve(d3.curveMonotoneX);
            const line = d3.line()
              .x(d => x(d.month) + x.bandwidth() / 2)
              .y(d => y(d.avg))
              .curve(d3.curveMonotoneX);
            meters.forEach((meter, idx) => {{
              const series = data.filter(d => d.meter === meter).sort((a, b) => a.month - b.month);
              if (!series.length) return;
              const color = colors[meter] || d3.schemeCategory10[idx % 10];
              g.append("path").datum(series).attr("d", area).attr("fill", color).attr("opacity", 0.15);
              g.append("path").datum(series).attr("d", line).attr("stroke", color).attr("fill", "none").attr("stroke-width", 2).attr("opacity", 0.85);
              g.selectAll("circle." + meter.replace(/\\s+/g, "-"))
                .data(series)
                .enter()
                .append("circle")
                .attr("cx", d => x(d.month) + x.bandwidth() / 2)
                .attr("cy", d => y(d.avg))
                .attr("r", 3)
                .attr("fill", color)
                .attr("opacity", 0.9)
                .on("mouseover", (event, d) => {{
                  tooltip.style("opacity", 1)
                    .html("<strong>" + meter + "</strong><br/>month: " + monthNames[d.month - 1] + "<br/>avg: " + d3.format(",.2f")(d.avg))
                    .style("left", (event.pageX + 10) + "px")
                    .style("top", (event.pageY - 28) + "px");
                }})
                .on("mouseout", () => tooltip.style("opacity", 0));
              const item = document.createElement("div");
              item.className = "legend-item";
              item.innerHTML = '<div class="legend-color" style="background:' + color + '"></div><span>' + meter + '</span>';
              legend.appendChild(item);
            }});
            g.append("g").attr("transform", "translate(0," + chartHeight + ")").call(d3.axisBottom(x).tickFormat((d, i) => monthNames[i]));
            g.append("g").call(d3.axisLeft(y).ticks(6));
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle").attr("x", margin.left + chartWidth / 2).attr("y", height - 8).text("month");
            svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle").attr("transform", "rotate(-90)").attr("x", -(margin.top + chartHeight / 2)).attr("y", 16).text(payload.y_label || "");
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


# ---------------------------------------------------------------------------
# Pydeck visualization functions
# ---------------------------------------------------------------------------


def create_column_layer_chart(
    df: pd.DataFrame,
    value_col: str | tuple[str, ...],
    config: Building3DConfig | None = None,
) -> pdk.Deck:
    """Create a pydeck column layer chart for building metrics.

    Args:
        df: DataFrame with lat, lon, and value columns.
        value_col: Column to use for elevation.
        config: Optional configuration for the chart.

    Returns:
        pdk.Deck object ready for rendering.
    """
    config = config or Building3DConfig()

    df_map = df.dropna(subset=[LAT_COL, LON_COL, value_col]).copy()
    if df_map.empty:
        msg = "No valid rows with lat/lon and metric"
        raise ValueError(msg)

    vals = df_map[value_col].astype("float64")
    q_low, q_high = vals.quantile([0.05, 0.95])
    clipped = vals.clip(q_low, q_high)
    df_map["__height__"] = clipped - clipped.min() + 1.0

    center_lat = float(df_map[LAT_COL].mean())
    center_lon = float(df_map[LON_COL].mean())

    layer = pdk.Layer(
        "ColumnLayer",
        data=df_map,
        get_position=[LON_COL, LAT_COL],
        get_elevation="__height__",
        elevation_scale=config.elevation_scale,
        radius=config.radius,
        get_fill_color=list(config.fill_color),
        pickable=True,
        auto_highlight=True,
    )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=config.view.zoom,
        pitch=config.view.pitch,
        bearing=config.view.bearing,
    )

    tooltip: dict[str, Any] = {
        "html": f"<b>{value_col}</b>: {{{{{value_col}}}}}",
        "style": {"backgroundColor": "black", "color": "white"},
    }

    return pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip=tooltip)  # type: ignore[arg-type]


def create_building_column_layer_chart(
    df: pd.DataFrame,
    value_col: str,
    cmap: str = "viridis",
    config: Building3DConfig | None = None,
) -> pdk.Deck:
    """Create 3D column layer at building centroids. Uses building height for extrusion."""
    config = config or Building3DConfig()
    df_map = df.dropna(subset=[LAT_COL, LON_COL, "height", value_col]).copy()
    if df_map.empty:
        msg = "No valid rows with lat/lon, height, and metric"
        raise ValueError(msg)

    vals = df_map[value_col].astype("float64")
    v_min, v_max = vals.min(), vals.max()
    span = v_max - v_min if v_max > v_min else 1.0
    df_map["__color__"] = [
        _colormap_color(cmap, (float(v) - v_min) / span) for v in df_map[value_col]
    ]

    layer = pdk.Layer(
        "ColumnLayer",
        data=df_map,
        get_position=[LON_COL, LAT_COL],
        get_elevation="height",
        elevation_scale=config.elevation_scale,
        radius=12,
        get_fill_color="__color__",
        pickable=True,
        auto_highlight=True,
    )

    view_state = pdk.ViewState(
        latitude=float(df_map[LAT_COL].mean()),
        longitude=float(df_map[LON_COL].mean()),
        zoom=16,
        pitch=55,
        bearing=0,
    )

    return pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        tooltip=True,
        map_style=_CARTO_POSITRON,
    )


def _colormap_color(name: str, t: float) -> list[int]:
    """Simple colormap with viridis, plasma, greens, reds, and end-use maps."""
    t = max(0.0, min(1.0, float(t)))

    if name == "plasma":
        stops = [
            (0.0, (13, 8, 135)),
            (0.25, (84, 3, 160)),
            (0.5, (139, 10, 165)),
            (0.75, (200, 54, 130)),
            (1.0, (240, 249, 33)),
        ]
    elif name == "viridis":
        stops = [
            (0.0, (68, 1, 84)),
            (0.25, (59, 82, 139)),
            (0.5, (33, 145, 140)),
            (0.75, (94, 201, 98)),
            (1.0, (253, 231, 37)),
        ]
    elif name == "greens":
        stops = [
            (0.0, (247, 252, 245)),
            (0.25, (199, 233, 192)),
            (0.5, (161, 217, 155)),
            (0.75, (116, 196, 118)),
            (1.0, (27, 120, 55)),
        ]
    elif name == "reds":
        stops = [
            (0.0, (255, 245, 240)),
            (0.25, (254, 224, 210)),
            (0.5, (252, 187, 161)),
            (0.75, (252, 146, 114)),
            (1.0, (222, 45, 38)),
        ]
    else:
        # single-hue colormap for end uses (base color scaled by t)
        base_colors: dict[str, tuple[int, int, int]] = {
            "heating": (220, 38, 38),
            "cooling": (37, 99, 235),
            "lighting": (234, 179, 8),
            "equipment": (16, 185, 129),
            "domestic_hot_water": (249, 115, 22),
        }
        key = name.replace("enduse_", "")
        r, g, b = base_colors.get(key, (147, 197, 253))
        return [int(r * t), int(g * t), int(b * t), 180]

    for (t0, c0), (t1, c1) in pairwise(stops):
        if t0 <= t <= t1:
            alpha = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            r = int(c0[0] + alpha * (c1[0] - c0[0]))
            g = int(c0[1] + alpha * (c1[1] - c0[1]))
            b = int(c0[2] + alpha * (c1[2] - c0[2]))
            return [r, g, b, 160]
    r, g, b = stops[-1][1]
    return [r, g, b, 160]


def create_building_map_deck(
    df: pd.DataFrame,
    cart_crs: str = "EPSG:3857",
    value_col: MapMetricColumn = None,
    cmap: str = "viridis",
    config: Building3DConfig | None = None,
    *,
    eui_unit: EnergyIntensityUnit = "kwh_m2",
) -> tuple[pdk.Deck, int, dict | None] | None:
    """Build pydeck deck for 3D building map from rotated_rectangle and height.

    Converts rotated_rectangle WKT to lat/lon, extrudes by height (m).
    Uses elevation_scale=1 so height maps 1:1. Optional value_col for coloring.

    Args:
        df: Source dataframe.
        cart_crs: CRS of rotated_rectangle.
        value_col: Column for color mapping (e.g. eui, total_energy, peak_per_sqm).
        cmap: greens, viridis, reds, or plasma.
        config: Optional Building3DConfig.
        eui_unit: when value_col is eui, scale from kwh/m² for display.
    """
    merged = build_map_df_from_output(df)
    if merged is not None:
        merged = _maybe_scale_eui_column_for_display(merged, value_col, eui_unit)
        features = build_map_features_from_df(
            merged, cart_crs=cart_crs, value_col=value_col
        )
    else:
        df_vis = _maybe_scale_eui_column_for_display(df, value_col, eui_unit)
        features = build_map_features_from_df(
            df_vis, cart_crs=cart_crs, value_col=value_col
        )
    if features is None:
        return None
    return _deck_from_features(features, config, cmap)


def create_building_map_deck_from_cache(
    geometry: list[dict],
    map_df: pd.DataFrame,
    value_col: MapMetricColumn,
    cmap: str = "viridis",
    config: Building3DConfig | None = None,
    *,
    eui_unit: EnergyIntensityUnit = "kwh_m2",
) -> tuple[pdk.Deck, int, dict | None] | None:
    """Build pydeck deck from cached geometry and map_df. No WKT parsing.

    Use when geometry and map_df are already computed (e.g. from prior run/CRS
    selection). Only adds the selected metric for coloring. When value_col is
    eui, map_df values are scaled from kwh/m² using eui_unit for display.
    """
    if len(geometry) != len(map_df):
        return None
    map_vis = _maybe_scale_eui_column_for_display(map_df, value_col, eui_unit)
    features = []
    for i, feat in enumerate(geometry):
        f = {"polygon": feat["polygon"], "height": feat["height"]}
        if value_col and value_col in map_vis.columns:
            v = map_vis.iloc[i][value_col]
            if v == v and v is not None:
                with contextlib.suppress(TypeError, ValueError):
                    f["value"] = float(v)
        features.append(f)
    return _deck_from_features(features, config, cmap)


def _deck_from_features(
    features: list[dict],
    config: Building3DConfig | None,
    cmap: str,
) -> tuple[pdk.Deck, int, dict | None]:
    """Create deck and stats from features (polygon, height, value)."""
    vals = [f["value"] for f in features if "value" in f and f["value"] is not None]
    value_stats = {"min": min(vals), "max": max(vals)} if vals else None
    config = config or Building3DConfig(elevation_scale=1.0)
    deck = create_polygon_layer_chart(
        features,
        config,
        cmap=cmap,
        value_key="value",
    )
    return deck, len(features), value_stats


def create_polygon_layer_chart(
    features: list[dict[str, Any]],
    config: Building3DConfig | None = None,
    cmap: str = "viridis",
    value_key: str = "value",
) -> pdk.Deck:
    """Create a pydeck polygon layer chart for rotated building footprints.

    Args:
        features: List of dicts with 'polygon' and 'height' keys.
        config: Optional configuration for the chart.
        cmap: Colormap name for building colors.
        value_key: Key in feature dict used for color mapping.

    Returns:
        pdk.Deck object ready for rendering.
    """
    config = config or Building3DConfig()

    vals = [
        f[value_key] for f in features if value_key in f and f[value_key] is not None
    ]
    v_min = min(vals) if vals else 0.0
    v_max = max(vals) if vals else 1.0
    span = v_max - v_min if v_max > v_min else 1.0
    default_color = [*list(config.fill_color[:3]), 160]

    # build minimal layer data: polygon, height, color, value (for tooltip only)
    layer_data: list[dict[str, Any]] = []
    for f in features:
        if value_key in f and f[value_key] is not None:
            t = (float(f[value_key]) - v_min) / span
            color = _colormap_color(cmap, t)
        else:
            color = default_color
        row: dict[str, Any] = {
            "polygon": f["polygon"],
            "height": f["height"],
            "color": color,
        }
        if value_key in f and f[value_key] is not None:
            row["value"] = f[value_key]
        layer_data.append(row)

    layer = pdk.Layer(
        "PolygonLayer",
        data=layer_data,
        get_polygon="polygon",
        get_elevation="height",
        elevation_scale=config.elevation_scale,
        get_fill_color="color",
        pickable=True,
        auto_highlight=True,
        extruded=True,
        wireframe=True,
    )

    # derive a reasonable center/zoom from feature polygons
    all_coords = [(float(x), float(y)) for f in layer_data for x, y in f["polygon"]]
    if all_coords:
        lons, lats = zip(*all_coords, strict=True)
        lon_center = sum(lons) / len(lons)
        lat_center = sum(lats) / len(lats)
        span = max(max(lons) - min(lons), max(lats) - min(lats))
        zoom = 15 if span < 0.005 else 14 if span < 0.02 else 13 if span < 0.05 else 12
    else:
        lon_center = lat_center = 0.0
        zoom = 0.8

    view_state = pdk.ViewState(
        latitude=lat_center,
        longitude=lon_center,
        zoom=zoom,
        pitch=55,
        bearing=0,
    )

    return pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        tooltip=True,
        map_style=_CARTO_POSITRON,
    )


def create_flat_footprint_deck(
    df: pd.DataFrame,
    cart_crs: str = "EPSG:3857",
    value_col: MapMetricColumn = None,
    cmap: str = "reds",
    fill_color: list[int] | None = None,
) -> tuple[pdk.Deck, int, dict | None] | None:
    """Flat (pitch=0) PolygonLayer using building footprints on Carto Positron basemap.

    Same footprint extraction as the 3D map but with no extrusion (bird's-eye view).
    Returns (deck, n_features, value_stats) or None if footprints unavailable.
    """
    from .utils import build_map_features_from_df

    features = build_map_features_from_df(df, cart_crs=cart_crs, value_col=value_col)
    if not features:
        return None

    vals = [f["value"] for f in features if "value" in f and f["value"] is not None]
    value_stats = {"min": min(vals), "max": max(vals)} if vals else None
    v_min = value_stats["min"] if value_stats else 0.0
    v_max = value_stats["max"] if value_stats else 1.0
    span = v_max - v_min if v_max > v_min else 1.0

    layer_data = []
    for f in features:
        if fill_color is not None:
            color = fill_color
        elif vals and "value" in f and f["value"] is not None:
            t = (float(f["value"]) - v_min) / span
            color = _colormap_color(cmap, t)
        else:
            color = [100, 140, 200, 180]
        row: dict[str, Any] = {"polygon": f["polygon"], "color": color}
        if "value" in f and f["value"] is not None:
            row["value"] = f["value"]
        layer_data.append(row)

    layer = pdk.Layer(
        "PolygonLayer",
        data=layer_data,
        get_polygon="polygon",
        get_fill_color="color",
        get_line_color=[80, 80, 80, 60],
        line_width_min_pixels=1,
        pickable=True,
        auto_highlight=True,
        extruded=False,
    )

    all_coords = [(float(x), float(y)) for f in layer_data for x, y in f["polygon"]]
    if all_coords:
        lons, lats = zip(*all_coords, strict=True)
        lon_center = sum(lons) / len(lons)
        lat_center = sum(lats) / len(lats)
        span_deg = max(max(lons) - min(lons), max(lats) - min(lats))
        zoom = (
            16
            if span_deg < 0.003
            else 15
            if span_deg < 0.008
            else 14
            if span_deg < 0.02
            else 13
            if span_deg < 0.05
            else 12
        )
    else:
        lon_center = lat_center = 0.0
        zoom = 12

    view_state = pdk.ViewState(
        latitude=lat_center, longitude=lon_center, zoom=zoom, pitch=0, bearing=0
    )
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        tooltip={"text": "Value: {value}"},  # type: ignore[arg-type]
        map_style=_CARTO_POSITRON,
    )
    return deck, len(features), value_stats


def load_rotated_polygon(wkt_value: str) -> list[tuple[float, float]] | None:
    """Load a polygon from WKT string and return exterior coords."""
    try:
        geom = shapely_wkt.loads(wkt_value)
    except Exception:
        return None

    if geom.is_empty:
        return None

    if isinstance(geom, Polygon):
        coords = list(geom.exterior.coords)
    elif isinstance(geom, MultiPolygon):
        poly = max(geom.geoms, key=lambda g: g.area)
        coords = list(poly.exterior.coords)
    else:
        return None

    return [(float(x), float(y)) for x, y in coords]


def compute_cartesian_offsets(
    offsets: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Project lat/lon offsets to local cartesian plane."""
    lat0 = sum(lat for _, lat in offsets) / len(offsets)
    lon0 = sum(lon for lon, _ in offsets) / len(offsets)
    meters_per_deg_lat = 110540.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))
    return [
        ((lon - lon0) * meters_per_deg_lon, (lat - lat0) * meters_per_deg_lat)
        for lon, lat in offsets
    ]


def extract_building_polygons(
    df: pd.DataFrame,
    height_col: str = "height",
    value_col: MapMetricColumn = None,
    cart_crs: str = "EPSG:3857",
) -> list[dict[str, Any]]:
    """Extract polygon features from dataframe with rotated rectangles.

    Converts rotated_rectangle WKT (in cartesian CRS) to lat/lon via pyproj,
    extrudes by height column.

    Args:
        df: DataFrame with ROTATED_RECTANGLE_COL and height_col.
        height_col: Column to use for building heights (extrusion).
        value_col: Optional column to use for feature values (color).
        cart_crs: CRS of rotated_rectangle WKT (default EPSG:3857).

    Returns:
        List of feature dicts for pydeck polygon layer.
    """
    df_reset = df.reset_index()

    if ROTATED_RECTANGLE_COL not in df_reset.columns:
        msg = "No rotated rectangle column found"
        raise ValueError(msg)

    if height_col not in df_reset.columns:
        msg = f"No height column '{height_col}' found"
        raise ValueError(msg)

    from pyproj import Transformer

    rect_series = df_reset[ROTATED_RECTANGLE_COL]
    height_series = df_reset[height_col].astype("float64")
    transformer = Transformer.from_crs(cart_crs, "EPSG:4326", always_xy=True)

    polygons: list[list[list[float]]] = []
    heights: list[float] = []
    values: list[float | None] = []

    for i, wkt_value in enumerate(rect_series):
        wkt_str = (
            getattr(wkt_value, "wkt", wkt_value) if wkt_value is not None else None
        )
        poly_lonlat = transform_rotated_rectangle_to_latlon(
            wkt_str or "", cart_crs, _transformer=transformer
        )
        if not poly_lonlat:
            continue

        height = float(height_series.iloc[i])
        if height <= 0 or height != height:  # nan check
            height = 10.0

        polygons.append(poly_lonlat)
        heights.append(height)
        values.append(
            float(df_reset.iloc[i][value_col])
            if value_col is not None and value_col in df_reset.columns
            else None
        )

    if not polygons:
        return []

    features: list[dict[str, Any]] = []
    for idx, polygon in enumerate(polygons):
        feat: dict[str, Any] = {"polygon": polygon, "height": heights[idx]}
        if value_col is not None and values[idx] is not None:
            feat["value"] = values[idx]
        features.append(feat)

    return features


# ---------------------------------------------------------------------------
# Overheating dashboard — new chart types
# ---------------------------------------------------------------------------


def create_threshold_overlay_kde_d3_html(
    series: dict[float, list[float]],
    *,
    title: str = "Metric distribution by threshold",
    x_label: str = "value",
    theme: Theme = "light",
) -> str:
    """Overlaid KDE curves, one per temperature threshold, colored yellow->red.

    Args:
        series: mapping from threshold (°C float) to list of per-building values.
        title: chart title.
        x_label: x-axis label.
        theme: "light" or "dark".
    """
    c = _theme_colors_d3_embedded(theme)

    # Build color mapping: lowest threshold -> yellow, highest -> red
    sorted_thresholds = sorted(series.keys())
    n = len(sorted_thresholds)

    def _interp_color(t: float) -> str:
        """Interpolate between #fef08a -> #f97316 -> #b91c1c."""
        c0 = (254.0, 240.0, 138.0)
        c1 = (249.0, 115.0, 22.0)
        c2 = (185.0, 28.0, 28.0)
        if t <= 0.5:
            u = t / 0.5
            rgb = tuple(c0[i] * (1 - u) + c1[i] * u for i in range(3))
        else:
            u = (t - 0.5) / 0.5
            rgb = tuple(c1[i] * (1 - u) + c2[i] * u for i in range(3))
        r, g, b_ = (round(max(0, min(255, v))) for v in rgb)
        return f"#{r:02x}{g:02x}{b_:02x}"

    threshold_colors = {
        thr: _interp_color(i / max(n - 1, 1)) for i, thr in enumerate(sorted_thresholds)
    }

    payload = {
        "curves": [
            {
                "threshold": thr,
                "color": threshold_colors[thr],
                "values": [
                    float(v) for v in series[thr] if v is not None and not math.isnan(v)
                ],
            }
            for thr in sorted_thresholds
            if series[thr]
        ],
        "title": title,
        "x_label": x_label,
    }

    payload_json = json.dumps(payload)

    html = f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8"/>
        <style>
          html, body {{ margin: 0; background: {c["bg"]}; font-family: sans-serif; }}
          .title {{ fill: {c["text"]}; font-size: 13px; font-weight: 600; }}
          .axis text {{ fill: {c["axis"]}; font-size: 11px; }}
          .axis .domain, .axis .tick line {{ stroke: {c["axis_line"]}; }}
          .x-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .legend-text {{ fill: {c["text"]}; font-size: 11px; }}
          .kde-curve {{ fill-opacity: 0.15; stroke-width: 2; }}
        </style>
      </head>
      <body>
        <div id="chart"></div>
        <script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
        <script>
          const DATA = {payload_json};
          const W = Math.max(document.body.clientWidth || 700, 400);
          const H = 240;
          const M = {{top: 28, right: 160, bottom: 40, left: 52}};
          const iW = W - M.left - M.right;
          const iH = H - M.top - M.bottom;

          const svg = d3.select("#chart").append("svg")
            .attr("width", W).attr("height", H);
          const g = svg.append("g").attr("transform", `translate(${{M.left}},${{M.top}})`);

          // KDE using Silverman bandwidth
          function epanechnikovKDE(bandwidth, thresholds, values) {{
            return thresholds.map(x => {{
              const sum = values.reduce((acc, v) => {{
                const u = (x - v) / bandwidth;
                return acc + (Math.abs(u) <= 1 ? 0.75 * (1 - u * u) / bandwidth : 0);
              }}, 0);
              return [x, sum / values.length];
            }});
          }}

          function silvermanBW(values) {{
            if (values.length < 2) return 1;
            const n = values.length;
            const mean = d3.mean(values);
            const std = Math.sqrt(values.reduce((a, v) => a + (v - mean) ** 2, 0) / (n - 1));
            const iqr = d3.quantile(values.slice().sort(d3.ascending), 0.75) -
                         d3.quantile(values.slice().sort(d3.ascending), 0.25);
            const s = Math.min(std, iqr / 1.34);
            return s > 0 ? 1.06 * s * Math.pow(n, -0.2) : 1;
          }}

          const curves = DATA.curves;
          if (!curves || curves.length === 0) {{
            g.append("text").attr("x", iW/2).attr("y", iH/2)
              .attr("text-anchor","middle").attr("class","title")
              .text("No data available");
          }} else {{
            // Compute domain from all values
            const allVals = curves.flatMap(c => c.values);
            const xMin = d3.min(allVals);
            const xMax = d3.max(allVals);
            const pad = (xMax - xMin) * 0.05 || 1;
            const xDomain = [Math.max(0, xMin - pad), xMax + pad];
            const xScale = d3.scaleLinear().domain(xDomain).range([0, iW]);

            const nTicks = 200;
            const step = (xDomain[1] - xDomain[0]) / nTicks;
            const evalPts = d3.range(xDomain[0], xDomain[1] + step, step);

            // Compute all KDE curves
            const kdeCurves = curves.map(c => {{
              if (c.values.length < 2) return {{ ...c, kde: [] }};
              const bw = silvermanBW(c.values);
              const kde = epanechnikovKDE(bw, evalPts, c.values);
              return {{ ...c, kde }};
            }}).filter(c => c.kde && c.kde.length > 0);

            const maxDensity = d3.max(kdeCurves.flatMap(c => c.kde.map(([, d]) => d)));
            const yScale = d3.scaleLinear().domain([0, maxDensity * 1.05 || 1]).range([iH, 0]);

            // Axes
            g.append("g").attr("class","axis").attr("transform",`translate(0,${{iH}})`)
              .call(d3.axisBottom(xScale).ticks(6));
            g.append("g").attr("class","axis").call(d3.axisLeft(yScale).ticks(4));

            g.append("text").attr("class","x-label")
              .attr("x", iW / 2).attr("y", iH + 34)
              .attr("text-anchor","middle")
              .text(DATA.x_label);

            // Title
            svg.append("text").attr("class","title")
              .attr("x", M.left + iW / 2).attr("y", 16)
              .attr("text-anchor","middle")
              .text(DATA.title);

            // Draw KDE fills then strokes
            const area = d3.area().x(([x]) => xScale(x)).y0(iH).y1(([,d]) => yScale(d)).curve(d3.curveBasis);
            const line = d3.line().x(([x]) => xScale(x)).y(([,d]) => yScale(d)).curve(d3.curveBasis);

            kdeCurves.forEach(c => {{
              g.append("path").datum(c.kde)
                .attr("class","kde-curve")
                .attr("fill", c.color)
                .attr("stroke", "none")
                .attr("d", area);
              g.append("path").datum(c.kde)
                .attr("fill","none")
                .attr("stroke", c.color)
                .attr("stroke-width", 2.0)
                .attr("d", line);
            }});

            // Legend on the right
            const lgX = iW + 12;
            kdeCurves.forEach((c, i) => {{
              const ly = i * 20;
              svg.append("rect")
                .attr("x", M.left + lgX).attr("y", M.top + ly)
                .attr("width", 12).attr("height", 12)
                .attr("rx", 2)
                .attr("fill", c.color);
              svg.append("text").attr("class","legend-text")
                .attr("x", M.left + lgX + 16).attr("y", M.top + ly + 10)
                .text(`${{c.threshold}}\\u00b0C`);
            }});
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_threshold_sensitivity_dot_range_d3_html(
    thresholds: list[float],
    medians: list[float],
    p25: list[float],
    p75: list[float],
    *,
    y_label: str,
    title: str = "threshold sensitivity",
    theme: Theme = "light",
) -> str:
    """Connected dot-and-IQR-range chart across temperature thresholds.

    Draws a vertical IQR bar (p25-p75) at each threshold and a line
    connecting the median dots - gives an aggregate view without the
    visual noise of per-building fan lines.
    """
    c = _theme_colors_d3_embedded(theme)
    payload = {
        "thresholds": [float(t) for t in thresholds],
        "medians": [float(v) for v in medians],
        "p25": [float(v) for v in p25],
        "p75": [float(v) for v in p75],
        "title": title,
        "y_label": y_label,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem;
                 color-scheme: {c["color_scheme"]}; background: {c["bg"]}; color: {c["text"]}; }}
          .axis text {{ fill: {c["axis"]}; font-size: 11px; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .tip {{ position: absolute; background: #111827; color: #e5e7eb; padding: 0.3rem 0.5rem;
                  border-radius: 0.4rem; font-size: 0.72rem; pointer-events: none; z-index: 1000; }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="sens" style="width:100%;height:300px;"></div>
        <script>
          const p = {data_json};
          const th = p.thresholds, meds = p.medians, lo = p.p25, hi = p.p75;
          const container = document.getElementById("sens");
          const tip = d3.select("body").append("div").attr("class","tip").style("opacity",0);
          if (!th.length) {{
            container.innerHTML = "<span style='color:{c["placeholder"]}'>no data</span>";
          }} else {{
            const width = container.clientWidth || 420, height = 300;
            const margin = {{top:20,right:20,bottom:44,left:60}};
            const W = width - margin.left - margin.right;
            const H = height - margin.top - margin.bottom;
            const svg = d3.select(container).append("svg").attr("width",width).attr("height",height);
            const g = svg.append("g").attr("transform","translate("+margin.left+","+margin.top+")");
            const x = d3.scaleLinear().domain([d3.min(th)-0.5, d3.max(th)+0.5]).range([0,W]);
            const allY = [...meds, ...lo, ...hi].filter(v => v!=null);
            const y = d3.scaleLinear().domain([0, d3.max(allY)*1.05||1]).nice().range([H,0]);
            g.append("g").attr("transform","translate(0,"+H+")").call(d3.axisBottom(x).tickValues(th).tickFormat(d3.format(".4g")));
            g.append("g").call(d3.axisLeft(y).ticks(5));
            // IQR bars
            th.forEach((t,i) => {{
              if (lo[i]==null || hi[i]==null) return;
              g.append("rect")
                .attr("x", x(t)-6).attr("width",12)
                .attr("y", y(hi[i])).attr("height", Math.max(0, y(lo[i])-y(hi[i])))
                .attr("fill","#f97316").attr("opacity",0.35);
            }});
            // median connecting line
            const lineGen = d3.line().x((_,i)=>x(th[i])).y((_,i)=>y(meds[i])).defined((_,i)=>meds[i]!=null).curve(d3.curveMonotoneX);
            g.append("path").datum(meds).attr("fill","none").attr("stroke","#ea580c").attr("stroke-width",2).attr("d",lineGen);
            // median dots
            th.forEach((t,i) => {{
              if (meds[i]==null) return;
              g.append("circle").attr("cx",x(t)).attr("cy",y(meds[i])).attr("r",5)
                .attr("fill","#ea580c").attr("stroke","{c["bg"]}").attr("stroke-width",1.5)
                .on("mouseover",(ev)=>{{ tip.style("opacity",1).html(t+"°C<br/>median: "+d3.format(",.1f")(meds[i])+"<br/>IQR: "+d3.format(",.1f")(lo[i])+"-"+d3.format(",.1f")(hi[i])).style("left",(ev.pageX+12)+"px").style("top",(ev.pageY-24)+"px"); }})
                .on("mouseout",()=>tip.style("opacity",0));
            }});
            svg.append("text").attr("class","axis-label").attr("text-anchor","middle")
              .attr("x",margin.left+W/2).attr("y",height-8).text("threshold (°C)");
            svg.append("text").attr("class","axis-label").attr("text-anchor","middle")
              .attr("transform","rotate(-90)").attr("x",-(margin.top+H/2)).attr("y",16)
              .text(p.y_label||"");
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_heat_index_stacked_bar_d3_html(
    building_ids: list[str],
    category_data: dict[str, list[float]],
    *,
    title: str = "heat index hours by building",
    max_buildings: int = 200,
    theme: Theme = "light",
) -> str:
    """Horizontal stacked bar chart of heat index category hours per building.

    Buildings are on the y-axis sorted by caution+ total (highest at top).
    category_data maps category name to list of float hours, aligned with building_ids.
    """
    c = _theme_colors_d3_embedded(theme)
    _CAT_COLORS = {
        "Normal [hr]": "#4ade80",
        "Caution [hr]": "#facc15",
        "Extreme Caution [hr]": "#f97316",
        "Danger [hr]": "#dc2626",
        "Extreme Danger [hr]": "#7f1d1d",
    }
    # clip to max_buildings
    n = min(len(building_ids), max_buildings)
    bids = building_ids[:n]
    cats = list(category_data.keys())
    data_rows = []
    for i, bid in enumerate(bids):
        row: dict[str, Any] = {"id": bid}
        for cat in cats:
            vals = category_data.get(cat, [])
            row[cat] = float(vals[i]) if i < len(vals) else 0.0
        data_rows.append(row)
    payload = {
        "rows": data_rows,
        "categories": cats,
        "colors": {cat: _CAT_COLORS.get(cat, "#9ca3af") for cat in cats},
        "title": title,
        "truncated": len(building_ids) > max_buildings,
        "total_buildings": len(building_ids),
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    bar_height = max(6, min(20, 800 // max(n, 1)))
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem;
                 color-scheme: {c["color_scheme"]}; background: {c["bg"]}; color: {c["text"]}; }}
          .axis text {{ fill: {c["axis"]}; font-size: 10px; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .tip {{ position: absolute; background: #111827; color: #e5e7eb; padding: 0.3rem 0.5rem;
                  border-radius: 0.4rem; font-size: 0.72rem; pointer-events: none; z-index: 1000; }}
          .legend-item {{ display: inline-flex; align-items: center; gap: 4px; margin-right: 10px; font-size: 11px; }}
          .legend-swatch {{ width: 12px; height: 12px; border-radius: 2px; flex-shrink: 0; }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="legend" style="display:flex;flex-wrap:wrap;margin-bottom:6px;"></div>
        <div id="chart" style="width:100%;overflow-y:auto;max-height:500px;"></div>
        <script>
          const p = {data_json};
          const cats = p.categories, colors = p.colors, rows = p.rows;
          // legend
          const leg = document.getElementById("legend");
          cats.forEach(cat => {{
            const item = document.createElement("div");
            item.className = "legend-item";
            item.innerHTML = "<div class='legend-swatch' style='background:"+colors[cat]+"'></div><span>"+cat.replace(" [hr]","")+"</span>";
            leg.appendChild(item);
          }});
          const container = document.getElementById("chart");
          const tip = d3.select("body").append("div").attr("class","tip").style("opacity",0);
          if (!rows.length) {{
            container.innerHTML = "<span style='color:{c["placeholder"]}'>no heat index data</span>";
          }} else {{
            const barH = {bar_height};
            const margin = {{top:10,right:20,bottom:30,left:80}};
            const width = (container.clientWidth || 480);
            const W = width - margin.left - margin.right;
            const H = rows.length * (barH + 2);
            const totalH = H + margin.top + margin.bottom;
            const svg = d3.select(container).append("svg").attr("width",width).attr("height",totalH);
            const g = svg.append("g").attr("transform","translate("+margin.left+","+margin.top+")");
            const stack = d3.stack().keys(cats);
            const series = stack(rows);
            const maxVal = d3.max(rows, r => cats.reduce((s,c)=>s+(r[c]||0),0)) || 1;
            const x = d3.scaleLinear().domain([0,maxVal]).range([0,W]);
            const y = d3.scaleBand().domain(rows.map(r=>r.id)).range([0,H]).padding(0.1);
            g.append("g").attr("transform","translate(0,"+H+")").call(d3.axisBottom(x).ticks(5));
            series.forEach(s => {{
              g.selectAll("rect.b"+s.key.replace(/[^a-z]/gi,"_"))
                .data(s).enter().append("rect")
                .attr("y", d=>y(d.data.id)).attr("height",y.bandwidth())
                .attr("x", d=>x(d[0])).attr("width", d=>Math.max(0,x(d[1])-x(d[0])))
                .attr("fill", colors[s.key]).attr("opacity",0.9)
                .on("mouseover",(ev,d)=>{{
                  const val = (d[1]-d[0]).toFixed(1);
                  tip.style("opacity",1).html(d.data.id+"<br/>"+s.key.replace(" [hr]","")+": "+val+" hr")
                    .style("left",(ev.pageX+12)+"px").style("top",(ev.pageY-24)+"px");
                }})
                .on("mouseout",()=>tip.style("opacity",0));
            }});
            g.append("g").call(d3.axisLeft(y).tickSize(0).tickPadding(4))
              .selectAll("text").style("font-size","9px");
            svg.append("text").attr("class","axis-label").attr("text-anchor","middle")
              .attr("x",margin.left+W/2).attr("y",totalH-4).text("hours");
            if (p.truncated) {{
              g.append("text").attr("x",W).attr("y",-2).attr("text-anchor","end")
                .attr("font-size","10px").attr("fill","{c["placeholder"]}")
                .text("showing top "+rows.length+" of "+p.total_buildings+" buildings");
            }}
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_box_plot_by_floors_d3_html(
    groups: list[str],
    boxes: list[dict[str, Any]],
    *,
    x_label: str = "number of floors",
    y_label: str = "EDH (degC-hr)",
    title: str = "EDH by floor count",
    theme: Theme = "light",
) -> str:
    """Box-and-whisker chart grouped by floor count bucket.

    boxes: list of dicts with keys min, q1, median, q3, max, n, outliers (list[float]).
    groups: x-axis category labels aligned with boxes.
    """
    c = _theme_colors_d3_embedded(theme)
    payload = {
        "groups": groups,
        "boxes": boxes,
        "x_label": x_label,
        "y_label": y_label,
        "title": title,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem;
                 color-scheme: {c["color_scheme"]}; background: {c["bg"]}; color: {c["text"]}; }}
          .axis text {{ fill: {c["axis"]}; font-size: 11px; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; }}
          .tip {{ position: absolute; background: #111827; color: #e5e7eb; padding: 0.3rem 0.5rem;
                  border-radius: 0.4rem; font-size: 0.72rem; pointer-events: none; z-index: 1000; }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="box" style="width:100%;height:400px;"></div>
        <script>
          const p = {data_json};
          const grps = p.groups, bxs = p.boxes;
          const container = document.getElementById("box");
          const tip = d3.select("body").append("div").attr("class","tip").style("opacity",0);
          if (!grps.length) {{
            container.innerHTML = "<span style='color:{c["placeholder"]}'>no data</span>";
          }} else {{
            const width = container.clientWidth || 420, height = 400;
            const margin = {{top:16,right:16,bottom:72,left:60}};
            const W = width-margin.left-margin.right;
            const H = height-margin.top-margin.bottom;
            const svg = d3.select(container).append("svg").attr("width",width).attr("height",height);
            const g = svg.append("g").attr("transform","translate("+margin.left+","+margin.top+")");
            const x = d3.scaleBand().domain(grps).range([0,W]).padding(0.4);
            const allY = bxs.flatMap(b=>[b.min,b.max,...(b.outliers||[])]).filter(v=>v!=null);
            const y = d3.scaleLinear().domain([0, d3.max(allY)*1.05||1]).nice().range([H,0]);
            g.append("g").attr("transform","translate(0,"+H+")")
              .call(d3.axisBottom(x))
              .selectAll("text")
                .attr("transform","rotate(-35)")
                .style("text-anchor","end")
                .attr("dx","-0.5em")
                .attr("dy","0.15em");
            g.append("g").call(d3.axisLeft(y).ticks(5));
            bxs.forEach((b,i) => {{
              const gname = grps[i];
              const cx = x(gname)+x.bandwidth()/2;
              const bw = x.bandwidth();
              // whiskers
              g.append("line").attr("x1",cx).attr("x2",cx).attr("y1",y(b.max)).attr("y2",y(b.q3))
                .attr("stroke","{c["axis_line"]}").attr("stroke-width",1.5);
              g.append("line").attr("x1",cx).attr("x2",cx).attr("y1",y(b.q1)).attr("y2",y(b.min))
                .attr("stroke","{c["axis_line"]}").attr("stroke-width",1.5);
              g.append("line").attr("x1",cx-bw*0.25).attr("x2",cx+bw*0.25).attr("y1",y(b.max)).attr("y2",y(b.max)).attr("stroke","{c["axis_line"]}").attr("stroke-width",1.5);
              g.append("line").attr("x1",cx-bw*0.25).attr("x2",cx+bw*0.25).attr("y1",y(b.min)).attr("y2",y(b.min)).attr("stroke","{c["axis_line"]}").attr("stroke-width",1.5);
              // IQR box
              g.append("rect")
                .attr("x",x(gname)).attr("width",bw)
                .attr("y",y(b.q3)).attr("height",Math.max(0,y(b.q1)-y(b.q3)))
                .attr("fill","#f97316").attr("opacity",0.4)
                .attr("stroke","#ea580c").attr("stroke-width",1)
                .on("mouseover",(ev)=>{{
                  tip.style("opacity",1).html(
                    gname+" floors (n="+b.n+")<br/>"+
                    "med: "+d3.format(",.1f")(b.median)+"<br/>"+
                    "IQR: "+d3.format(",.1f")(b.q1)+"-"+d3.format(",.1f")(b.q3)
                  ).style("left",(ev.pageX+12)+"px").style("top",(ev.pageY-24)+"px");
                }})
                .on("mouseout",()=>tip.style("opacity",0));
              // median line
              g.append("line").attr("x1",x(gname)).attr("x2",x(gname)+bw).attr("y1",y(b.median)).attr("y2",y(b.median))
                .attr("stroke","#9a3412").attr("stroke-width",2);
              // outlier dots
              (b.outliers||[]).forEach(ov => {{
                g.append("circle").attr("cx",cx).attr("cy",y(ov)).attr("r",2.5)
                  .attr("fill","#dc2626").attr("opacity",0.5);
              }});
            }});
            svg.append("text").attr("class","axis-label").attr("text-anchor","middle")
              .attr("x",margin.left+W/2).attr("y",height-4).text(p.x_label||"");
            svg.append("text").attr("class","axis-label").attr("text-anchor","middle")
              .attr("transform","rotate(-90)").attr("x",-(margin.top+H/2)).attr("y",16).text(p.y_label||"");
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)


def create_parallel_coordinates_d3_html(
    records: list[dict[str, float]],
    axes: list[str],
    *,
    color_axis: str | None = None,
    title: str = "parallel coordinates",
    theme: Theme = "light",
    max_records: int = 500,
    axis_labels: dict[str, str] | None = None,
) -> str:
    """Parallel coordinates chart with one line per building.

    Lines are colored by color_axis (warm scale from low to high). If more than
    max_records, samples evenly.
    """
    c = _theme_colors_d3_embedded(theme)
    if len(records) > max_records:
        step = max(1, len(records) // max_records)
        records = records[::step]
    payload = {
        "records": records,
        "axes": axes,
        "color_axis": color_axis,
        "title": title,
        "axis_labels": axis_labels or {},
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <style>
          html, body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem;
                 color-scheme: {c["color_scheme"]}; background: {c["bg"]}; color: {c["text"]}; }}
          .axis text {{ fill: {c["axis"]}; font-size: 10px; }}
          .axis line, .axis path {{ stroke: {c["axis_line"]}; }}
          .axis-label {{ fill: {c["axis"]}; font-size: 11px; font-weight: 600; }}
          .line {{ fill: none; stroke-width: 1; opacity: 0.35; }}
          .line:hover {{ opacity: 1; stroke-width: 2; }}
        </style>
        <script src="https://d3js.org/d3.v7.min.js"></script>
      </head>
      <body>
        <div id="pc" style="width:100%;height:380px;"></div>
        <script>
          const p = {data_json};
          const recs = p.records, axNames = p.axes, colorAx = p.color_axis;
          const axDisp = p.axis_labels || {{}};
          const container = document.getElementById("pc");
          if (!recs.length) {{
            container.innerHTML = "<span style='color:{c["placeholder"]}'>no data</span>";
          }} else {{
            const width = container.clientWidth || 600, height = 380;
            const margin = {{top:36,right:20,bottom:20,left:20}};
            const W = width-margin.left-margin.right;
            const H = height-margin.top-margin.bottom;
            const svg = d3.select(container).append("svg").attr("width",width).attr("height",height);
            const g = svg.append("g").attr("transform","translate("+margin.left+","+margin.top+")");
            // scales per axis
            const scales = {{}};
            axNames.forEach(ax => {{
              const ext = d3.extent(recs, r => r[ax]);
              scales[ax] = d3.scaleLinear().domain([ext[0]||0, ext[1]||1]).nice().range([H,0]);
            }});
            const xScale = d3.scalePoint().domain(axNames).range([0,W]);
            // color scale
            let colorScale = () => "{c["axis"]}";
            if (colorAx && scales[colorAx]) {{
              const cExt = d3.extent(recs, r => r[colorAx]);
              const cs = d3.scaleSequential(d3.interpolateYlOrRd).domain(cExt);
              colorScale = r => cs(r[colorAx]);
            }}
            // draw lines
            const lineGen = d3.line().defined(([,v])=>v!=null).x(([ax])=>xScale(ax)).y(([ax,v])=>scales[ax](v));
            recs.forEach(r => {{
              const pts = axNames.map(ax => [ax, r[ax]]);
              g.append("path").datum(pts).attr("class","line").attr("d",lineGen).attr("stroke",colorScale(r));
            }});
            // axes
            axNames.forEach(ax => {{
              const axG = g.append("g").attr("transform","translate("+xScale(ax)+",0)");
              axG.call(d3.axisLeft(scales[ax]).ticks(4));
              axG.append("text").attr("class","axis-label").attr("text-anchor","middle")
                .attr("y",-14).text((axDisp[ax] || ax).replace(/_/g," ").replace(/ zone weighted/i,"").replace(/ caution hours/i,""));
            }});
          }}
        </script>
      </body>
    </html>
    """
    return dedent(html)
