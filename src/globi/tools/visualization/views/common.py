"""Widgets and helpers shared by the dashboard pages."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import streamlit as st

from globi.tools.visualization.data_sources import DataSource, LocalDataSource
from globi.tools.visualization.export import render_html_to_png
from globi.tools.visualization.plotting import (
    EnergyIntensityUnit,
    Theme,
    energy_intensity_factor,
)
from globi.tools.visualization.results_data import (
    default_filters,
    filter_candidates,
    filter_label,
)
from globi.tools.visualization.utils import load_output_table

# greens/reds start at their first visible shade, matching the map colours
_COLORMAP_GRADIENTS = {
    "greens": "linear-gradient(to right, #c7e9c0, #74c476, #31a354, #006d2c)",
    "viridis": "linear-gradient(to right, #440154, #3b528b, #21918c, #5ec962, #fde725)",
    "reds": "linear-gradient(to right, #fee0d2, #fc9272, #fb6a4a, #de2d26)",
    "plasma": "linear-gradient(to right, #0d0887, #5c01a6, #9c179e, #ed7953, #f0f921)",
}
_VERSION_RE = re.compile(r"^v\d+(\.\d+)*$")
_UNIT_KEY = "globi_energy_intensity_unit"
CRS_CHOICE_KEY = "map_crs_choice"
AUTO_CRS = "auto"


@st.cache_data(show_spinner="Loading run…", max_entries=8)
def cached_load_run_parquet(path_str: str, mtime: float) -> pd.DataFrame:
    """Parquet for a run, cached by path and modification time."""
    return load_output_table(Path(path_str))


def load_run(
    data_source: DataSource, run_id: str
) -> tuple[pd.DataFrame, tuple[str, float] | None]:
    """Load a run (cached by file for local and downloaded S3 runs) and its (path, mtime) token."""
    if isinstance(data_source, LocalDataSource):
        pq = data_source.get_run_parquet_path(run_id)
        token = (str(pq.resolve()), pq.stat().st_mtime)
        return cached_load_run_parquet(*token), token
    return data_source.load_run_data(run_id), None


def render_colormap_legend(label: str, value_stats: dict, cmap: str) -> None:
    """Render colormap legend with the clipped colour range."""
    gradient = _COLORMAP_GRADIENTS.get(cmap, _COLORMAP_GRADIENTS["viridis"])
    v_min = value_stats["min"]
    v_max = value_stats["max"]
    st.markdown(
        f"""
<div style="margin-top: 0.5rem; font-size: 0.85rem;">
  <div style="margin-bottom: 0.15rem;">{label} (5th to 95th percentile; values beyond take the end colours)</div>
  <div style="display: flex; align-items: center; gap: 0.5rem;">
    <span style="color: #6b7280;">{v_min:,.1f}</span>
    <div style="
      flex: 1;
      height: 12px;
      border-radius: 999px;
      background: {gradient};
      border: 1px solid #d1d5db;
    "></div>
    <span style="color: #6b7280;">{v_max:,.1f}</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _theme_from_background_hex(bg: str) -> Theme | None:
    """Infer light vs dark from a #RRGGBB (or #RRGGBBAA) background hex."""
    if not (isinstance(bg, str) and bg.startswith("#")):
        return None
    h = bg.lstrip("#")
    if len(h) == 8:
        h = h[:6]
    if len(h) != 6:
        return None
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
    except ValueError:
        return None
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "dark" if lum < 0.45 else "light"  # type: ignore[return-value]


def _context_theme_type() -> str | None:
    """Return 'light' or 'dark' from ``st.context.theme`` when available."""
    try:
        ctx = getattr(st, "context", None)
        if ctx is None:
            return None
        th = getattr(ctx, "theme", None)
        if th is None:
            return None
        raw = th.get("type") if hasattr(th, "get") else None
        if raw is None:
            raw = getattr(th, "type", None)
        if isinstance(raw, str) and raw.lower() in ("light", "dark"):
            return raw.lower()
    except Exception:  # noqa: S110
        pass
    return None


def streamlit_theme() -> Theme:
    """Detect Streamlit theme (light/dark) for embedded D3 charts.

    Prefer ``st.context.theme.type`` (Streamlit 1.29+); fall back to
    ``theme.base`` and, when still unknown, infer from ``theme.backgroundColor``.
    """
    t_ctx = _context_theme_type()
    if t_ctx is not None:
        return t_ctx  # type: ignore[return-value]
    try:
        base = st.get_option("theme.base")
        if isinstance(base, str) and base.lower() in ("light", "dark"):
            return base.lower()  # type: ignore[return-value]
    except Exception:  # noqa: S110
        pass
    try:
        bg = st.get_option("theme.backgroundColor")
        inferred = _theme_from_background_hex(bg) if isinstance(bg, str) else None
        if inferred is not None:
            return inferred
    except Exception:  # noqa: S110
        pass
    return "light"


