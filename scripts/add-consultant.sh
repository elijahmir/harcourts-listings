#!/usr/bin/env bash
# Add a new consultant by copying the template and filling in the name.
# Usage:  ./scripts/add-consultant.sh "Jane Smith"

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 \"Full Name\""
  exit 1
fi

FULL_NAME="$1"

# Trim surrounding whitespace.
FULL_NAME="${FULL_NAME#"${FULL_NAME%%[![:space:]]*}"}"
FULL_NAME="${FULL_NAME%"${FULL_NAME##*[![:space:]]}"}"

if [[ -z "$FULL_NAME" ]]; then
  echo "Name cannot be empty."
  exit 1
fi

# Build a kebab-case slug from the name.
SLUG="$(printf '%s' "$FULL_NAME" \
  | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"

if [[ -z "$SLUG" ]]; then
  echo "Could not derive a slug from '$FULL_NAME'."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TEMPLATE_DIR="$PROJECT_ROOT/consultants/_template"
TARGET_DIR="$PROJECT_ROOT/consultants/$SLUG"

if [[ ! -d "$TEMPLATE_DIR" ]]; then
  echo "Template missing at $TEMPLATE_DIR. Cannot continue."
  exit 1
fi

if [[ -e "$TARGET_DIR" ]]; then
  echo "A consultant folder already exists at $TARGET_DIR."
  echo "Pick a different name, or remove the existing folder first."
  exit 1
fi

cp -R "$TEMPLATE_DIR" "$TARGET_DIR"

# Replace placeholder in every markdown file inside the new folder.
# sed -i '' works on macOS; GNU sed needs -i without the empty string. Detect.
if sed --version >/dev/null 2>&1; then
  SED_INPLACE=(sed -i)
else
  SED_INPLACE=(sed -i '')
fi

find "$TARGET_DIR" -type f -name "*.md" -print0 \
  | xargs -0 "${SED_INPLACE[@]}" -e "s/{CONSULTANT_NAME}/$FULL_NAME/g" -e "s/{CONSULTANT_SLUG}/$SLUG/g"

cat <<NEXT

Created consultants/$SLUG/ for "$FULL_NAME".

Next steps:
  1. cd consultants/$SLUG
  2. Run: claude
  3. The system will notice the profile is empty and offer to onboard $FULL_NAME.

Remember to add "$FULL_NAME" to the numbered list in the root CLAUDE.md so the
master prompt offers them as an option on the next session.

NEXT
