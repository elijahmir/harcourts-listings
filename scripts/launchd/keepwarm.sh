#!/usr/bin/env bash
# Keep the Claude login token fresh + act as an auth canary.
#
# The claude.ai Max OAuth token in ~/.claude/.credentials.json has a ~8h life
# and only auto-refreshes when it is USED while eli is the GUI console user.
# Running this every ~4h (via com.copypro.keepwarm) keeps it from ever expiring
# idle. If the auth has broken, the log line is tagged ALERT so a glance at
# logs/keepwarm.log tells you immediately.
set -uo pipefail

CLAUDE=/Users/eli/.nvm/versions/node/v24.16.0/bin/claude
LOG=/Users/eli/srv/harcourts-listings/logs/keepwarm.log
TS=$(date '+%Y-%m-%d %H:%M:%S')

# Run from HOME so we don't load a project CLAUDE.md; minimal prompt = minimal cost.
cd /Users/eli || exit 0
OUT=$("$CLAUDE" --print "reply with: pong" 2>&1 | head -3 | tr '\n' ' ')

if echo "$OUT" | grep -qiE '401|invalid|authenticate|not logged|bearer'; then
  echo "$TS ALERT auth-failing: $OUT" >> "$LOG"
  /usr/bin/osascript -e 'display notification "CopyPro Claude login needs re-auth (see RUNBOOK)" with title "CopyPro auth"' 2>/dev/null || true
else
  echo "$TS ok: $OUT" >> "$LOG"
fi
