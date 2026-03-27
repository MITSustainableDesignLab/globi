"""Tests for surrogate feature transforms."""

import pandas as pd

from globi.models.surrogate.transforms import (
    IdentityScaler,
    MinMaxScaler,
    StandardScaler,
    Transformers,
    XTransformer,
    YTransformer,
    encode_inputs,
)


def _base_input_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "cont_a": [1.0, 2.0, 4.0],
        "cont_b": [10.0, 20.0, 40.0],
        "cat": ["x", "y", "x"],
    })


def test_encode_inputs_with_min_max_continuous_encoding() -> None:
    """Continuous features are fit on train and transformed to [0, 1]."""
    x = _base_input_frame()
    conf = XTransformer(
        features=["cont_a", "cont_b", "cat"],
        continuous_features=["cont_a", "cont_b"],
        cont_scaler=MinMaxScaler(),
        cont_encoding="min-max",
        cat_map={"cat": ["x", "y"]},
        cat_encoding="index",
    )

    encoded = encode_inputs(x, conf=conf, fit_continuous=True)

    # continuous ranges should be min-max normalized on train-fit
    assert encoded["cont_a"].tolist() == [0.0, 1.0 / 3.0, 1.0]
    assert encoded["cont_b"].tolist() == [0.0, 1.0 / 3.0, 1.0]
    # categorical feature still encoded
    assert encoded["cat"].tolist() == [0, 1, 0]
    assert conf.cont_scaler.mins_ == {"cont_a": 1.0, "cont_b": 10.0}
    assert conf.cont_scaler.maxs_ == {"cont_a": 4.0, "cont_b": 40.0}


def test_encode_inputs_with_standard_continuous_encoding() -> None:
    """Continuous features can be standardized with standard mode."""
    x = _base_input_frame()
    conf = XTransformer(
        features=["cont_a", "cont_b", "cat"],
        continuous_features=["cont_a", "cont_b"],
        cont_scaler=StandardScaler(),
        cont_encoding="standard",
        cat_map={"cat": ["x", "y"]},
        cat_encoding="index",
    )

    encoded = encode_inputs(x, conf=conf, fit_continuous=True)
    # means are approximately zero after fitting/transforming same frame
    assert abs(float(encoded["cont_a"].mean())) < 1e-12
    assert abs(float(encoded["cont_b"].mean())) < 1e-12
    assert encoded["cat"].tolist() == [0, 1, 0]
    assert conf.cont_scaler.means_ == {"cont_a": 7.0 / 3.0, "cont_b": 70.0 / 3.0}


def test_encode_inputs_applies_fitted_continuous_scaler_to_new_data() -> None:
    """Test frames should use previously fit scaler parameters."""
    train = _base_input_frame()
    test = pd.DataFrame({
        "cont_a": [1.0, 2.5, 4.0],
        "cont_b": [10.0, 25.0, 40.0],
        "cat": ["y", "x", "y"],
    })
    conf = XTransformer(
        features=["cont_a", "cont_b", "cat"],
        continuous_features=["cont_a", "cont_b"],
        cont_scaler=MinMaxScaler(),
        cont_encoding="min-max",
        cat_map={"cat": ["x", "y"]},
        cat_encoding="index",
    )

    _ = encode_inputs(train, conf=conf, fit_continuous=True)
    encoded_test = encode_inputs(test, conf=conf)

    assert encoded_test["cont_a"].tolist() == [0.0, 0.5, 1.0]
    assert encoded_test["cont_b"].tolist() == [0.0, 0.5, 1.0]
    assert encoded_test["cat"].tolist() == [1, 0, 1]


def test_transformers_model_dump_and_validate_keeps_cont_transformer() -> None:
    """Continuous feature transformer is serialized in transforms payload."""
    transformers = Transformers(
        x=XTransformer(
            features=["cont_a", "cat"],
            continuous_features=["cont_a"],
            cont_scaler=MinMaxScaler(mins_={"cont_a": 1.0}, maxs_={"cont_a": 5.0}),
            cont_encoding="min-max",
            cat_map={"cat": ["x", "y"]},
            cat_encoding="one-hot",
        ),
        y=YTransformer(
            scaler=IdentityScaler(),
            targets=["target"],
            normalization=None,
        ),
    )

    dumped = transformers.model_dump(mode="json")
    roundtrip = Transformers.model_validate(dumped)

    assert roundtrip.x.cont_encoding == "min-max"
    assert isinstance(roundtrip.x.cont_scaler, MinMaxScaler)
    assert roundtrip.x.cont_scaler.mins_ == {"cont_a": 1.0}
    assert roundtrip.x.cont_scaler.maxs_ == {"cont_a": 5.0}
