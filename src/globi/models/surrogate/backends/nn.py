"""PyTorch neural network backend for surrogate training."""

import copy
import gc
import logging
import time
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from globi.models.surrogate.backends.base import (
    SurrogateModelBackend,
    TrainedModel,
    TrainingContext,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Activation helpers
# ---------------------------------------------------------------------------

ACTIVATION_REGISTRY: dict[str, type] = {}


def _populate_activation_registry() -> None:
    import torch.nn as nn

    ACTIVATION_REGISTRY.update({
        "relu": nn.ReLU,
        "gelu": nn.GELU,
        "silu": nn.SiLU,
        "tanh": nn.Tanh,
    })


def _get_activation(name: str):
    if not ACTIVATION_REGISTRY:
        _populate_activation_registry()
    cls = ACTIVATION_REGISTRY.get(name)
    if cls is None:
        msg = f"Unknown activation: {name!r}. Choose from {list(ACTIVATION_REGISTRY)}"
        raise ValueError(msg)
    return cls()


# ---------------------------------------------------------------------------
# Model hyper-parameters (architecture)
# ---------------------------------------------------------------------------


class NNModelConfig(BaseModel):
    """Architectural hyperparameters for the MLP surrogate."""

    activation: Literal["relu", "gelu", "silu", "tanh"] = Field(
        default="silu", description="Activation function used in every block."
    )
    layer_norm: bool = Field(
        default=True,
        description="Enable pre-norm LayerNorm in every block.",
    )
    dropout: float | None = Field(
        default=None,
        description="Dropout probability applied in every block. None disables dropout.",
    )
    hidden_dims: list[int] = Field(
        default_factory=lambda: [256, 256, 256, 256],
        description="Width of each hidden layer. Length determines depth.",
    )
    init_batch_norm: bool = Field(
        default=False,
        description="Apply batch normalization to the input features.",
    )
    quadratic_features: bool = Field(
        default=False,
        description="Prepend a quadratic polynomial feature expansion (outer product) to the MLP input.",
    )


# ---------------------------------------------------------------------------
# Optimizer configs (discriminated union)
# ---------------------------------------------------------------------------


class AdamOptimizerConfig(BaseModel):
    """Configuration for the Adam optimizer."""

    optimizer: Literal["adam"] = "adam"
    lr: float = Field(default=1e-4, description="Learning rate.")
    weight_decay: float = Field(default=0.0, description="Weight decay (L2 penalty).")
    betas: tuple[float, float] = Field(
        default=(0.9, 0.999), description="Adam beta coefficients."
    )

    def build(self, params):
        """Instantiate an Adam optimizer for the given parameters."""
        import torch.optim as optim

        return optim.Adam(
            params, lr=self.lr, weight_decay=self.weight_decay, betas=self.betas
        )


class SGDOptimizerConfig(BaseModel):
    """Configuration for the SGD optimizer."""

    optimizer: Literal["sgd"] = "sgd"
    lr: float = Field(default=1e-2, description="Learning rate.")
    momentum: float = Field(default=0.9, description="Momentum factor.")
    weight_decay: float = Field(default=0.0, description="Weight decay (L2 penalty).")

    def build(self, params):
        """Instantiate an SGD optimizer for the given parameters."""
        import torch.optim as optim

        return optim.SGD(
            params, lr=self.lr, momentum=self.momentum, weight_decay=self.weight_decay
        )


OptimizerConfig = Annotated[
    AdamOptimizerConfig | SGDOptimizerConfig,
    Field(discriminator="optimizer"),
]

# ---------------------------------------------------------------------------
# LR scheduler configs (discriminated union)
# ---------------------------------------------------------------------------


class CosineAnnealingSchedulerConfig(BaseModel):
    """Configuration for CosineAnnealingLR."""

    scheduler: Literal["cosine_annealing"] = "cosine_annealing"
    T_max: int | None = Field(
        default=None, description="Max iterations. Defaults to n_epochs at runtime."
    )
    eta_min: float = Field(default=0, description="Minimum learning rate.")

    def build(self, optimizer, *, n_epochs: int):
        """Instantiate a CosineAnnealingLR scheduler."""
        import torch.optim.lr_scheduler as lr_scheduler

        return lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=self.T_max if self.T_max is not None else n_epochs,
            eta_min=self.eta_min,
        )


class StepSchedulerConfig(BaseModel):
    """Configuration for StepLR."""

    scheduler: Literal["step"] = "step"
    step_size: int = Field(default=50, description="Period of learning rate decay.")
    gamma: float = Field(default=0.5, description="Multiplicative decay factor.")

    def build(self, optimizer, *, n_epochs: int):
        """Instantiate a StepLR scheduler."""
        import torch.optim.lr_scheduler as lr_scheduler

        return lr_scheduler.StepLR(
            optimizer, step_size=self.step_size, gamma=self.gamma
        )


