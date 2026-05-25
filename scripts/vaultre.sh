#!/usr/bin/env bash
# Convenience wrapper for the VaultRE CLI.
#
# Resolves the project root, loads .env (where VAULTRE_API_BASE/KEY/TOKEN live),
# and shells into the backend venv's Python so the consultant Claude can call
# this directly without worrying about which python or which working directory.
#
# Usage from the chat workflow:
#
#   ./scripts/vaultre.sh search "158 Preservation Drive"
#   ./scripts/vaultre.sh get 35489499
#   ./scripts/vaultre.sh photos 35489499
#   ./scripts/vaultre.sh download 35489499 consultants/wendy-squibb/sessions/session-XXXX/vaultre-photos
#
# The `download` subcommand puts photographs at <dest>/vaultre-<id>.jpg and
# floor plans at <dest>/floor-plans/vaultre-<id>.jpg — same shape the chat
# upload uses, so the workflow's Step 1.3 inspection rule applies.

set -euo pipefail

# Resolve the project root from THIS script's location, not the caller's pwd.
# Claude's Bash invocations might run from any consultant subdirectory.
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ROOT="$( dirname "$SCRIPT_DIR" )"

# Load .env so VAULTRE_API_KEY/TOKEN/BASE are available. If .env doesn't exist
# or the keys are missing, the underlying python will fail loudly with a
# structured JSON error to stderr — caller handles.
if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
fi

# Prefer the backend venv's python (has httpx). Fallback to system python3
# only if the venv hasn't been built yet (e.g., fresh clone before install.sh).
PYTHON="$ROOT/services/backend/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3)"
fi

cd "$ROOT"
exec "$PYTHON" -m services.backend.app.vaultre_cli "$@"
