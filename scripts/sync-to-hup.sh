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
# no diff filtering. The Supabase identity adapter lives at
# src/components/harcourts-chat/index.tsx in HUP-Sales-App and is
# intentionally NOT in the FILES list below, so re-running this never
# overwrites it. If that adapter needs to change, edit it directly.
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
  "components/avatar-circle.tsx"
  "components/confirm-dialog.tsx"
  "components/session-picker.tsx"
  "components/save-learning-form.tsx"
  "components/upload-button.tsx"
  "components/ui/button.tsx"
  "components/ui/input.tsx"
)

LIB_FILES=(
  "lib/ws.ts"
  "lib/utils.ts"
  "lib/storage.ts"
  "lib/avatars.ts"
)

# Public assets (avatars). Mirrored into HUP's /public/avatars so the
# <img src="/avatars/Wendy.png"> URLs resolve identically on both surfaces.
PUBLIC_DIR_SRC="$SRC_ROOT/apps/web/public/avatars"
PUBLIC_DIR_DST="$DST_ROOT/public/avatars"

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

# Mirror /public/avatars so the slug→/avatars/<Name>.png lookups resolve
# in HUP-Sales-App too. Whole-directory sync — extra avatars don't hurt,
# they're just unused PNGs.
if [[ -d "$PUBLIC_DIR_SRC" ]]; then
  mkdir -p "$PUBLIC_DIR_DST"
  rsync -a $DRY_RUN "$PUBLIC_DIR_SRC/" "$PUBLIC_DIR_DST/"
  echo "  ✓ /public/avatars/ (rsynced)"
fi

# Rewrite @/-style imports → relative paths. harcourts-listings uses
# @/components/* and @/lib/* aliases that resolve at apps/web/src;
# HUP-Sales-App's tsconfig also uses @/* but mapped to ./src/* — so an
# @/components/save-learning-form here points at src/components/, not
# the harcourts-chat folder. We keep the imports relative so this
# rewrite is mechanical and never wrong. index.tsx is the adapter and
# uses @/lib/supabase/client legitimately — we skip it.
if [[ -z "$DRY_RUN" ]]; then
  echo "  → rewriting @/ imports to relative paths…"
  cd "$DST"
  python3 - <<'PYEOF'
import re
from pathlib import Path

RULES = [
    (r'from "@/components/avatar-circle"',      'from "./avatar-circle"'),
    (r'from "@/components/confirm-dialog"',     'from "./confirm-dialog"'),
    (r'from "@/components/save-learning-form"', 'from "./save-learning-form"'),
    (r'from "@/components/session-picker"',     'from "./session-picker"'),
    (r'from "@/components/upload-button"',      'from "./upload-button"'),
    (r'from "@/components/ui/button"',          'from "./button"'),
    (r'from "@/components/ui/input"',           'from "./input"'),
    (r'from "@/lib/avatars"',                   'from "./lib/avatars"'),
    (r'from "@/lib/ws"',                        'from "./lib/ws"'),
    (r'from "@/lib/utils"',                     'from "./lib/utils"'),
    (r'from "@/lib/storage"',                   'from "./lib/storage"'),
]
for f in list(Path(".").glob("*.tsx")) + list(Path("./lib").glob("*.ts")):
    if f.name == "index.tsx":
        continue
    text = orig = f.read_text()
    for pat, repl in RULES:
        text = re.sub(pat, repl, text)
    if text != orig:
        f.write_text(text)
        print(f"     ↪ {f}")
PYEOF
fi

echo
echo "Synced into $DST"
echo
echo "Next:"
echo "  1. cd $DST_ROOT"
echo "  2. npm run build  # verify TypeScript compiles"
echo "  3. Commit + push for Vercel to rebuild"
