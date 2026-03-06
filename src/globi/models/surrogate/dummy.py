"""Dummy simulation for testing."""

from pathlib import Path

import pandas as pd
from scythe.base import ExperimentInputSpec, ExperimentOutputSpec
from scythe.registry import ExperimentRegistry


class DummySimulationInput(ExperimentInputSpec):
    """The input for the dummy simulation."""

    a: int
    b: float


class DummySimulationOutput(ExperimentOutputSpec):
    """The output for the dummy simulation."""

    c: float


@ExperimentRegistry.Register(
    description="A dummy simulation.",
)
def dummy_simulation(
    input_spec: DummySimulationInput, tempdir: Path
) -> DummySimulationOutput:
    """A dummy simulation."""
    df = pd.DataFrame({
        "target_0": [input_spec.a + input_spec.b],
        "target_1": [input_spec.a - input_spec.b],
        "target_2": [input_spec.a * input_spec.b],
        "target_3": [input_spec.a / input_spec.b],
    })
    df = df.set_index(input_spec.make_multiindex())
    return DummySimulationOutput(
        c=input_spec.a + input_spec.b, dataframes={"main_result": df}
    )
