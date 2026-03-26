"""Tests for the neural-network surrogate backend."""

import warnings

import numpy as np
import pandas as pd
import torch

from globi.models.surrogate.backends.nn import (
    NNBackend,
    NNModelConfig,
    ResidualMLPBlock,
)


def test_nn_model_config_accepts_legacy_skip_mode() -> None:
    """Legacy ``skip_mode`` config keys should be accepted and ignored."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = NNModelConfig(skip_mode="post_activation")

    assert "skip_mode" not in config.model_dump()
    assert any("skip_mode is deprecated and ignored" in str(w.message) for w in caught)


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


def test_make_raw_predict_fn_accepts_legacy_checkpoint_config() -> None:
    """Raw prediction loading should remain backward-compatible with old checkpoints."""
    config = NNModelConfig(hidden_dims=[8], layer_norm=True, dropout=None)

    from globi.models.surrogate.backends.nn import SurrogateMLP

    net = SurrogateMLP.from_config(n_features=3, n_outputs=2, config=config)
    legacy_checkpoint = {
        "state_dict": net.state_dict(),
        "n_features": 3,
        "n_outputs": 2,
        "model_config": {
            **config.model_dump(mode="json"),
            "skip_mode": "post_activation",
        },
    }

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        pred_fn = NNBackend.make_raw_predict_fn(legacy_checkpoint)

    x = pd.DataFrame(np.random.rand(4, 3).astype(np.float32), columns=["a", "b", "c"])
    y = pred_fn(x, ["a", "b", "c"])

    assert y.shape == (4, 2)
    assert any("skip_mode is deprecated and ignored" in str(w.message) for w in caught)
