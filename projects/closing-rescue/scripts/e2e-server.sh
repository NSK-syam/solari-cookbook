#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
e2e_db="$(mktemp "${TMPDIR:-/tmp}/closing-rescue-e2e.XXXXXX")"

cleanup() {
  rm -f "$e2e_db"
}
trap cleanup EXIT INT TERM

SEPTIC_SENTINEL_DB_PATH="$e2e_db" \
VITE_STORY_SPEED=0.5 \
  "$project_dir/scripts/dev.sh"
