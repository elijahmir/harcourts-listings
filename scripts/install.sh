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
#   ./scripts/install.sh funnel      # configure Tailscale Serve + Funnel (public HTTPS URL)
#   ./scripts/install.sh funnel-off  # tear down Tailscale Serve + Funnel
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
    yellow "  copied .env.example -> .env (filling in details next)"
  else
    green "  .env exists — only filling in missing values"
  fi
  prompt_missing_env_vars
}

# Read a key from .env. Empty string if absent or unset.
_get_env() {
  local key="$1"
  local val
  val="$(grep -E "^${key}=" "$PROJECT_ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  echo "$val"
}

# Set a key in .env (in-place if present, append otherwise). Quotes the
# value to handle whitespace + special chars cleanly. The marker comment
# above each block makes it obvious where each value came from on later
# inspection.
_set_env() {
  local key="$1" val="$2" comment="${3:-}"
  local tmp
  tmp="$(mktemp)"
  if grep -qE "^${key}=" "$PROJECT_ROOT/.env" 2>/dev/null; then
    # Existing line — replace its value with the new one. Using awk to
    # avoid sed's portability headaches around special chars on macOS.
    awk -v k="$key" -v v="$val" '
      BEGIN{FS=OFS="="}
      $1==k {print k"="v; next}
      {print}
    ' "$PROJECT_ROOT/.env" > "$tmp"
    mv "$tmp" "$PROJECT_ROOT/.env"
  else
    {
      [[ -n "$comment" ]] && printf "\n# %s\n" "$comment"
      printf "%s=%s\n" "$key" "$val"
    } >> "$PROJECT_ROOT/.env"
  fi
}

