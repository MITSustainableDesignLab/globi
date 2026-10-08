"""MkDocs hook: build the "Data & outputs" pages from a globi-data checkout.

globi-data (https://github.com/MITSustainableDesignLab/globi-data) holds the
versioned inputs and the provenance records of every simulation run. Rather
than copy its contents into these docs, this hook reads a checkout at build
time and generates:

- ``data/runs/index.md`` and one ``data/runs/<Partner>.md`` per partner,
- ``data/status.md``, ``data/inputs.md`` and ``data/surrogates.md``,
- ``data/reference/*.md``, globi-data's own reference docs with links rewritten.

The checkout is found, in order, at ``$GLOBI_DATA_ROOT``, ``../globi-data``,
``../../globi-data`` (both relative to ``mkdocs.yml``), or ``.globi-data``.
Pages that must not be published (discussion drafts, results from real partner
buildings) live outside this public repository. Set ``GLOBI_INTERNAL_DOCS`` to a
folder of Markdown files and they are added under ``internal/`` with a banner. The
build refuses to ``gh-deploy`` while that variable is set.

If no globi-data checkout exists the pages are still generated, each saying the data was not
available, so a build never fails for lack of the sibling repository. Set
``GLOBI_DATA_REQUIRED=1`` to make that an error instead.
"""

from __future__ import annotations

import html
import logging
import os
import posixpath
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from mkdocs.exceptions import PluginError
from mkdocs.structure.files import File, Files

log = logging.getLogger("mkdocs.hooks.globi_data")

GITHUB = "https://github.com/MITSustainableDesignLab/globi-data"
BLOB = f"{GITHUB}/blob/main"
TREE = f"{GITHUB}/tree/main"

# globi-data docs pulled in verbatim (links rewritten), keyed by source path.
REFERENCE_DOCS = {
    "docs/SCHEMA.md": "data/reference/schema.md",
    "docs/DATA-COMPONENTS.md": "data/reference/data-components.md",
    "docs/HOW-TO-ADD-A-VERSION.md": "data/reference/add-a-version.md",
    "docs/HOW-TO-DOWNLOAD-INPUTS.md": "data/reference/download-inputs.md",
}
# The partner source repository is private and must never be named on the
# public site. globi-data's own docs do name it, so these rewrites are applied
# to them on the way in, and `on_page_markdown` fails the build if any page
# still matches PRIVATE_PATTERN. If globi-data rewords a passage, the guard
# fires and a rewrite here needs updating.
PRIVATE_PATTERN = re.compile(r"partners[-_]data|globi-partners latest-results", re.I)
GIS_NOT_PUBLISHED = (
    "Building footprints are partner data and are not published. Each version\n"
    "records their exact size and fingerprint, so anyone who holds the file can\n"
    "confirm it is the one these results were built from."
)
PUBLIC_REWRITES: dict[str, list[tuple[str, str]]] = {
    "docs/HOW-TO-DOWNLOAD-INPUTS.md": [
        (
            r"## The building footprints are not here\n.*?(?=\n## )",
            "## The building footprints are not here\n\n" + GIS_NOT_PUBLISHED + "\n",
        ),
    ],
    "docs/HOW-TO-ADD-A-VERSION.md": [
        (r"--from \S*partners-data\S*", "--from <partner source directory>"),
    ],
    "docs/SCHEMA.md": [
        (
            r"  repo: globi-partners-data\n  remote: \S+\n",
            "  repo: <partner source repository>\n",
        ),
        (r"repo: globi-partners-data", "repo: <partner source repository>"),
        (
            r"`globi-partners latest-results --yaml-dir`",
            "the legacy `latest-results --yaml-dir` export",
        ),
        (
            r"`globi-partners-data/\.env` currently\nsets",
            "the run environment currently\nsets",
        ),
        (r"globi_partners_data: \{[^}]*\}", "source_data: {...}"),
    ],
    "docs/DATA-COMPONENTS.md": [
        (
            r"the preprocessor in `globi-partners-data`\n\(`packages/globi/src/globi/",
            "the preprocessor in globi\n(`src/globi/",
        ),
    ],
}

# Other globi-data files that have a generated page here.
PAGE_FOR = {
    "outputs/STATUS.md": "data/status.md",
    "outputs/README.md": "data/runs/index.md",
    "inputs/README.md": "data/inputs.md",
}

# Status keys follow globi-data's STATE_BADGES (src/globi_data/render.py).
# Each maps to (css class, icon, label); the class picks a status color.
STATUS_STYLE = {
    "ok": ("good", "●", "up to date"),
    "metadata-drift": ("info", "●", "docs changed only"),
    "code-drift": ("warning", "▲", "code changed"),
    "inferred": ("neutral", "○", "assumed"),
    "unpinned": ("neutral", "○", "unknown"),
    "stale": ("critical", "■", "stale"),
    "broken-pin": ("critical", "■", "broken"),
    "tampered": ("critical", "■", "tampered"),
}
LABEL_TO_STATUS = {label: key for key, (_, _, label) in STATUS_STYLE.items()}
LABEL_TO_STATUS["broken / tampered"] = "broken-pin"
STATUS_ORDER = list(STATUS_STYLE)
# globi-data's SEVERITY order (src/globi_data/status.py).
STATUS_ORDER_WORST_FIRST = [
    "tampered",
    "broken-pin",
    "stale",
    "code-drift",
    "unpinned",
    "inferred",
    "metadata-drift",
    "ok",
]

