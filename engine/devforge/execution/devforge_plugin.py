"""DevForgePluginExecutor — the default backend.

Uses DevForge's own Godot editor plugin over HTTP.  Operations are
returned in the /generate response and executed by the plugin on the
Godot side.  The plugin reports results back via /report.

This executor is a lightweight pass-through: it records the operations
for the current request context and marks them as pending execution.
The actual execution happens when the Godot plugin receives the HTTP
response and calls _execute_operations().

The one-time ``node_get_properties`` round-trip (to resolve Vector3 /
path serialization quirks) writes results into ``runtime_config`` so
the compiler and validator can use real Godot type information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from devforge.execution.interface import Executor, ExecutionResult
from devforge.reasoning.ai.repair.error_parser import ErrorParser
from devforge.infrastructure.logger import logger


@dataclass
class _PluginContext:
    """Per-request context shared between executor and server."""

    pending_operations: List[Dict[str, Any]] = field(default_factory=list)
    pending_files: List[Dict[str, Any]] = field(default_factory=list)
    scene_snapshot: Dict[str, Any] | None = None
    last_results: List[Dict[str, Any]] = field(default_factory=list)
    parsed_errors: List[Any] = field(default_factory=list)


class DevForgePluginExecutor(Executor):
    """Executor that delegates to DevForge's own Godot editor plugin.

    Operations are stored in a request-scoped context dict.  The server
    returns them in its HTTP response and the Godot plugin's
    ``_on_generate_completed()`` callback executes them, then sends
    results back via POST /report which populates ``last_results``.
    """

    def __init__(self, server_url: str = "http://127.0.0.1:8000"):
        self._server_url = server_url
        self._context: _PluginContext | None = None
        self._error_parser = ErrorParser()
        self._property_serialization: Dict[str, Dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Executor interface
    # ------------------------------------------------------------------

    def execute(
        self,
        operations: List[Dict[str, Any]],
        files: List[Dict[str, Any]],
        scene: Dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Record operations for the Godot plugin to execute.

        The plugin will execute them when it receives the /generate
        response and will report results back via /report.
        """
        ctx = self._ensure_context()
        ctx.pending_operations = operations
        ctx.pending_files = files

        if scene is not None:
            ctx.scene_snapshot = scene

        # Mark all as pending — results come back via /report
        pending_results = [
            {"operation": op, "success": True, "status": "pending"}
            for op in operations
        ]

        logger.info(
            "executor.plugin",
            f"Queued {len(operations)} ops for plugin execution",
            operations=len(operations),
            files=len(files),
        )

        return ExecutionResult(
            success=True,
            results=pending_results,
            scene_snapshot=ctx.scene_snapshot,
        )

    def get_scene(self) -> Dict[str, Any] | None:
        ctx = self._ensure_context()
        return ctx.scene_snapshot

    @property
    def backend_name(self) -> str:
        return "devforge_plugin"

    # ------------------------------------------------------------------
    # Report handling (called by server when Godot POSTs /report)
    # ------------------------------------------------------------------

    def apply_report(self, results: List[Dict[str, Any]], scene: Dict[str, Any]) -> None:
        """Ingest execution results from the Godot plugin's /report callback.

        Parses any error messages from failed operations through ErrorParser
        so repair planning has structured error data.

        Args:
            results: Per-operation results from the plugin.
            scene: Updated scene snapshot after execution.
        """
        ctx = self._ensure_context()
        ctx.last_results = results
        ctx.scene_snapshot = scene

        ok = sum(1 for r in results if r.get("success", False))
        failed = len(results) - ok

        # Route plugin error output through ErrorParser
        parsed_errors = []
        for r in results:
            if not r.get("success", False):
                error_msg = r.get("error", "")
                if error_msg:
                    parsed = self._error_parser.parse_report_from_text(error_msg)
                    parsed_errors.extend(parsed)

        ctx.parsed_errors = parsed_errors

        logger.info(
            "executor.plugin",
            f"Report received: {ok} ok, {failed} failed",
            parsed_errors=len(parsed_errors),
        )

    # ------------------------------------------------------------------
    # Serialization round-trip (one-time)
    # ------------------------------------------------------------------

    def resolve_property_types(
        self, sample_values: Dict[str, Any] | None = None
    ) -> Dict[str, str]:
        """Store property type mappings from a one-time Godot round-trip.

        Called once during startup/configuration to learn how Godot
        serializes Vector3, Transform3D, Color, and resource paths so
        the compiler can emit correct ``set_property`` values.

        Args:
            sample_values: Dict of property_name → serialized_value from
                           ``node_get_properties`` on a reference node.

        Returns:
            Dict mapping property name to serialization format hint.
        """
        hints: Dict[str, str] = {}
        values = sample_values or {}
        for prop, value in values.items():
            if isinstance(value, dict):
                if "x" in value and "y" in value:
                    hints[prop] = "vector"
                elif "r" in value and "g" in value:
                    hints[prop] = "color"
            elif isinstance(value, str) and value.startswith("res://"):
                hints[prop] = "resource_path"
            else:
                hints[prop] = type(value).__name__

        self._property_serialization = hints
        logger.info("executor.plugin", "Property types resolved", hints=hints)
        return hints

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_context(self) -> _PluginContext:
        if self._context is None:
            self._context = _PluginContext()
        return self._context
