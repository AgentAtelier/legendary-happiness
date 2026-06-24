#!/usr/bin/env bash
# forge lint — Ruff gate (recurrence-preventer).  Phase 0.9.
#
# Distinct from scripts/check.sh (which adds `ruff format --check` + the
# 500-line file-length gate).  This script is the fast feedback one — just
# lint, ~3 s on the full tree.
#
# Usage:
#   scripts/lint.sh          # lint-only (default)
#   scripts/lint.sh --fix     # apply safe auto-fixes (e.g. sort imports)
#   scripts/lint.sh --stats   # also print per-rule statistics
#
# Exit code: 0 on clean, 1 on violations.  Acceptable-violation rules
# (see docs/current/ACCEPTED.md) are whitelisted via `pyproject.toml`.

set -euo pipefail

RUFF=""
for venv in "$PWD/foundry/.venv/bin/ruff" "$PWD/hub/.venv/bin/ruff" "$(command -v ruff || true)"; do
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
ARGS+=(foundry/ hub/)

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
    "$RUFF" check foundry/ hub/ --statistics || true
fi

echo ""
echo "Lint clean.  ACCEPTED.md tracks deliberate ruff-disabled rules."
