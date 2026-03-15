"""Utilities for visualization and raw data processing."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

# TODO: update this after the building col PR merged

BUILDING_ID_COL = "building_id"
# the building id col from either the inputs folder or the artifacts folder
# check for any of the id combinations


LAT_COL = "lat"
LON_COL = "lon"
ROTATED_RECTANGLE_COL = "rotated_rectangle"

OUTPUT_FILE_NAME = "EnergyAndPeak.pq"


class RawResultsFormat:
    """Expected shape of Results.pq (outputs/TestRegion/v.x.y.z/Results.pq).

    Columns: MultiIndex with levels Measurement, Aggregation, Meter, Month.
    Index: building/feature multiindex from pipeline.
    """

    COL_MEASUREMENT = "Measurement"
    COL_AGGREGATION = "Aggregation"
    COL_METER = "Meter"
    COL_MONTH = "Month"
    MEASUREMENT_ENERGY = "Energy"
    MEASUREMENT_PEAK = "Peak"
    AGGREGATION_END_USES = "End Uses"
    AGGREGATION_UTILITIES = "Utilities"


@dataclass
class RetrofitUseCase:
    """Formatting and inputs for retrofit use case (e.g. baseline vs retrofit)."""

    # placeholder for retrofit-specific columns/aggregations
    pass


@dataclass
class OverHeatingUseCase:
    """Formatting and inputs for overheating use case."""

    # placeholder for overheating-specific columns/aggregations
    pass


RESULTS_PQ_NAME = "Results.pq"


def find_output_run_dirs(base_dir: Path | str) -> list[Path]:
    """Find directories under base_dir that contain at least one .pq or .parquet file.

    Returns sorted list of directory paths (run folders, e.g. TestRegion/dryrun/Baseline/v1.0.0).
    """
    root = Path(base_dir)
    if not root.exists():
        return []

    seen: set[Path] = set()
    for ext in ("*.pq", "*.parquet"):
        for path in root.rglob(ext):
            if path.is_file():
                seen.add(path.parent)
    return sorted(seen)


OVERHEATING_DF_KEYS = (
    "BasicOverheating",
    "ExceedanceDegreeHours",
    "HeatIndexCategories",
)
OVERHEATING_FILE_MAP = {
    "BasicOverheating": ("BasicOverheating.pq", "BasicOverheating.parquet"),
    "ExceedanceDegreeHours": (
        "ExceedanceDegreeHours.pq",
        "ExceedanceDegreeHours.parquet",
    ),
    "HeatIndexCategories": ("HeatIndexCategories.pq", "HeatIndexCategories.parquet"),
}


def run_has_overheating(run_dir: Path) -> bool:
    """True if run directory contains any overheating output."""
    return any(
        (run_dir / name).is_file()
        for names in OVERHEATING_FILE_MAP.values()
        for name in names
    )


def list_overheating_files_for_run(run_dir: Path) -> list[str]:
    """Return list of available overheating df keys (e.g. BasicOverheating, ExceedanceDegreeHours)."""
    available: list[str] = []
    for key, names in OVERHEATING_FILE_MAP.items():
        if any((run_dir / n).is_file() for n in names):
            available.append(key)
    return available


def get_overheating_thresholds(run_dir: Path) -> list[float]:
    """Read available heat thresholds from BasicOverheating (or ExceedanceDegreeHours)."""
    for key in ("BasicOverheating", "ExceedanceDegreeHours"):
        oh_path = get_overheating_file_for_run(run_dir, key)
        if oh_path is None:
            continue
        df = load_output_table(oh_path)
        flat = df.reset_index()
        thresh_col = _find_col(flat, "Threshold [degC]")
        polarity_col = _find_col(flat, "Polarity")
        if thresh_col is None:
            continue
        if polarity_col is not None:
            flat = flat[flat[polarity_col] == "Overheat"]
        vals = sorted(pd.Series(flat[thresh_col]).dropna().unique().tolist())
        if vals:
            return vals
    return [26.0, 30.0, 35.0]


def get_overheating_file_for_run(
    run_dir: Path, df_key: str = "BasicOverheating"
) -> Path | None:
    """Return overheating file path for given df_key if present."""
    names = OVERHEATING_FILE_MAP.get(
        df_key, ("BasicOverheating.pq", "BasicOverheating.parquet")
    )
    for name in names:
        p = run_dir / name
        if p.is_file():
            return p
    return None


def get_pq_file_for_run(run_dir: Path) -> Path | None:
    """Return the .pq file to load for a run.

    prefer the derived output (e.g. EnergyAndPeak.pq) when present, then
    fall back to Results.pq, then any .pq file.
    """
    preferred = run_dir / OUTPUT_FILE_NAME
    if preferred.is_file():
        return preferred

    results_pq = run_dir / RESULTS_PQ_NAME
    if results_pq.is_file():
        return results_pq
    pq_files = sorted(run_dir.glob("*.pq"))
    if pq_files:
        return pq_files[0]
    parquet_files = sorted(run_dir.glob("*.parquet"))
    return parquet_files[0] if parquet_files else None


def load_output_table(path: Path | str) -> pd.DataFrame:
    """Load a .pq or .parquet file into a dataframe."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    if p.suffix not in (".pq", ".parquet"):
        raise ValueError("unsupported")
    return pd.read_parquet(p)


