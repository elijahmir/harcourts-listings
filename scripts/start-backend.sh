#!/usr/bin/env bash
# Start (or restart) the FastAPI backend on port 8787.
#
# Sources .env into the process environment before launching uvicorn so
# config (HARCOURTS_REQUIRE_AUTH, HARCOURTS_SUPABASE_JWT_SECRET, etc.)
# is honoured. The previous nohup-from-shell pattern silently dropped
# these vars on restart, causing the WS handshake to start rejecting
# every connection with "jwt secret missing" — see commit message for
# the post-mortem.
#
# Usage:
#   ./scripts/start-backend.sh           # restart (kills any existing 8787 listener first)
#   ./scripts/start-backend.sh --status  # show running process + log tail
#   ./scripts/start-backend.sh --stop    # stop without restarting
#
# Log lives at /tmp/harcourts-backend.log. The process detaches from the
# launching shell (nohup + disown) so closing the terminal doesn't kill it.

set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ROOT="$( dirname "$SCRIPT_DIR" )"
LOG="/tmp/harcourts-backend.log"
PORT=8787
ENV_FILE="$ROOT/.env"
VENV_PY="$ROOT/services/backend/.venv/bin/python"

log()  { printf "  %s\n" "$*"; }
err()  { printf "  ERROR: %s\n" "$*" >&2; }

kill_existing() {
  local pids
  pids="$(pgrep -f "uvicorn.*services.backend.app.main.*${PORT}" || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  log "stopping existing backend (pids: $pids)"
  # shellcheck disable=SC2086
  kill -TERM $pids 2>/dev/null || true
  sleep 2
  pids="$(pgrep -f "uvicorn.*services.backend.app.main.*${PORT}" || true)"
  if [[ -n "$pids" ]]; then
    log "SIGTERM ignored, sending SIGKILL"
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
    sleep 1
  fi
}

cmd_stop() {
  kill_existing
  log "backend stopped."
}

cmd_status() {
  local pids
  pids="$(pgrep -af "uvicorn.*${PORT}" || true)"
  if [[ -z "$pids" ]]; then
    log "no backend running on port ${PORT}."
  else
    log "running:"
    echo "$pids" | sed 's/^/    /'
  fi
  log ""
  log "log tail ($LOG):"
  tail -n 15 "$LOG" 2>/dev/null | sed 's/^/    /' || log "  (no log yet)"
}

cmd_restart() {
  if [[ ! -x "$VENV_PY" ]]; then
    err "venv python not found at $VENV_PY — run scripts/install.sh first"
    exit 1
  fi

  kill_existing

  # Load .env into THIS shell's env so the child uvicorn inherits it.
  # `set -a` exports every variable assigned until `set +a`. Missing
  # .env is non-fatal — we just rely on defaults.
  if [[ -f "$ENV_FILE" ]]; then
    log "loading $ENV_FILE"
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  else
    log "no .env at $ENV_FILE — using defaults (HARCOURTS_REQUIRE_AUTH=true)"
  fi

  log "starting uvicorn on port $PORT"
  cd "$ROOT"
  nohup "$VENV_PY" -m uvicorn services.backend.app.main:app \
    --host 0.0.0.0 --port "$PORT" \
    > "$LOG" 2>&1 &
  disown
  local pid=$!

  sleep 3

  if ! kill -0 "$pid" 2>/dev/null; then
    err "backend died on startup — last 30 lines of log:"
    tail -n 30 "$LOG" >&2 || true
    exit 1
  fi

  if ! curl -sf "http://127.0.0.1:${PORT}/healthz" > /dev/null; then
    err "/healthz not responding — last 30 lines of log:"
    tail -n 30 "$LOG" >&2 || true
    exit 1
  fi

  log "backend up. PID=$pid  log=$LOG"
}

case "${1:-restart}" in
  --status|status) cmd_status ;;
  --stop|stop)     cmd_stop ;;
  --restart|restart|"") cmd_restart ;;
  *) err "unknown arg: $1"; echo "Usage: $0 [--status|--stop|--restart]" >&2; exit 2 ;;
esac
