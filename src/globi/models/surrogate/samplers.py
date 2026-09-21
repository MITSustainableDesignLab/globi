"""Conditional Priors and Samplers.

Ported from epengine/models/sampling.py with enhancements:
- Fixed NaN comparison bug in ConditionalPrior
- Added MultiColumnConditionalPrior for multi-column conditioning
  without requiring ConcatenateFeaturesSampler intermediate columns
"""

import gc
from abc import ABC, abstractmethod
from typing import Literal, cast

import networkx as nx
import numpy as np
import pandas as pd
from pydantic import BaseModel, model_validator

# TODO: Make sure that all of the samplers can be serialized and deserialized with proper discrimination, i.e. that they do not share identical field names.
# TODO: add support for keeping rows which already have values (i.e. do not overwrite values)


class SamplingError(Exception):
    """A sampling error."""

    pass


class Sampler(ABC):
    """A sampler."""

    @abstractmethod
    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Sample features from a prior, which may depend on a context."""
        pass

    @property
    @abstractmethod
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        pass


class UniformSampler(BaseModel, Sampler):
    """A uniform sampler which generates values uniformly between a min and max value."""

    min: float
    max: float
    round: Literal["ceil", "floor", "nearest"] | None = None

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Sample uniformly between a min and max value."""
        samples = generator.uniform(self.min, self.max, size=n)
        if self.round == "ceil":
            samples = np.ceil(samples)
        elif self.round == "floor":
            samples = np.floor(samples)
        elif self.round == "nearest":
            samples = np.round(samples)
        return samples

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return set()


class ClippedNormalSampler(BaseModel, Sampler):
    """A clipped normal sampler which generates values from a normal distribution, clipped to a min and max value."""

    mean: float
    std: float
    clip_min: float | None
    clip_max: float | None

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Sample from a normal distribution, clipped to a min and max value."""
        clip_min = self.clip_min if self.clip_min is not None else -np.inf
        clip_max = self.clip_max if self.clip_max is not None else np.inf
        samples = generator.normal(self.mean, self.std, size=n).clip(clip_min, clip_max)
        return samples

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return set()


class FixedValueSampler(BaseModel):
    """A fixed value sampler which generates a fixed value for all samples."""

    value: float | str | int | bool

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Sample a fixed value."""
        return np.full(n, self.value)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return set()


class CategoricalSampler(BaseModel):
    """A categorical sampler which generates values from a categorical distribution."""

    values: list[str] | list[float] | list[int]
    weights: list[float]

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Sample from a categorical distribution."""
        return generator.choice(self.values, size=n, p=self.weights)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return set()

    @model_validator(mode="after")
    def check_values_and_weights(self):
        """Check that the values and weights are the same length and normalized."""
        if len(self.values) != len(self.weights):
            msg = "values and weights must be the same length"
            raise ValueError(msg)
        if not np.isclose(sum(self.weights), 1):
            self.weights = [w / sum(self.weights) for w in self.weights]
        return self


class CopySampler(BaseModel):
    """A deterministic sampler which generates a copy of a feature in the provided context dataframe."""

    feature_to_copy: str

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compute a copy of a feature."""
        if self.feature_to_copy not in context.columns:
            msg = f"Feature to copy {self.feature_to_copy} not found in context dataframe."
            raise SamplingError(msg)
        if len(context) != n:
            msg = (
                f"Context dataframe must have {n} rows, but it has {len(context)} rows."
            )
            raise SamplingError(msg)
        return context[self.feature_to_copy].to_numpy()

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {self.feature_to_copy}


class AddValueSampler(BaseModel):
    """A deterministic sampler which adds a value to a feature."""

    feature_to_add_to: str
    value_to_add: float

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compute a sum of a feature and a value."""
        if self.feature_to_add_to not in context.columns:
            msg = f"Feature to add to {self.feature_to_add_to} not found in context dataframe."
            raise SamplingError(msg)
        return context[self.feature_to_add_to].to_numpy() + self.value_to_add

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {self.feature_to_add_to}


class SumValuesSampler(BaseModel):
    """A deterministic sampler which generates a sum of features."""

    features_to_sum: list[str]

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compute a sum of features."""
        if not all(f in context.columns for f in self.features_to_sum):
            msg = f"All features to sum {self.features_to_sum} must be found in context dataframe."
            raise SamplingError(msg)
        if len(context) != n:
            msg = (
                f"Context dataframe must have {n} rows, but it has {len(context)} rows."
            )
            raise SamplingError(msg)
        return np.sum(context[self.features_to_sum].to_numpy(), axis=1)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return set(self.features_to_sum)


