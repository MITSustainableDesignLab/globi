"""XGBoost backend for surrogate training."""

import warnings
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from globi.models.surrogate.backends.base import (
    SurrogateModelBackend,
    TrainedModel,
    TrainingContext,
)


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
            **self.model_dump(exclude_none=True),
        }
        if torch.cuda.is_available():
            params["device"] = "cuda"
        else:
            warnings.warn("CUDA is not available, using CPU.", stacklevel=3)
        return params


class XGBBackend(SurrogateModelBackend):
    """The parameters/backend for the xgboost model."""

    ml_backend: Literal["xgb"] = Field(
        default="xgb", description="The type of model to use."
    )
    hp: XGBModelConfig = Field(
        default_factory=XGBModelConfig,
        description="The hyperparameters for the model.",
    )
    trainer: XGBTrainerConfig = Field(
        default_factory=XGBTrainerConfig,
        description="The trainer hyperparameters for the model.",
    )

    def train(self, context: TrainingContext) -> TrainedModel:
        """Train an xgboost model and write model artifacts."""
        import xgboost as xgb

        prep = context.prepped_data
        train_dmat = xgb.DMatrix(
            prep.transformed.train.x.reset_index(drop=True),
            label=prep.transformed.train.y.reset_index(drop=True),
        )
        test_dmat = xgb.DMatrix(
            prep.transformed.test.x.reset_index(drop=True),
            label=prep.transformed.test.y.reset_index(drop=True),
        )

        evals = [(train_dmat, "train"), (test_dmat, "eval")]
        context.log("Training XGBoost model...")
        model = xgb.train(
            self.hp.param_dict,
            train_dmat,
            num_boost_round=self.trainer.num_boost_round,
            evals=evals,
            early_stopping_rounds=self.trainer.early_stopping_rounds,
            verbose_eval=self.trainer.verbose_eval,
        )
        context.log("Trained XGBoost model.")

        return TrainedModel(
            model_object=model,
            transformers=prep.transformers,
        )

    def save_model(self, model_object: Any, output_dir: Path) -> Path:
        """Serialize an xgboost model."""
        import xgboost as xgb

        if not isinstance(model_object, xgb.Booster):
            msg = f"Expected xgboost Booster, got {type(model_object)}"
            raise TypeError(msg)
        model_path = output_dir / "model.ubj"
        model_object.save_model(model_path.as_posix())
        return model_path

    @classmethod
    def load_model(cls, regressor_path: Path) -> Any:
        """Load an xgboost model from disk."""
        import xgboost as xgb

        model = xgb.Booster()
        model.load_model(regressor_path.as_posix())
        return model

    @classmethod
    def make_raw_predict_fn(cls, model_object: Any):
        """Create the raw xgboost prediction callable."""
        return lambda x, col_order: xgb_pred(x, col_order, model=model_object)


def xgb_pred(x: pd.DataFrame, col_order: list[str], *, model) -> np.ndarray:
    """Predict the targets for encoded features using xgboost."""
    import xgboost as xgb

    if not isinstance(model, xgb.Booster):
        msg = f"Model is not an xgboost model: {type(model)}"
        raise TypeError(msg)

    dmat = xgb.DMatrix(x.reset_index(drop=True))
    return model.predict(dmat)
