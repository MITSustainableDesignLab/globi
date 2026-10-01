"""Pipelines for the GloBI project."""

from globi.models.surrogate.dummy import dummy_simulation
from globi.pipelines.gis import preprocess_gis_file
from globi.pipelines.simulations import simulate_globi_building
from globi.pipelines.training import iterative_training

__all__ = [
    "dummy_simulation",
    "iterative_training",
    "preprocess_gis_file",
    "simulate_globi_building",
]
