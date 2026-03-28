"""Shared transform and prediction utilities for surrogate models."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataPair:
    """A pair of dataframes."""

    x: pd.DataFrame
    y: pd.DataFrame


@dataclass(frozen=True)
class TrainTestPair:
    """A pair of train and test dataframes."""

    train: DataPair
    test: DataPair


class MinMaxScaler(BaseModel, arbitrary_types_allowed=True):
    """The configuration for a min-max scaler."""

    mins_: dict[str, float] = Field(default_factory=dict)
    maxs_: dict[str, float] = Field(default_factory=dict)

    @property
    def mins(self) -> pd.Series:
        """The mins."""
        return pd.Series(self.mins_, name="mins", dtype=float)

    @property
    def maxs(self) -> pd.Series:
        """The maxs."""
        return pd.Series(self.maxs_, name="maxs", dtype=float)

    def fit(self, y: pd.DataFrame) -> None:
        """Fit the min-max scaler."""
        y_min = cast(pd.Series, y.min(axis=0))
        y_max = cast(pd.Series, y.max(axis=0))
        self.mins_ = y_min.to_dict()
        self.maxs_ = y_max.to_dict()

    @property
    def scale(self) -> pd.Series:
        """The scale."""
        scale = self.maxs - self.mins
        scale = scale.where(scale != 0, self.mins)
        scale = scale.where(scale != 0, 1)
        return scale

    def transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Transform the data."""
        return (y - self.mins) / self.scale

    def fit_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Fit and transform the data."""
        self.fit(y)
        return self.transform(y)

    def inverse_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Inverse transform the data."""
        return y * self.scale + self.mins


