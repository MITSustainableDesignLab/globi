"""Conditional Priors and Samplers.

Ported from epengine/models/sampling.py with enhancements:
- Fixed NaN comparison bug in ConditionalPrior
- Added MultiColumnConditionalPrior for multi-column conditioning
  without requiring ConcatenateFeaturesSampler intermediate columns
"""

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

    def sample(self, context: pd.DataFrame, n: int, generator: np.random.Generator):
        """Sample from a conditional prior."""
        conditional_samples = {
            c.match_val: c.sampler.sample(context, n, generator)
            for c in self.conditions
        }
        test_feature = context[self.source_feature].to_numpy()

        final = np.full(n, np.nan)

        any_matched_mask = np.full(n, False)
        for match_val, samples_for_match_val in conditional_samples.items():
            mask = test_feature == match_val
            any_matched_mask = any_matched_mask | mask
            final = np.where(mask, samples_for_match_val, final)

        if self.fallback_prior is not None:
            mask = ~any_matched_mask
            final = np.where(
                mask, self.fallback_prior.sample(context, n, generator), final
            )

        if (final == np.nan).any():
            msg = (
                "Final array contains NaN values; possibly due to an unmatched value for "
                f"feature {self.source_feature}."
            )
            raise SamplingError(msg)

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

        row_tuples = list(
            zip(*(context[f].to_numpy() for f in self.source_features), strict=True)
        )
        conditional_samples = {
            c.match_vals: c.sampler.sample(context, n, generator)
            for c in self.conditions
        }

        final = np.full(n, np.nan)
        any_matched = np.full(n, False)

        for match_vals, samples in conditional_samples.items():
            mask = np.array([t == match_vals for t in row_tuples])
            any_matched |= mask
            final = np.where(mask, samples, final)

        if self.fallback_prior is not None:
            final = np.where(
                ~any_matched,
                self.fallback_prior.sample(context, n, generator),
                final,
            )

        # TODO: previously was np.isnan(final), but this errored on str etc.
        # Check that the (final == np.nan).any() is correct and still catches what it is supposed to.
        if (final == np.nan).any():
            unmatched_examples = [
                row_tuples[i] for i in range(n) if not any_matched[i]
            ][:5]
            msg = (
                "Final array contains NaN values; possibly due to unmatched values for "
                f"features {self.source_features}. Examples of unmatched tuples: {unmatched_examples}"
            )
            raise SamplingError(msg)

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
        for feature in self.topological_sort:
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

            working_df[feature] = prior.sample(working_df, n, generator)
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
