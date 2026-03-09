"""Dummy simulation for testing."""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

import numpy as np
import pandas as pd
from scythe.base import ExperimentInputSpec, ExperimentOutputSpec
from scythe.registry import ExperimentRegistry

StratificationOption = Literal["some", "other", "option", "another"]


class DummySimulationInput(ExperimentInputSpec):
    """The input for the dummy simulation."""

    x0: float
    x1: float
    x2: float
    x3: float
    stratification_field: StratificationOption

    @property
    def encoded_stratification_field(self) -> float:
        """Encode the stratification field as an integer."""
        return get_args(StratificationOption).index(self.stratification_field) / (
            len(get_args(StratificationOption))
            - (1 if len(get_args(StratificationOption)) > 1 else 0)
        )

    @property
    def values(self) -> list[float]:
        """Get the values of the input spec."""
        vals = self.model_dump(
            exclude={
                "stratification_field",
                "experiment_id",
                "sort_index",
                "workflow_run_id",
                "root_workflow_run_id",
            }
        )
        x_vals = {k: v for k, v in vals.items() if k.startswith("x")}
        return [*x_vals.values(), self.encoded_stratification_field]

    def n_inputs(self) -> int:
        """Get the number of inputs."""
        return len(self.values)


class DummySimulationOutput(ExperimentOutputSpec):
    """The output for the dummy simulation."""

    y0: float


@ExperimentRegistry.Register(
    description="A dummy simulation.",
)
def dummy_simulation(
    input_spec: DummySimulationInput, tempdir: Path
) -> DummySimulationOutput:
    """A dummy simulation."""
    n_inputs = input_spec.n_inputs()
    n_outputs = 5
    problem = SyntheticMultiOutputProblem(
        n_inputs,
        SyntheticProblemConfig(
            n_outputs=5,
            n_latents=3,
            difficulty="easy",
            noise_std=0.0,
            normalize_outputs=True,
        ),
        input_spec.sort_index,
    )
    y = problem.evaluate(np.array(input_spec.values))

    main_result = pd.DataFrame({f"y{i}": [y[i]] for i in range(1, n_outputs)})
    main_result = main_result.set_index(input_spec.make_multiindex())
    main_result_neg = -main_result
    main_result = pd.concat(
        [main_result, main_result_neg],
        axis=1,
        keys=["positive", "negative"],
        names=["sign"],
    )
    return DummySimulationOutput(
        y0=y[0],
        dataframes={"main_result": main_result},
    )


@dataclass(frozen=True)
class SyntheticProblemConfig:
    """Configuration for a synthetic multi-output regression problem."""

    n_outputs: int = 8
    n_latents: int = 4
    difficulty: Literal["easy", "medium"] = "easy"
    noise_std: float = 0.0
    normalize_outputs: bool = True


