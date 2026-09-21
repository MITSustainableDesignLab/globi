"""Branching factor calculations."""

import json
import logging
import math

import numpy as np
from scythe.base import ExperimentInputSpec

logger = logging.getLogger(__name__)


# TODO: move this into scythe
def calculate_branching_factor[T: ExperimentInputSpec](
    specs: list[T],
) -> tuple[int, int, int]:
    """Calculate the branching factor for a given list of building specs.

    We do this by sampling 1k random buildings and checking the size of their serialized payloads.

    This is necessary because the async fanouts send all of the payloads for a branch over the wire at once.

    Args:
        specs (list[T]): The list of specs to calculate the branching factor for.

    Returns:
        factor (int): The branching factor.
        sims_per_branch (int): The number of simulations per branch.
        avg_bytes (int): The average size of the serialized payload.
    """
    logger.info("Calculating branching factor...")
    ixs = np.random.choice(len(specs), size=1000, replace=True)
    total_bytes = 0
    for ix in ixs:
        # check the file size of json.sumps
        stringified = json.dumps(specs[ix].model_dump(mode="json"), indent=2)
        nbytes = len(stringified.encode("utf-8"))
        total_bytes += nbytes
    avg_bytes = total_bytes / len(ixs)
    max_bytes_MB = 3  # safety factor, 4MB is actual amx
    max_bytes_B = max_bytes_MB * 1024 * 1024
    sims_per_branch = math.floor(max_bytes_B / avg_bytes)
    min_branches_required = math.ceil(len(specs) / sims_per_branch)
    logger.info(f"Avg payload size: {int(avg_bytes // 1024):0d} kB")
    logger.info(f"Avg sims per branch: {sims_per_branch}")
    logger.info(f"Min branches required: {min_branches_required}")
    return min_branches_required, sims_per_branch, math.ceil(avg_bytes)
