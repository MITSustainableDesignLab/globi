"""Type literals for the GloBI project."""

from typing import Literal

BasementAtticOccupationConditioningStatus = Literal[
    "none",
    "unoccupied_unconditioned",
    "unoccupied_conditioned",
    "occupied_unconditioned",
    "occupied_conditioned",
]

OccupiedOptions: list[BasementAtticOccupationConditioningStatus] = [
    "occupied_unconditioned",
    "occupied_conditioned",
]

UnoccupiedOptions: list[BasementAtticOccupationConditioningStatus] = [
    "none",
    "unoccupied_unconditioned",
    "unoccupied_conditioned",
]

ConditionedOptions: list[BasementAtticOccupationConditioningStatus] = [
    "occupied_conditioned",
    "unoccupied_conditioned",
]

UnconditionedOptions: list[BasementAtticOccupationConditioningStatus] = [
    "none",
    "unoccupied_unconditioned",
    "occupied_unconditioned",
]
