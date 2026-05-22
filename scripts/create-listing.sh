#!/usr/bin/env bash
# Start a new listing session. Pick a consultant, then exec claude from inside their folder
# so the consultant's CLAUDE.md is auto-loaded as the active persona.

set -euo pipefail

# Move to project root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Welcome banner.
cat <<'BANNER'
========================================================
  Harcourts Ulverstone & Penguin — Listing Generator
========================================================
BANNER

# Consultant roster. Order matters: numeric selection maps to this list.
NAMES=(
  "Wendy Squibb"
  "Kurt Knowles"
  "Jakub Lehman"
  "Jarrod Burr"
  "Raymond Buitenhuis"
  "Jodi Tunn"
  "Colin Tunn"
)
SLUGS=(
  "wendy-squibb"
  "kurt-knowles"
  "jakub-lehman"
  "jarrod-burr"
  "raymond-buitenhuis"
  "jodi-tunn"
  "colin-tunn"
)

echo
echo "Which Property Sales Consultant is this listing for?"
echo
for i in "${!NAMES[@]}"; do
  printf "  %d. %s\n" "$((i + 1))" "${NAMES[$i]}"
done
echo

# Lowercase helper that works on both bash 3 (macOS default) and bash 4+.
to_lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

SELECTED_SLUG=""
SELECTED_NAME=""

while [[ -z "$SELECTED_SLUG" ]]; do
  read -r -p "Reply with a name or number: " CHOICE
  CHOICE="${CHOICE#"${CHOICE%%[![:space:]]*}"}"  # ltrim
  CHOICE="${CHOICE%"${CHOICE##*[![:space:]]}"}"  # rtrim

  if [[ -z "$CHOICE" ]]; then
    echo "Please enter a name or a number."
    continue
  fi

  # Numeric selection.
  if [[ "$CHOICE" =~ ^[1-7]$ ]]; then
    idx=$((CHOICE - 1))
    SELECTED_SLUG="${SLUGS[$idx]}"
    SELECTED_NAME="${NAMES[$idx]}"
    break
  fi

  # Fuzzy name match: case-insensitive substring against full name or slug.
  CHOICE_LC="$(to_lower "$CHOICE")"
  MATCHES=()
  for i in "${!NAMES[@]}"; do
    NAME_LC="$(to_lower "${NAMES[$i]}")"
    SLUG_LC="${SLUGS[$i]}"
    if [[ "$NAME_LC" == *"$CHOICE_LC"* || "$SLUG_LC" == *"$CHOICE_LC"* ]]; then
      MATCHES+=("$i")
    fi
  done

  if [[ ${#MATCHES[@]} -eq 0 ]]; then
    echo "No match for '$CHOICE'. Try a number or a clearer name."
    continue
  fi

  if [[ ${#MATCHES[@]} -gt 1 ]]; then
    echo "That matches more than one consultant:"
    for m in "${MATCHES[@]}"; do
      printf "  - %s\n" "${NAMES[$m]}"
    done
    echo "Please be more specific."
    continue
  fi

  idx="${MATCHES[0]}"
  CANDIDATE_NAME="${NAMES[$idx]}"
  CANDIDATE_SLUG="${SLUGS[$idx]}"
  read -r -p "I read that as '$CANDIDATE_NAME'. Correct? [Y/n] " CONFIRM
  CONFIRM="$(to_lower "${CONFIRM:-y}")"
  if [[ "$CONFIRM" == "y" || "$CONFIRM" == "yes" ]]; then
    SELECTED_SLUG="$CANDIDATE_SLUG"
    SELECTED_NAME="$CANDIDATE_NAME"
  fi
done

# Email capture with simple validation: must contain @ and a dot after the @, no spaces.
EMAIL=""
ATTEMPTS=0
while [[ -z "$EMAIL" && $ATTEMPTS -lt 3 ]]; do
  read -r -p "What is your email? I will tag the session record with it: " RAW_EMAIL
  RAW_EMAIL="${RAW_EMAIL#"${RAW_EMAIL%%[![:space:]]*}"}"
  RAW_EMAIL="${RAW_EMAIL%"${RAW_EMAIL##*[![:space:]]}"}"
  if [[ "$RAW_EMAIL" == *" "* ]]; then
    echo "Email cannot contain spaces. Try again."
  elif [[ "$RAW_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
    EMAIL="$RAW_EMAIL"
  else
    echo "That does not look like a valid email. It must contain an @ and a dot after the @."
  fi
  ATTEMPTS=$((ATTEMPTS + 1))
done

if [[ -z "$EMAIL" ]]; then
  echo "No valid email after several tries. Exiting."
  exit 1
fi

TARGET_DIR="$PROJECT_ROOT/consultants/$SELECTED_SLUG"
if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Consultant folder missing: $TARGET_DIR"
  exit 1
fi

echo
echo "Loading $SELECTED_NAME's workspace ($SELECTED_SLUG)."
echo "Session will be tagged with: $EMAIL"
echo

# Expose the email to Claude so the consultant CLAUDE.md can record it on the session folder.
export HARCOURTS_USER_EMAIL="$EMAIL"
export HARCOURTS_CONSULTANT_SLUG="$SELECTED_SLUG"
export HARCOURTS_CONSULTANT_NAME="$SELECTED_NAME"

# Load .env (if present) so VaultRE and any other shared config make it into
# the Claude session. .env is gitignored.
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$PROJECT_ROOT/.env"
  set +a
fi

cd "$TARGET_DIR"

if ! command -v claude >/dev/null 2>&1; then
  echo "The 'claude' command is not on PATH. Install Claude Code, then re-run this script."
  exit 1
fi

# Use 'acceptEdits' permission mode so claude auto-approves file edits that
# the workflow requires (creating session folders, writing session.json, etc.)
# without nagging the staff member. This still prompts on Bash and other
# escalations, which is the right safety baseline for an unattended chat.
exec claude --permission-mode acceptEdits
