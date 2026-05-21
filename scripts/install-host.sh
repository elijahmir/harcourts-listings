#!/usr/bin/env bash
# Idempotent host installer for the Harcourts listing system.
#
# Detects what's already on the Mac, installs the things it can install
# automatically (ttyd, uploader venv), and writes the two launchd plists with
# the right absolute paths for THIS machine. Tailscale and the claude CLI are
# noted but not installed — those need a human in the loop.
#
# Usage:
#   ./scripts/install-host.sh           # install / reinstall everything
#   ./scripts/install-host.sh check     # just report status, change nothing
#   ./scripts/install-host.sh restart   # reload launchd services
#   ./scripts/install-host.sh stop      # unload launchd services
#   ./scripts/install-host.sh uninstall # stop and remove plists

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
TTYD_PLIST="$LAUNCH_AGENTS/com.harcourts.ttyd.plist"
UPLOADER_PLIST="$LAUNCH_AGENTS/com.harcourts.uploader.plist"

# --- output helpers ----------------------------------------------------------

green()  { printf "\033[1;32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[1;33m%s\033[0m\n" "$*"; }
red()    { printf "\033[1;31m%s\033[0m\n" "$*"; }
hdr()    { printf "\n\033[1m==> %s\033[0m\n" "$*"; }

# --- subcommands -------------------------------------------------------------

cmd_check() {
  hdr "Host check"

  if [[ "$(uname)" == "Darwin" ]]; then
    green "  macOS detected ($(sw_vers -productVersion))"
  else
    red "  Not macOS — this installer only supports macOS." ; exit 1
  fi

  if command -v brew >/dev/null 2>&1; then
    green "  Homebrew: $(brew --prefix)"
  else
    red "  Homebrew is missing. Install from https://brew.sh first." ; exit 1
  fi

  if command -v ttyd >/dev/null 2>&1; then
    green "  ttyd:     $(command -v ttyd)"
  else
    yellow "  ttyd:     not installed (the installer will fix this)"
  fi

  if [[ -d /Applications/Tailscale.app ]]; then
    green "  Tailscale GUI: installed"
  else
    yellow "  Tailscale GUI: missing — install from the Mac App Store or https://tailscale.com/download/macos"
  fi

  if command -v claude >/dev/null 2>&1; then
    green "  claude CLI: $(command -v claude)"
  else
    yellow "  claude CLI: not on PATH. Install with one of:"
    yellow "                npm install -g @anthropic-ai/claude-code"
    yellow "                brew install --cask claude-code   (if available on your tap)"
    yellow "              then run 'claude' once and sign in to your Anthropic account."
  fi

  if command -v python3 >/dev/null 2>&1; then
    green "  python3:  $(command -v python3) ($(python3 --version 2>&1))"
  else
    red "  python3:  missing (required for the uploader)" ; exit 1
  fi

  if [[ -f "$PROJECT_ROOT/.env" ]]; then
    green "  .env:     present"
    if grep -q "^HARCOURTS_UPLOADER_BASE_URL=http://localhost" "$PROJECT_ROOT/.env"; then
      yellow "    NOTE: HARCOURTS_UPLOADER_BASE_URL is still localhost. Update it to your Tailnet hostname before phones can use it."
    fi
  else
    yellow "  .env:     missing. Copy .env.example to .env and fill in values."
  fi

  if [[ -d "$PROJECT_ROOT/services/uploader/.venv" ]]; then
    green "  uploader venv: present"
  else
    yellow "  uploader venv: missing (the installer will create it)"
  fi

  if [[ -f "$TTYD_PLIST" ]] && launchctl list com.harcourts.ttyd >/dev/null 2>&1; then
    green "  ttyd service: loaded"
  else
    yellow "  ttyd service: not loaded"
  fi

  if [[ -f "$UPLOADER_PLIST" ]] && launchctl list com.harcourts.uploader >/dev/null 2>&1; then
    green "  uploader service: loaded"
  else
    yellow "  uploader service: not loaded"
  fi
}

ensure_brew_pkg() {
  local pkg="$1"
  if ! command -v "$pkg" >/dev/null 2>&1; then
    hdr "Installing $pkg via brew (may take a minute)"
    brew install "$pkg"
  fi
}

ensure_uploader_venv() {
  hdr "Setting up uploader Python environment"
  cd "$PROJECT_ROOT/services/uploader"
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi
  .venv/bin/pip install --quiet --disable-pip-version-check --upgrade pip
  .venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt
  cd "$PROJECT_ROOT"
}

