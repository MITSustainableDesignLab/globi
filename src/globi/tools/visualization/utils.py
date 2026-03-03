"""Utilities for visualization and raw data processing."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

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


OVERHEATING_PQ_NAMES = ("BasicOverheating.pq", "BasicOverheating.parquet")


def run_has_overheating(run_dir: Path) -> bool:
    """True if run directory contains overheating output (BasicOverheating)."""
    return any((run_dir / name).is_file() for name in OVERHEATING_PQ_NAMES)


def get_overheating_file_for_run(run_dir: Path) -> Path | None:
    """Return BasicOverheating file path if present."""
    for name in OVERHEATING_PQ_NAMES:
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


def build_map_features_from_df(  # noqa: C901
    df: pd.DataFrame,
    cart_crs: str = "EPSG:3857",
    default_height_m: float = 10.0,
    value_col: str | None = None,
) -> list[dict] | None:
    """Extract map features from dataframe with rotated_rectangle and height.

    Converts each rotated_rectangle WKT (in cart_crs) to lat/lon polygon,
    extrudes by height (meters). Works with flat parquet or index-flattened data.

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

    features: list[dict] = []
    for i in range(len(df_flat)):
        wkt_val = df_flat.iloc[i][rect_col]
        wkt_str = getattr(wkt_val, "wkt", wkt_val) if wkt_val is not None else None
        if not isinstance(wkt_str, str):
            continue

        poly_lonlat = transform_rotated_rectangle_to_latlon(wkt_str, cart_crs)
        if not poly_lonlat:
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

        feat: dict = {"polygon": poly_lonlat, "height": float(h)}
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
) -> list[list[float]] | None:
    """Convert rotated_rectangle WKT (in cartesian CRS) to lat/lon polygon.

    Transforms each vertex from cart_crs to EPSG:4326. Returns [[lon, lat], ...]
    for pydeck polygon layer, or None if invalid.
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
        transformer = Transformer.from_crs(cart_crs, "EPSG:4326", always_xy=True)
        result: list[list[float]] = []
        for x, y in coords:
            lon, lat = transformer.transform(float(x), float(y))
            result.append([float(lon), float(lat)])
    except Exception:
        return None
    return result


def build_map_df_from_output(  # noqa: C901
    df: pd.DataFrame,
    cart_crs: str = "EPSG:3857",
) -> pd.DataFrame | None:
    """Build map-ready dataframe directly from output parquet.

    Extracts lat/lon from rotated_rectangle, computes EUI/peak metrics,
    no merge with inputs. Returns df with building_id, lat, lon,
    rotated_rectangle, height, eui, peak_per_sqm, end-use eui cols.
    """
    import logging

    from pyproj import Transformer
    from shapely import from_wkt

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

    transformer = Transformer.from_crs(cart_crs, "EPSG:4326", always_xy=True)
    log = logging.getLogger(__name__)
    rows: list[dict] = []

    for idx, (_, row) in enumerate(df_reset.iterrows()):
        wkt = row.get(rect_col)
        if not isinstance(wkt, str):
            continue
        try:
            geom = from_wkt(wkt)
            if geom.is_empty:
                continue
            cx, cy = geom.centroid.x, geom.centroid.y
            lon, lat = transformer.transform(cx, cy)
            bid = str(row[bid_col])
        except Exception as exc:
            log.debug("skip row: %s", exc)
            continue

        area_val = df.index.get_level_values(area_level)[idx]
        try:
            fval = float(area_val)  # type: ignore[arg-type]
            area = fval if fval > 0 else None
        except (TypeError, ValueError):
            area = None
        if area is None:
            continue

        row_vals = df.iloc[idx]
        total_energy = float(row_vals[energy_cols].sum())
        peak = float(row_vals[peak_cols].max())
        eui = total_energy / area
        peak_per_sqm = peak / area

        # height from output parquet index (height col, else num_floors * f2f_height)
        h_col = _find_col(df_reset, "height")
        nf_col = _find_col(df_reset, "num_floors")
        f2f_col = _find_col(df_reset, "f2f_height")
        height_m = 6.0
        if h_col is not None and h_col in row.index:
            try:
                hv = row[h_col]
                hm = float(hv)
                if hm == hm:  # not nan
                    height_m = hm
            except (TypeError, ValueError):
                pass
        elif nf_col is not None and nf_col in row.index:
            f2f = 3.0
            if f2f_col is not None and f2f_col in row.index:
                try:
                    fv = row[f2f_col]
                    f2f = float(fv) if fv == fv else 3.0
                except (TypeError, ValueError):
                    pass
            try:
                nv = row[nf_col]
                nm = float(nv)
                if nm == nm:  # not nan
                    height_m = nm * f2f
            except (TypeError, ValueError):
                pass

        row_dict: dict = {
            BUILDING_ID_COL: bid,
            LAT_COL: float(lat),
            LON_COL: float(lon),
            ROTATED_RECTANGLE_COL: wkt,
            "height": height_m,
            "eui": eui,
            "peak_per_sqm": peak_per_sqm,
            "total_energy": total_energy,
            "total_peak": peak,
        }
        for meter in {
            str(c[2]) for c in energy_cols if isinstance(c, tuple) and len(c) > 2
        }:
            cols_m = [c for c in energy_cols if c[2] == meter]
            if cols_m:
                meter_eui = float(row_vals[cols_m].sum()) / area
                row_dict[f"eui_{meter.lower().replace(' ', '_')}"] = meter_eui
        rows.append(row_dict)

    if not rows:
        return None
    out = pd.DataFrame(rows)
    out[LAT_COL] = out[LAT_COL].astype("float64")
    out[LON_COL] = out[LON_COL].astype("float64")
    return out


def build_overheating_map_df(
    run_dir: Path,
    cart_crs: str = "EPSG:3857",
    heat_threshold_c: float = 26.0,
    aggregation: str = "Zone Weighted",
) -> pd.DataFrame | None:
    """Build map-ready df with overheating hours per building.

    Merges BasicOverheating (hours above threshold) with EnergyAndPeak geometry.
    Returns df with lat, lon, rotated_rectangle, height, overheating_hours.

    Args:
        run_dir: Run directory containing BasicOverheating and EnergyAndPeak.
        cart_crs: CRS for rotated_rectangle.
        heat_threshold_c: Overheating threshold (default 26C).
        aggregation: "Zone Weighted" or "Worst Zone".
    """
    oh_path = get_overheating_file_for_run(run_dir)
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
    oh_sub = oh_sub.rename(columns={val_col: "overheating_hours"})
    oh_sub[bid_col] = oh_sub[bid_col].astype(str)

    geo_df[BUILDING_ID_COL] = geo_df[BUILDING_ID_COL].astype(str)
    merged = geo_df.merge(oh_sub, on=BUILDING_ID_COL, how="inner")
    return merged if not merged.empty else None


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
