"""Environment helpers for running globi pipelines without a Hatchet server.

Importing ``globi.pipelines`` (directly or transitively) constructs a
``hatchet_sdk.Hatchet`` client at import time, which validates ``HATCHET_CLIENT_TOKEN``
as a JWT and reads the broadcast address from its claims.  No network connection is
made until a workflow is actually submitted, so a syntactically valid token is enough
for local, in-process execution.
"""

import os
from pathlib import Path

HATCHET_ENV_EXAMPLE_FILE = ".env.local.host.hatchet.example"

_LOCAL_DEFAULTS = {
    "HATCHET_CLIENT_TLS_STRATEGY": "none",
    "HATCHET_CLIENT_HOST_PORT": "localhost:7077",
}


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upwards from `start` (default: cwd) looking for the hatchet example env file."""
    start = (start or Path.cwd()).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / HATCHET_ENV_EXAMPLE_FILE).exists():
            return candidate
    # fall back to the package's own location (installed in editable mode)
    pkg_root = Path(__file__).resolve().parents[3]
    if (pkg_root / HATCHET_ENV_EXAMPLE_FILE).exists():
        return pkg_root
    return None


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def ensure_local_hatchet_env(
    repo_root: Path | None = None, *, strict: bool = True
) -> None:
    """Populate the Hatchet client env vars with offline-safe defaults if unset.

    Existing values (e.g. from `make cli-native`'s `--env-file`s) are never overwritten.
    The token is read from `.env.local.host.hatchet.example` in the repo root.

    Args:
        repo_root: Where to look for the example env file (default: search upwards).
        strict: Raise if no token could be found; otherwise leave the env untouched
            and let the Hatchet client report the problem on import.
    """
    root = repo_root or find_repo_root()
    file_values = _parse_env_file(root / HATCHET_ENV_EXAMPLE_FILE) if root else {}
    for key, value in {**_LOCAL_DEFAULTS, **file_values}.items():
        os.environ.setdefault(key, value)
    if strict and "HATCHET_CLIENT_TOKEN" not in os.environ:
        msg = (
            "HATCHET_CLIENT_TOKEN is not set and no "
            f"{HATCHET_ENV_EXAMPLE_FILE} could be found to read a default from."
        )
        raise RuntimeError(msg)
