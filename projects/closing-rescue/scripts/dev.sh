#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  if [[ -n "${backend_pid:-}" ]]; then kill "$backend_pid" 2>/dev/null || true; fi
  if [[ -n "${frontend_pid:-}" ]]; then kill "$frontend_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

(
  cd "$project_dir/backend"
  uv run uvicorn septic_sentinel.api:app --host 127.0.0.1 --port 8000
) &
backend_pid=$!

(
  cd "$project_dir/frontend"
  npm run dev -- --host 127.0.0.1
) &
frontend_pid=$!

printf 'Septic Sentinel: http://localhost:5173\n'
wait "$backend_pid" "$frontend_pid"