class MultiplyValueSampler(BaseModel):
    """A deterministic sampler which generates a product of a feature and a value."""

    feature_to_multiply: str
    value_to_multiply: float

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compute a multiply of a feature."""
        if self.feature_to_multiply not in context.columns:
            msg = f"Feature to multiply {self.feature_to_multiply} not found in context dataframe."
            raise SamplingError(msg)
        if len(context) != n:
            msg = (
                f"Context dataframe must have {n} rows, but it has {len(context)} rows."
            )
            raise SamplingError(msg)
        return context[self.feature_to_multiply].to_numpy() * self.value_to_multiply

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {self.feature_to_multiply}


class ProductValuesSampler(BaseModel):
    """A deterministic sampler which generates a product of features."""

    features_to_multiply: list[str]

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compute a product of features."""
        if not all(f in context.columns for f in self.features_to_multiply):
            msg = f"All features to multiply {self.features_to_multiply} must be found in context dataframe."
            raise SamplingError(msg)
        if len(context) != n:
            msg = (
                f"Context dataframe must have {n} rows, but it has {len(context)} rows."
            )
            raise SamplingError(msg)
        return np.prod(context[self.features_to_multiply].to_numpy(), axis=1)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return set(self.features_to_multiply)


class InvertSampler(BaseModel):
    """A deterministic sampler which generates the multiplicative inverse of a feature."""

    feature_to_invert: str

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compute an invert of a feature."""
        if self.feature_to_invert not in context.columns:
            msg = f"Feature to invert {self.feature_to_invert} not found in context dataframe."
            raise SamplingError(msg)
        if len(context) != n:
            msg = (
                f"Context dataframe must have {n} rows, but it has {len(context)} rows."
            )
            raise SamplingError(msg)
        return 1 / context[self.feature_to_invert].to_numpy()

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {self.feature_to_invert}


class PowerSampler(BaseModel):
    """A deterministic sampler which generates a power of a feature."""

    feature_to_power: str
    power: float

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compute a power of a feature."""
        return context[self.feature_to_power].to_numpy() ** self.power

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {self.feature_to_power}


class LogSampler(BaseModel):
    """A deterministic sampler which generates a log of a feature."""

    feature_to_log: str
    base: float = np.e

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compute a log of a feature."""
        if self.feature_to_log not in context.columns:
            msg = (
                f"Feature to log {self.feature_to_log} not found in context dataframe."
            )
            raise SamplingError(msg)
        if len(context) != n:
            msg = (
                f"Context dataframe must have {n} rows, but it has {len(context)} rows."
            )
            raise SamplingError(msg)
        return np.log(context[self.feature_to_log].to_numpy()) / np.log(self.base)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {self.feature_to_log}


class RoundSampler(BaseModel):
    """A deterministic sampler which applies ceil, floor, or nearest to a feature."""

    feature_to_round: str
    operation: Literal["ceil", "floor", "nearest"]

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Apply ceil, floor, or nearest to a feature."""
        if self.feature_to_round not in context.columns:
            msg = f"Feature to round {self.feature_to_round} not found in context dataframe."
            raise SamplingError(msg)
        if len(context) != n:
            msg = (
                f"Context dataframe must have {n} rows, but it has {len(context)} rows."
            )
            raise SamplingError(msg)
        values = context[self.feature_to_round].to_numpy()
        if self.operation == "ceil":
            return np.ceil(values)
        if self.operation == "floor":
            return np.floor(values)
        return np.round(values)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {self.feature_to_round}


