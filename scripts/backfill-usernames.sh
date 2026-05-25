#!/usr/bin/env bash
# Backfill historical SQLite user_name rows to use full Supabase
# identities. Once HUP-Sales-App becomes the chat's primary entry point,
# every new session gets its user_name from the verified JWT's `email`
# claim — but the rows that pre-date that switch carry whatever name
# the operator typed into the localStorage name-prompt ("Elijah",
# "Sarah", etc.). This script normalises those so the audit/history
# panel reads cleanly.
#
# It's safe to run multiple times — each mapping is conditional on
# the current value being the un-normalised display name.
#
# Usage:
#   ./scripts/backfill-usernames.sh
#   ./scripts/backfill-usernames.sh --dry-run
#
# Add new mappings below as needed. Format:  display_name → email
set -euo pipefail

ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
DB="$ROOT/data/listings.db"

if [[ ! -f "$DB" ]]; then
  echo "FAIL: SQLite db not found at $DB" >&2
  exit 1
fi

DRY=false
[[ "${1:-}" == "--dry-run" ]] && DRY=true

# Add mappings here as the team onboards. The right-hand side is the
# Supabase email claim — the canonical identity we'll see going forward.
declare -a MAPPINGS=(
  "Elijah|elijah.mirandilla@harcourts.com.au"
)

run_sql() {
  if [[ "$DRY" == true ]]; then
    echo "would run: sqlite3 \"$DB\" \"$1\""
  else
    sqlite3 "$DB" "$1"
  fi
}

for m in "${MAPPINGS[@]}"; do
  from="${m%%|*}"
  to="${m#*|}"
  affected="$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE user_name='$from';")"
  echo "  $from → $to  ($affected sessions)"
  if [[ "$affected" -gt 0 ]]; then
    run_sql "UPDATE sessions SET user_name='$to' WHERE user_name='$from';"
  fi
done

echo
echo "Done. New session creates from HUP-Sales-App will use the email claim automatically."