def chart_download(
    key: str,
    csv_data: str,
    html_content: str,
    base_filename: str,
    *,
    compact: bool = False,
) -> None:
    """Single download control: format dropdown + download button (CSV, HTML, PNG)."""
    if not compact:
        st.caption("Download as")
    col_sel, col_btn = st.columns([1, 1])
    with col_sel:
        fmt = st.selectbox(
            "Format",
            options=["CSV", "HTML", "PNG"],
            key=f"format_{key}",
            label_visibility="collapsed",
        )
    with col_btn:
        disabled = False
        if fmt == "CSV":
            data, mime, fname = csv_data, "text/csv", f"{base_filename}.csv"
        elif fmt == "HTML":
            data, mime, fname = html_content, "text/html", f"{base_filename}.html"
        else:
            cache_key = f"_png_{key}_{hash(html_content)}"
            if cache_key not in st.session_state:
                with st.spinner("Generating PNG..."):
                    st.session_state[cache_key] = render_html_to_png(html_content)
            png_bytes = st.session_state[cache_key]
            if png_bytes is None:
                st.caption("PNG export isn't available here; download HTML instead.")
                data, mime, fname = b"", "image/png", f"{base_filename}.png"
                disabled = True
            else:
                data, mime, fname = png_bytes, "image/png", f"{base_filename}.png"
        st.download_button(
            "Download",
            data=data,
            file_name=fname,
            mime=mime,
            key=f"dl_{key}",
            disabled=disabled,
        )


def eui_unit() -> EnergyIntensityUnit:
    """Energy-intensity unit chosen under Settings in the sidebar."""
    return "kbtu_sqft" if st.session_state.get(_UNIT_KEY) == "kBTU/ft²" else "kwh_m2"


def eui_unit_suffix(unit: EnergyIntensityUnit) -> str:
    """Short unit label for energy intensity values."""
    return "kBTU/ft²" if unit == "kbtu_sqft" else "kWh/m²"


def resolve_map_crs(hint: dict[str, Any] | None) -> str:
    """Footprint CRS: the sidebar choice, or the guess from the data when set to automatic."""
    choice = st.session_state.get(CRS_CHOICE_KEY, AUTO_CRS)
    if choice != AUTO_CRS:
        return choice
    guess = (hint or {}).get("suggested_crs")
    return guess if isinstance(guess, str) else "EPSG:3857"


def map_crs_caption(hint: dict[str, Any] | None, crs: str) -> None:
    """Say which coordinate system the map uses and where to change it."""
    if st.session_state.get(CRS_CHOICE_KEY, AUTO_CRS) == AUTO_CRS:
        how = (
            "guessed from the data" if (hint or {}).get("suggested_crs") else "default"
        )
        st.caption(
            f"Coordinate system {crs} ({how}). If buildings look misplaced, "
            "change it under Settings in the sidebar."
        )


def map_caption(
    n_features: int, *, hidden_large: int = 0, downsampled_from: int | None = None
) -> None:
    """Building count, plus anything left off the map and why."""
    msg = f"{n_features:,} buildings on the map"
    if downsampled_from:
        msg += f" (a sample of {downsampled_from:,}, to keep the browser responsive)"
    if hidden_large:
        noun = "building" if hidden_large == 1 else "buildings"
        msg += (
            f". {hidden_large:,} {noun} over 10,000 m² left off so they "
            "don't hide the rest"
        )
    st.caption(msg + ".")


def ran(label: str, key: str) -> bool:
    """Button whose results stay up on later reruns (st.button is only True on the click itself)."""
    if st.button(label, key=key, type="primary"):
        st.session_state[f"{key}_ran"] = True
    return st.session_state.get(f"{key}_ran", False)


def run_label(run_id: str) -> str:
    """Readable run name, most specific part first so truncated chips stay distinct.

    E.g. "MA_Commercial/Baseline/v1.0.0" -> "Baseline (v1.0.0) · MA_Commercial".
    """
    parts = run_id.replace("\\", "/").split("/")
    version = parts.pop() if len(parts) > 1 and _VERSION_RE.match(parts[-1]) else None
    head = parts[-1] + (f" ({version})" if version else "")
    return " · ".join([head, " / ".join(parts[:-1])]) if len(parts) > 1 else head


