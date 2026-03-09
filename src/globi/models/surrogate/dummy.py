"""Dummy simulation for testing."""

import math
from pathlib import Path
from typing import Literal, get_args

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
    problem = SimpleSyntheticProblem(
        n_inputs,
        n_outputs,
        seed=input_spec.sort_index,
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


class SimpleSyntheticProblem:
    """A simple synthetic problem."""

    def __init__(self, n_inputs: int, n_outputs: int, seed: int):
        """Initialize the simple synthetic problem."""
        self.n_inputs = n_inputs
        self.n_outputs = n_outputs
        rng = np.random.default_rng(seed)

        self.alpha = rng.normal(size=n_outputs)
        self.beta = rng.normal(scale=0.8, size=(n_outputs, n_inputs))
        self.gamma = rng.normal(scale=0.4, size=(n_outputs, n_inputs))
        self.delta = rng.normal(scale=0.3, size=(n_outputs, max(0, n_inputs - 1)))
        self.eta = rng.normal(scale=0.2, size=n_outputs)
        self.sine_dim = rng.integers(0, n_inputs, size=n_outputs)

    def evaluate(self, x: np.ndarray) -> np.ndarray:
        """Evaluate the simple synthetic problem."""
        x = np.asarray(x, dtype=float)
        x = np.clip(x, 0.0, 1.0)

        linear = self.beta @ x
        quad = self.gamma @ (x**2)

        if self.n_inputs > 1:
            pairwise_terms = x[:-1] * x[1:]
            pairwise = self.delta @ pairwise_terms
        else:
            pairwise = np.zeros(self.n_outputs)

        periodic = np.array([
            self.eta[j] * math.sin(2 * math.pi * x[self.sine_dim[j]])
            for j in range(self.n_outputs)
        ])

        return self.alpha + linear + quad + pairwise + periodic