write_plists() {
  hdr "Writing launchd plists with paths for THIS machine"
  mkdir -p "$LAUNCH_AGENTS"
  mkdir -p "$PROJECT_ROOT/services/ttyd"

  local ttyd_bin brew_prefix
  ttyd_bin="$(command -v ttyd)"
  brew_prefix="$(brew --prefix)"

  cat > "$TTYD_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.harcourts.ttyd</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ttyd_bin</string>
    <string>-p</string>
    <string>7681</string>
    <string>-W</string>
    <string>-t</string>
    <string>titleFixed=Harcourts Listings</string>
    <string>-t</string>
    <string>fontSize=15</string>
    <string>$PROJECT_ROOT/scripts/create-listing.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>$HOME</string>
    <key>PATH</key>
    <string>$brew_prefix/bin:$brew_prefix/sbin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin</string>
    <key>HARCOURTS_PROJECT_ROOT</key>
    <string>$PROJECT_ROOT</string>
  </dict>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/services/ttyd/ttyd.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/services/ttyd/ttyd.log</string>
</dict>
</plist>
EOF
  green "  wrote $TTYD_PLIST"

  cat > "$UPLOADER_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.harcourts.uploader</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PROJECT_ROOT/services/uploader/.venv/bin/python</string>
    <string>$PROJECT_ROOT/services/uploader/server.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>$HOME</string>
    <key>HARCOURTS_PROJECT_ROOT</key>
    <string>$PROJECT_ROOT</string>
    <key>HARCOURTS_UPLOADER_HOST</key>
    <string>0.0.0.0</string>
    <key>HARCOURTS_UPLOADER_PORT</key>
    <string>8080</string>
  </dict>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/services/uploader/uploader.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/services/uploader/uploader.log</string>
</dict>
</plist>
EOF
  green "  wrote $UPLOADER_PLIST"
}

reload_services() {
  hdr "Loading services into launchd"
  for label in com.harcourts.uploader com.harcourts.ttyd; do
    if launchctl list "$label" >/dev/null 2>&1; then
      launchctl unload "$LAUNCH_AGENTS/$label.plist" 2>/dev/null || true
    fi
    launchctl load "$LAUNCH_AGENTS/$label.plist"
    green "  $label loaded"
  done
  sleep 1
}

verify_services() {
  hdr "Verifying services respond"
  local ok=1
  if curl -fsS --max-time 3 http://127.0.0.1:8080/healthz >/dev/null; then
    green "  uploader: healthy at http://127.0.0.1:8080"
  else
    red "  uploader: not responding on http://127.0.0.1:8080 — check $PROJECT_ROOT/services/uploader/uploader.log"
    ok=0
  fi
  # ttyd serves HTML at root; a 200 means it's up
  if curl -fsS --max-time 3 -o /dev/null http://127.0.0.1:7681/; then
    green "  ttyd:     listening at http://127.0.0.1:7681"
  else
    red "  ttyd:     not responding on http://127.0.0.1:7681 — check $PROJECT_ROOT/services/ttyd/ttyd.log"
    ok=0
  fi
  return $((1 - ok))
}

print_next_steps() {
  hdr "Next steps"
  cat <<NEXT

  Local URLs (test on this Mac first):
    Listings: http://localhost:7681
    Photos:   http://localhost:8080

  To make the system reachable from phones and laptops:

  1. Sign in to Tailscale on this Mac (click the Tailscale menu bar icon).
     If you don't have an account, create one — the free tier covers your
     office.

  2. Find this Mac's Tailnet name. Easiest path: Tailscale menu bar icon
     -> "Network devices" -> "This Machine". Copy the name that ends in
     ".ts.net" (looks like "harcourts-mac.tail-xxxx.ts.net").

  3. Edit ${PROJECT_ROOT}/.env and set:
       HARCOURTS_UPLOADER_BASE_URL=http://<that name>:8080

     Then run:  $0 restart

  4. Invite each staff member's phone/laptop to your Tailnet (Tailscale admin
     console -> "Users" -> "Invite users"). They install the Tailscale app,
     accept, and connect.

  5. Send each staff member these two URLs:
       Listings: http://<that name>:7681
       Photos:   http://<that name>:8080
     Plus the guide at docs/MOBILE-SETUP.md.

  Logs:
    Uploader: $PROJECT_ROOT/services/uploader/uploader.log
    ttyd:     $PROJECT_ROOT/services/ttyd/ttyd.log

NEXT
}

cmd_install() {
  cmd_check
  ensure_brew_pkg ttyd
  ensure_uploader_venv
  write_plists
  reload_services
  if verify_services; then
    print_next_steps
  else
    yellow "One or more services failed verification. Check the logs above and re-run:"
    yellow "  $0 restart"
    exit 1
  fi
}

cmd_restart() {
  reload_services
  verify_services
}

cmd_stop() {
  hdr "Stopping services"
  for label in com.harcourts.ttyd com.harcourts.uploader; do
    if launchctl list "$label" >/dev/null 2>&1; then
      launchctl unload "$LAUNCH_AGENTS/$label.plist" 2>/dev/null || true
      green "  $label unloaded"
    else
      yellow "  $label was not running"
    fi
  done
}

cmd_uninstall() {
  cmd_stop
  hdr "Removing plists"
  rm -f "$TTYD_PLIST" "$UPLOADER_PLIST"
  green "  removed $TTYD_PLIST"
  green "  removed $UPLOADER_PLIST"
  yellow "  (kept the venv at services/uploader/.venv — delete it manually if you want it gone)"
}

# --- main --------------------------------------------------------------------

case "${1:-install}" in
  install)    cmd_install ;;
  check)      cmd_check ;;
  restart)    cmd_restart ;;
  stop)       cmd_stop ;;
  uninstall)  cmd_uninstall ;;
  *)
    red "Unknown subcommand: $1"
    echo "Usage: $0 [install|check|restart|stop|uninstall]"
    exit 1
    ;;
esac
