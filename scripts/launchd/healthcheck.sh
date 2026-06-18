#!/usr/bin/env bash
# Backend liveness + console-user check, every 30 min (via com.copypro.healthcheck).
# Logs only failures (plus a once-a-day heartbeat) so the log stays readable.
set -uo pipefail

LOG=/Users/eli/srv/harcourts-listings/logs/healthcheck.log
TS=$(date '+%Y-%m-%d %H:%M:%S')

HEALTH=$(curl -sS -m5 http://127.0.0.1:8787/healthz 2>&1 | head -c 60)
echo "$HEALTH" | grep -q '"ok":true' && BE=ok || BE=DOWN

# Token refresh needs eli to be the GUI console user.
CONSOLE=$(stat -f "%Su" /dev/console 2>/dev/null || echo "?")

# Tunnel
pgrep -f ngrok >/dev/null && TUN=up || TUN=DOWN

if [ "$BE" != "ok" ] || [ "$CONSOLE" != "eli" ] || [ "$TUN" != "up" ]; then
  echo "$TS ALERT backend=$BE console=$CONSOLE tunnel=$TUN" >> "$LOG"
  /usr/bin/osascript -e 'display notification "CopyPro health issue (see RUNBOOK-auth-recovery)" with title "CopyPro"' 2>/dev/null || true
else
  # heartbeat once a day (when minute is ~00:00-00:29 window of the 30-min ticks)
  HOUR=$(date '+%H'); MIN=$(date '+%M')
  if [ "$HOUR" = "09" ] && [ "$MIN" -lt 30 ]; then
    echo "$TS ok backend=$BE console=$CONSOLE tunnel=$TUN" >> "$LOG"
  fi
fi