def require_geo_columns(df: pd.DataFrame) -> tuple[str, str]:
    """Require deterministic lat/lon columns; raise if missing."""
    if LAT_COL not in df.columns:
        raise ValueError(LAT_COL)
    if LON_COL not in df.columns:
        raise ValueError(LON_COL)
    return (LAT_COL, LON_COL)


def has_geo_columns(df: pd.DataFrame) -> bool:
    """True if df has both lat and lon columns."""
    return LAT_COL in df.columns and LON_COL in df.columns


def _column_key(col: str | tuple[str, ...]) -> str:
    """Normalize column label for comparison (MultiIndex columns are tuples)."""
    return col.lower() if isinstance(col, str) else str(col).lower()


def list_numeric_columns(
    df: pd.DataFrame, exclude: Iterable[str] | None = None
) -> list[str] | list[tuple[str, ...]]:
    """List numeric columns, optionally excluding some. Works with MultiIndex columns."""
    exclude_set = {_column_key(c) for c in (exclude or [])}
    numeric_cols: list[str] | list[tuple[str, ...]] = []
    for col in df.select_dtypes(include=["number"]).columns:
        if _column_key(col) in exclude_set:
            continue
        numeric_cols.append(col)
    return numeric_cols


def list_categorical_columns(df: pd.DataFrame, max_unique: int = 50) -> list[str]:
    """List categorical columns suitable for grouping."""
    cols: list[str] = []
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            continue
        unique = df[col].nunique(dropna=True)
        if 1 < unique <= max_unique:
            cols.append(col)
    return cols


def sanitize_for_json(df: pd.DataFrame) -> pd.DataFrame:
    """Make dataframe safe for json serialization."""
    safe = df.copy()
    for col in safe.columns:
        if pd.api.types.is_datetime64_any_dtype(safe[col]):
            safe[col] = safe[col].astype("string")
    return safe


def _find_col(df: pd.DataFrame, name: str):
    """Find column by name, handling MultiIndex."""
    if not isinstance(df.columns, pd.MultiIndex):
        return name if name in df.columns else None
    for col in df.columns:
        if isinstance(col, tuple) and any(
            isinstance(x, str) and x == name for x in col
        ):
            return col
    return None


# column name variants for rotated rectangle (geometry.py uses GLOBI_ROTATED_RECTANGLE)
ROTATED_RECTANGLE_ALIASES = ("rotated_rectangle", "GLOBI_ROTATED_RECTANGLE")
HEIGHT_ALIASES = ("height",)
HEIGHT_FALLBACK_COLS = ("num_floors", "f2f_height")


def _wkt_to_geoseries_wgs(
    wkt_series: pd.Series,
    cart_crs: str = "EPSG:3857",
) -> tuple[pd.Series, Any] | None:
    """Parse WKT to Shapely, build GeoSeries, transform to WGS84.

    Step 1: apply(from_wkt) for parsing. Step 2: GeoSeries(..., crs=cart_crs).
    Step 3: to_crs(EPSG:4326) for batch transform. Returns (valid_mask, gs_wgs)
    or None if no valid geometries.
    """
    import geopandas as gpd
    from shapely import from_wkt

    def _safe_from_wkt(v):
        w = getattr(v, "wkt", v) if v is not None else None
        if not isinstance(w, str):
            return None
        else:
            try:
                geom = from_wkt(w)
            except Exception:
                return None
            else:
                return None if geom.is_empty else geom

    shapely_geo = wkt_series.apply(_safe_from_wkt)
    valid_mask = shapely_geo.notna()
    if not bool(valid_mask.any()):
        return None

    shapely_valid = shapely_geo[valid_mask]
    geo_series = gpd.GeoSeries(shapely_valid, crs=cart_crs)
    gs_wgs = geo_series.to_crs("EPSG:4326")
    return (valid_mask, gs_wgs)  # type: ignore[return-value]


def _geom_to_polygon_coords(geom) -> list[list[float]] | None:
    """Extract exterior coords from Polygon or MultiPolygon as [[lon, lat], ...]."""
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(geom, Polygon):
        coords = list(geom.exterior.coords)
    elif isinstance(geom, MultiPolygon):
        poly = max(geom.geoms, key=lambda g: g.area)
        coords = list(poly.exterior.coords)
    else:
        return None
    if len(coords) < 3:
        return None
    return [[float(x), float(y)] for x, y in coords]