WEATHER_LABEL = {"tmy": "Current climate (TMY)", "ftmy": "Future climate (fTMY 2050)"}


# ---------------------------------------------------------------- data model


@dataclass
class Experiment:
    """The current output version of one ``<Partner>/<weather>/<Scenario>``."""

    name: str
    partner: str
    weather: str
    scenario: str
    scenario_kind: str
    current: str
    manifest: dict[str, Any]
    versions: list[dict[str, Any]]
    status: str = "unpinned"
    status_detail: str = ""

    @property
    def run_time(self) -> datetime | None:
        """Parse ``run_timestamp``, or None if it is not a timestamp."""
        ts = self.manifest.get("run_timestamp")
        try:
            return datetime.strptime(str(ts), "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            return None

    @property
    def path(self) -> str:
        """The experiment's directory, relative to the globi-data root."""
        return f"outputs/runs/{self.name}"


@dataclass
class GlobiData:
    """Everything the generated pages read from a globi-data checkout."""

    root: Path | None
    commit: str | None = None
    experiments: list[Experiment] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    surrogates: list[dict[str, Any]] = field(default_factory=list)
    batches: list[dict[str, Any]] = field(default_factory=list)
    status_generated_at: str | None = None

    @property
    def partners(self) -> list[str]:
        """Partners with at least one recorded experiment."""
        return sorted({e.partner for e in self.experiments})


def _yaml(path: Path) -> Any:
    with path.open() as f:
        return yaml.safe_load(f)


def locate_root(config_dir: Path) -> Path | None:
    """Find a globi-data checkout; see the module docstring for the order."""
    candidates = []
    if env := os.environ.get("GLOBI_DATA_ROOT"):
        candidates.append(Path(env).expanduser())
    candidates += [
        config_dir.parent / "globi-data",
        config_dir.parent.parent / "globi-data",
        config_dir / ".globi-data",
    ]
    for c in candidates:
        path = c if c.is_absolute() else config_dir / c
        if (path / "published.yml").exists() or (path / "inputs").is_dir():
            return path.resolve()
    return None


def _git_commit(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            ref_path = root / ".git" / ref[5:]
            if ref_path.exists():
                return ref_path.read_text().strip()[:7]
            packed = (root / ".git" / "packed-refs").read_text()
            m = re.search(rf"^([0-9a-f]{{40}}) {re.escape(ref[5:])}$", packed, re.M)
            return m.group(1)[:7] if m else None
        return ref[:7]
    except OSError:
        return None


def _parse_status(root: Path) -> tuple[dict[str, tuple[str, str]], str | None]:
    """Read the generated ``outputs/STATUS.md`` rather than recompute it."""
    path = root / "outputs" / "STATUS.md"
    if not path.exists():
        return {}, None
    text = path.read_text()
    generated = re.search(r"_Generated (.+?)\._", text)
    rows = {}
    for line in text.splitlines():
        m = re.match(
            r"\|\s*\[([^\]]+)\]\([^)]*\)\s*\|\s*(.+?)\s*\|.*\|\s*(.*?)\s*\|\s*$", line
        )
        if not m:
            continue
        badge = re.sub(r"^[^\w]+", "", m.group(2)).strip()
        rows[m.group(1)] = (LABEL_TO_STATUS.get(badge, "unpinned"), m.group(3))
    return rows, generated.group(1) if generated else None


def load(root: Path | None) -> GlobiData:
    """Read every manifest the generated pages need."""
    data = GlobiData(root=root)
    if root is None:
        return data
    data.commit = _git_commit(root)
    status, data.status_generated_at = _parse_status(root)

    for current_file in sorted((root / "outputs" / "runs").glob("*/*/*/CURRENT.yml")):
        exp_dir = current_file.parent
        current = _yaml(current_file)
        manifest_path = exp_dir / current["manifest"]
        if not manifest_path.exists():
            log.warning("globi-data: %s points at a missing manifest", current_file)
            continue
        manifest = _yaml(manifest_path)
        versions_file = exp_dir / "versions.yml"
        versions = (
            _yaml(versions_file).get("versions", []) if versions_file.exists() else []
        )
        name = manifest.get("experiment") or str(
            exp_dir.relative_to(root / "outputs" / "runs")
        )
        exp = Experiment(
            name=name,
            partner=manifest.get("partner", exp_dir.parts[-3]),
            weather=manifest.get("weather", exp_dir.parts[-2]),
            scenario=manifest.get("scenario_value", exp_dir.parts[-1]),
            scenario_kind=manifest.get("scenario_kind") or "",
            current=current["current"],
            manifest=manifest,
            versions=versions,
        )
        exp.status, exp.status_detail = status.get(name, ("unpinned", ""))
        data.experiments.append(exp)

    index = root / "inputs" / "index.yml"
    if index.exists():
        data.inputs = _yaml(index).get("partners", [])

    for manifest_path in sorted(
        (root / "outputs" / "surrogates").glob("*/v*/surrogate-version.yml")
    ):
        data.surrogates.append(
            _yaml(manifest_path) | {"_dir": manifest_path.parent.relative_to(root)}
        )

    for manifest_path in sorted((root / "outputs" / "batches").glob("*/v*/*.yml")):
        doc = _yaml(manifest_path)
        if isinstance(doc, dict) and doc.get("kind", "").endswith("version"):
            data.batches.append(doc | {"_dir": manifest_path.parent.relative_to(root)})
    return data


# ---------------------------------------------------------------- rendering helpers


def esc(value: Any) -> str:
    """HTML-escape a value for use in text or an attribute."""
    return html.escape(str(value), quote=True)


def chip(status: str) -> str:
    """A status chip: icon and label, with color as support."""
    cls, icon, label = STATUS_STYLE.get(status, STATUS_STYLE["unpinned"])
    return f'<span class="gd-chip gd-chip--{cls}"><span aria-hidden="true">{icon}</span> {label}</span>'


def short(sha: str | None, n: int = 12) -> str:
    """A shortened hash in code style, or a dash."""
    return f"`{sha[:n]}`" if sha else "—"


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Render a Markdown table."""
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += [
        "| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |"
        for row in rows
    ]
    return "\n".join(out)


def unavailable(data: GlobiData) -> str | None:
    """The warning shown on data pages when no checkout was found."""
    if data.root is not None:
        return None
    return (
        '!!! warning "globi-data was not found at build time"\n'
        "    This page is generated from a checkout of\n"
        f"    [globi-data]({GITHUB}). Clone it beside this repository, or set\n"
        "    `GLOBI_DATA_ROOT`, and rebuild the docs.\n"
    )


def source_note(data: GlobiData, path: str) -> str:
    """A footer naming the globi-data file a page was generated from."""
    at = f" at commit `{data.commit}`" if data.commit else ""
    return (
        f'<p class="gd-source">Generated from <a href="{BLOB}/{path}"><code>globi-data/{path}</code></a>'
        f"{at}. Edit the data there, not this page.</p>"
    )


def stat_tiles(tiles: list[tuple[str, Any, str]]) -> str:
    """A row of stat tiles: (label, value, optional sub-line)."""
    cells = "".join(
        f'<div class="gd-tile"><div class="gd-tile__label">{esc(label)}</div>'
        f'<div class="gd-tile__value">{esc(value)}</div>'
        + (f'<div class="gd-tile__sub">{sub}</div>' if sub else "")
        + "</div>"
        for label, value, sub in tiles
    )
    return f'<div class="gd-tiles">{cells}</div>'


# ---------------------------------------------------------------- charts


def timeline_svg(experiments: list[Experiment]) -> str:
    """Dot plot of when each run happened: one row per partner, colored by weather."""
    runs = [e for e in experiments if e.run_time]
    if not runs:
        return ""
    partners = sorted({e.partner for e in runs})
    t0 = min(e.run_time for e in runs)  # type: ignore[type-var]
    t1 = max(e.run_time for e in runs)  # type: ignore[type-var]
    day0 = t0.replace(hour=0, minute=0, second=0)
    n_days = max((t1 - day0).days + 1, 2)
    left, right, top, row_h = 168, 24, 16, 34
    width = 720
    plot_w = width - left - right
    height = top + row_h * len(partners) + 40

    def x(t: datetime) -> float:
        return left + plot_w * (t - day0).total_seconds() / (n_days * 86400)

    parts = [
        f'<svg class="gd-chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-labelledby="gd-tl-title" preserveAspectRatio="xMinYMin meet">',
        '<title id="gd-tl-title">Simulation run dates by partner, colored by weather</title>',
    ]
    step = 1 if n_days <= 14 else 7
    for d in range(0, n_days + 1, step):
        tx = left + plot_w * d / n_days
        parts.append(
            f'<line class="gd-grid" x1="{tx:.1f}" x2="{tx:.1f}" y1="{top}" y2="{height - 34}"/>'
        )
        if d < n_days and (d % (2 * step) == 0 or n_days <= 8):
            label = day0.toordinal() + d
            parts.append(
                f'<text class="gd-axis" x="{tx:.1f}" y="{height - 16}" text-anchor="middle">'
                f"{datetime.fromordinal(label).strftime('%b %-d')}</text>"
            )
    for i, partner in enumerate(partners):
        cy = top + row_h * i + row_h / 2
        parts.append(
            f'<text class="gd-label" x="{left - 12}" y="{cy + 4:.1f}" text-anchor="end">'
            f"{esc(partner.replace('_', ' '))}</text>"
        )
        parts.append(
            f'<line class="gd-baseline" x1="{left}" x2="{width - right}" y1="{cy}" y2="{cy}"/>'
        )
        for e in sorted(
            (r for r in runs if r.partner == partner), key=lambda r: r.weather != "tmy"
        ):
            dy = -5 if e.weather == "tmy" else 5
            series = 1 if e.weather == "tmy" else 2
            tip = f"{e.name} · run {e.run_time:%Y-%m-%d %H:%M} · {e.manifest.get('version', '')}"  # type: ignore[union-attr]
            parts.append(
                f'<a href="{e.partner}/#{anchor(e)}"><circle class="gd-dot gd-series-{series}" '
                f'cx="{x(e.run_time):.1f}" cy="{cy + dy}" r="5"><title>{esc(tip)}</title></circle></a>'  # type: ignore[arg-type]
            )
    parts.append("</svg>")
    legend = (
        '<div class="gd-legend">'
        '<span><i class="gd-key gd-series-1"></i>tmy (current climate)</span>'
        '<span><i class="gd-key gd-series-2"></i>ftmy (future climate)</span></div>'
    )
    return f'<figure class="gd-figure">{legend}{"".join(parts)}</figure>'


def hbar_svg(
    title: str, rows: list[tuple[str, float]], fmt: str = "{:.2f}", unit: str = ""
) -> str:
    """Horizontal bars for one measure; value labelled at each bar's tip."""
    if not rows:
        return ""
    vmax = max(v for _, v in rows) or 1.0
    left, right, bar, gap, top = 170, 64, 18, 12, 8
    width = 640
    plot_w = width - left - right
    height = top + len(rows) * (bar + gap) + 8
    parts = [
        f'<svg class="gd-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">',
        f'<line class="gd-baseline" x1="{left}" x2="{left}" y1="{top - 4}" y2="{height - 4}"/>',
    ]
    for i, (label, value) in enumerate(rows):
        y = top + i * (bar + gap)
        w = max(plot_w * value / vmax, 2)
        r = min(4, w / 2)
        path = (
            f"M{left},{y} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} v{bar - 2 * r} "
            f"a{r},{r} 0 0 1 -{r},{r} h-{w - r:.1f} z"
        )
        text = fmt.format(value) + unit
        parts.append(
            f'<text class="gd-label" x="{left - 10}" y="{y + bar / 2 + 4}" text-anchor="end">{esc(label)}</text>'
            f'<path class="gd-bar gd-series-1" d="{path}"><title>{esc(label)}: {esc(text)}</title></path>'
            f'<text class="gd-value" x="{left + w + 6:.1f}" y="{y + bar / 2 + 4}">{esc(text)}</text>'
        )
    parts.append("</svg>")
    return f'<figure class="gd-figure"><figcaption>{esc(title)}</figcaption>{"".join(parts)}</figure>'


def status_bar(counts: Counter[str]) -> str:
    """A single 100% bar of experiments by status, with a legend of counts."""
    total = sum(counts.values())
    if not total:
        return ""
    segs, legend = [], []
    for key in STATUS_ORDER:
        n = counts.get(key, 0)
        if not n:
            continue
        cls, icon, label = STATUS_STYLE[key]
        segs.append(
            f'<span class="gd-seg gd-status-{cls}" style="flex:{n}" title="{label}: {n}"></span>'
        )
        legend.append(
            f'<span><i class="gd-key gd-status-{cls}"></i>{icon} {label} <b>{n}</b></span>'
        )
    return (
        f'<figure class="gd-figure"><div class="gd-legend">{"".join(legend)}</div>'
        f'<div class="gd-stack" role="img" aria-label="Experiments by status">{"".join(segs)}</div></figure>'
    )


# ---------------------------------------------------------------- pages


def anchor(e: Experiment) -> str:
    """The heading anchor of an experiment on its partner page."""
    return re.sub(r"[^a-z0-9]+", "-", f"{e.weather}-{e.scenario}".lower()).strip("-")


def coverage_matrix(data: GlobiData) -> str:
    """Partners x (weather, scenario kind), each cell the scenario and its status."""
    cols = [(w, k) for w in ("tmy", "ftmy") for k in ("baseline", "alternative")]
    by_key = {(e.partner, e.weather, e.scenario_kind): e for e in data.experiments}
    head = "".join(f"<th>{w}<br><small>{k}</small></th>" for w, k in cols)
    rows = []
    for p in data.partners:
        cells = []
        for w, k in cols:
            e = by_key.get((p, w, k))
            if e is None:
                cells.append('<td class="gd-empty">—</td>')
            else:
                cells.append(
                    f'<td><a href="{p}/#{anchor(e)}">{esc(e.scenario)}</a><br>{chip(e.status)}'
                    f" <code>{esc(e.current)}</code></td>"
                )
        rows.append(
            f'<tr><th scope="row"><a href="{p}/">{esc(p.replace("_", " "))}</a></th>{"".join(cells)}</tr>'
        )
    return (
        '<div class="gd-scroll"><table class="gd-matrix"><thead><tr><th>Partner</th>'
        f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def page_runs_index(data: GlobiData) -> str:
    """The run catalog: tiles, coverage matrix, timeline and table."""
    out = ["# Run catalog", ""]
    if msg := unavailable(data):
        return "\n".join([*out, msg])
    exps = data.experiments
    n_files = sum(
        len(e.manifest.get("result_files") or e.manifest.get("results") or [])
        for e in exps
    )
    confidence = Counter(
        e.manifest.get("provenance", {}).get("input", {}).get("confidence")
        for e in exps
    )
    out += [
        "Every simulation run recorded in globi-data, one entry per",
        "`<Partner>/<weather>/<Scenario>`. The parquet results stay in S3; what is",
        "shown here is the record of where they are and what produced them. See",
        "[Output structure](../outputs-structure.md) for how these records are laid out.",
        "",
        stat_tiles([
            ("Partners", len(data.partners), ""),
            (
                "Experiments",
                len(exps),
                f"{len(exps) // max(len(data.partners), 1)} per partner",
            ),
            ("Result files", n_files, "parquet, in S3"),
            (
                "Input pinned exactly",
                confidence.get("exact", 0),
                f"{confidence.get('inferred', 0)} inferred",
            ),
        ]),
        "",
        "## Coverage",
        "",
        "Each partner runs two scenarios (a baseline and an alternative) under two",
        "weather files. Each cell links to that run's provenance.",
        "",
        coverage_matrix(data),
        "",
        "## When the runs happened",
        "",
        "Hover a dot for the run's experiment and timestamp; click it for the details.",
        "",
        timeline_svg(exps),
        "",
        "## All experiments",
        "",
    ]
    rows = []
    for e in exps:
        prov = e.manifest.get("provenance", {})
        rows.append([
            f"[{e.name}]({e.partner}.md#{anchor(e)}) `{e.current}`",
            f"{e.manifest.get('version', '')} · {e.run_time:%Y-%m-%d}"
            if e.run_time
            else "",
            f"`{prov.get('input', {}).get('version', '—')}` {prov.get('input', {}).get('confidence', '—')}",
            chip(e.status),
        ])
    out.append(md_table(["Experiment", "Scythe run", "Input", "Status"], rows))
    if data.batches:
        out += ["", "## Batches", ""]
        out.append(
            md_table(
                ["Batch", "Version", "Status", "Summary"],
                [
                    [
                        f"[{b.get('experiment', b['_dir'])}]({TREE}/{b['_dir']})",
                        f"`{b.get('output_version', '')}`",
                        b.get("status", ""),
                        b.get("summary", ""),
                    ]
                    for b in data.batches
                ],
            )
        )
    out += ["", source_note(data, "outputs/index.yml")]
    return "\n".join(out)


def lineage_mermaid(partner: str, exps: list[Experiment]) -> str:
    """A flowchart from input versions to runs to their S3 prefixes."""
    lines = ["```mermaid", "flowchart LR"]
    inputs = sorted({
        e.manifest.get("provenance", {}).get("input", {}).get("version", "?")
        for e in exps
    })
    for v in inputs:
        lines.append(f'    in_{v}[("inputs/{partner}/{v}")]')
    for i, e in enumerate(exps):
        inp = e.manifest.get("provenance", {}).get("input", {})
        edge = "-->" if inp.get("confidence") == "exact" else "-.->"
        lines.append(
            f'    in_{inp.get("version", "?")} {edge} r{i}["{e.weather} / {e.scenario}<br/>{e.current}"]'
        )
        lines.append(
            f'    r{i} --> s{i}[/"S3: {e.manifest.get("version", "")}<br/>{e.manifest.get("run_timestamp", "")}"/]'
        )
    lines += [
        "```",
        "",
        "<small>Solid arrow: input version recorded at run time. "
        "Dashed: inferred during backfill.</small>",
    ]
    return "\n".join(lines)


def page_partner(data: GlobiData, partner: str) -> str:
    """One partner's experiments with full provenance."""
    exps = sorted(
        (e for e in data.experiments if e.partner == partner),
        key=lambda e: (e.weather != "tmy", e.scenario_kind != "baseline"),
    )
    out = [f"# {partner.replace('_', ' ')}", ""]
    inp = next((i for i in data.inputs if i["partner"] == partner), None)
    if inp:
        out += [
            f"Current input bundle: [`{inp['current']}`]({TREE}/inputs/partners/{partner}/{inp['current']}) "
            f"({inp.get('bundle_kind', '')}, {len(inp.get('versions', []))} version(s)).",
            "",
        ]
    out += ["## Lineage", "", lineage_mermaid(partner, exps), ""]
    for e in exps:
        m = e.manifest
        prov = m.get("provenance", {})
        pin, code, store = (
            prov.get("input", {}),
            prov.get("code", {}),
            prov.get("storage", {}),
        )
        globi = code.get("globi") or {}
        out += [
            f"## {WEATHER_LABEL.get(e.weather, e.weather)} · {e.scenario} {{ #{anchor(e)} }}",
            "",
            f"{chip(e.status)} {esc(e.status_detail)}",
            "",
            f"`{e.name}` · output `{e.current}` · {esc(m.get('summary', ''))}",
            "",
            md_table(
                ["", ""],
                [
                    ["Scenario", f"{e.scenario} ({e.scenario_kind})"],
                    [
                        "Input version",
                        f"[`{pin.get('version')}`]({BLOB}/{pin.get('manifest_path', '')}) — "
                        f"confidence **{pin.get('confidence')}**",
                    ],
                    ["Input bundle sha256", short(pin.get("bundle_sha256"))],
                    [
                        "GIS file (not published)",
                        f"{short((pin.get('gis_file') or {}).get('sha256'))}, "
                        f"{((pin.get('gis_file') or {}).get('bytes') or 0) / 1e6:,.0f} MB",
                    ],
                    [
                        "globi",
                        f"`{globi.get('describe') or short(globi.get('commit'))}`",
                    ],
                    [
                        "Scythe run",
                        f"{m.get('version', '')} · `{m.get('run_timestamp', '')}`",
                    ],
                    ["S3 run prefix", f"`{store.get('run_prefix', '')}`"],
                ],
            ),
            "",
            '??? note "Result files"',
            "",
            "    "
            + md_table(
                ["Key", "Object", "sha256"],
                [
                    [
                        f"`{r['result_key']}`",
                        f"`final/{posixpath.basename(r['s3_uri'])}`",
                        short(r.get("sha256"))
                        if r.get("sha256")
                        else f"not computed ({r.get('sha256_source')})",
                    ]
                    for r in m.get("result_files", [])
                ],
            ).replace("\n", "\n    "),
            "",
            "    Download with `globi-data outputs download "
            + e.name
            + " --dest ./results`.",
            "",
        ]
        if len(e.versions) > 1:
            out += [
                md_table(
                    ["Version", "Status", "Created", "Summary"],
                    [
                        [
                            f"`{v['version']}`",
                            v.get("status", ""),
                            str(v.get("created_at", ""))[:10],
                            v.get("summary", ""),
                        ]
                        for v in e.versions
                    ],
                ),
                "",
            ]
        out += [
            f"[Manifest on GitHub]({BLOB}/{e.path}/{e.current}/output-version.yml)",
            "",
        ]
    out.append(source_note(data, f"outputs/runs/{partner}"))
    return "\n".join(out)


def page_status(data: GlobiData) -> str:
    """Every experiment's staleness verdict."""
    out = ["# Results status", ""]
    if msg := unavailable(data):
        return "\n".join([*out, msg])
    at = (
        f" globi-data last regenerated it at {data.status_generated_at}."
        if data.status_generated_at
        else ""
    )
    out += [
        "Whether each set of results still matches the inputs and code that are current.",
        f"This is read from globi-data's generated `outputs/STATUS.md`.{at}",
        "",
        status_bar(Counter(e.status for e in data.experiments)),
        "",
        md_table(
            ["Status", "Meaning"],
            [
                [chip("ok"), "Built from the current inputs."],
                [
                    chip("stale"),
                    "Inputs changed in a way that affects results. Re-run.",
                ],
                [
                    chip("metadata-drift"),
                    "Inputs changed, but only documentation. No re-run needed.",
                ],
                [chip("code-drift"), "Simulation code moved on since this run."],
                [
                    chip("inferred"),
                    "Which inputs produced this was inferred during backfill, not recorded.",
                ],
                [
                    chip("broken-pin"),
                    "The recorded inputs cannot be found or no longer match.",
                ],
            ],
        ),
        "",
        "## By experiment",
        "",
        "Grouped worst-first. Each experiment links to its full provenance.",
        "",
    ]
    groups: dict[str, list[Experiment]] = defaultdict(list)
    for e in data.experiments:
        groups[e.status].append(e)
    for status in STATUS_ORDER_WORST_FIRST:
        exps = groups.get(status)
        if not exps:
            continue
        details = {e.status_detail for e in exps}
        shared = len(details) == 1
        out += [f"### {chip(status)} {len(exps)}", ""]
        if shared and (detail := details.pop()):
            out += [esc(detail), ""]
        rows = []
        for e in exps:
            pin = e.manifest.get("provenance", {}).get("input", {})
            cur = next(
                (i["current"] for i in data.inputs if i["partner"] == e.partner), "—"
            )
            row = [
                f"[{e.name}](runs/{e.partner}.md#{anchor(e)})",
                f"`{pin.get('version')}`",
                f"`{cur}`",
            ]
            rows.append(row if shared else [*row, esc(e.status_detail)])
        headers = ["Experiment", "Built from", "Current input"]
        out += [md_table(headers if shared else [*headers, "Detail"], rows), ""]
    out += ["", source_note(data, "outputs/STATUS.md")]
    return "\n".join(out)


def page_inputs(data: GlobiData) -> str:
    """The current input bundle for each partner."""
    out = ["# Input bundles", ""]
    if msg := unavailable(data):
        return "\n".join([*out, msg])
    used = Counter(
        e.manifest.get("provenance", {}).get("input", {}).get("partner")
        for e in data.experiments
    )
    out += [
        "Each partner's inputs are frozen, numbered bundles. Output records pin a",
        "bundle by the sha256 of its `input-version.yml`, so a result can always be",
        "traced to the exact files that produced it. See",
        "[What makes up a region](reference/data-components.md) for what each file does.",
        "",
    ]
    rows = []
    for p in data.inputs:
        statuses = Counter(v.get("status") for v in p.get("versions", []))
        rows.append([
            f"[{p['partner']}]({TREE}/inputs/partners/{p['partner']})",
            f"`{p.get('current')}`",
            p.get("bundle_kind", ""),
            ", ".join(f"{n} {s}" for s, n in statuses.items()),
            used.get(p["partner"], 0) or "—",
            short(p.get("bundle_sha256")),
        ])
    out.append(
        md_table(
            [
                "Partner",
                "Current",
                "Kind",
                "Versions",
                "Experiments built on it",
                "Bundle sha256",
            ],
            rows,
        )
    )
    out += ["", source_note(data, "inputs/index.yml")]
    return "\n".join(out)


def _feature_groups(features: list[dict[str, Any]]) -> list[list[str]]:
    """Collapse runs of numbered features (shading_mask_00..47) into one row."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in features:
        groups[re.sub(r"_\d+$", "_*", f["name"])].append(f)
    rows = []
    for name, fs in groups.items():
        f = fs[0]
        label = f"`{name}` x{len(fs)}" if len(fs) > 1 else f"`{name}`"
        rows.append([
            label,
            f["source"],
            f["kind"],
            f.get("unit") or "",
            f"`{f['default']}`" if f.get("default") is not None else "",
            esc(f.get("description") or ""),
        ])
    return rows


def page_surrogates(data: GlobiData) -> str:
    """Every recorded surrogate version."""
    out = ["# Surrogate models", ""]
    if msg := unavailable(data):
        return "\n".join([*out, msg])
    out += [
        "A surrogate is a trained regressor that stands in for EnergyPlus: semantic",
        "fields, weather and geometry go in, end-use energy intensity comes out. Each",
        "is versioned under `outputs/surrogates/<Partner>/vNNN/` with its",
        "`transforms.yml` (the model's input contract) kept in git and the model",
        "itself in S3.",
        "",
    ]
    if not data.surrogates:
        out.append("No surrogate versions are recorded yet.")
    for s in data.surrogates:
        out += [
            f"## {s['partner']} `{s['surrogate_version']}` — {s.get('status', '')}",
            "",
        ]
        if s.get("example"):
            out += [
                '!!! warning "Illustrative example"',
                f"    {esc(s.get('summary', ''))}",
                "",
            ]
        by_source = Counter(f["source"] for f in s.get("features", []))
        training = s.get("provenance", {}).get("training", {})
        model = s.get("model", {})
        out += [
            stat_tiles([
                ("Backend", model.get("backend", "—"), esc(model.get("format", ""))),
                (
                    "Features",
                    len(s.get("features", [])),
                    " · ".join(f"{n} {src}" for src, n in by_source.most_common()),
                ),
                ("Targets", len(s.get("targets", [])), "end uses, kWh/m²/yr"),
                (
                    "Training samples",
                    training.get("n_samples", "—"),
                    f"{training.get('n_iterations', '—')} iterations",
                ),
            ]),
            "",
        ]
        metrics = (s.get("metrics") or {}).get("per_target") or {}
        if metrics:

            def end_use(name: str) -> str:
                """The last path segment of a target name."""
                return name.rsplit("/", 1)[-1]

            rows = sorted(
                ((end_use(k), v.get("cvrmse") or 0.0) for k, v in metrics.items()),
                key=lambda r: -r[1],
            )
            out += [
                hbar_svg(
                    f"CV(RMSE) on held-out folds, by end use (lower is better; {metrics and s['metrics'].get('n_folds')} folds)",
                    [(n, v * 100) for n, v in rows],
                    fmt="{:.0f}",
                    unit="%",
                ),
                "",
                md_table(
                    ["End use", "R²", "CV(RMSE)", "NMBE"],
                    [
                        [end_use(k), v.get("r2"), v.get("cvrmse"), v.get("nmbe")]
                        for k, v in metrics.items()
                    ],
                ),
                "",
            ]
        out += [
            "**Weather options.** Weather is a model input, not a directory level, so one",
            "surrogate covers current and future climate.",
            "",
            md_table(
                ["Label", "Value", "File in the pinned input bundle"],
                [
                    [w.get("label"), f"`{w['value']}`", f"`{w.get('input_file')}`"]
                    for w in s.get("weather_options", [])
                ],
            ),
            "",
            '??? note "Features"',
            "",
            "    "
            + md_table(
                ["Feature", "Source", "Kind", "Unit", "Default", "Notes"],
                _feature_groups(s.get("features", [])),
            ).replace("\n", "\n    "),
            "",
            f"[Manifest]({BLOB}/{s['_dir']}/surrogate-version.yml) · "
            f"[transforms.yml]({BLOB}/{s['_dir']}/transforms.yml)",
            "",
        ]
    out.append(source_note(data, "outputs/surrogates"))
    return "\n".join(out)


def rewrite_links(text: str, src: str, dest: str) -> str:
    """Point a globi-data doc's relative links at pages here, or at GitHub."""
    src_dir = posixpath.dirname(src)
    dest_dir = posixpath.dirname(dest)
    targets = REFERENCE_DOCS | PAGE_FOR

    def fix(m: re.Match[str]) -> str:
        label, url = m.group(1), m.group(2)
        if re.match(r"^[a-z]+:|^#|^/", url):
            return m.group(0)
        path, _, frag = url.partition("#")
        resolved = posixpath.normpath(posixpath.join(src_dir, path))
        if resolved in targets:
            new = posixpath.relpath(targets[resolved], dest_dir)
        else:
            kind = (
                "tree"
                if path.endswith("/") or "." not in posixpath.basename(resolved)
                else "blob"
            )
            new = f"{GITHUB}/{kind}/main/{resolved}"
        return f"[{label}]({new}{'#' + frag if frag else ''})"

    return re.sub(r"\[([^\]]*)\]\(([^)\s]+)\)", fix, text)


def page_reference(data: GlobiData, src: str, dest: str) -> str:
    """A globi-data doc with its links rewritten for this site."""
    title = posixpath.basename(src)
    if data.root is None or not (data.root / src).exists():
        return f"# {title}\n\n" + (
            unavailable(data) or f"`{src}` is missing from globi-data."
        )
    text = (data.root / src).read_text()
    for pattern, replacement in PUBLIC_REWRITES.get(src, []):
        text = re.sub(pattern, replacement, text, flags=re.S)
    text = rewrite_links(text, src, dest)
    return text.rstrip() + "\n\n" + source_note(data, src) + "\n"


# ---------------------------------------------------------------- mkdocs events

_DATA: GlobiData | None = None
_INTERNAL: Path | None = None
INTERNAL_PREFIX = "internal/"
INTERNAL_BANNER = (
    '!!! danger "Internal: not for publication"\n'
    "    This page is built from private partner data and exists only in local\n"
    "    builds with `GLOBI_INTERNAL_DOCS` set. Do not share it outside the team.\n\n"
)


class InternalDeployError(PluginError):
    """An attempt to deploy a build that includes internal pages."""

    def __init__(self) -> None:
        """Explain why the deploy was refused."""
        super().__init__(
            "GLOBI_INTERNAL_DOCS is set: refusing to deploy a site with internal pages."
        )


def _internal_pages(root: Path) -> list[str]:
    """Internal Markdown pages as site paths, index first."""
    pages = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.md"))
    pages.sort(key=lambda p: posixpath.basename(p) != "index.md")
    return [INTERNAL_PREFIX + p for p in pages]


def _inject_partner_pages(items: list[Any], partners: list[str]) -> bool:
    """Add one nav entry per partner to the section holding the catalog."""
    for item in items:
        if not isinstance(item, dict):
            continue
        for value in item.values():
            if not isinstance(value, list):
                continue
            if "data/runs/index.md" in value:
                value += [{p.replace("_", " "): f"data/runs/{p}.md"} for p in partners]
                return True
            if _inject_partner_pages(value, partners):
                return True
    return False


def on_config(config: Any) -> Any:
    """Locate and load globi-data, and add partner pages to the nav."""
    global _DATA
    config_dir = Path(config.config_file_path).parent
    root = locate_root(config_dir)
    if root is None:
        message = "globi-data checkout not found; data pages will say so (set GLOBI_DATA_ROOT)"
        if os.environ.get("GLOBI_DATA_REQUIRED") == "1":
            raise SystemExit(message)
        log.info(message)
    else:
        log.info("globi-data: reading %s", root)
    _DATA = load(root)

    if config.nav:
        _inject_partner_pages(config.nav, _DATA.partners)

    global _INTERNAL
    if env := os.environ.get("GLOBI_INTERNAL_DOCS"):
        if "gh-deploy" in sys.argv:
            raise InternalDeployError
        _INTERNAL = Path(env).expanduser().resolve()
        log.warning(
            "Including INTERNAL pages from %s: do not deploy this build", _INTERNAL
        )
        if config.nav is not None:
            config.nav.append({"Internal (not published)": _internal_pages(_INTERNAL)})
    return config


def on_files(files: Files, config: Any) -> Files:
    """Add the generated pages to the site."""
    data = _DATA or load(None)
    pages = {
        "data/runs/index.md": page_runs_index(data),
        "data/status.md": page_status(data),
        "data/inputs.md": page_inputs(data),
        "data/surrogates.md": page_surrogates(data),
    }
    pages |= {f"data/runs/{p}.md": page_partner(data, p) for p in data.partners}
    pages |= {
        dest: page_reference(data, src, dest) for src, dest in REFERENCE_DOCS.items()
    }
    for uri, content in pages.items():
        files.append(File.generated(config, uri, content=content))
    if _INTERNAL is not None:
        for path in sorted(_INTERNAL.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                uri = INTERNAL_PREFIX + path.relative_to(_INTERNAL).as_posix()
                files.append(File.generated(config, uri, abs_src_path=str(path)))
    return files


class PrivateReferenceError(PluginError):
    """A page names the private partner repository."""

    def __init__(self, src_uri: str, line: int, match: str) -> None:
        """Say where the reference is and how to fix it."""
        super().__init__(
            f"{src_uri}:{line} mentions the private partner repository ({match!r}). "
            "Remove it, or add a rewrite to PUBLIC_REWRITES."
        )


def on_page_markdown(markdown: str, page: Any, **_: Any) -> str:
    """Refuse to publish a page that names the private partner repository."""
    if page.file.src_uri.startswith(INTERNAL_PREFIX):
        return INTERNAL_BANNER + markdown
    if m := PRIVATE_PATTERN.search(markdown):
        line = markdown.count("\n", 0, m.start()) + 1
        raise PrivateReferenceError(page.file.src_uri, line, m.group(0))
    return markdown
