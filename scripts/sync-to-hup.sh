#!/usr/bin/env bash
# Sync the chat UI components from this repo into HUP-Sales-App.
#
# Run after any chat.tsx / session-picker.tsx / save-learning-form.tsx /
# upload-button.tsx / lib/ws.ts edit that you want to ship to the
# Vercel-hosted app at /dashboard/copypro. The destination directory is
# `<HUP-Sales-App>/src/components/harcourts-chat/` — a self-contained
# folder so adding to gitignore later is trivial.
#
# Usage:
#   ./scripts/sync-to-hup.sh                       # uses default path
#   HUP_SALES_APP_PATH=/elsewhere ./scripts/sync-to-hup.sh
#   ./scripts/sync-to-hup.sh --dry-run             # show what would change
#
# This script is intentionally simple — no smart import-path rewriting,
# no diff filtering. After it runs, the HUP-Sales-App-side adapter
# (src/components/harcourts-chat/index.tsx) takes care of bridging
# Supabase identity into the chat hook. If that adapter ever needs to
# change, edit it there; this script never touches it.
set -euo pipefail

SRC_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
DST_ROOT="${HUP_SALES_APP_PATH:-$HOME/Developer/elijahmir/HUP-Sales-App}"
DST="$DST_ROOT/src/components/harcourts-chat"

DRY_RUN=""
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN="--dry-run"
fi

if [[ ! -d "$DST_ROOT" ]]; then
  echo "FAIL: HUP-Sales-App not found at $DST_ROOT" >&2
  echo "      Set HUP_SALES_APP_PATH to override." >&2
  exit 1
fi

echo "Source: $SRC_ROOT/apps/web/src"
echo "Dest:   $DST"
echo

mkdir -p "$DST/lib"

# Files that get copied straight through. The adapter / page wrapper on
# the HUP side imports from `./lib/ws` and `./` so paths stay stable.
FILES=(
  "components/chat.tsx"
  "components/session-picker.tsx"
  "components/save-learning-form.tsx"
  "components/upload-button.tsx"
  "components/ui/button.tsx"
  "components/ui/input.tsx"
)

LIB_FILES=(
  "lib/ws.ts"
  "lib/utils.ts"
)

for f in "${FILES[@]}"; do
  src="$SRC_ROOT/apps/web/src/$f"
  base="$(basename "$f")"
  # Flatten components/ui/* into the same dir for simplicity.
  dst="$DST/$base"
  if [[ -f "$src" ]]; then
    rsync -a $DRY_RUN "$src" "$dst"
    echo "  ✓ $base"
  else
    echo "  ! missing source: $src" >&2
  fi
done

for f in "${LIB_FILES[@]}"; do
  src="$SRC_ROOT/apps/web/src/$f"
  base="$(basename "$f")"
  dst="$DST/lib/$base"
  if [[ -f "$src" ]]; then
    rsync -a $DRY_RUN "$src" "$dst"
    echo "  ✓ lib/$base"
  else
    echo "  ! missing source: $src" >&2
  fi
done

echo
echo "Synced into $DST"
echo
echo "Next:"
echo "  1. cd $DST_ROOT"
echo "  2. Adjust import paths if HUP-Sales-App uses a different @/ alias"
echo "     (the harcourts-listings repo uses @/components/* and @/lib/* —"
echo "      after sync, files reference './session-picker' etc. directly,"
echo "      but the cn() helper still imports from ./lib/utils)"
echo "  3. npm run build  # verify TypeScript compiles in the new context"
echo "  4. Commit + push for Vercel to rebuild"