class ThresholdSampler(BaseModel):
    """A deterministic sampler which generates a boolean value based on a threshold."""

    feature_to_compare: str
    threshold: float
    operator: Literal["<", "<=", "==", ">=", ">"]
    true_value: float | str | int | bool
    false_value: float | str | int | bool

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compare a feature to a threshold."""
        if self.feature_to_compare not in context.columns:
            msg = f"Feature to compare {self.feature_to_compare} not found in context dataframe."
            raise SamplingError(msg)
        source_values = context[self.feature_to_compare].to_numpy()
        if self.operator == "<":
            return np.where(
                source_values < self.threshold, self.true_value, self.false_value
            )
        elif self.operator == "<=":
            return np.where(
                source_values <= self.threshold, self.true_value, self.false_value
            )
        elif self.operator == "==":
            return np.where(
                source_values == self.threshold, self.true_value, self.false_value
            )
        elif self.operator == ">=":
            return np.where(
                source_values >= self.threshold, self.true_value, self.false_value
            )
        elif self.operator == ">":
            return np.where(
                source_values > self.threshold, self.true_value, self.false_value
            )
        else:
            msg = f"Invalid operator {self.operator}."
            raise SamplingError(msg)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {self.feature_to_compare}


class ColumnComparatorSampler(BaseModel):
    """A deterministic sampler which compares one column to another column."""

    left_feature: str
    right_feature: str
    operator: Literal["<", "<=", "==", ">=", ">"]
    true_value: float | str | int | bool
    false_value: float | str | int | bool

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compare one column to another column."""
        if self.left_feature not in context.columns:
            msg = f"Left feature {self.left_feature} not found in context dataframe."
            raise SamplingError(msg)
        if self.right_feature not in context.columns:
            msg = f"Right feature {self.right_feature} not found in context dataframe."
            raise SamplingError(msg)
        left_values = context[self.left_feature].to_numpy()
        right_values = context[self.right_feature].to_numpy()
        if self.operator == "<":
            return np.where(
                left_values < right_values, self.true_value, self.false_value
            )
        elif self.operator == "<=":
            return np.where(
                left_values <= right_values, self.true_value, self.false_value
            )
        elif self.operator == "==":
            return np.where(
                left_values == right_values, self.true_value, self.false_value
            )
        elif self.operator == ">=":
            return np.where(
                left_values >= right_values, self.true_value, self.false_value
            )
        elif self.operator == ">":
            return np.where(
                left_values > right_values, self.true_value, self.false_value
            )
        else:
            msg = f"Invalid operator {self.operator}."
            raise SamplingError(msg)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {self.left_feature, self.right_feature}


class ConcatenateFeaturesSampler(BaseModel):
    """A deterministic sampler which concatenates features.

    Retained for backward compatibility. Prefer MultiColumnConditionalPrior
    for multi-column conditioning instead of creating intermediate compound key columns.
    """

    features_to_concatenate: list[str]
    separator: str = ":"

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Compute a concatenation of features."""
        if not all(f in context.columns for f in self.features_to_concatenate):
            msg = f"All features to concatenate {self.features_to_concatenate} must be found in context dataframe."
            raise SamplingError(msg)
        if len(context) != n:
            msg = (
                f"Context dataframe must have {n} rows, but it has {len(context)} rows."
            )
            raise SamplingError(msg)
        cols: pd.DataFrame = cast(pd.DataFrame, context[self.features_to_concatenate])
        return cols.astype(str).agg(self.separator.join, axis=1).to_numpy()

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return set(self.features_to_concatenate)


PriorSampler = (
    UniformSampler
    | ClippedNormalSampler
    | FixedValueSampler
    | CategoricalSampler
    | CopySampler
    | AddValueSampler
    | SumValuesSampler
    | MultiplyValueSampler
    | ProductValuesSampler
    | InvertSampler
    | LogSampler
    | RoundSampler
    | ConcatenateFeaturesSampler
    | PowerSampler
    | ThresholdSampler
    | ColumnComparatorSampler
)


# TODO: Rename this to MatchCondition
class ConditionalPriorCondition(BaseModel):
    """A conditional prior condition."""

    match_val: str | float | int | bool
    sampler: PriorSampler

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Sample from a conditional prior condition."""
        return self.sampler.sample(context, n, generator)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return self.sampler.depends_on


# TODO: Rename this to MultiColumnMatchCondition
class MultiColumnCondition(BaseModel):
    """A condition that matches on multiple source features simultaneously.

    Used with MultiColumnConditionalPrior to condition on combinations
    of column values without creating intermediate compound key columns.
    """

    match_vals: tuple[str | float | int | bool, ...]
    sampler: PriorSampler

    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Sample from this condition's sampler."""
        return self.sampler.sample(context, n, generator)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return self.sampler.depends_on


