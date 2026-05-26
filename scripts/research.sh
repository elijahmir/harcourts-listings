#!/usr/bin/env bash
# Deep-research wrapper around the google-ai-mode skill at
# shared/skills/google-ai-mode/. Used by the consultant Claude during
# Phase 1 / market-context research for a listing. Returns a markdown
# block with the AI synthesis + inline source citations [1][2][3].
#
# Usage (from anywhere in the project):
#
#   ./scripts/research.sh "school catchments near Penguin TAS 2026"
#   ./scripts/research.sh "Tasmania coastal property market 2026 trends"
#
# First-run cost: the skill auto-installs its own .venv + Playwright
# (~200 MB browser binaries) the first time it runs. Subsequent runs
# are 10-30s each.
#
# This is COMPLEMENTARY to Claude's built-in WebSearch / WebFetch — use
# this when you want a synthesised answer pulling from multiple sources,
# WebSearch when you want a raw list of links to inspect.

set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ROOT="$( dirname "$SCRIPT_DIR" )"
SKILL_DIR="$ROOT/shared/skills/google-ai-mode"

if [[ ! -d "$SKILL_DIR" ]]; then
    echo "FAIL: skill directory not found at $SKILL_DIR" >&2
    echo "(Should have been added under shared/skills/google-ai-mode/ in the repo)" >&2
    exit 1
fi

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <query>" >&2
    echo "Example: $0 \"school catchments near Penguin TAS\"" >&2
    exit 2
fi

# The skill's run.py wrapper handles venv bootstrap. We use --save so
# results land in shared/skills/google-ai-mode/results/ for audit and
# so the chat agent can re-read them without another browser run.
cd "$SKILL_DIR"
PYTHON="$(command -v python3)"
if [[ -x ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
fi
exec "$PYTHON" scripts/run.py search.py --query "$*" --save