def _compute_heights_vectorized(
    sub: pd.DataFrame,
    df_flat: pd.DataFrame,
    has_height: bool,
    default_height_m: float,
) -> pd.Series:
    """Compute height series for vectorized features."""
    nf_col = _find_col(df_flat, "num_floors")
    f2f_col = _find_col(df_flat, "f2f_height")
    f2f_default = 3.0
    if f2f_col is not None and f2f_col in df_flat.columns:
        f2f_vals = sub[f2f_col].apply(
            lambda v: float(v) if v == v and v is not None else f2f_default
        )
    else:
        f2f_vals = pd.Series(f2f_default, index=sub.index)

    if has_height:
        heights = sub["height"].astype(float, errors="ignore")
        heights = heights.where((heights > 0) & heights.notna(), default_height_m)
    elif nf_col is not None and nf_col in sub.columns:
        heights = (sub[nf_col].astype(float, errors="ignore") * f2f_vals).fillna(
            default_height_m
        )
    else:
        heights = pd.Series(default_height_m, index=sub.index)
    return heights.clip(lower=0.01).fillna(default_height_m)  # type: ignore[return-value]


def _build_map_features_vectorized(
    df_flat: pd.DataFrame,
    rect_col: str,
    cart_crs: str,
    default_height_m: float,
    has_height: bool,
    has_num_floors: bool,
    value_col: str | None,
) -> list[dict] | None:
    """Vectorized path: batch parse WKT and transform via geopandas."""
    import contextlib

    wkt_series = cast(
        pd.Series,
        df_flat[rect_col].apply(
            lambda v: getattr(v, "wkt", v) if v is not None else None
        ),
    )
    parsed = _wkt_to_geoseries_wgs(wkt_series, cart_crs=cart_crs)
    if parsed is None:
        return None

    valid_mask, gs_wgs = parsed
    valid_geom = ~gs_wgs.is_empty & gs_wgs.geom_type.isin(["Polygon", "MultiPolygon"])
    if not bool(valid_geom.any()):
        return None

    sub = df_flat.loc[valid_mask].loc[valid_geom.index].copy()
    gs_wgs = gs_wgs.loc[valid_geom]
    heights = _compute_heights_vectorized(sub, df_flat, has_height, default_height_m)

    features: list[dict] = []
    for idx, geom in zip(sub.index, gs_wgs, strict=True):
        poly_lonlat = _geom_to_polygon_coords(geom)
        if poly_lonlat is None:
            continue

        row = sub.loc[idx]
        feat: dict = {"polygon": poly_lonlat, "height": float(heights.loc[idx])}
        if value_col and value_col in sub.columns:
            v = row[value_col]
            if v == v and v is not None:
                with contextlib.suppress(TypeError, ValueError):
                    feat["value"] = float(v)
        features.append(feat)

    return features if features else None


def build_map_features_from_df(  # noqa: C901
    df: pd.DataFrame,
    cart_crs: str = "EPSG:3857",
    default_height_m: float = 10.0,
    value_col: str | None = None,
) -> list[dict] | None:
    """Extract map features from dataframe with rotated_rectangle and height.

    Converts each rotated_rectangle WKT (in cart_crs) to lat/lon polygon,
    extrudes by height (meters). Works with flat parquet or index-flattened data.
    Uses vectorized geopandas path for large datasets.

    Args:
        df: DataFrame with rotated_rectangle (or GLOBI_ROTATED_RECTANGLE) and height.
        cart_crs: CRS of rotated_rectangle coordinates (default EPSG:3857).
        default_height_m: Fallback height when missing/invalid.
        value_col: Optional column for coloring (e.g. eui, total_energy).

    Returns:
        List of {polygon, height, value?} dicts for pydeck, or None if no valid features.
    """
    df_flat = df.reset_index() if hasattr(df.index, "names") and df.index.names else df

    rect_col = None
    for alias in ROTATED_RECTANGLE_ALIASES:
        if alias in df_flat.columns:
            rect_col = alias
            break
    if rect_col is None:
        return None

    has_height = "height" in df_flat.columns
    has_num_floors = _find_col(df_flat, "num_floors") is not None
    if not has_height and not has_num_floors:
        return None

    # use vectorized path for 50+ rows
    if len(df_flat) >= 50:
        result = _build_map_features_vectorized(
            df_flat,
            rect_col,
            cart_crs,
            default_height_m,
            has_height,
            has_num_floors,
            value_col,
        )
        if result is not None:
            return result

    # fallback: row-by-row for small datasets or when vectorized fails
    from pyproj import Transformer

    transformer = Transformer.from_crs(cart_crs, "EPSG:4326", always_xy=True)
    features: list[dict] = []
    for i in range(len(df_flat)):
        wkt_val = df_flat.iloc[i][rect_col]
        wkt_str = getattr(wkt_val, "wkt", wkt_val) if wkt_val is not None else None
        if not isinstance(wkt_str, str):
            continue

        poly_lonlat = transform_rotated_rectangle_to_latlon(
            wkt_str, cart_crs, _transformer=transformer
        )
        if poly_lonlat is None:
            continue

        row = df_flat.iloc[i]
        h = default_height_m
        if has_height:
            try:
                hv = float(row["height"])
                if hv > 0 and hv == hv:
                    h = hv
            except (TypeError, ValueError):
                pass
        elif has_num_floors:
            nf_col = _find_col(df_flat, "num_floors")
            f2f_col = _find_col(df_flat, "f2f_height")
            f2f = 3.0
            if f2f_col is not None and f2f_col in df_flat.columns:
                try:
                    fv = row[f2f_col]
                    f2f = float(fv) if fv == fv else 3.0
                except (TypeError, ValueError):
                    pass
            try:
                nv = row[nf_col]
                if nv == nv:
                    h = float(nv) * f2f
            except (TypeError, ValueError, KeyError):
                pass

        feat = {"polygon": poly_lonlat, "height": float(h)}
        if value_col and value_col in df_flat.columns:
            try:
                v = row[value_col]
                if v == v and v is not None:
                    feat["value"] = float(v)
            except (TypeError, ValueError):
                pass
        features.append(feat)

    return features if features else None


