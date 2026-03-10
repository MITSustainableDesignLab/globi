"""Configs for the surrogate model pipeline."""

import warnings
from typing import Any, Literal

from pydantic import BaseModel, Field


class XGBTrainerConfig(BaseModel):
    """The trainer hyperparameters for the xgboost model."""

    num_boost_round: int = Field(
        default=4000, description="The number of boosting rounds."
    )
    early_stopping_rounds: int = Field(
        default=10, description="The number of boosting rounds to early stop."
    )
    verbose_eval: bool = Field(
        default=True, description="Whether to print verbose evaluation results."
    )


class XGBModelConfig(BaseModel):
    """The model hyperparameters for the xgboost model."""

    max_depth: int = Field(default=5, description="The maximum depth of the tree.")
    eta: float = Field(default=0.1, description="The learning rate.")
    min_child_weight: int | None = Field(
        default=3, description="The minimum child weight."
    )
    subsample: float | None = Field(default=None, description="The subsample rate.")
    colsample_bytree: float | None = Field(
        default=None, description="The column sample by tree rate."
    )
    alpha: float | None = Field(default=None, description="The alpha parameter.")
    lam: float | None = Field(default=None, description="The lambda parameter.")
    gamma: float | None = Field(default=None, description="The gamma parameter.")
    seed: int = Field(
        default=42, description="The seed for the random number generator."
    )

    @property
    def param_dict(self) -> dict[str, Any]:
        """The dictionary of parameters."""
        import torch

        params = {
            "objective": "reg:squarederror",
            "eval_metric": "rmse",
            "tree_method": "auto",
            "seed": self.seed,
            # hyperparameters
            **self.model_dump(
                exclude_none=True,
            ),
        }
        if torch.cuda.is_available():
            params["device"] = "cuda"
        else:
            warnings.warn("CUDA is not available, using CPU.", stacklevel=3)
        return params


class XGBHyperparameters(BaseModel):
    """The parameters for the xgboost model."""

    hp: XGBModelConfig = Field(
        default_factory=XGBModelConfig,
        description="The hyperparameters for the model.",
    )
    trainer: XGBTrainerConfig = Field(
        default_factory=XGBTrainerConfig,
        description="The trainer hyperparameters for the model.",
    )


class LGBHyperparameters(BaseModel):
    """The parameters for the lightgbm model."""

    objective: Literal["regression", "binary", "multiclass"] = Field(
        default="regression", description="The objective function to use."
    )
    metric: Literal["rmse"] = Field(
        default="rmse", description="The metric to optimize."
    )
    # TODO: add other parameters as needed


ModelHPType = XGBHyperparameters | LGBHyperparameters
