"""LightGBM backend for surrogate training."""

import logging
import zipfile
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

logger = logging.getLogger(__name__)


class LGBTrainerConfig(BaseModel):
    """The trainer hyperparameters for the lightgbm model."""

    num_boost_round: int = Field(
        default=4000, description="The number of boosting rounds."
    )
    early_stopping_rounds: int = Field(
        default=20, description="The number of boosting rounds to early stop."
    )


class LGBModelConfig(BaseModel):
    """The model hyperparameters for the lightgbm model."""

    objective: Literal["regression", "binary", "multiclass"] = Field(
        default="regression", description="The objective function to use."
    )
    metric: Literal["rmse"] = Field(
        default="rmse", description="The metric to optimize."
    )
    learning_rate: float = Field(default=0.1, description="The learning rate.")
    num_leaves: int = Field(default=31, description="The number of leaves in the tree.")
    max_depth: int = Field(default=-1, description="The maximum depth of the tree.")

    @property
    def param_dict(self) -> dict[str, Any]:
        """The dictionary of parameters."""
        return self.model_dump(exclude_none=True)


class LGBBackend(SurrogateModelBackend):
    """The parameters/backend for the lightgbm model."""

    ml_backend: Literal["lgb"] = Field(
        default="lgb", description="The type of model to use."
    )
    hp: LGBModelConfig = Field(
        default_factory=LGBModelConfig,
        description="The hyperparameters for the model.",
    )
    trainer: LGBTrainerConfig = Field(
        default_factory=LGBTrainerConfig,
        description="The trainer hyperparameters for the model.",
    )

    def train(self, context: TrainingContext) -> TrainedModel:
        """Train lightgbm models and write model artifacts."""
        import lightgbm as lgb

        prep = context.prepped_data
        col_order = prep.transformers.y.targets
        models: dict[str, lgb.Booster] = {}

        logger.info("Training LightGBM model...")
        for col in col_order:
            lgb_train = lgb.Dataset(
                prep.transformed.train.x,
                prep.transformed.train.y.reset_index(drop=True)[col],
            )
            lgb_test = lgb.Dataset(
                prep.transformed.test.x,
                prep.transformed.test.y.reset_index(drop=True)[col],
            )

            lgb_params = self.hp.param_dict
            # TODO: inspect runtimes
            # if torch.cuda.is_available():
            #     lgb_params["device"] = "gpu"

            model = lgb.train(
                lgb_params,
                lgb_train,
                num_boost_round=self.trainer.num_boost_round,
                valid_sets=[lgb_test],
                valid_names=["eval"],
                callbacks=[lgb.early_stopping(self.trainer.early_stopping_rounds)],
            )
            models[col] = model

        logger.info("Trained LightGBM model.")
        return TrainedModel(
            model_object=models,
            transformers=prep.transformers,
        )

    def save_model(self, model_object: Any, output_dir: Path) -> Path:
        """Serialize lightgbm models as a portable zip archive."""
        import lightgbm as lgb
        import yaml

        if not isinstance(model_object, dict):
            msg = f"Expected dict of lightgbm models, got {type(model_object)}"
            raise TypeError(msg)

        model_root_path = output_dir / "lgb"
        model_root_path.mkdir(parents=True, exist_ok=True)
        model_paths: dict[str, str] = {}
        for col, booster in model_object.items():
            if not isinstance(booster, lgb.Booster):
                msg = f"Model for column {col} is not a Booster: {type(booster)}"
                raise TypeError(msg)
            relative_model_path = Path("models") / f"{col}.lgb"
            model_path = model_root_path / relative_model_path
            model_path.parent.mkdir(parents=True, exist_ok=True)
            booster.save_model(model_path.as_posix())
            model_paths[col] = relative_model_path.as_posix()

        with open(model_root_path / "col_spec.yaml", "w") as f:
            yaml.dump(model_paths, f, indent=2, sort_keys=False)

        model_output_zip_path = output_dir / "model.zip"
        with zipfile.ZipFile(model_output_zip_path, "w") as zipf:
            for path in model_root_path.glob("**/*"):
                if path.is_file():
                    zipf.write(path, path.relative_to(model_root_path))
        return model_output_zip_path

    @classmethod
    def load_model(cls, regressor_path: Path) -> Any:
        """Load lightgbm models from a zip archive."""
        import tempfile

        import lightgbm as lgb
        import yaml

        models: dict[str, lgb.Booster] = {}
        with tempfile.TemporaryDirectory() as tmp:
            extract_root = Path(tmp) / "lgb"
            extract_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(regressor_path, "r") as zipf:
                zipf.extractall(extract_root)

            with open(extract_root / "col_spec.yaml") as f:
                col_spec = yaml.safe_load(f)
            if not isinstance(col_spec, dict):
                msg = f"Expected a dict in col_spec.yaml, got {type(col_spec)}"
                raise TypeError(msg)

            for col, rel_path in col_spec.items():
                model_path = extract_root / Path(str(rel_path))
                models[col] = lgb.Booster(model_file=model_path.as_posix())
        return models

    @classmethod
    def make_raw_predict_fn(cls, model_object: Any):
        """Create the raw lightgbm prediction callable."""
        return lambda x, col_order: lgb_pred(x, col_order, model=model_object)


def lgb_pred(x: pd.DataFrame, col_order: list[str], *, model) -> np.ndarray:
    """Predict the targets for encoded features using lightgbm."""
    import lightgbm as lgb

    if not isinstance(model, dict):
        msg = (
            f"Model is not a dictionary: {type(model)}. "
            "LGB pred expects a dictionary of models per column."
        )
        raise TypeError(msg)

    preds = {}
    for col in col_order:
        booster = model[col]
        if not isinstance(booster, lgb.Booster):
            msg = (
                f"Model for column {col} is not a lightgbm model: {type(booster)}. "
                "LGB pred expects a dictionary of lightgbm models per column."
            )
            raise TypeError(msg)
        preds[col] = booster.predict(x.reset_index(drop=True))
    return np.stack(list(preds.values()), axis=1)