def transform_rotated_rectangle_to_latlon(
    wkt: str,
    cart_crs: str = "EPSG:3857",
    *,
    _transformer=None,
) -> list[list[float]] | None:
    """Convert rotated_rectangle WKT (in cartesian CRS) to lat/lon polygon.

    Transforms each vertex from cart_crs to EPSG:4326. Returns [[lon, lat], ...]
    for pydeck polygon layer, or None if invalid.
    Pass _transformer to reuse (avoids creating one per call in loops).
    """
    from pyproj import Transformer
    from shapely import from_wkt
    from shapely.geometry import MultiPolygon, Polygon

    wkt_str = getattr(wkt, "wkt", wkt) if wkt is not None else ""
    if not isinstance(wkt_str, str):
        return None
    try:
        geom = from_wkt(wkt_str)
        if geom.is_empty:
            return None
        if isinstance(geom, Polygon):
            coords = list(geom.exterior.coords)
        elif isinstance(geom, MultiPolygon):
            poly = max(geom.geoms, key=lambda g: g.area)
            coords = list(poly.exterior.coords)
        else:
            return None
        if len(coords) < 3:
            return None

        trans = _transformer
        if trans is None:
            trans = Transformer.from_crs(cart_crs, "EPSG:4326", always_xy=True)

        # batch transform all vertices
        import numpy as np

        xs = np.array([c[0] for c in coords], dtype=float)
        ys = np.array([c[1] for c in coords], dtype=float)
        lons, lats = trans.transform(xs, ys)
        result = [[float(lon), float(lat)] for lon, lat in zip(lons, lats, strict=True)]
    except Exception:
        return None
    return result