class PriorABC(ABC):
    """A prior."""

    @abstractmethod
    def sample(
        self, context: pd.DataFrame, n: int, generator: np.random.Generator
    ) -> np.ndarray:
        """Sample from a prior."""
        pass

    @property
    @abstractmethod
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        pass


class ConditionalPrior(BaseModel, PriorABC):
    """A conditional prior that selects a sampler based on a single source feature."""

    source_feature: str
    conditions: list[ConditionalPriorCondition]
    fallback_prior: PriorSampler | None

    @staticmethod
    def _sample_for_indices(
        sampler: PriorSampler,
        context: pd.DataFrame,
        indices: np.ndarray,
        generator: np.random.Generator,
        sampler_label: str,
    ) -> np.ndarray:
        """Sample only for selected row indices and validate output length."""
        n_for_sampler = int(indices.size)
        context_for_sampler = context.iloc[indices]
        samples = sampler.sample(context_for_sampler, n_for_sampler, generator)
        if len(samples) != n_for_sampler:
            msg = (
                f"{sampler_label} returned an invalid number of samples: "
                f"expected {n_for_sampler}, got {len(samples)}."
            )
            raise SamplingError(msg)
        return np.asarray(samples)

    @staticmethod
    def _merge_samples(
        final: np.ndarray | None,
        n: int,
        indices: np.ndarray,
        samples: np.ndarray,
    ) -> np.ndarray:
        """Merge sampled values into the final array with dtype promotion if needed."""
        if final is None:
            final = np.empty(n, dtype=samples.dtype)
        else:
            promoted_dtype = np.result_type(final.dtype, samples.dtype)
            if promoted_dtype != final.dtype:
                final = final.astype(promoted_dtype, copy=False)

        if final is None:
            msg = "Internal error: final samples array was not initialized."
            raise SamplingError(msg)
        final[indices] = samples
        return final

    def sample(self, context: pd.DataFrame, n: int, generator: np.random.Generator):
        """Sample from a conditional prior."""
        if self.source_feature not in context.columns:
            msg = (
                f"Source feature {self.source_feature} not found in context dataframe."
            )
            raise SamplingError(msg)
        if len(context) != n:
            msg = (
                f"Context dataframe must have {n} rows, but it has {len(context)} rows."
            )
            raise SamplingError(msg)

        test_feature = context[self.source_feature].to_numpy()

        final: np.ndarray | None = None

        any_matched_mask = np.full(n, False)
        for condition in self.conditions:
            matched_indices = np.flatnonzero(test_feature == condition.match_val)
            if matched_indices.size == 0:
                continue

            samples_for_condition = self._sample_for_indices(
                sampler=condition.sampler,
                context=context,
                indices=matched_indices,
                generator=generator,
                sampler_label="Conditional prior sampler",
            )
            final = self._merge_samples(
                final=final, n=n, indices=matched_indices, samples=samples_for_condition
            )
            any_matched_mask[matched_indices] = True

        if self.fallback_prior is not None:
            unmatched_indices = np.flatnonzero(~any_matched_mask)
            if unmatched_indices.size > 0:
                fallback_samples = self._sample_for_indices(
                    sampler=self.fallback_prior,
                    context=context,
                    indices=unmatched_indices,
                    generator=generator,
                    sampler_label="Fallback prior",
                )
                final = self._merge_samples(
                    final=final,
                    n=n,
                    indices=unmatched_indices,
                    samples=fallback_samples,
                )
                any_matched_mask[unmatched_indices] = True

        unmatched_mask = ~any_matched_mask
        if unmatched_mask.any():
            unmatched_examples = test_feature[unmatched_mask][:5]
            msg = (
                "No condition matched some rows and no fallback prior filled them for "
                f"feature {self.source_feature}. Examples: {unmatched_examples}"
            )
            raise SamplingError(msg)

        if final is None:
            return np.empty(n)

        return final

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {self.source_feature} | {
            dependency for c in self.conditions for dependency in c.depends_on
        }