# Prompts the operator for any required env vars that are missing. Stdin
# is /dev/tty so we don't get tripped up if the script is piped from a
# remote one-liner. If stdin can't be opened (truly headless context),
# we skip prompting and just print a checklist the operator can fill in.
prompt_missing_env_vars() {
  local interactive=true
  if [[ ! -t 0 ]] && ! exec 0</dev/tty 2>/dev/null; then
    interactive=false
  fi

  hdr "Checking required secrets in .env"

  # ---- VaultRE -----------------------------------------------------------
  local vre_key="$(_get_env VAULTRE_API_KEY)"
  local vre_tok="$(_get_env VAULTRE_API_TOKEN)"
  if [[ -z "$vre_key" || "$vre_key" == "REPLACE_ME" ]]; then
    if [[ "$interactive" == true ]]; then
      echo
      note "  Need VaultRE API key (from your VaultRE admin)."
      read -r -p "    VAULTRE_API_KEY: " vre_key
      [[ -n "$vre_key" ]] && _set_env VAULTRE_API_KEY "$vre_key"
    else
      yellow "  VAULTRE_API_KEY missing — set it in .env before running funnel."
    fi
  else
    green "  VAULTRE_API_KEY present"
  fi
  if [[ -z "$vre_tok" || "$vre_tok" == "REPLACE_ME" ]]; then
    if [[ "$interactive" == true ]]; then
      read -r -p "    VAULTRE_API_TOKEN: " vre_tok
      [[ -n "$vre_tok" ]] && _set_env VAULTRE_API_TOKEN "$vre_tok"
    else
      yellow "  VAULTRE_API_TOKEN missing — set it in .env before running funnel."
    fi
  else
    green "  VAULTRE_API_TOKEN present"
  fi

  # ---- Supabase JWT secret (production auth) -----------------------------
  # Skip prompting if the operator explicitly opted into dev mode. On a
  # production host, this secret is the entire gate between Funnel-public
  # URL and the chat backend — without it, anyone who learns the URL is
  # in. Make this prompt loud.
  local require_auth="$(_get_env HARCOURTS_REQUIRE_AUTH)"
  if [[ "$require_auth" != "false" ]]; then
    local jwt_secret="$(_get_env HARCOURTS_SUPABASE_JWT_SECRET)"
    if [[ -z "$jwt_secret" || "$jwt_secret" == "REPLACE_ME" ]]; then
      if [[ "$interactive" == true ]]; then
        echo
        note "  Need Supabase JWT Secret (from Supabase admin →"
        note "  Project Settings → API → JWT Secret). Without this, the"
        note "  chat backend rejects every Vercel/browser request as 401."
        note "  (To skip and run in unauthed dev mode, leave blank and we"
        note "  will set HARCOURTS_REQUIRE_AUTH=false.)"
        read -r -p "    HARCOURTS_SUPABASE_JWT_SECRET: " jwt_secret
        if [[ -n "$jwt_secret" ]]; then
          _set_env HARCOURTS_SUPABASE_JWT_SECRET "$jwt_secret" \
            "Supabase JWT signing secret (HS256) — required for production auth"
          _set_env HARCOURTS_REQUIRE_AUTH "true" \
            "Reject unauthed requests when true"
          green "  Supabase JWT secret saved — auth ENABLED"
        else
          _set_env HARCOURTS_REQUIRE_AUTH "false" \
            "Dev mode: skip JWT verification (do NOT use in production)"
          yellow "  No secret entered — falling back to DEV mode (no auth)"
          yellow "  Re-run \`./scripts/install.sh\` to set it later."
        fi
      else
        yellow "  HARCOURTS_SUPABASE_JWT_SECRET missing and no TTY for"
        yellow "  prompting. Add it to .env before exposing the funnel."
      fi
    else
      green "  HARCOURTS_SUPABASE_JWT_SECRET present — auth enabled"
      _set_env HARCOURTS_REQUIRE_AUTH "true"
    fi
  else
    yellow "  HARCOURTS_REQUIRE_AUTH=false (dev mode — funnel URL is open)"
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
    <string>8787</string>
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
  note "Test:  curl -s http://127.0.0.1:8787/healthz"
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

# --- Tailscale Funnel ------------------------------------------------------
# Tailscale Funnel exposes ONE entry point publicly over HTTPS. Our stack has
# two ports (frontend on 3010, backend on 8787), so we register each path
# as a public Funnel route to fan out behind that single entry point:
#
#   /          → frontend (3010)
#   /api/*     → backend  (8787)
#   /healthz   → backend  (8787)
#   /ws/*      → backend  (8787)  ← WebSocket; Tailscale proxies HTTP/1.1 Upgrade
#
# This script targets Tailscale 1.96+ (the `--set-path` form on `funnel`
# directly; the old `serve` then `funnel <target>` pattern silently
# clobbered the / mapping in 1.96, see the funnel block below).

resolve_tailscale_cli() {
  # Prefer brew-installed CLI, then App Store version's bundled binary.
  if command -v tailscale >/dev/null 2>&1; then
    echo "tailscale"; return 0
  fi
  if [[ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]]; then
    echo "/Applications/Tailscale.app/Contents/MacOS/Tailscale"; return 0
  fi
  return 1
}

cmd_funnel() {
  hdr "Tailscale Funnel — public HTTPS URL"

  local TS
  if ! TS="$(resolve_tailscale_cli)"; then
    red "  tailscale CLI not found."
    note "  Options to install:"
    note "    A. brew install tailscale && sudo brew services start tailscale"
    note "    B. If you have the App Store Tailscale GUI, expose the CLI:"
    note "         sudo ln -sf /Applications/Tailscale.app/Contents/MacOS/Tailscale \\"
    note "             /usr/local/bin/tailscale"
    return 1
  fi
  green "  tailscale CLI: $TS ($("$TS" version 2>&1 | head -1))"

  # Confirm tailscale is logged in. If TS_AUTHKEY is exported in the env,
  # attempt unattended bringup using it — this is what makes Neo (or any
  # SSH-only host) work without a human in front of a browser. The key
  # comes from https://login.tailscale.com/admin/settings/keys and should
  # be set BEFORE running this script:
  #     export TS_AUTHKEY=tskey-auth-XXXXXX
  #     ./scripts/install.sh funnel
  if ! "$TS" status >/dev/null 2>&1; then
    if [[ -n "${TS_AUTHKEY:-}" ]]; then
      note "  TS_AUTHKEY found — running unattended \`tailscale up\`…"
      if ! "$TS" up --authkey="$TS_AUTHKEY" --accept-routes 2>&1; then
        red "  unattended tailscale up failed. Check that TS_AUTHKEY is valid"
        red "  (regenerate at https://login.tailscale.com/admin/settings/keys)."
        return 1
      fi
      green "  tailscale up succeeded via TS_AUTHKEY."
    else
      red "  not logged into Tailscale on this Mac."
      note "  Two options:"
      note "    A) Interactive:  $TS up    (browser opens, sign in, re-run this command)"
      note "    B) Unattended:   export TS_AUTHKEY=tskey-auth-XXXX  &&  re-run this command"
      note "       Generate the key at https://login.tailscale.com/admin/settings/keys"
      return 1
    fi
  fi
  local TAILNET_NAME
  TAILNET_NAME="$("$TS" status --self --json 2>/dev/null \
                | python3 -c "import sys, json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" \
                2>/dev/null || true)"
  if [[ -z "$TAILNET_NAME" ]]; then
    yellow "  could not auto-detect this Mac's tailnet hostname."
    note   "  Run \`$TS status\` manually to confirm Tailscale is up."
  else
    green "  tailnet hostname: $TAILNET_NAME"
  fi

  # Pre-flight: confirm the one-time tailnet bootstrap has been done. Three
  # things must be on at the *tailnet* level (not per-node) — none of them
  # can be set via the Tailscale REST API (enabling HTTPS certs is a
  # legal opt-in to Let's Encrypt's public CT log), so this pre-flight
  # cannot self-heal. It can only fail loudly with the exact URLs to click.
  # See docs/HOST-SETUP.md section 0 for the full rationale.
  hdr "Pre-flight: tailnet bootstrap check"
  local PROBE_OUT
  PROBE_OUT="$("$TS" serve --bg --yes --set-path=/_probe 3010 </dev/null 2>&1 || true)"
  "$TS" serve reset >/dev/null 2>&1 || true
  if echo "$PROBE_OUT" | grep -qiE "serve is not enabled|funnel is not allowed|not allowed to use funnel"; then
    red "  Tailnet bootstrap incomplete. The Tailscale admin console toggles"
    red "  must be set ONCE for the whole tailnet before any host can serve"
    red "  a Funnel URL. These are NOT API-settable."
    echo
    note "  Open these three URLs in a browser and complete them:"
    note "  1) https://login.tailscale.com/admin/dns"
    note "       — turn on MagicDNS and HTTPS Certificates"
    note "  2) https://login.tailscale.com/admin/acls/file"
    note "       — add the nodeAttrs funnel block (see HOST-SETUP.md §0.2)"
    note "  3) https://login.tailscale.com/admin/settings/keys (optional)"
    note "       — generate a TS_AUTHKEY for unattended host bringup"
    echo
    note "  Raw CLI output for diagnosis:"
    echo "$PROBE_OUT" | sed 's/^/    /'
    return 1
  fi
  green "  Tailnet bootstrap looks good — proceeding."

  # Wipe any existing serve/funnel state so this is idempotent.
  note "  tearing down any previous tailscale serve/funnel config…"
  "$TS" serve reset >/dev/null 2>&1 || true
  "$TS" funnel reset >/dev/null 2>&1 || true

  # Configure path-based routing directly via `tailscale funnel`. Two
  # gotchas baked in from earlier debugging — both verified live:
  #
  #   1. The `funnel <target>` form (no --set-path) means "proxy / to
  #      target", which silently overwrites any existing / mapping. Don't
  #      use that pattern.
  #   2. `--set-path=/X 8787` strips the /X prefix when forwarding (treats
  #      port as http://127.0.0.1:8787 with no path), so a request to
  #      /healthz hits the backend's / route → 404. The fix is to pass a
  #      full target URL including the path: the prefix is still stripped
  #      but the target's own path is appended, so the net request to the
  #      backend keeps the original path. Verified: /api/sessions/X →
  #      http://127.0.0.1:8787/api/sessions/X.
  #
  #   /          → frontend (3010)
  #   /api/*     → backend  (8787) at /api/*
  #   /healthz   → backend  (8787) at /healthz
  #   /ws/*      → backend  (8787) at /ws/*  (WS upgrade flows through)
  hdr "Configuring Tailscale Funnel (path → port routing, all public)"
  set +e
  "$TS" funnel --bg --yes --set-path=/        3010
  "$TS" funnel --bg --yes --set-path=/api     http://127.0.0.1:8787/api
  "$TS" funnel --bg --yes --set-path=/healthz http://127.0.0.1:8787/healthz
  "$TS" funnel --bg --yes --set-path=/ws      http://127.0.0.1:8787/ws
  local rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    red "  funnel command failed (exit $rc)."
    note "  Common causes:"
    note "  1. Funnel isn't enabled for this node yet. Visit:"
    note "       https://login.tailscale.com/admin/settings/funnel"
    note "     and add this machine's name to the allowed list."
    note "  2. HTTPS certs aren't enabled. Visit:"
    note "       https://login.tailscale.com/admin/dns"
    note "     and enable both MagicDNS and HTTPS certificates."
    return 1
  fi

  green "  Funnel enabled."

  echo
  if [[ -n "$TAILNET_NAME" ]]; then
    cat <<EOF
============================================================
  PUBLIC URL: https://${TAILNET_NAME}
============================================================

Share that URL with teammates. Their phones / laptops do NOT need
Tailscale installed. Any device on any network can reach it.

Quick test:
   curl -sI https://${TAILNET_NAME} | head -1            # → HTTP/2 200
   curl -s https://${TAILNET_NAME}/healthz               # → JSON with consultants

============================================================
  ⚡  NEXT — wire this URL into HUP-Sales-App on Vercel
============================================================

Copy these EXACT key/value pairs into Vercel env vars
(HUP-Sales-App project → Settings → Environment Variables):

  NEXT_PUBLIC_HARCOURTS_BACKEND_URL = https://${TAILNET_NAME}

Then redeploy the Vercel app so the build picks up the new value:

   cd /path/to/HUP-Sales-App
   vercel --prod

(or click "Redeploy" in the Vercel dashboard)

Once that's done, /dashboard/copypro on the live HUP-Sales-App will
talk to this Mac's backend over HTTPS.
============================================================
EOF
  else
    cat <<EOF
============================================================
  Funnel is up — check the URL with:
      $TS serve status
============================================================
EOF
  fi
}

cmd_funnel_off() {
  hdr "Tailscale Funnel — tear down"
  local TS
  if ! TS="$(resolve_tailscale_cli)"; then
    red "  tailscale CLI not found, nothing to do."
    return 0
  fi
  "$TS" funnel reset 2>/dev/null || "$TS" funnel --bg off 2>/dev/null || true
  "$TS" serve  reset 2>/dev/null || "$TS" serve  --bg off 2>/dev/null || true
  green "  Funnel and Serve configurations cleared."
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

4. Auto-start the services on boot:

       ./scripts/install.sh launchd

5. Publish a public HTTPS URL for teammates (Tailscale Funnel — required
   for production; teammates need NO install on their devices):

       ./scripts/install.sh funnel

   Prereq: \`tailscale\` CLI is installed AND logged in. If the command
   prints an install/login hint, follow it and re-run.

Smoke test locally first:
   curl -s http://127.0.0.1:8787/healthz | python3 -m json.tool
   open http://127.0.0.1:3010

Then over the public URL (after funnel is up):
   curl -s https://<your-mac>.tail-xxxxxx.ts.net/healthz

NEXT
}

# --- entry point -----------------------------------------------------------

main() {
  local sub="${1:-install}"
  case "$sub" in
    check)      cmd_check ;;
    verify)     cmd_verify ;;
    launchd)    cmd_launchd ;;
    funnel)     cmd_funnel ;;
    funnel-off) cmd_funnel_off ;;
    restart)    cmd_restart ;;
    uninstall)  cmd_uninstall ;;
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
      echo "Usage: $0 [check|install|verify|launchd|funnel|funnel-off|restart|uninstall]"
      exit 1
      ;;
  esac
}

main "$@"
