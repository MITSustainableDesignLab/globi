"""Utilities for visualization and raw data processing."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# TODO: update this after the building col PR merged
BUILDING_ID_COL = "building_id"
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
    """Find directories under base_dir that contain at least one .pq file.

    Returns sorted list of directory paths (run folders, e.g. TestRegion/dryrun/Baseline/v1.0.0).
    """
    root = Path(base_dir)
    if not root.exists():
        return []

    # TODO: update this depending on the method for accessing runs
    seen: set[Path] = set()
    for path in root.rglob("*.pq"):
        if path.is_file():
            seen.add(path.parent)
    return sorted(seen)


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
    return pq_files[0] if pq_files else None


def load_output_table(path: Path | str) -> pd.DataFrame:
    """Load a .pq (parquet) file into a dataframe. Uses pandas; Results.pq has no geometry."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    if p.suffix != ".pq":
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