class MultiColumnConditionalPrior(BaseModel, PriorABC):
    """A conditional prior that selects a sampler based on multiple source features.

    This eliminates the need for ConcatenateFeaturesSampler + compound key columns.
    Instead of creating an intermediate concatenated column and matching on strings,
    this prior directly matches on tuples of column values.

    Example usage::

        prior = MultiColumnConditionalPrior(
            source_features=["Typology", "Age_bracket"],
            conditions=[
                MultiColumnCondition(
                    match_vals=("SFH", "pre_1975"),
                    sampler=CategoricalSampler(values=[...], weights=[...]),
                ),
                MultiColumnCondition(
                    match_vals=("MFH", "post_2003"),
                    sampler=UniformSampler(min=0.5, max=1.0),
                ),
            ],
            fallback_prior=CategoricalSampler(values=[...], weights=[...]),
        )
    """

    source_features: list[str]
    conditions: list[MultiColumnCondition]
    fallback_prior: PriorSampler | None

    @model_validator(mode="after")
    def validate_condition_lengths(self):
        """Ensure all conditions have match_vals aligned with source_features."""
        for i, c in enumerate(self.conditions):
            if len(c.match_vals) != len(self.source_features):
                msg = (
                    f"Condition {i}: match_vals length {len(c.match_vals)} "
                    f"!= source_features length {len(self.source_features)}"
                )
                raise ValueError(msg)
        return self

    @staticmethod
    def _matched_indices_for_condition(
        source_values: list[np.ndarray],
        match_vals: tuple[str | float | int | bool, ...],
        n: int,
    ) -> np.ndarray:
        """Return row indices that match all source-feature values for a condition."""
        mask = np.full(n, True)
        for feature_values, match_val in zip(source_values, match_vals, strict=True):
            mask &= feature_values == match_val
        return np.flatnonzero(mask)

    @staticmethod
    def _unmatched_tuple_examples(
        source_values: list[np.ndarray], unmatched_indices: np.ndarray
    ) -> list[tuple[object, ...]]:
        """Build a few unmatched source-feature tuples for error reporting."""
        return [
            tuple(feature_values[i] for feature_values in source_values)
            for i in unmatched_indices[:5]
        ]

    def sample(self, context: pd.DataFrame, n: int, generator: np.random.Generator):
        """Sample from a multi-column conditional prior."""
        for f in self.source_features:
            if f not in context.columns:
                msg = f"Source feature {f} not found in context dataframe."
                raise SamplingError(msg)
        if len(context) != n:
            msg = (
                f"Context dataframe must have {n} rows, but it has {len(context)} rows."
            )
            raise SamplingError(msg)

        source_values = [context[f].to_numpy() for f in self.source_features]
        final: np.ndarray | None = None
        any_matched = np.full(n, False)

        for condition in self.conditions:
            matched_indices = self._matched_indices_for_condition(
                source_values=source_values, match_vals=condition.match_vals, n=n
            )
            if matched_indices.size == 0:
                continue

            samples = ConditionalPrior._sample_for_indices(
                sampler=condition.sampler,
                context=context,
                indices=matched_indices,
                generator=generator,
                sampler_label="Multi-column conditional prior sampler",
            )
            final = ConditionalPrior._merge_samples(
                final=final, n=n, indices=matched_indices, samples=samples
            )
            any_matched[matched_indices] = True

        if self.fallback_prior is not None:
            unmatched_indices = np.flatnonzero(~any_matched)
            if unmatched_indices.size > 0:
                fallback_samples = ConditionalPrior._sample_for_indices(
                    sampler=self.fallback_prior,
                    context=context,
                    indices=unmatched_indices,
                    generator=generator,
                    sampler_label="Multi-column fallback prior",
                )
                final = ConditionalPrior._merge_samples(
                    final=final,
                    n=n,
                    indices=unmatched_indices,
                    samples=fallback_samples,
                )
                any_matched[unmatched_indices] = True

        unmatched_mask = ~any_matched
        if unmatched_mask.any():
            unmatched_indices = np.flatnonzero(unmatched_mask)
            unmatched_examples = self._unmatched_tuple_examples(
                source_values=source_values, unmatched_indices=unmatched_indices
            )
            msg = (
                "No condition matched some rows and no fallback prior filled them for "
                f"features {self.source_features}. Examples of unmatched tuples: {unmatched_examples}"
            )
            raise SamplingError(msg)

        if final is None:
            return np.empty(n)

        return final

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return set(self.source_features) | {
            dependency for c in self.conditions for dependency in c.sampler.depends_on
        }