class SyntheticMultiOutputProblem:
    """Deterministic synthetic multi-output function family.

    Inputs:
        x in [0, 1]^d

    Outputs:
        y in R^m

    Design goals:
    - cheap to evaluate
    - arbitrary input dimension
    - arbitrary output count
    - some outputs share latent structure
    - some outputs contain mild independent residuals
    - difficulty is tunable but never absurd
    """

    def __init__(self, n_inputs: int, config: SyntheticProblemConfig, seed: int):
        """Initialize the synthetic multi-output problem."""
        if n_inputs < 1:
            msg = "n_inputs must be >= 1"
            raise ValueError(msg)
        if config.n_outputs < 1:
            msg = "n_outputs must be >= 1"
            raise ValueError(msg)
        if config.n_latents < 1:
            msg = "n_latents must be >= 1"
            raise ValueError(msg)

        self.n_inputs = n_inputs
        self.config = config
        self.rng = np.random.default_rng(seed)
        self.seed = seed

        self.active_dims_per_latent = (
            min(5, n_inputs) if config.difficulty == "easy" else min(8, n_inputs)
        )
        self.freq_max = 2 if config.difficulty == "easy" else 4
        self.residual_scale = 0.05 if config.difficulty == "easy" else 0.12

        # Shared latent parameters
        self.latent_defs = [
            self._make_latent_definition(k) for k in range(config.n_latents)
        ]

        # Output mixing weights: this is what creates output dependency
        self.mix_weights = self.rng.normal(
            loc=0.0,
            scale=1.0 / math.sqrt(config.n_latents),
            size=(config.n_outputs, config.n_latents),
        )

        # Small output-specific residual definitions
        self.residual_defs = [
            self._make_residual_definition(j) for j in range(config.n_outputs)
        ]

        # Optional approximate normalization constants computed deterministically
        self.output_shift = np.zeros(config.n_outputs, dtype=float)
        self.output_scale = np.ones(config.n_outputs, dtype=float)
        if config.normalize_outputs:
            self._fit_normalization()

    def evaluate(self, x: np.ndarray) -> np.ndarray:
        """Evaluate all outputs at one input vector x."""
        x = np.asarray(x, dtype=float)
        if x.shape != (self.n_inputs,):
            msg = f"Expected x shape {(self.n_inputs,)}, got {x.shape}"
            raise ValueError(msg)

        # Clamp defensively; upstream encoder should already map into [0, 1]
        x = np.clip(x, 0.0, 1.0)

        z = np.array([self._eval_latent(x, ld) for ld in self.latent_defs], dtype=float)
        y = self.mix_weights @ z

        # Add small output-specific residuals so not everything is perfectly low-rank
        residual = np.array(
            [self._eval_residual(x, rd) for rd in self.residual_defs], dtype=float
        )
        y = y + residual

        if self.config.noise_std > 0:
            # deterministic if seed fixed and call order fixed; default is off for stable tests
            y = y + self.rng.normal(
                0.0, self.config.noise_std, size=self.config.n_outputs
            )

        y = (y - self.output_shift) / self.output_scale
        return y

    def _make_latent_definition(self, k: int) -> dict[str, Any]:
        """Create one latent function definition."""
        latent_type = k % 4
        dims = self.rng.choice(
            self.n_inputs, size=self.active_dims_per_latent, replace=False
        )

        if latent_type == 0:
            # additive sinusoid
            return {
                "type": "additive_sin",
                "dims": dims,
                "amp": self.rng.uniform(0.4, 1.2, size=len(dims)),
                "freq": self.rng.integers(1, self.freq_max + 1, size=len(dims)),
                "phase": self.rng.uniform(0.0, 2 * math.pi, size=len(dims)),
            }

        if latent_type == 1:
            # smooth quadratic bowl-ish feature
            return {
                "type": "quadratic",
                "dims": dims,
                "weight": self.rng.uniform(0.5, 1.5, size=len(dims)),
                "center": self.rng.uniform(0.2, 0.8, size=len(dims)),
            }

        if latent_type == 2:
            # pairwise interaction latent
            pair_count = max(1, len(dims) // 2)
            pair_dims = dims[: 2 * pair_count].reshape(pair_count, 2)
            return {
                "type": "pairwise_sin",
                "pairs": pair_dims,
                "weight": self.rng.uniform(0.4, 1.0, size=pair_count),
            }

        # Friedman-like latent, adapted to arbitrary dimension by cycling
        d0 = dims[0 % len(dims)]
        d1 = dims[1 % len(dims)]
        d2 = dims[2 % len(dims)]
        d3 = dims[3 % len(dims)]
        d4 = dims[4 % len(dims)]
        return {
            "type": "friedman_like",
            "dims": np.array([d0, d1, d2, d3, d4], dtype=int),
        }

    def _make_residual_definition(self, j: int) -> dict[str, Any]:
        """Create a small output-specific residual."""
        dims = self.rng.choice(self.n_inputs, size=min(3, self.n_inputs), replace=False)
        return {
            "dims": dims,
            "amp": self.rng.uniform(0.2, 0.8, size=len(dims)) * self.residual_scale,
            "freq": self.rng.integers(1, self.freq_max + 1, size=len(dims)),
            "phase": self.rng.uniform(0.0, 2 * math.pi, size=len(dims)),
        }

    def _eval_latent(self, x: np.ndarray, ld: dict[str, Any]) -> float:
        t = ld["type"]

        if t == "additive_sin":
            dims = ld["dims"]
            return float(
                np.sum(
                    ld["amp"] * np.sin(2 * math.pi * ld["freq"] * x[dims] + ld["phase"])
                )
            )

        if t == "quadratic":
            dims = ld["dims"]
            xc = x[dims] - ld["center"]
            return float(np.sum(ld["weight"] * xc * xc))

        if t == "pairwise_sin":
            total = 0.0
            for w, (i, j) in zip(ld["weight"], ld["pairs"], strict=True):
                total += float(w * math.sin(math.pi * x[i] * x[j]))
            return total

        if t == "friedman_like":
            i0, i1, i2, i3, i4 = ld["dims"]
            return float(
                10.0 * math.sin(math.pi * x[i0] * x[i1])
                + 20.0 * (x[i2] - 0.5) ** 2
                + 10.0 * x[i3]
                + 5.0 * x[i4]
            )

        msg = f"Unknown latent type: {t}"
        raise ValueError(msg)

    def _eval_residual(self, x: np.ndarray, rd: dict[str, Any]) -> float:
        dims = rd["dims"]
        return float(
            np.sum(rd["amp"] * np.sin(2 * math.pi * rd["freq"] * x[dims] + rd["phase"]))
        )

    def _fit_normalization(self) -> None:
        """Approximate output mean/std over a fixed reference design."""
        ref_rng = np.random.default_rng(self.seed + 1_000_000)
        n_ref = 2048 if self.config.difficulty == "easy" else 4096
        X = ref_rng.uniform(0.0, 1.0, size=(n_ref, self.n_inputs))

        Y = np.zeros((n_ref, self.config.n_outputs), dtype=float)
        for i in range(n_ref):
            z = np.array(
                [self._eval_latent(X[i], ld) for ld in self.latent_defs], dtype=float
            )
            residual = np.array(
                [self._eval_residual(X[i], rd) for rd in self.residual_defs],
                dtype=float,
            )
            Y[i] = self.mix_weights @ z + residual

        self.output_shift = Y.mean(axis=0)
        self.output_scale = Y.std(axis=0)
        self.output_scale[self.output_scale < 1e-8] = 1.0