def build_map_df_from_output(  # noqa: C901
    df: pd.DataFrame,
    cart_crs: str = "EPSG:3857",
) -> pd.DataFrame | None:
    """Build map-ready dataframe directly from output parquet.

    Extracts lat/lon from rotated_rectangle. Output Energy is kWh/m² and Peak
    is kW/m², so eui and peak_per_sqm are used directly; total_energy and
    total_peak are eui*area and peak_per_sqm*area. Returns df with building_id,
    lat, lon, rotated_rectangle, height, eui, peak_per_sqm, total_energy,
    total_peak, end-use eui cols. Uses vectorized geopandas for geometry when
    100+ rows.
    """
    import logging

    df_reset = df.reset_index()
    bid_col = _find_col(df_reset, BUILDING_ID_COL)
    rect_col = _find_col(df_reset, ROTATED_RECTANGLE_COL)
    if bid_col is None or rect_col is None:
        return None

    # find area level for EUI
    area_level: int | None = None
    for i, name in enumerate(df.index.names or []):
        if name == "feature.geometry.energy_model_conditioned_area":
            area_level = i
            break
    if area_level is None:
        return None

    energy_cols = [
        c
        for c in df.columns
        if isinstance(c, tuple) and c[0] == "Energy" and c[1] == "End Uses"
    ]
    peak_cols = [
        c
        for c in df.columns
        if isinstance(c, tuple) and c[0] == "Peak" and c[1] == "Raw"
    ]
    if not energy_cols or not peak_cols:
        return None

    areas = df.index.get_level_values(area_level)
    # output Energy is kWh/m², Peak is kW/m² - use directly as eui and peak_per_sqm
    eui_arr = df[energy_cols].sum(axis=1).values
    peak_per_sqm_arr = df[peak_cols].max(axis=1).values

    h_col = _find_col(df_reset, "height")
    nf_col = _find_col(df_reset, "num_floors")
    f2f_col = _find_col(df_reset, "f2f_height")
    log = logging.getLogger(__name__)

    # vectorized path for 100+ rows: batch parse WKT and transform centroids
    use_vectorized = len(df_reset) >= 100
    lon_lat_by_idx: dict[int, tuple[float, float]] = {}
    wkt_by_idx: dict[int, str] = {}

    if use_vectorized:
        wkt_series = cast(
            pd.Series,
            df_reset[rect_col].apply(
                lambda v: getattr(v, "wkt", v) if v is not None else None
            ),
        )
        parsed = _wkt_to_geoseries_wgs(wkt_series, cart_crs=cart_crs)
        if parsed is not None:
            _, gs_wgs = parsed
            valid_geom = ~gs_wgs.is_empty
            for idx in gs_wgs.loc[valid_geom].index:
                geom = gs_wgs.loc[idx]
                cx, cy = geom.centroid.x, geom.centroid.y
                lon_lat_by_idx[idx] = (float(cy), float(cx))  # lat, lon
                wkt_by_idx[idx] = str(wkt_series.loc[idx])
        else:
            use_vectorized = False

    if not use_vectorized:
        from pyproj import Transformer
        from shapely import from_wkt

        transformer = Transformer.from_crs(cart_crs, "EPSG:4326", always_xy=True)
        for idx in range(len(df_reset)):
            wkt = df_reset.iloc[idx][rect_col]
            if not isinstance(wkt, str):
                wkt = getattr(wkt, "wkt", None) if wkt is not None else None
            if not isinstance(wkt, str):
                continue
            try:
                geom = from_wkt(wkt)
                if geom.is_empty:
                    continue
                cx, cy = geom.centroid.x, geom.centroid.y
                lon, lat = transformer.transform(cx, cy)
                lon_lat_by_idx[idx] = (float(lat), float(lon))
                wkt_by_idx[idx] = wkt
            except Exception as exc:
                log.debug("skip row %s: %s", idx, exc)

    rows: list[dict] = []
    for idx, (lat, lon) in lon_lat_by_idx.items():
        wkt = wkt_by_idx.get(idx, "")
        try:
            area_val = areas[idx]
            fval = float(area_val)  # type: ignore[arg-type]
            area = fval if fval > 0 else None
        except (TypeError, ValueError, IndexError):
            area = None
        if area is None:
            continue

        eui = float(eui_arr[idx])
        peak_per_sqm = float(peak_per_sqm_arr[idx])
        total_energy = eui * area
        total_peak = peak_per_sqm * area

        row = df_reset.iloc[idx]
        bid = str(row[bid_col])
        height_m = 6.0
        if h_col is not None and h_col in df_reset.columns:
            try:
                hv = row[h_col]
                hm = float(hv)
                if hm == hm:
                    height_m = hm
            except (TypeError, ValueError):
                pass
        elif nf_col is not None and nf_col in df_reset.columns:
            f2f = 3.0
            if f2f_col is not None and f2f_col in df_reset.columns:
                try:
                    fv = row[f2f_col]
                    f2f = float(fv) if fv == fv else 3.0
                except (TypeError, ValueError):
                    pass
            try:
                nv = row[nf_col]
                nm = float(nv)
                if nm == nm:
                    height_m = nm * f2f
            except (TypeError, ValueError):
                pass

        row_dict: dict = {
            BUILDING_ID_COL: bid,
            LAT_COL: lat,
            LON_COL: lon,
            ROTATED_RECTANGLE_COL: wkt,
            "height": height_m,
            "conditioned_area": area,
            "eui": eui,
            "peak_per_sqm": peak_per_sqm,
            "total_energy": total_energy,
            "total_peak": total_peak,
        }
        row_vals = df.iloc[idx]
        for meter in {
            str(c[2]) for c in energy_cols if isinstance(c, tuple) and len(c) > 2
        }:
            cols_m = [c for c in energy_cols if c[2] == meter]
            if cols_m:
                meter_eui = float(row_vals[cols_m].sum())  # already kWh/m²
                row_dict[f"eui_{meter.lower().replace(' ', '_')}"] = meter_eui
        rows.append(row_dict)

    if not rows:
        return None
    out = pd.DataFrame(rows)
    out[LAT_COL] = out[LAT_COL].astype("float64")
    out[LON_COL] = out[LON_COL].astype("float64")
    return out


def _extract_basic_overheating(
    oh_flat: pd.DataFrame,
    bid_col,
    heat_threshold_c: float,
    aggregation: str,
) -> pd.DataFrame | None:
    """Extract building-level overheating hours from BasicOverheating flat df."""
    polarity_col = _find_col(oh_flat, "Polarity")
    thresh_col = _find_col(oh_flat, "Threshold [degC]")
    agg_col = _find_col(oh_flat, "Aggregation Unit")
    group_col = _find_col(oh_flat, "Group")
    val_col = "Total Hours [hr]" if "Total Hours [hr]" in oh_flat.columns else None
    if not all([polarity_col, thresh_col, agg_col, group_col, val_col]):
        return None
    mask = (
        (oh_flat[polarity_col] == "Overheat")
        & (oh_flat[thresh_col] == heat_threshold_c)
        & (oh_flat[agg_col] == "Building")
        & (oh_flat[group_col] == aggregation)
    )
    oh_sub = oh_flat.loc[mask, [bid_col, val_col]].drop_duplicates(subset=[bid_col])
    oh_sub = oh_sub.rename(columns={val_col: "map_value"})
    return oh_sub