class NoSchedulerConfig(BaseModel):
    """Placeholder that disables LR scheduling."""

    scheduler: Literal["none"] = "none"

    def build(self, optimizer, *, n_epochs: int):
        """Return None (no scheduler)."""
        return None


SchedulerConfig = Annotated[
    CosineAnnealingSchedulerConfig | StepSchedulerConfig | NoSchedulerConfig,
    Field(discriminator="scheduler"),
]

# ---------------------------------------------------------------------------
# Trainer hyper-parameters
# ---------------------------------------------------------------------------


class NNTrainerConfig(BaseModel):
    """Training hyper-parameters for the neural network backend."""

    epochs: int = Field(default=4000, description="Maximum number of training epochs.")
    batch_size: int = Field(default=256, description="Mini-batch size.")
    early_stopping_patience: int | None = Field(
        default=20,
        description="Epochs without validation improvement before stopping. None disables early stopping.",
    )
    early_stopping_min_delta: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Minimum validation loss decrease vs the previous best to count as an improvement "
            "for early stopping. Zero means any strictly lower validation loss resets patience."
        ),
    )
    l1_penalty: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "L1 regularization strength: added to the training loss as penalty times the sum of "
            "|theta| over all model parameters. Zero disables. L2-style weight decay remains "
            "on the optimizer via weight_decay."
        ),
    )
    max_training_minutes: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "If set, stop training when elapsed monotonic time since the start of the first "
            "training batch reaches this many minutes. None disables the limit. A partial epoch "
            "is discarded (no validation for that epoch)."
        ),
    )
    optimizer: OptimizerConfig = Field(
        default_factory=AdamOptimizerConfig,
        description="Optimizer configuration.",
    )
    scheduler: SchedulerConfig = Field(
        default_factory=CosineAnnealingSchedulerConfig,
        description="Learning rate scheduler configuration.",
    )


def _trainable_weight_l1(model: Any) -> Any:
    """Sum of |theta| over trainable parameters (scalar tensor)."""
    return sum(p.abs().sum() for p in model.parameters() if p.requires_grad)


# ---------------------------------------------------------------------------
# PyTorch modules
# ---------------------------------------------------------------------------


