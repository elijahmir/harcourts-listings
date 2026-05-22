#!/usr/bin/env bash
# Bootstrap the Harcourts listing system on a fresh Mac.
#
# Idempotent — safe to re-run after a `git pull` to update deps and
# rebuild the frontend. Usage:
#
#   ./scripts/install.sh             # full install (default)
#   ./scripts/install.sh check       # just report state, change nothing
#   ./scripts/install.sh verify      # spawn claude --print, confirm permissions
#   ./scripts/install.sh launchd     # install both launchd services
#   ./scripts/install.sh restart     # reload launchd services
#   ./scripts/install.sh uninstall   # stop services + remove plists
#
# The launchd subcommands write to ~/Library/LaunchAgents/. They reference
# absolute paths to THIS checkout — re-run after moving the repo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

BACKEND_DIR="$PROJECT_ROOT/services/backend"
WEB_DIR="$PROJECT_ROOT/apps/web"
DATA_DIR="$PROJECT_ROOT/data"
OUTPUTS_DIR="$PROJECT_ROOT/outputs"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
BACKEND_PLIST="$LAUNCH_AGENTS/com.harcourts.backend.plist"
WEB_PLIST="$LAUNCH_AGENTS/com.harcourts.web.plist"

# --- output helpers ---------------------------------------------------------

green()  { printf "\033[1;32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[1;33m%s\033[0m\n" "$*"; }
red()    { printf "\033[1;31m%s\033[0m\n" "$*"; }
hdr()    { printf "\n\033[1m==> %s\033[0m\n" "$*"; }
note()   { printf "    %s\n" "$*"; }

# --- preflight --------------------------------------------------------------

require_macos() {
  if [[ "$(uname)" != "Darwin" ]]; then
    red "Not macOS — this installer only supports macOS." ; exit 1
  fi
}

find_python() {
  # Prefer python3.12 (modern PEP 604 syntax used by the backend).
  for candidate in python3.12 python3.13 python3.11 /opt/homebrew/bin/python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then
      "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null \
        && { echo "$candidate"; return 0; }
    fi
  done
  return 1
}

cmd_check() {
  hdr "Preflight"
  require_macos
  green "  macOS detected ($(sw_vers -productVersion))"

  if PY="$(find_python)"; then
    green "  python: $PY ($("$PY" --version 2>&1))"
  else
    red   "  python: 3.11+ NOT FOUND"
    note  "  Install with:  brew install python@3.12"
  fi

  if command -v claude >/dev/null 2>&1; then
    green "  claude: $(command -v claude) ($(claude --version 2>&1 | head -1))"
  else
    red   "  claude: NOT FOUND"
    note  "  Install Claude Code from https://docs.claude.com/en/docs/claude-code/setup"
  fi

  if command -v node >/dev/null 2>&1; then
    green "  node: $(node --version)"
  else
    red   "  node: NOT FOUND"
    note  "  Install with:  brew install node"
  fi

  if command -v npm >/dev/null 2>&1; then
    green "  npm: $(npm --version)"
  else
    red   "  npm: NOT FOUND (comes with node)"
  fi

  if command -v git >/dev/null 2>&1; then
    green "  git: $(git --version)"
  else
    red   "  git: NOT FOUND"
    note  "  Install Xcode CLT:  xcode-select --install"
  fi

  if command -v tailscale >/dev/null 2>&1; then
    green "  tailscale: $(tailscale version | head -1)"
  else
    yellow "  tailscale: NOT FOUND (optional, only needed for remote access)"
    note   "  Install with:  brew install tailscale && sudo brew services start tailscale"
  fi

  echo
  if [[ -d "$BACKEND_DIR/.venv" ]]; then
    green "  backend venv:  exists at services/backend/.venv"
  else
    yellow "  backend venv:  not yet created"
  fi
  if [[ -d "$WEB_DIR/node_modules" ]]; then
    green "  frontend deps: installed (apps/web/node_modules present)"
  else
    yellow "  frontend deps: not yet installed"
  fi
  if [[ -f "$PROJECT_ROOT/.env" ]]; then
    green "  .env file:     present"
  else
    yellow "  .env file:     missing (will be copied from .env.example on install)"
  fi
  if [[ -d "$WEB_DIR/.next" ]]; then
    green "  frontend build: .next/ present"
  else
    yellow "  frontend build: not built yet (install will run \`npm run build\`)"
  fi

  echo
  if [[ -f "$BACKEND_PLIST" ]]; then
    green "  launchd backend:  installed at $BACKEND_PLIST"
  else
    yellow "  launchd backend:  not installed"
  fi
  if [[ -f "$WEB_PLIST" ]]; then
    green "  launchd web:      installed at $WEB_PLIST"
  else
    yellow "  launchd web:      not installed"
  fi
}

