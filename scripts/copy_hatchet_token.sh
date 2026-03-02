#!/usr/bin/env bash
# Ensure .env.local.hatchet and .env.local.host.hatchet exist; copy from example if missing.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$script_dir/.." && pwd)"

if [[ ! -f "$root/.env.local.hatchet" ]]; then
  cp "$root/.env.local.hatchet.example" "$root/.env.local.hatchet"
  echo "Created .env.local.hatchet from .env.local.hatchet.example"
fi
if [[ ! -f "$root/.env.local.host.hatchet" ]]; then
  cp "$root/.env.local.host.hatchet.example" "$root/.env.local.host.hatchet"
  echo "Created .env.local.host.hatchet from .env.local.host.hatchet.example"
fi
