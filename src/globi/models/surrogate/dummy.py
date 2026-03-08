"""Dummy simulation for testing."""

import math
from pathlib import Path
from typing import Literal

import pandas as pd
from scythe.base import ExperimentInputSpec, ExperimentOutputSpec
from scythe.registry import ExperimentRegistry


class DummySimulationInput(ExperimentInputSpec):
    """The input for the dummy simulation."""

    weather_file: Literal["some", "other"]
    a: int
    b: float
    c: int


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
        "target_2": [input_spec.a * input_spec.b * input_spec.c],
        "target_3": [input_spec.a / math.sin(input_spec.b)],
    })
    df_neg = -df
    df = pd.concat([df, df_neg], axis=1, keys=["positive", "negative"], names=["sign"])
    df = df.set_index(input_spec.make_multiindex())
    return DummySimulationOutput(
        c=input_spec.a + input_spec.b, dataframes={"main_result": df}
    )
