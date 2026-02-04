"""plotting utilities for d3-based visualizations."""

from __future__ import annotations

import json
from textwrap import dedent

import pandas as pd

from .utils import sanitize_for_json


def create_raw_data_d3_html(
    df: pd.DataFrame,
    value_column: str | tuple[str, ...],
    category_column: str | tuple[str, ...] | None = None,
    title: str = "raw data summary",
) -> str:
    """Build a small d3 dashboard for a single numeric column. Uses string keys for JSON."""
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
          body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            padding: 0.75rem;
            background: #f9fafb;
            color: #111827;
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
            background: #ffffff;
            border-radius: 0.75rem;
            padding: 0.75rem 1rem 1rem;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
            border: 1px solid #e5e7eb;
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
            fill: #4b5563;
            font-size: 11px;
          }}
          .axis text {{
            fill: #4b5563;
            font-size: 10px;
          }}
          .axis line,
          .axis path {{
            stroke: #e5e7eb;
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
                .style("padding", "0.5rem")
                .style("color", "#6b7280")
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
                .style("padding", "0.5rem")
                .style("color", "#6b7280")
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
                .style("padding", "0.5rem")
                .style("color", "#6b7280")
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
) -> str:
    """Build a histogram d3 card."""
    payload = {"values": values, "title": title, "x_label": x_label}
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; }}
          .chart {{ width: 100%; height: 260px; }}
          .axis-label {{ fill: #4b5563; font-size: 11px; }}
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
            container.innerHTML = "no data available";
          }} else {{
            const width = container.clientWidth || 360;
            const height = 260;
            const margin = {{ top: 16, right: 16, bottom: 40, left: 52 }};
            const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;
            const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
            const x = d3.scaleLinear().domain(d3.extent(values)).nice().range([0, chartWidth]);
            const bins = d3.bin().domain(x.domain()).thresholds(25)(values);
            const y = d3.scaleLinear().domain([0, d3.max(bins, d => d.length) || 1]).nice().range([chartHeight, 0]);
            g.append("g").attr("transform", "translate(0," + chartHeight + ")").call(d3.axisBottom(x).ticks(6));
            g.append("g").call(d3.axisLeft(y).ticks(5));
            g.selectAll("rect")
              .data(bins)
              .enter()
              .append("rect")
              .attr("x", d => x(d.x0))
              .attr("y", d => y(d.length))
              .attr("width", d => Math.max(0, x(d.x1) - x(d.x0) - 1))
              .attr("height", d => chartHeight - y(d.length))
              .attr("fill", "#4f46e5")
              .attr("opacity", 0.85)
              .on("mouseover", (event, d) => {{
                tooltip.style("opacity", 1)
                  .html("range: [" + d3.format(",.2f")(d.x0) + ", " + d3.format(",.2f")(d.x1) + ")<br/>count: " + d.length)
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
              .attr("stroke", "#ef4444")
              .attr("stroke-width", 2)
              .attr("d", kdeLine);
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
              .text("count");
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
) -> str:
    """Build a pie d3 card."""
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
          body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; }}
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
            container.innerHTML = "no data available";
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
            g.selectAll("path")
              .data(pie(data))
              .enter()
              .append("path")
              .attr("d", arc)
              .attr("fill", d => color(d.data.label))
              .attr("stroke", "#fff")
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


def create_monthly_timeseries_d3_html(
    records: list[dict],
    meters: list[str],
    colors: dict[str, str],
    title: str,
    y_label: str,
) -> str:
    """Build a monthly timeseries d3 card with legend."""
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
          body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; }}
          .chart {{ width: 100%; height: 300px; }}
          .legend {{ display: flex; flex-wrap: wrap; gap: 0.5rem; font-size: 0.75rem; margin-top: 0.5rem; }}
          .legend-item {{ display: flex; align-items: center; gap: 0.4rem; }}
          .legend-color {{ width: 12px; height: 12px; border-radius: 2px; }}
          .axis-label {{ fill: #4b5563; font-size: 11px; }}
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
            container.innerHTML = "no data available";
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
