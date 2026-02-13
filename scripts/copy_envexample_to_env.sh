#!/usr/bin/env bash
# Copy .env.example to .env if .env does not exist

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$script_dir/.." && pwd)"

if [[ ! -f "$root/.env" ]]; then
  cp "$root/.env.example" "$root/.env"
  echo "Created .env from .env.example"
fi
