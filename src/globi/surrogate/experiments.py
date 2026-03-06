"""Scythe experiments for surrogate training.

Two experiments are registered:
- simulate_training_sample: runs a single FlatModel simulation for training data
- train_cv_fold: trains a single CV fold of the surrogate model
"""

import logging
from pathlib import Path
from typing import cast

import lightgbm as lgb
import numpy as np
import pandas as pd
from epinterface.sbem.flat_model import FlatModel
from scythe.registry import ExperimentRegistry
from sklearn.model_selection import StratifiedKFold

from globi.models.surrogate import (
    Metrics,
    TrainFoldInputSpec,
    TrainFoldOutputSpec,
    TrainingSimInputSpec,
    TrainingSimOutputSpec,
    compute_training_metrics,
)

logger = logging.getLogger(__name__)


@ExperimentRegistry.Register(retries=2, schedule_timeout="10h", execution_timeout="30m")
def simulate_training_sample(
    input_spec: TrainingSimInputSpec, tempdir: Path
) -> TrainingSimOutputSpec:
    """Simulate a single FlatModel instance for training data generation.

    1. Build FlatModel from flat_model_params, override with GIS geometry
    2. Simulate with neighbor geometry from GIS
    3. Extract features (all FlatModel fields + shading mask)
    4. Extract energy/peak results
    """
    gis_overrides = {
        "Width": input_spec.width,
        "Depth": input_spec.depth,
        "NFloors": input_spec.num_floors,
        "Rotation": input_spec.rotation,
    }
    merged_params = {**input_spec.flat_model_params, **gis_overrides}
    flat_model = FlatModel(**merged_params)

    neighbor_kwargs: dict = {}
    if input_spec.neighbor_polys:
        neighbor_kwargs = {
            "neighbor_polys": input_spec.neighbor_polys,
            "neighbor_heights": input_spec.neighbor_heights,
            "building_polygon": input_spec.rotated_rectangle,
            "building_rotation_angle": input_spec.long_edge_angle,
        }

    result = flat_model.simulate(
        eplus_parent_dir=tempdir,
        **neighbor_kwargs,
    )

    features_dict = flat_model.feature_dict(
        neighbor_polys=input_spec.neighbor_polys or None,
        neighbor_heights=input_spec.neighbor_heights or None,
    )
    features_dict["weather_file_id"] = input_spec.weather_file_id

    features_df = pd.DataFrame([features_dict])
    energy_and_peak = result.energy_and_peak.to_frame().T

    return TrainingSimOutputSpec(
        dataframes={"Features": features_df, "EnergyAndPeak": energy_and_peak}
    )


@ExperimentRegistry.Register(retries=1, schedule_timeout="2h", execution_timeout="1h")
def train_cv_fold(input_spec: TrainFoldInputSpec, tempdir: Path) -> TrainFoldOutputSpec:
    """Train a single CV fold of the surrogate model.

    1. Load combined training data
    2. Stratified k-fold split by weather file
    3. Train LightGBM models per target column
    4. Compute metrics globally and per stratum
    5. Save models to tempdir
    """
    data_path = (
        input_spec.fetch_uri(input_spec.data_uri)
        if not isinstance(input_spec.data_uri, Path)
        else input_spec.data_uri
    )
    data = pd.read_parquet(data_path)

    feature_cols = input_spec.feature_columns
    target_cols = input_spec.target_columns
    strat_col = input_spec.stratification_column
    lgb_params = input_spec.hyperparameters.to_lgb_params()

    X = data[feature_cols]
    strat_values = data[strat_col] if strat_col in data.columns else None

    skf = StratifiedKFold(n_splits=input_spec.n_folds, shuffle=True, random_state=42)
    split_col = strat_values if strat_values is not None else np.zeros(len(data))
    splits = list(skf.split(X, split_col))
    train_idx, test_idx = splits[input_spec.fold_index]

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]

    global_metrics_rows: list[Metrics] = []
    stratum_metrics_rows: list[Metrics] = []

    for target_col in target_cols:
        y_train = data[target_col].iloc[train_idx]
        y_test = data[target_col].iloc[test_idx]

        model = lgb.LGBMRegressor(**lgb_params)
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)
        y_pred_series = pd.Series(y_pred, index=y_test.index)

        global_m = compute_training_metrics(
            y_test, y_pred_series, target_col, input_spec.fold_index
        )
        global_metrics_rows.append(global_m)

        model_path = tempdir / f"model_{target_col}_fold{input_spec.fold_index}.lgb"
        model.booster_.save_model(str(model_path))  # pyright: ignore [reportOptionalMemberAccess]

        if strat_values is not None:
            test_strat = strat_values.iloc[test_idx]
            for stratum in test_strat.unique():
                stratum_mask = test_strat == stratum
                if stratum_mask.sum() == 0:
                    continue
                strat_m = compute_training_metrics(
                    y_test[stratum_mask],
                    cast(pd.Series, y_pred_series[stratum_mask]),
                    target_col,
                    input_spec.fold_index,
                    stratum,
                )
                stratum_metrics_rows.append(strat_m)

    global_metrics_df = pd.DataFrame(global_metrics_rows)
    stratum_metrics_df = pd.DataFrame(stratum_metrics_rows)

    return TrainFoldOutputSpec(
        dataframes={
            "GlobalMetrics": global_metrics_df,
            "StratumMetrics": stratum_metrics_df,
        }
    )
