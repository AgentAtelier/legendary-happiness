"""Executor interface — abstract base for applying operations to Godot."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ExecutionResult:
    """Result of executing operations on a Godot scene.

    Attributes:
        success: Whether ALL operations succeeded.
        results: Per-operation results with success/error.
        errors: Top-level error messages (connection failures, etc.).
        scene_snapshot: Updated scene tree after execution (if available).
        raw_logs: Raw Godot output logs for error parsing.
    """

    success: bool = True
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    scene_snapshot: Dict[str, Any] | None = None
    raw_logs: str | None = None

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.results if not r.get("success", False))

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.get("success", False))

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "results": self.results,
            "errors": self.errors,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }


class Executor(ABC):
    """Abstract interface for applying operations to a Godot scene.

    Two concrete backends exist:
      - DevForgePluginExecutor: operations returned to Godot plugin via HTTP.
      - GodotAIMCPExecutor: operations sent to godot-ai MCP server directly.

    The executor is called AFTER the pipeline generates operations and
    BEFORE the server sends its response.
    """

    @abstractmethod
    def execute(
        self,
        operations: List[Dict[str, Any]],
        files: List[Dict[str, Any]],
        scene: Dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Apply operations to the Godot scene.

        Args:
            operations: List of operation dicts (add_node, attach_script, etc.).
            files: List of file dicts ({path, content}) to create.
            scene: Current scene tree snapshot (may be None).

        Returns:
            ExecutionResult with per-op success/failure and any errors.
        """
        ...

    @abstractmethod
    def get_scene(self) -> Dict[str, Any] | None:
        """Get the current scene tree from the live editor.

        Returns:
            Scene tree dict in the format {name, type, children, ...}
            or None if no scene is available.
        """
        ...

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Human-readable name of this executor backend."""
        ...

    def resolve_property_types(
        self, sample_values: Dict[str, Any] | None = None
    ) -> Dict[str, str]:
        """Resolve Godot property serialization types.

        Performs a one-time round-trip (via ``node_get_properties`` for
        MCP, or from sample values for the plugin executor) to learn how
        Godot serializes Vector3, Color, resource paths, etc.

        Results are cached and returned so the compiler can emit correct
        ``set_property`` values.

        Args:
            sample_values: Optional sample values from a reference node.
                           Used by DevForgePluginExecutor; ignored by
                           the MCP executor which fetches from Godot.

        Returns:
            Dict mapping property name → serialization format hint
            ("vector", "color", "resource_path", etc.).
        """
        return {}