# --- install steps ----------------------------------------------------------

setup_backend() {
  hdr "Backend (services/backend/)"
  cd "$BACKEND_DIR"

  PY="$(find_python)" || { red "Need Python 3.11+. Install via: brew install python@3.12"; exit 1; }

  if [[ ! -d .venv ]]; then
    note "creating venv with $PY"
    "$PY" -m venv .venv
  else
    note "venv exists"
  fi

  note "installing Python deps"
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
  green "  backend deps installed"
}

setup_frontend() {
  hdr "Frontend (apps/web/)"
  cd "$WEB_DIR"

  if [[ ! -d node_modules ]]; then
    note "running npm install (~1-2 min on first run)"
  else
    note "running npm install (incremental)"
  fi
  npm install --silent

  if [[ ! -f .env.local ]]; then
    note "creating .env.local from .env.example"
    cp .env.example .env.local
  fi

  note "building production bundle (npm run build)"
  npm run build --silent
  green "  frontend built — .next/ ready for production serve"
}

setup_env_file() {
  hdr "Project root .env"
  if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    yellow "  copied .env.example -> .env (fill in real VaultRE keys when ready)"
  else
    green "  .env exists"
  fi
}

ensure_dirs() {
  hdr "Runtime directories"
  mkdir -p "$DATA_DIR" "$OUTPUTS_DIR"
  green "  data/ and outputs/ ready"
}

# --- launchd ---------------------------------------------------------------

