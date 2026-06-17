#!/usr/bin/env bash
# Build devforge_audit_bundle.zip for external review.
#
# Replaces the ad-hoc find|zip one-liner that caused audit findings
# F4 (27 __pycache__ dirs shipped) and F6 (devforge/execution/
# godot_ai_mcp.py excluded by the over-broad '*/godot_ai*' pattern —
# that pattern was meant for the EXTERNAL godot-ai checkout only).
#
# Usage: scripts/build_audit_bundle.sh [output.zip]

set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-$HOME/devforge_audit_bundle.zip}"

# Refuse to bundle a tree that fails its own test suite (the Round-2
# audit's root cause: fixes and tests shipped without being run together).
scripts/run_all_tests.sh

rm -f "$OUT"
zip -r -q "$OUT" . \
    -x '*/__pycache__/*' \
    -x '__pycache__/*' \
    -x '.venv/*' \
    -x '*.pyc' \
    -x '.git/*' \
    -x '*/.pytest_cache/*' \
    -x '*/addons/godot_ai*' \
    -x '*/godot-ai/*'

# Sanity checks: the two files the broken bundler dropped must be present.
for must_have in devforge/execution/godot_ai_mcp.py devforge/requirements.txt; do
    if ! unzip -l "$OUT" "$must_have" > /dev/null 2>&1; then
        echo "ERROR: $must_have missing from bundle — exclusion patterns are wrong again." >&2
        exit 1
    fi
done
if unzip -l "$OUT" | grep -q '__pycache__'; then
    echo "ERROR: __pycache__ leaked into the bundle." >&2
    exit 1
fi

echo "Bundle OK: $OUT ($(du -h "$OUT" | cut -f1))"
