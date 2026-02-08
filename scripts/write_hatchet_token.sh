#!/usr/bin/env bash
# Write HATCHET_CLIENT_TOKEN from hatchet-admin output into env files.
# Reads stdin and uses the first line that looks like a JWT (three dot-separated
# base64url segments), ignoring other lines (e.g. "cleaning up server config").

set -euo pipefail

KEY="HATCHET_CLIENT_TOKEN"
# JWT: three base64url segments separated by dots (optional = padding)
JWT_REGEX='^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+=*$'

# First line that looks like a JWT is the token
token=""
while IFS= read -r line; do
  line="${line//$'\r'/}"
  line="${line%"${line##*[![:space:]]}"}"
  line="${line#"${line%%[![:space:]]*}"}"
  if [[ -n "$line" && "$line" =~ $JWT_REGEX ]]; then
    token="$line"
    break
  fi
done

if [[ -z "$token" ]]; then
  echo "No JWT token found in input (expected a line with three dot-separated base64 segments)." >&2
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$script_dir/.." && pwd)"
export HATCHET_TOKEN="$token"

update_file() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "${KEY}=${token}" > "$file"
  elif grep -qE "^${KEY}=|^${KEY}[[:space:]]*=" "$file"; then
    awk -v key="$KEY" 'BEGIN { v=ENVIRON["HATCHET_TOKEN"] }
      /^HATCHET_CLIENT_TOKEN[[:space:]]*=/ { if (!n) { print key "=" v; n=1; next } }
      { print }' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
  else
    echo "${KEY}=${token}" >> "$file"
  fi
  echo "Updated ${KEY} in $(basename "$file")"
}

update_file "$root/.env.local.hatchet"
update_file "$root/.env.local.host.hatchet"
