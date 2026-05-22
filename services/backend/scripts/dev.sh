#!/usr/bin/env bash
# Run the backend with hot-reload for local development.
#
# Usage:
#   ./scripts/dev.sh             # binds 127.0.0.1:3000
#   PORT=4000 ./scripts/dev.sh   # custom port
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$BACKEND_DIR"

# Activate a local venv if one exists; otherwise rely on the system Python.
if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-3000}"

exec python -m uvicorn app.main:app --reload --host "$HOST" --port "$PORT"
