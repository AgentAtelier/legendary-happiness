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

# --- Ruff checks (excludes legacy/experiments/archive via pyproject) ---
echo "=== ruff check ==="
"$RUFF" check hub/ engine/ "$@"

echo "=== ruff format --check ==="
"$RUFF" format --check hub/ engine/

# --- File-length gate ---
# Enforces "no NEW god files". The existing god files are grandfathered and
# tracked for splitting in docs/current/GOD-FILE-SPLIT-PLAN.md. Tests, the dying
# legacy runners, experiments, and archived code are exempt. When you split a
# grandfathered file below 500 lines, delete it from the list below.
echo "=== file-length gate (max $MAX_LINES lines; new files only) ==="

GRANDFATHERED=(
    "engine/devforge/platform/mcp_server.py"
    "hub/hub.py"
    "engine/devforge/compilation/pipeline/engine.py"
    "engine/devforge/compilation/pipeline/architecture_compiler.py"
    "engine/devforge/spatial/ssp.py"
    "engine/devforge/infrastructure/llm/gateway.py"
    "engine/devforge/simulator/simulator.py"
    "engine/devforge/governance/analyzer.py"
    "engine/devforge/execution/godot_ai_executor.py"
    "engine/devforge/platform/monitor/monitor.py"
    "engine/devforge/spatial/compiler.py"
    "engine/devforge/infrastructure/llm/llama_client.py"
    "hub/forge_ops.py"
    "engine/devforge/governance/gate1.py"
    "engine/devforge/spatial/bsp.py"
)

EXIT=0
while IFS= read -r -d '' f; do
    rel="${f#"$ROOT"/}"
    case "$rel" in
        */tests/*|*/test_*|*/.venv/*) continue ;;
        hub/static/*|engine/experiments/*|engine/docs/*|engine/integration_tests/*) continue ;;
    esac
    skip=0
    for g in "${GRANDFATHERED[@]}"; do [ "$rel" = "$g" ] && skip=1 && break; done
    [ "$skip" -eq 1 ] && continue
    lines=$(wc -l < "$f")
    if [ "$lines" -gt "$MAX_LINES" ]; then
        echo "FAIL: $rel is $lines lines (max $MAX_LINES). Split it, or grandfather it with a tracking note."
        EXIT=1
    fi
done < <(find "$ROOT/hub" "$ROOT/engine" -name "*.py" -print0)

if [ "$EXIT" -ne 0 ]; then
    echo "File-length gate FAILED"
    exit 1
fi

echo ""
echo "All checks passed."