class ResidualMLPBlock:
    """A single residual MLP block.

    Instantiated as an ``nn.Module`` at runtime so that ``torch`` is only
    imported when actually needed.
    """

    @staticmethod
    def create(
        in_dim: int,
        out_dim: int,
        *,
        activation: str,
        layer_norm: bool,
        dropout: float | None,
    ):
        """Build and return an ``nn.Module`` implementing one residual block."""
        import torch
        import torch.nn as nn

        class _Block(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.norm = nn.LayerNorm(in_dim) if layer_norm else nn.Identity()
                self.fc = nn.Linear(in_dim, out_dim)
                self.act = _get_activation(activation)
                self.drop = (
                    nn.Dropout(dropout) if dropout is not None else nn.Identity()
                )
                self.skip_proj = (
                    nn.Linear(in_dim, out_dim) if in_dim != out_dim else nn.Identity()
                )

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                residual = self.skip_proj(x)
                h = self.norm(x)
                h = self.fc(h)
                h = self.act(h)
                h = self.drop(h)
                return residual + h

        return _Block()


class SurrogateMLP:
    """Factory for the full MLP ``nn.Module``.

    Wrapping the ``nn.Module`` in a factory avoids a module-level ``torch``
    import, matching the lazy-import pattern of the other backends.
    """

    @staticmethod
    def from_config(
        n_features: int,
        n_outputs: int,
        config: NNModelConfig,
    ):
        """Construct the MLP from architectural config and runtime dimensions."""
        import torch
        import torch.nn as nn

        use_quad = config.quadratic_features
        init_batch_norm = config.init_batch_norm
        effective_input_dim = n_features**2 if use_quad else n_features
        dims = [effective_input_dim, *config.hidden_dims]

        class _MLP(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.quadratic_features = use_quad
                self.init_batch_norm = init_batch_norm
                self.bn = (
                    nn.BatchNorm1d(effective_input_dim)
                    if init_batch_norm
                    else nn.Identity()
                )
                blocks: list[nn.Module] = []
                for i in range(len(dims) - 1):
                    blocks.append(
                        ResidualMLPBlock.create(
                            dims[i],
                            dims[i + 1],
                            activation=config.activation,
                            layer_norm=config.layer_norm,
                            dropout=config.dropout,
                        )
                    )
                self.blocks = nn.Sequential(*blocks) if blocks else nn.Identity()
                self.head = nn.Linear(dims[-1], n_outputs)
                self.n_features = n_features
                self.n_outputs = n_outputs

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                if self.quadratic_features:
                    x = (x.unsqueeze(-1) * x.unsqueeze(-2)).flatten(start_dim=-2)
                x = self.bn(x)
                return self.head(self.blocks(x))

        return _MLP()


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class NNBackend(SurrogateModelBackend):
    """PyTorch MLP backend for surrogate model training."""

    ml_backend: Literal["nn"] = Field(
        default="nn", description="The type of model to use."
    )
    hp: NNModelConfig = Field(
        default_factory=NNModelConfig,
        description="The architectural hyperparameters for the model.",
    )
    trainer: NNTrainerConfig = Field(
        default_factory=NNTrainerConfig,
        description="The training hyperparameters for the model.",
    )

    # ----- training --------------------------------------------------------

    def _batch_training_loss(self, model: Any, pred: Any, yb: Any, loss_fn: Any) -> Any:
        """MSE plus optional L1 penalty on trainable weights."""
        loss = loss_fn(pred, yb)
        l1_lambda = self.trainer.l1_penalty
        if l1_lambda > 0.0:
            loss = loss + l1_lambda * _trainable_weight_l1(model)
        return loss

    def _train_epoch_batches(
        self,
        model: Any,
        train_loader: Any,
        device: Any,
        optimizer: Any,
        loss_fn: Any,
        *,
        training_start_mono: float | None,
        max_seconds: float | None,
    ) -> tuple[float, int, bool, float | None]:
        """Run one epoch of training batches; optional wall-time cap from first batch start."""
        train_loss_accum = 0.0
        n_train_batches = 0
        timed_out = False
        for xb, yb in train_loader:
            if training_start_mono is None:
                training_start_mono = time.monotonic()
            elif (
                max_seconds is not None
                and (time.monotonic() - training_start_mono) >= max_seconds
            ):
                timed_out = True
                break
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            pred = model(xb)
            loss = self._batch_training_loss(model, pred, yb, loss_fn)
            loss.backward()
            optimizer.step()
            train_loss_accum += loss.item()
            n_train_batches += 1
        return train_loss_accum, n_train_batches, timed_out, training_start_mono

    def train(self, context: TrainingContext) -> TrainedModel:
        """Train a PyTorch MLP and return the best model."""
        import torch
        from torch.utils.data import DataLoader, TensorDataset

        prep = context.prepped_data

        x_train_np = prep.transformed.train.x.reset_index(drop=True).to_numpy(
            dtype=np.float32
        )
        y_train_np = prep.transformed.train.y.reset_index(drop=True).to_numpy(
            dtype=np.float32
        )
        x_val_np = prep.transformed.test.x.reset_index(drop=True).to_numpy(
            dtype=np.float32
        )
        y_val_np = prep.transformed.test.y.reset_index(drop=True).to_numpy(
            dtype=np.float32
        )

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if not torch.cuda.is_available():
            warnings.warn("CUDA is not available, using CPU.", stacklevel=2)

        n_features = x_train_np.shape[1]
        n_outputs = y_train_np.shape[1]

        model = SurrogateMLP.from_config(n_features, n_outputs, self.hp)
        model = model.to(device)

        train_ds = TensorDataset(
            torch.from_numpy(x_train_np), torch.from_numpy(y_train_np)
        )
        val_ds = TensorDataset(torch.from_numpy(x_val_np), torch.from_numpy(y_val_np))
        train_loader = DataLoader(
            train_ds, batch_size=self.trainer.batch_size, shuffle=True, drop_last=True
        )
        val_loader = DataLoader(
            val_ds, batch_size=self.trainer.batch_size, shuffle=False, drop_last=True
        )

        optimizer = self.trainer.optimizer.build(model.parameters())
        lr_scheduler = self.trainer.scheduler.build(
            optimizer, n_epochs=self.trainer.epochs
        )

        loss_fn = torch.nn.MSELoss()

        best_val_loss = float("inf")
        best_state: dict[str, Any] = {}
        epochs_without_improvement = 0

        logger.info(
            f"Training NN ({n_features} -> {self.hp.hidden_dims} -> {n_outputs}) on {device}..."
        )

        train_loss_history = []
        val_loss_history = []
        max_minutes = self.trainer.max_training_minutes
        max_seconds = max_minutes * 60.0 if max_minutes is not None else None
        training_start_mono: float | None = None

        for epoch in range(self.trainer.epochs):
            # --- train -------------------------------------------------
            model.train()
            (
                train_loss_accum,
                n_train_batches,
                timed_out,
                training_start_mono,
            ) = self._train_epoch_batches(
                model,
                train_loader,
                device,
                optimizer,
                loss_fn,
                training_start_mono=training_start_mono,
                max_seconds=max_seconds,
            )

            if timed_out:
                logger.info(
                    f"  Stopping at epoch {epoch} "
                    f"(max training time {max_minutes} minutes elapsed)."
                )
                break

            # --- validate ----------------------------------------------
            model.eval()
            val_loss_accum = 0.0
            n_val_batches = 0
            with torch.no_grad():
                for xb, yb in val_loader:
                    xb, yb = xb.to(device), yb.to(device)
                    val_loss_accum += loss_fn(model(xb), yb).item()
                    n_val_batches += 1

            avg_train = train_loss_accum / max(n_train_batches, 1)
            avg_val = val_loss_accum / max(n_val_batches, 1)
            train_loss_history.append(avg_train)
            val_loss_history.append(avg_val)

            if lr_scheduler is not None:
                lr_scheduler.step()

            min_delta = self.trainer.early_stopping_min_delta
            if avg_val < best_val_loss - min_delta:
                best_val_loss = avg_val
                best_state = copy.deepcopy(model.state_dict())
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1

            print_every_n = 10
            if epoch % print_every_n == 0 or epoch == self.trainer.epochs - 1:
                last_n_train = train_loss_history[-print_every_n:]
                last_n_val = val_loss_history[-print_every_n:]
                avg_last_n_train = sum(last_n_train) / len(last_n_train)
                avg_last_n_val = sum(last_n_val) / len(last_n_val)
                logger.info(
                    f"  Epoch {epoch:>4d}/{self.trainer.epochs}  "
                    f"train_mse={avg_last_n_train:.6f}  val_mse={avg_last_n_val:.6f}  "
                    f"best_val={best_val_loss:.6f}"
                )

            if (
                self.trainer.early_stopping_patience is not None
                and epochs_without_improvement >= self.trainer.early_stopping_patience
            ):
                logger.info(
                    f"  Early stopping at epoch {epoch} "
                    f"(no improvement for {self.trainer.early_stopping_patience} epochs)."
                )
                break

        if best_state:
            model.load_state_dict(best_state)
        model.eval()
        logger.info("Trained NN model.")
        # clean up some gpu memory by deleting tensors and so on
        del train_ds, val_ds, train_loader, val_loader
        gc.collect()
        torch.cuda.empty_cache()

        return TrainedModel(
            model_object=model,
            transformers=prep.transformers,
        )

    # ----- serialization ---------------------------------------------------

    def save_model(self, model_object: Any, output_dir: Path) -> Path:
        """Serialize the MLP checkpoint (weights + architecture metadata)."""
        import torch

        model_path = output_dir / "model.pt"
        torch.save(
            {
                "state_dict": model_object.state_dict(),
                "n_features": model_object.n_features,
                "n_outputs": model_object.n_outputs,
                "model_config": self.hp.model_dump(mode="json"),
            },
            model_path,
        )
        return model_path

    @classmethod
    def load_model(cls, regressor_path: Path) -> Any:
        """Load a checkpoint dict from disk."""
        import torch

        return torch.load(regressor_path, map_location="cpu", weights_only=False)

    @classmethod
    def make_raw_predict_fn(
        cls,
        model_object: Any,
    ) -> Callable[[pd.DataFrame, list[str]], np.ndarray]:
        """Create the raw NN prediction callable."""
        import torch
        from torch.utils.data import DataLoader, TensorDataset

        if isinstance(model_object, dict):
            config = NNModelConfig(**model_object["model_config"])
            n_features: int = model_object["n_features"]
            n_outputs: int = model_object["n_outputs"]
            model = SurrogateMLP.from_config(n_features, n_outputs, config)
            model.load_state_dict(model_object["state_dict"])
        else:
            model = model_object

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)
        model.eval()

        def _predict(x: pd.DataFrame, col_order: list[str]) -> np.ndarray:
            batch_size = 1024
            dataloader = DataLoader(
                TensorDataset(
                    torch.from_numpy(
                        x.reset_index(drop=True).to_numpy(dtype=np.float32)
                    ),
                ),
                batch_size=batch_size,
                shuffle=False,
            )
            preds = []
            with torch.no_grad():
                for (xb,) in dataloader:
                    xb = xb.to(device)
                    pred = model(xb)
                    preds.append(pred.cpu().numpy())
            return np.concatenate(preds, axis=0)

        return _predict