class UnconditionalPrior(BaseModel, PriorABC):
    """An unconditional prior."""

    sampler: PriorSampler

    def sample(self, context: pd.DataFrame, n: int, generator: np.random.Generator):
        """Sample from an unconditional prior."""
        return self.sampler.sample(context, n, generator)

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return self.sampler.depends_on


Prior = UnconditionalPrior | ConditionalPrior | MultiColumnConditionalPrior


class Priors(BaseModel):
    """A collection of priors defining a dependency graph for sampling."""

    sampled_features: dict[str, Prior]

    def sample(self, context: pd.DataFrame, n: int, generator: np.random.Generator):
        """Sample from all priors in dependency order."""
        working_df = context.copy(deep=True)
        # TODO: Similarly, how do we ensure that there are no cycles in the dependency graph?
        for i, feature in enumerate(self.topological_sort):
            if (i + 1) % 20 == 0:
                new_working_df = working_df.copy(
                    deep=True
                )  # copy every 20 features to avoid fragmentation issues
                del working_df
                gc.collect()
                working_df = new_working_df
            if feature not in self.sampled_features and feature not in context.columns:
                msg = f"Feature {feature} not found in sampled features or context dataframe."
                raise SamplingError(msg)
            if feature not in self.sampled_features:
                if feature not in self.root_features:
                    msg = (
                        f"Feature {feature} not found in root features but expected to."
                    )
                    raise SamplingError(msg)

                # it's a context feature dependency, so we can skip over to the next
                continue

            prior = self.sampled_features[feature]

            working_df.loc[:, feature] = prior.sample(working_df, n, generator)
        if working_df.isna().any().any():  # pyright: ignore [reportAttributeAccessIssue]
            cols_that_are_na = working_df.columns[working_df.isna().any()]
            # TODO: allow na values eg in training?
            msg = f"Working dataframe contains NaN values; possibly due to an unmatched value: {cols_that_are_na[:5]}{'...' if len(cols_that_are_na) > 5 else ''}"
            raise SamplingError(msg)
        return working_df

    @property
    def depends_on(self) -> set[str]:
        """The features that this sampler depends on."""
        return {
            dependency
            for prior in self.sampled_features.values()
            for dependency in prior.depends_on
        }

    @property
    def dependency_graph(self) -> nx.DiGraph:
        """Construct a dependency graph between columns in the context dataframe.

        Edges connect *from* the dependency *to* the dependent feature.
        """
        g = nx.DiGraph()
        for feature, prior in self.sampled_features.items():
            if prior.depends_on:
                for dependency in prior.depends_on:
                    g.add_edge(dependency, feature)
        # TODO: make sure that this is okay and that id does not cause problem siwth select_prior_tree_for_changed_features...
        for feature in self.sampled_features:
            if feature not in g.nodes:
                g.add_node(feature)

        return g

    @property
    def topological_sort(self) -> list[str]:
        """The topological sort of the features."""
        return list(nx.topological_sort(self.dependency_graph))

    @property
    def root_features(self) -> set[str]:
        """The features that have no dependencies."""
        return {
            node
            for node in self.dependency_graph.nodes
            if self.dependency_graph.in_degree(node) == 0
        }

    def select_prior_tree_for_changed_features(
        self, changed_features: set[str], resample_changed_features: bool = True
    ) -> "Priors":
        """Select the prior tree for the changed features.

        Returns a new Priors object with only the priors that are
        downstream of the changed features.

        Args:
            changed_features: The features that have changed.
            resample_changed_features: Whether to resample the changed features
                themselves (dependencies are always resampled). You probably want
                this to be False, but for backwards compatibility it defaults to True.

        Returns:
            A new Priors object with only the downstream priors.
        """
        g = self.dependency_graph
        all_changing_priors: set[str] = set()
        for any_feature in self.root_features.union(set(self.sampled_features.keys())):
            if any(f == any_feature for f in changed_features):
                descendants = nx.descendants(g, any_feature)

                if any_feature in self.sampled_features and resample_changed_features:
                    all_changing_priors.add(any_feature)

                for dep in descendants:
                    if dep in self.sampled_features:
                        all_changing_priors.add(dep)

        return Priors(
            sampled_features={
                f: p
                for f, p in self.sampled_features.items()
                if f in all_changing_priors
            }
        )
