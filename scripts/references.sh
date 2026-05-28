#!/usr/bin/env bash
# Fetch this consultant's thumbs-up writing references for the current
# chat user — the strong past listings the agent should study in Phase 3.
#
# Reads from the environment the backend injects into the chat subprocess
# (see services/backend/app/runner.py). It does NOT read .env; the secret
# arrives via the parent process, never printed:
#   HARCOURTS_BACKEND_URL      e.g. http://127.0.0.1:8787
#   HARCOURTS_INTERNAL_TOKEN   shared secret authenticating this wrapper
#   HARCOURTS_CHAT_USER_EMAIL  who's chatting (scopes to their up-votes)
#   HARCOURTS_CONSULTANT_SLUG  active consultant
#
# The backend returns: the caller's own thumbs-up listings + any
# admin-promoted public references, for this consultant only, newest
# first, with full body_md so the agent can study tone + structure.
#
# Usage:
#   ./scripts/references.sh                  # recent up-voted refs (default 5)
#   ./scripts/references.sh "highland lake"  # place/environment keyword match
#   ./scripts/references.sh "" 3             # explicit limit
set -euo pipefail

QUERY="${1:-}"
LIMIT="${2:-5}"

: "${HARCOURTS_BACKEND_URL:?references.sh: HARCOURTS_BACKEND_URL not set}"
: "${HARCOURTS_INTERNAL_TOKEN:?references.sh: HARCOURTS_INTERNAL_TOKEN not set}"
: "${HARCOURTS_CHAT_USER_EMAIL:?references.sh: HARCOURTS_CHAT_USER_EMAIL not set}"
: "${HARCOURTS_CONSULTANT_SLUG:?references.sh: HARCOURTS_CONSULTANT_SLUG not set}"

# Minimal URL-encoder for query-string values (addresses are ASCII).
urlencode() {
  local s="$1" out="" c i
  for (( i=0; i<${#s}; i++ )); do
    c="${s:$i:1}"
    case "$c" in
      [a-zA-Z0-9._~-]) out+="$c" ;;
      *) printf -v c '%%%02X' "'$c"; out+="$c" ;;
    esac
  done
  printf '%s' "$out"
}

url="${HARCOURTS_BACKEND_URL%/}/api/listings/references"
url+="?consultant_slug=$(urlencode "$HARCOURTS_CONSULTANT_SLUG")"
url+="&as_user=$(urlencode "$HARCOURTS_CHAT_USER_EMAIL")"
url+="&limit=$(urlencode "$LIMIT")"
if [[ -n "$QUERY" ]]; then
  url+="&q=$(urlencode "$QUERY")"
fi

curl -sS -H "X-Internal-Token: ${HARCOURTS_INTERNAL_TOKEN}" "$url"
