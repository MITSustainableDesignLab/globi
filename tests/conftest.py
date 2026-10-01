"""Shared pytest configuration for globi.

Importing anything under ``globi.pipelines`` builds a Hatchet client at import time,
so we populate offline-safe env defaults before any test module is collected.
"""

from pathlib import Path

import pytest

from globi.validation.env import ensure_local_hatchet_env

REPO_ROOT = Path(__file__).resolve().parents[1]

ensure_local_hatchet_env(REPO_ROOT)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the opt-in flag for EnergyPlus-backed tests."""
    parser.addoption(
        "--run-energyplus",
        action="store_true",
        default=False,
        help="Run tests that execute real EnergyPlus simulations (slow).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip `energyplus`-marked tests unless explicitly requested."""
    if config.getoption("--run-energyplus"):
        return
    skip = pytest.mark.skip(reason="needs --run-energyplus")
    for item in items:
        if "energyplus" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def e2e_data_dir(repo_root: Path) -> Path:
    """The e2e fixture directory."""
    return repo_root / "tests" / "data" / "e2e"


_BACKEND_MODULES = {"xgb": "xgboost", "lgb": "lightgbm", "nn": "torch"}


@pytest.fixture(params=["xgb", "lgb", "nn"])
def backend_name(request: pytest.FixtureRequest) -> str:
    """Parametrize over ML backends, skipping any whose library is not installed."""
    name: str = request.param
    pytest.importorskip(_BACKEND_MODULES[name])
    if name == "xgb":
        # XGBModelConfig.param_dict imports torch to probe for CUDA.
        pytest.importorskip("torch")
    return name
