#!/usr/bin/env bash
# forge lint — Ruff gate (recurrence-preventer).  Phase 0.9.
#
# Distinct from scripts/check.sh (which adds `ruff format --check` + the
# 500-line file-length gate).  This script is the fast feedback one — just
# lint, ~3 s on the full tree.
#
# Scope: run from foundry/ (where the venv lives) with `ruff check .` so the
# pyproject.toml at the repo root is the single source of truth for rule
# selection, ignores, and excluded paths (`extend-exclude`).  The handful of
# deliberate-style rules that the project chooses to ignore are documented
# in docs/current/ACCEPTED.md.
#
# Usage:
#   scripts/lint.sh          # lint-only (default)
#   scripts/lint.sh --fix     # apply safe auto-fixes (e.g. sort imports)
#   scripts/lint.sh --stats   # also print per-rule statistics
#
# Exit code: 0 on clean, 1 on violations.  Acceptable-violation rules
# (see docs/current/ACCEPTED.md) are whitelisted via `pyproject.toml`.

set -euo pipefail

# Resolve the script's own dir so we can `cd foundry` deterministically
# regardless of the caller's CWD.  Running ruff from foundry/ matches the
# convention in AGENTS.md (every developer runs commands from foundry/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FOUNDRY_DIR="$SCRIPT_DIR/../foundry"
if [ ! -d "$FOUNDRY_DIR" ]; then
    echo "ERROR: foundry/ not found relative to $SCRIPT_DIR" >&2
    exit 2
fi
cd "$FOUNDRY_DIR"

RUFF=""
for venv in "$PWD/.venv/bin/ruff" "$PWD/../hub/.venv/bin/ruff" "$(command -v ruff || true)"; do
    if [ -x "$venv" ]; then RUFF="$venv"; break; fi
done
if [ -z "$RUFF" ]; then
    echo "ERROR: ruff not found.  Install with:" >&2
    echo "  pip install -r foundry/requirements-dev.txt" >&2
    exit 2
fi
echo "=== ruff version ==="
"$RUFF" --version

ARGS=(check)
if [ "${1:-}" = "--fix" ]; then
    ARGS+=(--fix)
fi
ARGS+=(.)

echo "=== ruff ${ARGS[*]} ==="
if ! "$RUFF" "${ARGS[@]}"; then
    echo ""
    echo "Lint FAILED.  Acceptable violations are documented in docs/current/ACCEPTED.md."
    echo "To apply safe auto-fixes: scripts/lint.sh --fix"
    exit 1
fi

if [ "${1:-}" = "--stats" ] || [ "${2:-}" = "--stats" ]; then
    echo ""
    echo "=== ruff statistics ==="
    "$RUFF" check . --statistics || true
fi

echo ""
echo "Lint clean.  ACCEPTED.md tracks deliberate ruff-disabled rules."
