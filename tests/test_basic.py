"""Basic tests for globi package."""


def test_foo():
    """A simple test to allow ci/cd tk complete."""
    pass


def test_normalized_mean_bias_error_uses_mean_true_denominator() -> None:
    """NMBE equals mean residual divided by mean target."""
    import pandas as pd

    from globi.models.surrogate.metrics import normalized_mean_bias_error

    targets = pd.DataFrame({
        "t1": [10.0, 20.0, 30.0],
        "t2": [5.0, 5.0, 5.0],
    })
    preds = pd.DataFrame({
        "t1": [11.0, 19.0, 31.0],
        "t2": [4.0, 5.0, 6.0],
    })

    nmbe = normalized_mean_bias_error(preds=preds, targets=targets)

    # t1 residuals: [-1, 1, -1], mean=-1/3; mean_true=20 => -1/60
    # t2 residuals: [1, 0, -1], mean=0; mean_true=5 => 0
    assert nmbe.tolist() == [-1.0 / 60.0, 0.0]


def test_normalized_mean_bias_error_uses_one_when_mean_true_is_zero() -> None:
    """NMBE falls back to MBE when mean true is zero."""
    import pandas as pd

    from globi.models.surrogate.metrics import normalized_mean_bias_error

    targets = pd.DataFrame({"t0": [1.0, -1.0]})
    preds = pd.DataFrame({"t0": [0.0, -2.0]})

    nmbe = normalized_mean_bias_error(preds=preds, targets=targets)

    # residuals: [1, 1], mean=1; mean_true=0 so denominator is 1
    assert nmbe.tolist() == [1.0]
