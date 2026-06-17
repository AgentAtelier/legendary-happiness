#!/usr/bin/env bash
# Run every test that works without the live llama.cpp/godot-ai/Godot stack.
#
# This is the fix-verification loop the Round-2 audit asked for: run it
# after every change batch, and before building any audit bundle.
# Exits nonzero if anything fails.

set -u
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

failures=0

run() {
    echo "──────────────────────────────────────────────────"
    echo "▶ $*"
    if ! "$@"; then
        echo "✗ FAILED: $*"
        failures=$((failures + 1))
    fi
}

run "$PY" -m devforge.health_check
run "$PY" -m devforge.verify_pipeline
run "$PY" devforge/tests/test_import_walk.py
run "$PY" devforge/tests/test_gateway_budget.py
run "$PY" devforge/tests/test_artifact_store.py
run "$PY" devforge/tests/test_script_extractor.py
run "$PY" devforge/tests/test_rename_remove.py
run "$PY" devforge/tests/test_repair_engine.py
run "$PY" devforge/tests/test_context_clamp.py
run "$PY" devforge/tests/test_prompt_templates.py
run "$PY" devforge/tests/test_scene_doctor.py
run "$PY" devforge/tests/test_batch_operator.py
run "$PY" devforge/tests/test_error_triage.py
run "$PY" devforge/tests/test_template_forge.py
run "$PY" devforge/tests/test_progress_journal.py
run "$PY" devforge/tests/test_lorekeeper.py
run "$PY" devforge/tests/test_quest_validator.py
run "$PY" devforge/tests/test_performance_sentinel.py
run "$PY" devforge/tests/test_content_linter.py
run "$PY" devforge/tests/test_polish_pass.py
run "$PY" devforge/tests/test_project_navigator.py
run "$PY" devforge/tests/test_test_harness.py
run "$PY" devforge/tests/test_balance_simulator.py
run "$PY" devforge/tests/test_signal_mapper.py
run "$PY" devforge/tests/test_smoke_runner.py
run "$PY" devforge/tests/test_design_companion.py
run "$PY" devforge/tests/test_dialogue_engine.py
run "$PY" devforge/tests/test_scene_refactorer.py
run "$PY" devforge_project_tests/test_imports.py
run "$PY" -m pytest devforge/tests/test_godot_ai_mcp.py -q

echo "══════════════════════════════════════════════════"
if [ "$failures" -eq 0 ]; then
    echo "All test suites passed."
else
    echo "$failures suite(s) FAILED."
fi
exit "$failures"