def _extract_exceedance_degree_hours(
    oh_flat: pd.DataFrame,
    bid_col,
    heat_threshold_c: float,
    aggregation: str,
) -> pd.DataFrame | None:
    """Extract building-level EDH from ExceedanceDegreeHours flat df."""
    polarity_col = _find_col(oh_flat, "Polarity")
    thresh_col = _find_col(oh_flat, "Threshold [degC]")
    agg_col = _find_col(oh_flat, "Aggregation Unit")
    group_col = _find_col(oh_flat, "Group")
    val_col = "EDH [degC-hr]" if "EDH [degC-hr]" in oh_flat.columns else None
    if not all([polarity_col, thresh_col, agg_col, group_col, val_col]):
        return None
    mask = (
        (oh_flat[polarity_col] == "Overheat")
        & (oh_flat[thresh_col] == heat_threshold_c)
        & (oh_flat[agg_col] == "Building")
        & (oh_flat[group_col] == aggregation)
    )
    oh_sub = oh_flat.loc[mask, [bid_col, val_col]].drop_duplicates(subset=[bid_col])
    oh_sub = oh_sub.rename(columns={val_col: "map_value"})
    return oh_sub


def _extract_heat_index_categories(
    oh_flat: pd.DataFrame,
    bid_col,
    aggregation: str,
    metric: str,
) -> pd.DataFrame | None:
    """Extract building-level heat index metric from HeatIndexCategories flat df."""
    agg_col = _find_col(oh_flat, "Aggregation Unit")
    group_col = _find_col(oh_flat, "Group")
    if agg_col is None or group_col is None:
        return None
    # map UI aggregation to HeatIndex Group values
    group_map = {"Zone Weighted": "Zone Weighted", "Worst Zone": "Worst per Timestep"}
    group_val = group_map.get(aggregation, aggregation)
    mask = (oh_flat[agg_col] == "Building") & (oh_flat[group_col] == group_val)
    hi_sub = oh_flat.loc[mask].copy()
    if hi_sub.empty:
        return None
    danger_cols = [
        c
        for c in hi_sub.columns
        if c
        in (
            "Extreme Danger [hr]",
            "Danger [hr]",
            "Extreme Caution [hr]",
            "Caution [hr]",
        )
    ]
    if metric == "danger_hours" and danger_cols:
        hi_sub["map_value"] = hi_sub[danger_cols].sum(axis=1)
    elif metric in hi_sub.columns:
        hi_sub["map_value"] = hi_sub[metric]
    else:
        return None
    oh_sub = hi_sub[[bid_col, "map_value"]].drop_duplicates(subset=[bid_col])
    return oh_sub


def build_overheating_map_df(
    run_dir: Path,
    cart_crs: str = "EPSG:3857",
    heat_threshold_c: float = 26.0,
    aggregation: str = "Zone Weighted",
    data_source_type: str = "BasicOverheating",
    heat_index_metric: str = "danger_hours",
) -> pd.DataFrame | None:
    """Build map-ready df with overheating metric per building.

    Merges overheating data with EnergyAndPeak geometry. Returns df with lat, lon,
    rotated_rectangle, height, map_value.

    Args:
        run_dir: Run directory containing overheating and EnergyAndPeak files.
        cart_crs: CRS for rotated_rectangle.
        heat_threshold_c: Overheating threshold (BasicOverheating, ExceedanceDegreeHours).
        aggregation: Zone Weighted, Worst Zone, etc.
        data_source_type: BasicOverheating, ExceedanceDegreeHours, or HeatIndexCategories.
        heat_index_metric: For HeatIndexCategories: danger_hours or column name.
    """
    oh_path = get_overheating_file_for_run(run_dir, data_source_type)
    energy_path = get_pq_file_for_run(run_dir)
    if oh_path is None or energy_path is None:
        return None

    oh_df = load_output_table(oh_path)
    energy_df = load_output_table(energy_path)

    geo_df = build_map_df_from_output(energy_df, cart_crs=cart_crs)
    if geo_df is None:
        return None

    oh_flat = oh_df.reset_index()
    bid_col = _find_col(oh_flat, BUILDING_ID_COL)
    if bid_col is None:
        return None

    if data_source_type == "BasicOverheating":
        oh_sub = _extract_basic_overheating(
            oh_flat, bid_col, heat_threshold_c, aggregation
        )
    elif data_source_type == "ExceedanceDegreeHours":
        oh_sub = _extract_exceedance_degree_hours(
            oh_flat, bid_col, heat_threshold_c, aggregation
        )
    elif data_source_type == "HeatIndexCategories":
        oh_sub = _extract_heat_index_categories(
            oh_flat, bid_col, aggregation, heat_index_metric
        )
    else:
        return None

    if oh_sub is None or oh_sub.empty:
        return None

    oh_sub[bid_col] = oh_sub[bid_col].astype(str)
    geo_df[BUILDING_ID_COL] = geo_df[BUILDING_ID_COL].astype(str)
    merged = geo_df.merge(oh_sub, on=BUILDING_ID_COL, how="inner")
    return merged if not merged.empty else None


