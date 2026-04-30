"""Smoke tests for conditional prior sampling behavior.

Run with:
    python scripts/test_conditional_priors.py
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd

from globi.models.surrogate.samplers import (
    ConditionalPrior,
    ConditionalPriorCondition,
    CopySampler,
    MultiColumnCondition,
    MultiColumnConditionalPrior,
    SamplingError,
)


def _require(condition: bool, message: str) -> None:
    """Raise AssertionError with message when condition is not met."""
    if not condition:
        raise AssertionError(message)


def _track_copy_sampler_calls(
    prior: Any, context: pd.DataFrame
) -> list[dict[str, Any]]:
    """Execute prior.sample while recording CopySampler call metadata."""
    calls: list[dict[str, Any]] = []
    original_sample = CopySampler.sample

    def tracking_sample(
        self: CopySampler,
        subset_context: pd.DataFrame,
        n: int,
        generator: np.random.Generator,
    ) -> np.ndarray:
        calls.append({
            "feature_to_copy": self.feature_to_copy,
            "n": n,
            "rows": len(subset_context),
            "kind_values": tuple(subset_context["kind"].tolist()),
            "stage_values": tuple(subset_context["stage"].tolist()),
        })
        return original_sample(self, subset_context, n, generator)

    with patch.object(
        CopySampler, "sample", autospec=True, side_effect=tracking_sample
    ):
        _ = prior.sample(context, len(context), np.random.default_rng(0))

    return calls


def _single_call(calls: list[dict[str, Any]], feature_to_copy: str) -> dict[str, Any]:
    matching_calls = [c for c in calls if c["feature_to_copy"] == feature_to_copy]
    _require(
        len(matching_calls) == 1,
        f"Expected exactly one call for {feature_to_copy}, got {len(matching_calls)}",
    )
    return matching_calls[0]


def test_conditional_prior_subset_sampling() -> None:
    """ConditionalPrior samples only matched rows for each condition."""
    context = pd.DataFrame({
        "kind": ["A", "A", "B", "C", "B", "A"],
        "stage": [1, 1, 2, 3, 2, 1],
        "value_for_a": [10, 11, 12, 13, 14, 15],
        "value_for_b": [20, 21, 22, 23, 24, 25],
        "value_fallback": [30, 31, 32, 33, 34, 35],
    })

    prior = ConditionalPrior(
        source_feature="kind",
        conditions=[
            ConditionalPriorCondition(
                match_val="A", sampler=CopySampler(feature_to_copy="value_for_a")
            ),
            ConditionalPriorCondition(
                match_val="B", sampler=CopySampler(feature_to_copy="value_for_b")
            ),
        ],
        fallback_prior=CopySampler(feature_to_copy="value_fallback"),
    )

    out = prior.sample(context, len(context), np.random.default_rng(42))
    expected = np.array([10, 11, 22, 33, 24, 15])
    _require(np.array_equal(out, expected), f"Unexpected output: {out}")

    calls = _track_copy_sampler_calls(prior, context)
    call_a = _single_call(calls, "value_for_a")
    call_b = _single_call(calls, "value_for_b")
    call_fallback = _single_call(calls, "value_fallback")

    _require(
        call_a["n"] == 3 and call_a["rows"] == 3, "Expected A sampler to get 3 rows"
    )
    _require(
        call_b["n"] == 2 and call_b["rows"] == 2, "Expected B sampler to get 2 rows"
    )
    _require(
        call_fallback["n"] == 1 and call_fallback["rows"] == 1,
        "Expected fallback sampler to get 1 row",
    )
    _require(set(call_a["kind_values"]) == {"A"}, "A sampler saw unexpected kinds")
    _require(set(call_b["kind_values"]) == {"B"}, "B sampler saw unexpected kinds")
    _require(
        set(call_fallback["kind_values"]) == {"C"},
        "Fallback sampler saw unexpected kinds",
    )


def test_multicolumn_conditional_prior_subset_sampling() -> None:
    """MultiColumnConditionalPrior samples only matched tuples per condition."""
    context = pd.DataFrame({
        "kind": ["A", "A", "B", "C", "B", "A", "B"],
        "stage": [1, 2, 2, 3, 2, 1, 1],
        "value_for_a1": [100, 101, 102, 103, 104, 105, 106],
        "value_for_b2": [200, 201, 202, 203, 204, 205, 206],
        "value_fallback": [300, 301, 302, 303, 304, 305, 306],
    })

    prior = MultiColumnConditionalPrior(
        source_features=["kind", "stage"],
        conditions=[
            MultiColumnCondition(
                match_vals=("A", 1), sampler=CopySampler(feature_to_copy="value_for_a1")
            ),
            MultiColumnCondition(
                match_vals=("B", 2), sampler=CopySampler(feature_to_copy="value_for_b2")
            ),
        ],
        fallback_prior=CopySampler(feature_to_copy="value_fallback"),
    )

    out = prior.sample(context, len(context), np.random.default_rng(123))
    expected = np.array([100, 301, 202, 303, 204, 105, 306])
    _require(np.array_equal(out, expected), f"Unexpected output: {out}")

    calls = _track_copy_sampler_calls(prior, context)
    call_a1 = _single_call(calls, "value_for_a1")
    call_b2 = _single_call(calls, "value_for_b2")
    call_fallback = _single_call(calls, "value_fallback")

    _require(
        call_a1["n"] == 2 and call_a1["rows"] == 2,
        "Expected (A,1) sampler to get 2 rows",
    )
    _require(
        call_b2["n"] == 2 and call_b2["rows"] == 2,
        "Expected (B,2) sampler to get 2 rows",
    )
    _require(
        call_fallback["n"] == 3 and call_fallback["rows"] == 3,
        "Expected multi fallback sampler to get 3 rows",
    )
    _require(
        set(zip(call_a1["kind_values"], call_a1["stage_values"], strict=True))
        == {("A", 1)},
        "(A,1) sampler saw unexpected tuples",
    )
    _require(
        set(zip(call_b2["kind_values"], call_b2["stage_values"], strict=True))
        == {("B", 2)},
        "(B,2) sampler saw unexpected tuples",
    )
    _require(
        set(
            zip(
                call_fallback["kind_values"], call_fallback["stage_values"], strict=True
            )
        )
        == {("A", 2), ("C", 3), ("B", 1)},
        "Multi fallback sampler saw unexpected tuples",
    )


def test_unmatched_without_fallback_raises() -> None:
    """Both conditional prior variants raise when unmatched rows remain."""
    context = pd.DataFrame({
        "kind": ["A", "C"],
        "stage": [1, 2],
        "value_for_a": [1, 2],
    })

    single = ConditionalPrior(
        source_feature="kind",
        conditions=[
            ConditionalPriorCondition(
                match_val="A", sampler=CopySampler(feature_to_copy="value_for_a")
            )
        ],
        fallback_prior=None,
    )
    multi = MultiColumnConditionalPrior(
        source_features=["kind", "stage"],
        conditions=[
            MultiColumnCondition(
                match_vals=("A", 1), sampler=CopySampler(feature_to_copy="value_for_a")
            )
        ],
        fallback_prior=None,
    )

    try:
        single.sample(context, len(context), np.random.default_rng(7))
        msg = "Expected ConditionalPrior to raise SamplingError."
        raise AssertionError(msg)
    except SamplingError:
        pass

    try:
        multi.sample(context, len(context), np.random.default_rng(7))
        msg = "Expected MultiColumnConditionalPrior to raise SamplingError."
        raise AssertionError(msg)
    except SamplingError:
        pass


def main() -> None:
    """Run all smoke tests."""
    test_conditional_prior_subset_sampling()
    print("PASS: ConditionalPrior subset sampling")

    test_multicolumn_conditional_prior_subset_sampling()
    print("PASS: MultiColumnConditionalPrior subset sampling")

    test_unmatched_without_fallback_raises()
    print("PASS: Unmatched rows raise without fallback")

    print("All conditional prior smoke tests passed.")


if __name__ == "__main__":
    main()
