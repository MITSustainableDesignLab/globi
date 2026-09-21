"""Local (in-process) surrogate training harness and EnergyPlus validation.

This package mirrors the stages of the hatchet ``iterative_training`` workflow
(sample -> simulate -> combine -> train per fold -> evaluate -> recurse) as plain
functions that run on a single machine with no Hatchet server or S3 bucket, and adds
tooling for comparing a trained surrogate against deterministic EnergyPlus runs.

Importing this package populates offline-safe Hatchet client env vars (only where
unset), because the surrogate models transitively construct a Hatchet client at
import time.
"""

from globi.validation.env import ensure_local_hatchet_env

ensure_local_hatchet_env(strict=False)

__all__ = ["ensure_local_hatchet_env"]
