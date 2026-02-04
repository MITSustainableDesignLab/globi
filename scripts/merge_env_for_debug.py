"""Merge env files for VS Code/Cursor debugger (same order as Make cli-native)."""

import os
from pathlib import Path


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse an env file into a dictionary."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def main() -> None:
    """Main function."""
    root = Path(__file__).resolve().parent.parent
    aws_env = os.environ.get("AWS_ENV", "local.host")
    hatchet_env = os.environ.get("HATCHET_ENV", "local.host")

    env_files = [
        root / f".env.{aws_env}.aws",
        root / f".env.{hatchet_env}.hatchet",
        root / ".env.scythe.fanouts",
        root / ".env.scythe.storage",
    ]

    merged: dict[str, str] = {}
    for p in env_files:
        merged.update(parse_env_file(p))

    out_path = root / ".env.debug"
    out_path.write_text(
        "\n".join(f"{k}={v}" for k, v in merged.items()) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(merged)} vars to {out_path}")


if __name__ == "__main__":
    main()