def scenario_label(run_id: str, run_ids: list[str]) -> str:
    """Shortest readable name that still tells the selected runs apart."""
    parts = run_id.split("/")
    for n in range(1, len(parts) + 1):
        tail = "/".join(parts[-n:])
        if not _VERSION_RE.match(parts[-n]) and all(
            r == run_id or "/".join(r.split("/")[-n:]) != tail for r in run_ids
        ):
            return run_label(tail)
    return run_label(run_id)


def _range_options(values: pd.Index) -> list[float]:
    """Slider stops: every value when there are few, else 5% quantiles (handles skewed sizes)."""
    num = (
        cast(pd.Series, pd.to_numeric(pd.Series(values), errors="coerce"))
        .dropna()
        .to_numpy()
    )
    uniq = np.unique(num)
    if len(uniq) <= 21:
        return uniq.tolist()
    return np.unique(np.quantile(num, np.linspace(0, 1, 21))).tolist()


def _fmt_number(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def building_filters(df: pd.DataFrame) -> dict[str, tuple | list]:
    """Sidebar filters built from the run's building attributes; returns active selections.

    Floor area and age are offered by default when present; any other attribute can be added.
    """
    candidates = filter_candidates(df)
    if not candidates:
        return {}
    selections: dict[str, tuple | list] = {}
    with st.sidebar:
        st.markdown("### Filter buildings")
        chosen = st.multiselect(
            "Filter by",
            options=candidates,
            default=default_filters(candidates),
            format_func=filter_label,
            # keyed on the options so switching to a run with other attributes starts fresh
            key=f"filter_by_{hash(tuple(candidates))}",
        )
        for name in chosen:
            values = df.index.get_level_values(name)
            if pd.api.types.is_numeric_dtype(values) and not pd.api.types.is_bool_dtype(
                values
            ):
                stops = _range_options(values)
                if len(stops) < 2:
                    continue
                low, high = st.select_slider(
                    filter_label(name),
                    options=stops,
                    value=(stops[0], stops[-1]),
                    format_func=_fmt_number,
                    key=f"filter_{name}_{hash(tuple(stops))}",
                )
                if (low, high) != (stops[0], stops[-1]):
                    selections[name] = (low, high)
            else:
                options = sorted(values.unique().tolist(), key=str)
                picked = st.multiselect(
                    filter_label(name),
                    options=options,
                    placeholder="All",
                    key=f"filter_{name}_{hash(tuple(map(str, options)))}",
                )
                if picked:
                    selections[name] = picked
    return selections


def fmt_energy(kwh: float) -> str:
    """Energy in kWh, shown with a readable unit (kWh, MWh, GWh, TWh)."""
    if abs(kwh) >= 1e9:
        return f"{kwh / 1e9:,.1f} TWh"
    if abs(kwh) >= 1e6:
        return f"{kwh / 1e6:,.1f} GWh"
    if abs(kwh) >= 1e3:
        return f"{kwh / 1e3:,.1f} MWh"
    return f"{kwh:,.0f} kWh"


def kpi_row(kpis: dict[str, float], unit: EnergyIntensityUnit = "kwh_m2") -> None:
    """Buildings, floor area, area-weighted EUI and total energy for the current selection."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Buildings", f"{kpis['buildings']:,.0f}")
    c2.metric("Floor area", f"{kpis['area']:,.0f} m²")
    c3.metric(
        "Energy use intensity",
        f"{kpis['eui'] * energy_intensity_factor(unit):,.0f} {eui_unit_suffix(unit)}",
        help="Annual energy per unit of floor area, weighted by building size.",
    )
    c4.metric("Annual energy", fmt_energy(kpis["energy"]))


@st.cache_data(max_entries=8, show_spinner=False)
def _zip(files: tuple[tuple[str, str], ...]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files:
            z.writestr(name, content)
    return buf.getvalue()


def section_download(files: dict[str, str], name: str, key: str) -> None:
    """One download for a section: its chart data (CSV) and interactive charts (HTML) as a zip."""
    st.download_button(
        "Download charts and data",
        data=_zip(tuple(files.items())),
        file_name=f"{name}.zip",
        mime="application/zip",
        key=key,
        icon=":material/download:",
        on_click="ignore",
        help="A zip with each chart's data as CSV and the charts as interactive HTML.",
    )
