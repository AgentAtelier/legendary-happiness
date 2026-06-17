"""Compatibility shim — re-exports from godot_ai_executor.py.

This file was renamed in Phase 1A (cleanup/layer3-code-health).
The executor class now lives in ``godot_ai_executor.py``;
session management in ``mcp_session.py``; op translation in
``op_translator.py``.

Importers should migrate to the new path, but this shim is kept
for one cycle so external imports don't break.
"""

from devforge.execution.godot_ai_executor import GodotAIMCPExecutor  # noqa: F401
