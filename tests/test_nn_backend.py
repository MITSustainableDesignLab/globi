"""Tests for the neural-network surrogate backend."""

import numpy as np
import pandas as pd
import pytest
import torch

from globi.models.surrogate.backends.nn import (
    NNBackend,
    NNModelConfig,
    ResidualMLPBlock,
    SurrogateMLP,
)


def test_nn_model_config_rejects_unknown_skip_mode_field() -> None:
    """Unknown config fields should be rejected (no skip_mode compatibility shim)."""
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        NNModelConfig(skip_mode="post_activation")


def test_residual_block_uses_fixed_pre_norm_formulation() -> None:
    """Residual block should compute skip + dropout(activation(linear(norm(x))))."""
    torch.manual_seed(0)
    block = ResidualMLPBlock.create(
        in_dim=3,
        out_dim=4,
        activation="tanh",
        layer_norm=True,
        dropout=None,
    )
    x = torch.randn(5, 3)

    with torch.no_grad():
        expected = block.skip_proj(x) + block.drop(
            block.act(block.linear(block.norm(x)))
        )
        actual = block(x)

    assert torch.allclose(actual, expected)


def test_make_raw_predict_fn_with_strict_current_checkpoint_config() -> None:
    """Raw prediction loading should work with strict current config shape."""
    config = NNModelConfig(hidden_dims=[8], layer_norm=True, dropout=None)

    net = SurrogateMLP.from_config(n_features=3, n_outputs=2, config=config)
    checkpoint = {
        "state_dict": net.state_dict(),
        "n_features": 3,
        "n_outputs": 2,
        "model_config": config.model_dump(mode="json"),
    }

    pred_fn = NNBackend.make_raw_predict_fn(checkpoint)

    x = pd.DataFrame(np.random.rand(4, 3).astype(np.float32), columns=["a", "b", "c"])
    y = pred_fn(x, ["a", "b", "c"])

    assert y.shape == (4, 2)