write_backend_plist() {
  cat > "$BACKEND_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.harcourts.backend</string>
  <key>ProgramArguments</key>
  <array>
    <string>${BACKEND_DIR}/.venv/bin/python</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>3000</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${BACKEND_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>${HOME}</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/harcourts-backend.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/harcourts-backend.log</string>
</dict>
</plist>
PLIST
}

write_web_plist() {
  cat > "$WEB_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.harcourts.web</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd "${WEB_DIR}" && npm run start -- --hostname 0.0.0.0</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${WEB_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>${HOME}</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/harcourts-web.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/harcourts-web.log</string>
</dict>
</plist>
PLIST
}

cmd_launchd() {
  hdr "Install launchd services"
  mkdir -p "$LAUNCH_AGENTS"

  # Unload first if already loaded (idempotent).
  launchctl unload "$BACKEND_PLIST" 2>/dev/null || true
  launchctl unload "$WEB_PLIST" 2>/dev/null || true

  write_backend_plist
  write_web_plist
  green "  wrote $BACKEND_PLIST"
  green "  wrote $WEB_PLIST"

  launchctl load "$BACKEND_PLIST"
  launchctl load "$WEB_PLIST"
  green "  loaded both services"

  echo
  note "Logs:  tail -f /tmp/harcourts-backend.log"
  note "       tail -f /tmp/harcourts-web.log"
  note "Test:  curl -s http://127.0.0.1:3000/healthz"
  note "       open http://127.0.0.1:3010"
}

cmd_restart() {
  hdr "Restart launchd services"
  launchctl unload "$BACKEND_PLIST" 2>/dev/null || true
  launchctl unload "$WEB_PLIST" 2>/dev/null || true
  launchctl load "$BACKEND_PLIST" 2>/dev/null || true
  launchctl load "$WEB_PLIST" 2>/dev/null || true
  green "  restarted"
}

cmd_uninstall() {
  hdr "Uninstall launchd services"
  launchctl unload "$BACKEND_PLIST" 2>/dev/null || true
  launchctl unload "$WEB_PLIST" 2>/dev/null || true
  rm -f "$BACKEND_PLIST" "$WEB_PLIST"
  green "  unloaded + removed plists"
  note  "  (the repo and data/ are untouched — delete those manually if needed)"
}

# --- verify ---------------------------------------------------------------
# Spawns `claude --print` with the exact flags services/backend/app/runner.py
# uses, sends a one-word prompt, and confirms the response is sane. This is
# the definitive "is this Mac fully set up?" check — exercises:
#   - claude binary on PATH + signed-in account
#   - --add-dir scoping for consultant + shared + outputs
#   - --permission-mode bypassPermissions auto-approving tools
#   - .claude/settings.json deny rules not blocking the basics
# If this passes, every teammate's chat session will work the same way (the
# chat agent has no per-user permission concept; it's per-host).

cmd_verify() {
  hdr "Verify chat permissions"

  if ! command -v claude >/dev/null 2>&1; then
    red "  claude CLI not on PATH. Install Claude Code first."
    return 1
  fi

  # Pick the first real consultant folder (alphabetical, skipping _template).
  local consultant_folder=""
  if [[ -d "$PROJECT_ROOT/consultants" ]]; then
    for d in "$PROJECT_ROOT/consultants"/*/; do
      local name; name="$(basename "$d")"
      [[ "$name" == _* ]] && continue
      consultant_folder="${d%/}"
      break
    done
  fi
  if [[ -z "$consultant_folder" ]]; then
    red "  no real consultant folder found under consultants/. Repo incomplete?"
    return 1
  fi

  note "using consultant: $(basename "$consultant_folder")"
  note "spawning a minimal \`claude --print\` to confirm everything's in place…"
  note "(this consumes about 10 tokens from your Claude Max plan)"

  local prompt="Smoke check from install.sh — reply with exactly the single word OK and nothing else."
  # NOTE: --add-dir is variadic (<directories...>), so passing the prompt as
  # a positional argument after a chain of --add-dir gets it eaten as another
  # directory. Stdin sidesteps that — it's also how runner.py feeds prompts
  # to the subprocess in production.
  local output rc
  set +e
  output="$(printf '%s' "$prompt" | claude --print \
    --permission-mode bypassPermissions \
    --add-dir "$consultant_folder" \
    --add-dir "$PROJECT_ROOT/shared" \
    --add-dir "$PROJECT_ROOT/outputs" \
    --input-format text 2>&1)"
  rc=$?
  set -e

  echo
  if [[ $rc -eq 0 ]] && grep -q "OK" <<<"$output"; then
    green "  ✓ claude responded cleanly. This Mac is ready."
    note  "  Every teammate's chat session will work identically — permissions"
    note  "  in this system are per host (this Mac), not per user."
    return 0
  fi

  red "  ✗ verification failed (claude exit code: $rc)"
  echo
  note "Captured output (first 10 lines):"
  echo "$output" | head -10 | sed 's/^/      /'
  echo
  note "Most likely causes, in order:"
  note "  1. Not signed in. Fix: claude login"
  note "  2. Missing settings.json entries — see HOST-SETUP.md step 5."
  note "  3. claude CLI version too old. Fix: brew upgrade claude  (or reinstall)"
  note "  4. Network / Anthropic outage. Try again in a minute."
  return 1
}

# --- next-steps banner -----------------------------------------------------

print_next_steps() {
  cat <<'NEXT'

============================================================
  SETUP COMPLETE — three things still need to happen by hand
============================================================

1. Log into Claude on this Mac (one-time, opens a browser):

       claude login

   Use the SAME Anthropic Max-plan account as your dev Mac.

2. Paste these four lines into .claude/settings.json's "permissions.allow"
   array (so the chat-driven file move flow works for ALL consultants):

       "Bash(mv ./consultants/**)",
       "Bash(cp ./consultants/**)",
       "Bash(ls ./consultants/**)",
       "Bash(cat ./consultants/**)"

3. Confirm the chat permissions are in place (spawns one tiny test turn):

       ./scripts/install.sh verify

   If this passes, every teammate's chat works the same way (the system
   is per-host, not per-user — see docs/HOST-SETUP.md#trust-model).

4. Auto-start the services on boot (optional but recommended):

       ./scripts/install.sh launchd

For remote access from teammates' phones, see docs/HOST-SETUP.md
(Tailscale Funnel section).

Smoke test the running services:
   curl -s http://127.0.0.1:3000/healthz | python3 -m json.tool
   open http://127.0.0.1:3010

NEXT
}

# --- entry point -----------------------------------------------------------

main() {
  local sub="${1:-install}"
  case "$sub" in
    check)     cmd_check ;;
    verify)    cmd_verify ;;
    launchd)   cmd_launchd ;;
    restart)   cmd_restart ;;
    uninstall) cmd_uninstall ;;
    install|"")
      cmd_check
      require_macos
      setup_env_file
      ensure_dirs
      setup_backend
      setup_frontend
      print_next_steps
      ;;
    *)
      red "Unknown subcommand: $sub"
      echo "Usage: $0 [check|install|verify|launchd|restart|uninstall]"
      exit 1
      ;;
  esac
}

main "$@"
