"""DevForge Execution — pluggable Godot scene executors.

Backend (a): DevForgePluginExecutor — default, uses DevForge's own
    Godot editor plugin over HTTP. Operations are returned in the
    /generate response and executed by the plugin.

Backend (b): GodotAIMCPExecutor — uses the godot-ai MCP server
    via streamable-http for batch_execute, scene hierarchy, and
    log parsing.
"""

from devforge.execution.devforge_plugin import DevForgePluginExecutor
from devforge.execution.godot_ai_executor import GodotAIMCPExecutor
from devforge.execution.interface import ExecutionResult, Executor

__all__ = [
    "Executor",
    "ExecutionResult",
    "DevForgePluginExecutor",
    "GodotAIMCPExecutor",
]