def _load_one_overheating_metric(
    run_dir: Path,
    df_key: str,
    bid_col: str,
    heat_threshold_c: float,
    aggregation: str,
) -> pd.DataFrame | None:
    """Load one overheating metric as building_id + value df."""
    oh_path = get_overheating_file_for_run(run_dir, df_key)
    if not oh_path:
        return None
    df = load_output_table(oh_path)
    flat = df.reset_index()
    bid = _find_col(flat, bid_col)
    if not bid:
        return None
    if df_key == "BasicOverheating":
        sub = _extract_basic_overheating(flat, bid, heat_threshold_c, aggregation)
        col_name = "BasicOverheating_hr"
    elif df_key == "ExceedanceDegreeHours":
        sub = _extract_exceedance_degree_hours(flat, bid, heat_threshold_c, aggregation)
        col_name = "ExceedanceDegreeHours"
    elif df_key == "HeatIndexCategories":
        sub = _extract_heat_index_categories(flat, bid, aggregation, "danger_hours")
        col_name = "HeatIndex_danger_hr"
    else:
        return None
    if sub is None:
        return None
    sub = sub.rename(columns={"map_value": col_name})
    sub[bid] = sub[bid].astype(str)
    return sub


def _summarize_values(vals) -> dict[str, float]:
    """Compute mean, median, p95, max from a numeric array."""
    import numpy as np

    return {
        "mean": float(np.mean(vals)),
        "median": float(np.median(vals)),
        "p95": float(np.percentile(vals, 95)),
        "max": float(np.max(vals)),
    }


def _build_basic_edh_records(
    run_dir: Path,
    available: list[str],
    thresholds: list[float],
    aggregation: str,
) -> dict[str, dict[str, float]]:
    records: dict[str, dict[str, float]] = {}
    for df_key in ("BasicOverheating", "ExceedanceDegreeHours"):
        if df_key not in available:
            continue
        label_prefix = "Basic" if df_key == "BasicOverheating" else "EDH"
        for thresh in thresholds:
            sub = _load_one_overheating_metric(
                run_dir, df_key, BUILDING_ID_COL, thresh, aggregation
            )
            if sub is None or sub.empty:
                continue
            vals = sub.iloc[:, -1].dropna().values
            if len(vals) > 0:
                records[f"{label_prefix} {thresh}C"] = _summarize_values(vals)
    return records


def _build_heat_index_record(
    run_dir: Path,
    available: list[str],
    aggregation: str,
) -> dict[str, dict[str, float]] | None:
    if "HeatIndexCategories" not in available:
        return None
    sub = _load_one_overheating_metric(
        run_dir, "HeatIndexCategories", BUILDING_ID_COL, 0.0, aggregation
    )
    if sub is None or sub.empty:
        return None
    vals = sub.iloc[:, -1].dropna().values
    if len(vals) == 0:
        return None
    return {"HeatIndex discomfort": _summarize_values(vals)}


def build_overheating_summary_df(
    run_dir: Path,
    aggregation: str = "Zone Weighted",
) -> pd.DataFrame | None:
    """Build summary stats (mean, median, max, p95) per metric and threshold.

    Rows = stat names, columns = metric/threshold combos. Suitable for heatmap.
    """
    available = list_overheating_files_for_run(run_dir)
    if not available:
        return None

    thresholds = get_overheating_thresholds(run_dir)
    records: dict[str, dict[str, float]] = {}
    records.update(
        _build_basic_edh_records(run_dir, available, thresholds, aggregation)
    )
    hi_rec = _build_heat_index_record(run_dir, available, aggregation)
    if hi_rec:
        records.update(hi_rec)

    if not records:
        return None

    df = pd.DataFrame(records)
    df.index.name = "statistic"
    return df.reset_index()


def load_heat_index_summary_for_chart(
    run_dir: Path,
    aggregation: str = "Zone Weighted",
) -> dict[str, float] | None:
    """Load HeatIndexCategories and return summed hours by category for stacked bar.

    Returns dict like {"Extreme Danger [hr]": 0, "Danger [hr]": 10, ...}.
    """
    oh_path = get_overheating_file_for_run(run_dir, "HeatIndexCategories")
    if oh_path is None:
        return None
    oh_df = load_output_table(oh_path)
    oh_flat = oh_df.reset_index()
    agg_col = _find_col(oh_flat, "Aggregation Unit")
    group_col = _find_col(oh_flat, "Group")
    if agg_col is None or group_col is None:
        return None
    group_map = {"Zone Weighted": "Zone Weighted", "Worst Zone": "Worst per Timestep"}
    group_val = group_map.get(aggregation, aggregation)
    mask = (oh_flat[agg_col] == "Building") & (oh_flat[group_col] == group_val)
    hi_sub = oh_flat.loc[mask]
    if hi_sub.empty:
        return None
    cat_cols = [
        c
        for c in hi_sub.columns
        if c
        in (
            "Extreme Danger [hr]",
            "Danger [hr]",
            "Extreme Caution [hr]",
            "Caution [hr]",
            "Normal [hr]",
        )
    ]
    if not cat_cols:
        return None
    return hi_sub[cat_cols].sum().to_dict()


