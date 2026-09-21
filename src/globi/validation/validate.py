"""Validate a trained surrogate against deterministic (EnergyPlus) ground truth.

The ground truth is the output of the standard GloBI run: buildings whose semantic
fields are fully defined in the GIS data (no priors), simulated with EnergyPlus.  The
surrogate (`globi.models.surrogate.inference.SurrogateEnsemble`) predicts from the
feature index those simulations carry, and this module compares the two per building
and at stock level.  Only the comparison lives here; how to apply a surrogate is
defined on the inference side.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import geopandas as gpd
import numpy as np
import pandas as pd

from globi.models.configs import GISPreprocessorColumnMap, GloBIExperimentSpec
from globi.models.surrogate.inference import (
    AREA_COLUMN,
    SEMANTIC_PREFIX,
    SurrogateEnsemble,
)
from globi.models.surrogate.metrics import compute_frame_metrics
from globi.models.surrogate.training import flatten_result_frames
from globi.models.tasks import GloBIBuildingSpec
from globi.pipelines.gis import build_building_specs, preprocess_gis_file

logger = logging.getLogger(__name__)


def deterministic_specs(
    manifest: GloBIExperimentSpec,
    *,
    n: int | None,
    seed: int = 0,
    building_ids: list[str] | None = None,
    preprocessed: tuple[gpd.GeoDataFrame, GISPreprocessorColumnMap] | None = None,
) -> tuple[list[GloBIBuildingSpec], list[str]]:
    """Build simulation specs for buildings exactly as the GIS data defines them.

    Overheating / hourly outputs are disabled so the result frames match what the
    training samples produce.

    Args:
        manifest: The experiment manifest (GIS, db, semantic fields, ...).
        n: Number of buildings to sample (None = all).
        seed: Sampling seed.
        building_ids: Use exactly these buildings instead of sampling.
        preprocessed: An already preprocessed `(gdf, colmap)` pair to use instead of
            running `preprocess_gis_file` again.

    Returns:
        The specs and the ids of the buildings they describe.
    """
    gdf, colmap = preprocessed or preprocess_gis_file(
        manifest.gis_preprocessor_config,
        manifest.file_config,
        scenario=manifest.scenario,
    )
    if building_ids is not None:
        mask = gdf[colmap.Building_ID_col].isin(list(building_ids))
        gdf = cast(gpd.GeoDataFrame, gdf[mask])
    elif n is not None:
        gdf = cast(gpd.GeoDataFrame, gdf.sample(n=min(n, len(gdf)), random_state=seed))
    parent = manifest.model_copy(
        update={"overheating_config": None, "hourly_data_config": None}
    )
    specs = build_building_specs(
        gdf, colmap, manifest.file_config, parent_experiment_spec=parent
    )
    return specs, [s.building_id for s in specs]


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


@dataclass
class ValidationResult:
    """All validation outputs (also written to `out_dir`)."""

    per_building: pd.DataFrame
    metrics_global: pd.DataFrame
    metrics_by_group: pd.DataFrame
    aggregate: pd.DataFrame
    metrics_per_fold: pd.DataFrame
    unseen: dict[str, set]
    out_dir: Path

    @property
    def report_path(self) -> Path:
        """Path to the markdown report."""
        return self.out_dir / "report.md"


def _group_columns(features: pd.DataFrame) -> list[str]:
    cols = [c for c in features.columns if c.startswith(SEMANTIC_PREFIX)]
    if "num_floors" in features.columns:
        cols.append("num_floors")
    return [c for c in cols if features[c].nunique() > 1]


def _stock_aggregate(
    truth: pd.DataFrame, pred: pd.DataFrame, area: pd.Series
) -> pd.DataFrame:
    """Area-weighted totals (kWh) of intensity targets (kWh/m2), true vs predicted."""
    true_total = truth.mul(area.to_numpy(), axis=0).sum(axis=0)
    pred_total = pred.mul(area.to_numpy(), axis=0).sum(axis=0)
    out = pd.DataFrame({"true_total": true_total, "pred_total": pred_total})
    out.insert(0, "n", len(truth))
    out["error"] = out["pred_total"] - out["true_total"]
    out["pct_error"] = out["error"] / out["true_total"].where(out["true_total"] != 0, 1)
    out.index.name = "target"
    return out


_GROUP_LEVELS = ["group_column", "group_value", "target"]


def _concat_named(
    frames: Mapping[Any, pd.DataFrame], *, axis: Literal[0, 1], names: list[str]
) -> pd.DataFrame:
    """`pd.concat` with a keyed outer level, typed loosely to satisfy pandas-stubs."""
    return cast(
        pd.DataFrame,
        pd.concat(frames, axis=axis, names=names),  # pyright: ignore [reportCallIssue, reportArgumentType]
    )


def _per_building_frame(
    features: pd.DataFrame,
    truth: pd.DataFrame,
    pred: pd.DataFrame,
    has_unseen: pd.Series,
    *,
    id_cols: list[str],
) -> pd.DataFrame:
    """Flat per-building frame: id/grouping columns + true/pred/err per target."""
    out = pd.DataFrame(features[[c for c in id_cols if c in features]])
    out["has_unseen_category"] = has_unseen.to_numpy()
    for t in truth.columns:
        out[f"{t}/true"] = truth[t].to_numpy()
        out[f"{t}/pred"] = pred[t].to_numpy()
        out[f"{t}/abs_err"] = (pred[t] - truth[t]).abs().to_numpy()
        out[f"{t}/pct_err"] = (
            (pred[t] - truth[t]) / truth[t].where(truth[t] != 0, np.nan)
        ).to_numpy()
    return out


def _global_metrics(
    truth: pd.DataFrame, pred: pd.DataFrame, has_unseen: pd.Series
) -> pd.DataFrame:
    """Ensemble metrics on all buildings and, if relevant, on the seen-category subset."""
    subsets = {"all": compute_frame_metrics(pred, truth)}
    if has_unseen.any() and (~has_unseen).sum() >= 2:
        seen = cast(np.ndarray, (~has_unseen).to_numpy())
        subsets["seen_only"] = compute_frame_metrics(
            cast(pd.DataFrame, pred[seen]), cast(pd.DataFrame, truth[seen])
        )
    return _concat_named(subsets, axis=1, names=["subset", "metric"])


def _group_metrics(
    features: pd.DataFrame, truth: pd.DataFrame, pred: pd.DataFrame, groups: list[str]
) -> pd.DataFrame:
    """Metrics per value of each grouping column (groups with <2 buildings skipped)."""
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    for col in groups:
        for val, idx in features.groupby(col).groups.items():
            if len(idx) < 2:
                continue
            frame = compute_frame_metrics(pred.loc[idx], truth.loc[idx])
            frame.insert(0, "n", len(idx))
            frames[(col, str(val))] = frame
    if not frames:
        return pd.DataFrame()
    return _concat_named(frames, axis=0, names=_GROUP_LEVELS).sort_index()


def _group_aggregates(
    features: pd.DataFrame,
    truth: pd.DataFrame,
    pred: pd.DataFrame,
    area: pd.Series,
    groups: list[str],
) -> pd.DataFrame:
    """Area-weighted stock totals overall (`("all", "all")`) and per group value."""
    frames = {("all", "all"): _stock_aggregate(truth, pred, area)}
    for col in groups:
        for val, idx in features.groupby(col).groups.items():
            frames[(col, str(val))] = _stock_aggregate(
                truth.loc[idx], pred.loc[idx], area.loc[idx]
            )
    return _concat_named(frames, axis=0, names=_GROUP_LEVELS).sort_index()


def validate_surrogate(
    ensemble: SurrogateEnsemble,
    ground_truth: dict[str, pd.DataFrame],
    *,
    out_dir: Path,
    area_column: str = AREA_COLUMN,
    group_columns: list[str] | None = None,
) -> ValidationResult:
    """Compare surrogate predictions to EnergyPlus results for the same buildings.

    Args:
        ensemble: The trained surrogate (per-fold metrics are reported alongside the
            ensemble's).
        ground_truth: Raw simulation result frames keyed like the training data
            (e.g. `{"EnergyAndPeakAnnual": df}`), feature MultiIndex on the rows.
        out_dir: Where to write parquet outputs and `report.md`.
        area_column: Index column used to area-weight the stock aggregates.
        group_columns: Index columns to break metrics down by (default: every
            `feature.semantic.*` column with >1 value, plus `num_floors`).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    truth = flatten_result_frames(ground_truth, ensemble.targets)
    features = truth.index.to_frame(index=False)
    truth = truth.reset_index(drop=True)

    per_fold = ensemble.predict_per_fold(features)
    pred = cast(pd.DataFrame, sum(per_fold) / len(per_fold))
    unseen = ensemble.unseen_categories(features)
    has_unseen = pd.Series(False, index=features.index)
    for col, extra in unseen.items():
        has_unseen |= features[col].isin(list(extra))
    if unseen:
        logger.warning(
            "%d/%d buildings have categorical values unseen in training: %s",
            int(has_unseen.sum()),
            len(features),
            {k: sorted(map(str, v)) for k, v in unseen.items()},
        )

    groups = group_columns or _group_columns(features)
    if area_column in features.columns:
        area = cast(pd.Series, features[area_column].astype(float))
    else:
        logger.warning("Area column %s not found; aggregating unweighted.", area_column)
        area = pd.Series(1.0, index=features.index)

    fold_frames = {
        f"fold_{i}": compute_frame_metrics(p, truth) for i, p in enumerate(per_fold)
    }
    fold_frames["ensemble"] = compute_frame_metrics(pred, truth)

    result = ValidationResult(
        per_building=_per_building_frame(
            features,
            truth,
            pred,
            has_unseen,
            id_cols=["building_id", area_column, *groups],
        ),
        metrics_global=_global_metrics(truth, pred, has_unseen),
        metrics_by_group=_group_metrics(features, truth, pred, groups),
        aggregate=_group_aggregates(features, truth, pred, area, groups),
        metrics_per_fold=pd.concat(fold_frames, axis=1, names=["model", "metric"]),
        unseen=unseen,
        out_dir=out_dir,
    )
    _write_outputs(result, pred, truth, features)
    return result


def _write_outputs(
    result: ValidationResult,
    pred: pd.DataFrame,
    truth: pd.DataFrame,
    features: pd.DataFrame,
) -> None:
    out = result.out_dir
    pd.concat({"true": truth, "pred": pred}, axis=1).set_index(
        pd.MultiIndex.from_frame(features)
    ).to_parquet(out / "predictions.parquet")
    result.per_building.to_parquet(out / "per_building.parquet")
    result.metrics_global.to_parquet(out / "metrics_global.parquet")
    result.metrics_per_fold.to_parquet(out / "metrics_per_fold.parquet")
    if not result.metrics_by_group.empty:
        result.metrics_by_group.to_parquet(out / "metrics_by_group.parquet")
    result.aggregate.to_parquet(out / "aggregate.parquet")
    result.report_path.write_text(render_report(result))


def _md(df: pd.DataFrame | pd.Series) -> str:
    """Markdown table, falling back to plain text if `tabulate` is unavailable."""
    try:
        return str(df.to_markdown(floatfmt=".4g"))
    except ImportError:
        return "```\n" + df.to_string() + "\n```"


def render_report(result: ValidationResult) -> str:
    """Render a markdown summary of the validation."""
    n = len(result.per_building)
    lines = [
        "# Surrogate validation report",
        "",
        f"Buildings: **{n}**; targets: **{len(result.metrics_global)}**; "
        f"fold models: **{result.metrics_per_fold.columns.get_level_values('model').nunique() - 1}**",
        "",
    ]
    if result.unseen:
        lines += [
            "> **Warning**: some buildings have categorical values never seen in "
            f"training ({int(result.per_building['has_unseen_category'].sum())}/{n}):",
            "",
            *[
                f"> - `{col}`: {sorted(map(str, vals))}"
                for col, vals in result.unseen.items()
            ],
            "",
        ]
    lines += [
        "## Global metrics (ensemble, all buildings)",
        "",
        _md(result.metrics_global["all"]),
        "",
    ]
    if "seen_only" in result.metrics_global.columns.get_level_values("subset"):
        lines += [
            "## Global metrics (buildings with seen categories only)",
            "",
            _md(result.metrics_global["seen_only"]),
            "",
        ]
    stock = result.aggregate.loc[("all", "all")]
    lines += [
        "## Stock aggregate (area-weighted totals)",
        "",
        _md(stock),
        "",
        "## Per-fold vs ensemble (r2 / cvrmse)",
        "",
        _md(result.metrics_per_fold.xs("r2", level="metric", axis=1)),
        "",
        _md(result.metrics_per_fold.xs("cvrmse", level="metric", axis=1)),
        "",
    ]
    if not result.metrics_by_group.empty:
        lines += ["## Metrics by group (n, r2, cvrmse, nmbe)", ""]
        by_group = result.metrics_by_group[["n", "r2", "cvrmse", "nmbe"]]
        lines += [_md(by_group), ""]
        lines += ["## Stock aggregate by group", ""]
        grouped = result.aggregate.drop(index=("all", "all"), errors="ignore")
        lines += [_md(grouped), ""]
    lines += [
        "## Files",
        "",
        "- `predictions.parquet`: true/pred per target, feature MultiIndex",
        "- `per_building.parquet`: flat per-building errors with grouping columns",
        "- `metrics_global.parquet`, `metrics_per_fold.parquet`, `metrics_by_group.parquet`",
        "- `aggregate.parquet`: area-weighted stock totals overall and per group",
        "",
    ]
    return "\n".join(lines)
