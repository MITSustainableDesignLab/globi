"""Write HATCHET_CLIENT_TOKEN from hatchet-admin output into env files.

Reads token from stdin (first line that looks like a JWT). Updates only
HATCHET_CLIENT_TOKEN in .env.local.hatchet and .env.local.host.hatchet,
leaving all other keys and comments unchanged.
"""

import re
import sys
from pathlib import Path

# JWT: three base64url segments separated by dots (optional padding =)
JWT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+=*$")

HATCHET_KEY = "HATCHET_CLIENT_TOKEN"
ENV_FILES = (".env.local.hatchet", ".env.local.host.hatchet")


def extract_token(lines: list[str]) -> str | None:
    """Return the first line that looks like a JWT, or None."""
    for line in lines:
        s = line.strip()
        if s and JWT_PATTERN.fullmatch(s):
            return s
    return None


def update_env_file(path: Path, token: str) -> None:
    """Set or replace HATCHET_CLIENT_TOKEN in path; leave other lines unchanged."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    new_lines: list[str] = []
    key_prefix = f"{HATCHET_KEY}="
    replaced = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(key_prefix) or stripped.startswith(f"{HATCHET_KEY} ="):
            # Replace this line with the new token (preserve style: key=value)
            new_lines.append(f"{HATCHET_KEY}={token}")
            replaced = True
        else:
            new_lines.append(line)

    if not replaced:
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append(f"{HATCHET_KEY}={token}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def main() -> None:
    """Read token from stdin, update both hatchet env files."""
    root = Path(__file__).resolve().parent.parent

    if len(sys.argv) > 1:
        # Token passed as first argument (e.g. for testing)
        token = sys.argv[1].strip()
        if not JWT_PATTERN.fullmatch(token):
            sys.exit("Argument does not look like a JWT.")
    else:
        input_lines = sys.stdin.read().splitlines()
        token = extract_token(input_lines)
        if not token:
            sys.exit(
                "No JWT token found in input (expected a single line with three dot-separated base64 segments)."
            )

    for name in ENV_FILES:
        path = root / name
        update_env_file(path, token)
        print(f"Updated {HATCHET_KEY} in {path.name}")


if __name__ == "__main__":
    main()