def merge_with_building_locations(  # noqa: C901
    df: pd.DataFrame,
    locations_df: pd.DataFrame,
) -> pd.DataFrame | None:
    """Merge output data with building locations.

    Args:
        df: Output dataframe with BUILDING_ID_COL.
        locations_df: Locations dataframe with BUILDING_ID_COL, lat, lon.

    Returns:
        Merged dataframe or None if no matches.
    """
    df_reset = df.reset_index() if df.index.name else df

    def _ensure_flat_building_id(source: pd.DataFrame) -> pd.DataFrame:
        """Ensure source has a flat building_id column."""
        if BUILDING_ID_COL in source.columns:
            return source

        # multiindex column where one of the levels is building_id
        if isinstance(source.columns, pd.MultiIndex):
            for col in source.columns:
                if not isinstance(col, tuple):
                    continue
                if any(
                    isinstance(level, str) and level.lower() == BUILDING_ID_COL
                    for level in col
                ):
                    out = source.copy()
                    out[BUILDING_ID_COL] = out[col]
                    return out

        # index or index level named building_id
        if source.index.name == BUILDING_ID_COL:
            return source.reset_index()
        if isinstance(source.index, pd.MultiIndex) and BUILDING_ID_COL in (
            source.index.names or []
        ):
            return source.reset_index(level=BUILDING_ID_COL)

        return source

    df_prepared = _ensure_flat_building_id(df_reset)

    if BUILDING_ID_COL not in df_prepared.columns:
        return None
    if BUILDING_ID_COL not in locations_df.columns:
        return None

    # flatten multiindex columns so we can merge on a regular column name
    if isinstance(df_prepared.columns, pd.MultiIndex):
        df_flat = df_prepared.copy()
        flat_cols: list[str] = []
        for col in df_flat.columns:
            if isinstance(col, tuple):
                # take the first non-empty level, else join all levels
                non_empty = [str(level) for level in col if str(level)]
                flat_cols.append(
                    non_empty[0] if non_empty else "_".join(str(level) for level in col)
                )
            else:
                flat_cols.append(str(col))
        df_flat.columns = flat_cols
    else:
        df_flat = df_prepared

    if BUILDING_ID_COL not in df_flat.columns:
        return None

    # always include lat/lon, and rotated_rectangle if available, from locations
    loc_cols = [BUILDING_ID_COL, LAT_COL, LON_COL]
    if ROTATED_RECTANGLE_COL in locations_df.columns:
        loc_cols.append(ROTATED_RECTANGLE_COL)
    loc_subset = locations_df.loc[
        locations_df[LAT_COL].notna() & locations_df[LON_COL].notna(),
        loc_cols,
    ]

    # coerce id columns to string to avoid subtle type mismatches
    df_flat = df_flat.copy()
    df_flat[BUILDING_ID_COL] = df_flat[BUILDING_ID_COL].astype("string")
    loc_subset = loc_subset.copy()
    loc_subset[BUILDING_ID_COL] = loc_subset[BUILDING_ID_COL].astype("string")

    merged = df_flat.merge(loc_subset, on=BUILDING_ID_COL, how="inner")

    return merged if not merged.empty else None


def compute_scenario_comparison(
    baseline_df: pd.DataFrame,
    comparison_df: pd.DataFrame,
    metric_col: str,
) -> pd.DataFrame:
    """Compute percent change between two scenarios.

    Args:
        baseline_df: Baseline scenario data.
        comparison_df: Comparison scenario data.
        metric_col: Column to compare.

    Returns:
        DataFrame with percent_change column.
    """
    if BUILDING_ID_COL not in baseline_df.columns:
        msg = "baseline_df missing building_id"
        raise ValueError(msg)
    if BUILDING_ID_COL not in comparison_df.columns:
        msg = "comparison_df missing building_id"
        raise ValueError(msg)

    baseline = baseline_df[[BUILDING_ID_COL, metric_col]].copy()
    baseline.columns = [BUILDING_ID_COL, "baseline_value"]

    comparison = comparison_df[[BUILDING_ID_COL, metric_col]].copy()
    comparison.columns = [BUILDING_ID_COL, "comparison_value"]

    merged = baseline.merge(comparison, on=BUILDING_ID_COL, how="inner")
    merged["percent_change"] = (
        (merged["comparison_value"] - merged["baseline_value"])
        / merged["baseline_value"]
        * 100
    )

    return merged