class StandardScaler(BaseModel, arbitrary_types_allowed=True):
    """The configuration for a standard scaler."""

    means_: dict[str, float] = Field(default_factory=dict)
    stds_: dict[str, float] = Field(default_factory=dict)

    @property
    def means(self) -> pd.Series:
        """The means."""
        return pd.Series(self.means_, name="means", dtype=float)

    @property
    def stds(self) -> pd.Series:
        """The stds."""
        return pd.Series(self.stds_, name="stds", dtype=float)

    def fit(self, y: pd.DataFrame) -> None:
        """Fit the standard scaler."""
        y_mean = cast(pd.Series, y.mean(axis=0))
        y_std = cast(pd.Series, y.std(axis=0))
        y_std = y_std.where(y_std != 0, 1)
        self.means_ = y_mean.to_dict()
        self.stds_ = y_std.to_dict()

    def transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Transform the data."""
        return (y - self.means) / self.stds

    def fit_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Fit and transform the data."""
        self.fit(y)
        return self.transform(y)

    def inverse_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Inverse transform the data."""
        return y * self.stds + self.means


class IdentityScaler(BaseModel, frozen=True):
    """A scaler that does nothing."""

    def fit(self, y: pd.DataFrame) -> None:
        """Fit the identity scaler."""

    def transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Transform the data."""
        return y

    def fit_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Fit and transform the data."""
        self.fit(y)
        return self.transform(y)

    def inverse_transform(self, y: pd.DataFrame) -> pd.DataFrame:
        """Inverse transform the data."""
        return y


class XTransformer(BaseModel, arbitrary_types_allowed=True, frozen=True):
    """A transformer for the x features."""

    features: list[str]
    continuous_features: list[str] = Field(default_factory=list)
    cont_scaler: MinMaxScaler | StandardScaler | IdentityScaler = Field(
        default_factory=IdentityScaler
    )
    cont_encoding: Literal["min-max", "standard"] | None
    cat_map: dict[str, list[str | float | int]]
    cat_encoding: Literal["index", "one-hot"]


class YTransformer(BaseModel, arbitrary_types_allowed=True, frozen=True):
    """A transformer for the y features."""

    scaler: MinMaxScaler | StandardScaler | IdentityScaler
    targets: list[str]
    normalization: Literal["min-max", "standard"] | None


class Transformers(BaseModel, frozen=True):
    """A pair of transformers."""

    x: XTransformer
    y: YTransformer


@dataclass(frozen=True)
class PrepDataResult:
    """The result of preparing the data."""

    selected: TrainTestPair
    transformed: TrainTestPair
    transformers: Transformers


def index_encode_categorical_columns(
    df: pd.DataFrame, *, cats: dict[str, list[str | float | int]]
) -> pd.DataFrame:
    """Index encode the categorical columns."""
    df = df.copy(deep=True)
    for col in cats:
        if col not in df.columns:
            msg = f"Column {col} not found in dataframe."
            raise ValueError(msg)
        df[col] = pd.Categorical(df[col], categories=cats[col]).codes
    return df


def one_hot_encode_categorical_columns(
    df: pd.DataFrame, *, cats: dict[str, list[str | float | int]]
) -> pd.DataFrame:
    """One-hot encode the categorical columns."""
    new_df = df.copy(deep=True)
    col_blocks: list[pd.DataFrame] = []
    regular_col_names = [c for c in new_df.columns if c not in cats]
    col_blocks.append(new_df.loc[:, regular_col_names])
    for col in cats:
        if col not in df.columns:
            msg = f"Column {col} not found in dataframe."
            raise ValueError(msg)
        onehot_block = pd.get_dummies(
            pd.Categorical(df[col], categories=cats[col]), prefix=col, prefix_sep="."
        ).astype(float)
        col_blocks.append(onehot_block)
    new_df = pd.concat(col_blocks, axis=1)

    return new_df


def scale_continuous_columns(
    df: pd.DataFrame,
    *,
    continuous_features: list[str],
    scaler: MinMaxScaler | StandardScaler | IdentityScaler,
) -> pd.DataFrame:
    """Scale the continuous columns."""
    if not continuous_features:
        return df
    missing_cols = [col for col in continuous_features if col not in df.columns]
    if missing_cols:
        msg = f"Continuous columns not found in dataframe: {missing_cols}."
        raise ValueError(msg)
    df = df.copy(deep=True)
    continuous_df = cast(pd.DataFrame, df.loc[:, continuous_features])
    scaled_continuous_df = scaler.transform(continuous_df)
    df.loc[:, continuous_features] = scaled_continuous_df.astype(float)
    return df


def encode_inputs(
    x: pd.DataFrame,
    *,
    conf: XTransformer,
    fit_continuous: bool = False,
    log: Callable[[str], None] = lambda x: logger.info(x),
) -> pd.DataFrame:
    """Encode the inputs."""
    log(f"Selecting {len(conf.features)} features out of {len(x.columns)}...")
    x_encoded = x.loc[:, conf.features]
    log("Selected features.")

    log(
        f"Encoding {len(conf.continuous_features)} continuous inputs with "
        f"{conf.cont_encoding} encoding..."
    )
    if fit_continuous and conf.continuous_features:
        conf.cont_scaler.fit(
            cast(pd.DataFrame, x_encoded.loc[:, conf.continuous_features])
        )
    x_encoded = scale_continuous_columns(
        x_encoded,
        continuous_features=conf.continuous_features,
        scaler=conf.cont_scaler,
    )
    log("Encoded continuous inputs.")

    log(f"Encoding categorical inputs with {conf.cat_encoding} encoding...")
    if conf.cat_encoding == "index":
        x_encoded = index_encode_categorical_columns(x_encoded, cats=conf.cat_map)
    elif conf.cat_encoding == "one-hot":
        x_encoded = one_hot_encode_categorical_columns(x_encoded, cats=conf.cat_map)
    else:
        raise NotImplementedError(
            f"Unsupported categorical encoding: {conf.cat_encoding}"
        )
    log("Encoded inputs.")
    return x_encoded.set_index(pd.MultiIndex.from_frame(x))


def predict[T: pd.DataFrame | np.ndarray](
    x: pd.DataFrame,
    *,
    conf: Transformers,
    pred_fn: Callable[[pd.DataFrame, list[str]], T],
) -> pd.DataFrame:
    """Predict the targets for the given features."""
    x_encoded = encode_inputs(
        x,
        conf=conf.x,
    )
    preds = pred_fn(x_encoded.reset_index(drop=True), conf.y.targets)
    preds = pd.DataFrame(preds, columns=pd.Index(conf.y.targets), index=x_encoded.index)
    if conf.y.scaler:
        preds = conf.y.scaler.inverse_transform(preds)
    return preds
