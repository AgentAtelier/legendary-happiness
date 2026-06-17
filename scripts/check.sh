#!/usr/bin/env bash
# forge check — Guardrail script: ruff lint + format check + file-length gate.
# Run from the project root.
#
# Usage:
#   scripts/check.sh          # Full check (ruff + file-length gate)
#   scripts/check.sh --fix    # Same + auto-fix lint violations

set -euo pipefail

RUFF="$PWD/hub/.venv/bin/ruff"
ROOT="$PWD"
MAX_LINES=500

# --- Ruff checks ---
echo "=== ruff check ==="
"$RUFF" check hub/ engine/ "$@"

echo "=== ruff format --check ==="
"$RUFF" format --check hub/ engine/

# --- File-length gate ---
echo "=== file-length gate (max $MAX_LINES lines) ==="
EXIT=0
while IFS= read -r -d '' f; do
    lines=$(wc -l < "$f")
    if [ "$lines" -gt "$MAX_LINES" ]; then
        echo "FAIL: $f is $lines lines (max $MAX_LINES)"
        EXIT=1
    fi
done < <(find "$ROOT/hub" "$ROOT/engine" -name "*.py" -print0)

if [ "$EXIT" -ne 0 ]; then
    echo "File-length gate FAILED"
    exit 1
fi

echo ""
echo "All checks passed."
