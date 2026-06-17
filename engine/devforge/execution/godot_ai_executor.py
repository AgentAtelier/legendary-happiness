"""GodotAIMCPExecutor — MCP client backend for godot-ai.

Connects to the godot-ai MCP server over Streamable HTTP and holds one
persistent session open across all tool calls.  Previously each
``execute()`` and ``get_scene()`` call opened a fresh connection; now a
single session is reused, with automatic reconnect and circuit-breaker
backoff on failure.

Calls:
  - ``batch_execute`` to apply operations to the live Godot scene.
  - ``godot://scene/hierarchy`` to read the current scene tree.
  - ``logs_read`` to fetch Godot output logs for error parsing.

Depends on the ``mcp`` Python package for the client transport.

Split from ``godot_ai_mcp.py`` (Phase 1A).  Session management lives in
``mcp_session.py``; op translation + result parsing lives in
``op_translator.py``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from devforge.infrastructure.logger import logger
from devforge.reasoning.ai.repair.error_parser import ErrorParser

from .interface import ExecutionResult, Executor
from .mcp_session import MCPSession
from .op_translator import (
    DROP_FIELDS,
    FIELD_MAP,
    OP_TO_COMMAND,
    normalize_op_result,
    parse_tool_result,
    parse_tool_result_text,
    res_path,
    translate_ops_to_commands,
    unwrap_scene_hierarchy,
)


class GodotAIMCPExecutor(Executor):
    """Executor that sends operations to godot-ai via its MCP server.

    Uses the ``mcp`` package's Streamable HTTP client to call
    tools on the godot-ai server.  Requires godot-ai to be running
    with its MCP endpoint exposed (typically ``:8000/mcp``).

    Usage::

        executor = GodotAIMCPExecutor(mcp_url="http://localhost:8000/mcp")
        result = executor.execute(operations, files, scene)
    """

    # Tool names exposed by godot-ai's MCP server
    # Audited against godot-ai's registered MCP tools (June 2026).
    # The *_manage tools dispatch on an `op` argument and nest handler
    # kwargs under `params` — {"op": ..., "params": {...}}.
    TOOL_BATCH_EXECUTE = "batch_execute"
    TOOL_SCENE_HIERARCHY = "scene_get_hierarchy"
    TOOL_LOGS_READ = "logs_read"
    TOOL_NODE_GET_PROPERTIES = "node_get_properties"
    TOOL_EDITOR_MANAGE = "editor_manage"  # ops: monitors_get, game_eval, state, ...
    TOOL_EDITOR_SCREENSHOT = "editor_screenshot"  # dedicated tool, source="game"|"viewport"
    TOOL_SCRIPT_MANAGE = "script_manage"  # ops: read, detach, find_symbols
    TOOL_FILESYSTEM_MANAGE = "filesystem_manage"  # ops: read_text, write_text, reimport, search
    TOOL_PROJECT_RUN = "project_run"  # dedicated tool: mode, scene, autosave
    TOOL_PROJECT_MANAGE = "project_manage"  # ops: stop, settings_get, settings_set

    # Backward-compatible class-level aliases for translation tables.
    # These live in op_translator.py now; kept here so external code
    # that references GodotAIMCPExecutor._OP_TO_COMMAND still works.
    _OP_TO_COMMAND = OP_TO_COMMAND
    _FIELD_MAP = FIELD_MAP
    _DROP_FIELDS = DROP_FIELDS

    def __init__(self, mcp_url: str = "http://localhost:8000/mcp"):
        self._error_parser = ErrorParser()
        self._property_serialization: Dict[str, Dict[str, str]] = {}

        # Persistent MCP session (background loop + circuit-breaker)
        self._session = MCPSession(mcp_url)

    # ------------------------------------------------------------------
    # Executor interface
    # ------------------------------------------------------------------

    def execute(
        self,
        operations: List[Dict[str, Any]],
        files: List[Dict[str, Any]],
        scene: Dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Send operations to godot-ai via MCP ``batch_execute``.

        Creates script files first, then calls batch_execute for scene
        operations.  Fetches logs afterward for error parsing.
        """
        logger.info(
            "executor.mcp",
            f"Sending {len(operations)} ops to godot-ai MCP",
            operations=len(operations),
            files=len(files),
        )

        try:
            return self._run(self._execute_async(operations, files, scene))
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"MCP execution failed: {type(exc).__name__}: {exc}",
            )
            return ExecutionResult(
                success=False,
                errors=[f"MCP connection error: {type(exc).__name__}: {exc}"],
                results=[],
            )

    def get_scene(self) -> Dict[str, Any] | None:
        """Fetch the live scene tree from godot-ai MCP."""
        logger.info("executor.mcp", "Fetching scene hierarchy")
        try:
            return self._run(self._get_scene_async())
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"Scene fetch failed: {type(exc).__name__}: {exc}",
            )
            return None

    def read_logs(self) -> str | None:
        """Fetch the raw Godot editor log text."""
        logger.info("executor.mcp", "Fetching Godot logs")
        try:
            return self._run(self._read_logs_async())
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"Logs read failed: {type(exc).__name__}: {exc}",
            )
            return None

    def resolve_node_properties(self, node_path: str) -> dict | None:
        """Fetch live properties for a single scene node."""
        logger.info("executor.mcp", f"Resolving properties for {node_path}")
        try:
            return self._run(self._resolve_node_properties_async(node_path))
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"Property resolution failed for {node_path}: {type(exc).__name__}: {exc}",
            )
            return None

    def get_performance_monitors(self, monitors: list[str] | None = None) -> dict | None:
        """Fetch live performance metrics from the Godot editor."""
        logger.info("executor.mcp", "Fetching performance monitors")
        try:
            return self._run(self._get_performance_monitors_async(monitors))
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"Performance monitors fetch failed: {type(exc).__name__}: {exc}",
            )
            return None

    def find_symbols(self, path: str) -> dict | None:
        """Find symbols in a GDScript file."""
        logger.info("executor.mcp", f"Finding symbols in {path}")
        try:
            return self._run(self._find_symbols_async(path))
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"find_symbols failed for {path}: {type(exc).__name__}: {exc}",
            )
            return None

    def search_filesystem(
        self,
        query: str,
        path: str = "res://",
        recursive: bool = True,
    ) -> dict | None:
        """Search the project filesystem for files matching *query*."""
        logger.info("executor.mcp", f"Searching filesystem for '{query}'")
        try:
            return self._run(self._search_filesystem_async(query, path, recursive))
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"search_filesystem failed for '{query}': {type(exc).__name__}: {exc}",
            )
            return None

    @property
    def backend_name(self) -> str:
        return "godot_ai_mcp"

    # ------------------------------------------------------------------
    # Background-loop dispatch helper
    # ------------------------------------------------------------------

    def _run(self, coro, timeout: float = 480.0):
        """Run a coroutine on the executor's dedicated event loop."""
        return self._session.run_coro(coro, timeout=timeout)

    # ------------------------------------------------------------------
    # Tool call helpers (delegated to session)
    # ------------------------------------------------------------------

    async def _ensure_session(self):
        return await self._session.ensure()

    async def _close_session(self):
        await self._session.close()

    async def _call_tool_safe(self, session, name: str, arguments: dict) -> Any:
        return await self._session.call_tool_safe(session, name, arguments)

    def run_project(self, mode: str = "main", scene: str = "") -> dict | None:
        """Launch the game from the Godot editor."""
        logger.info("executor.mcp", f"Launching project (mode={mode})")
        try:
            return self._run(self._run_project_async(mode, scene))
        except Exception as exc:
            logger.error("executor.mcp", f"run_project failed: {exc}")
            return None

    def stop_project(self) -> dict | None:
        """Stop the running game."""
        logger.info("executor.mcp", "Stopping project")
        try:
            return self._run(self._stop_project_async())
        except Exception as exc:
            logger.error("executor.mcp", f"stop_project failed: {exc}")
            return None

    def game_eval(self, expression: str) -> str | None:
        """Evaluate a GDScript expression in the running game."""
        logger.info("executor.mcp", f"Evaluating: {expression[:80]}")
        try:
            return self._run(self._game_eval_async(expression))
        except Exception as exc:
            logger.error("executor.mcp", f"game_eval failed: {exc}")
            return None

    def take_screenshot(self) -> str | None:
        """Capture a screenshot of the running game."""
        logger.info("executor.mcp", "Taking screenshot")
        try:
            return self._run(self._take_screenshot_async())
        except Exception as exc:
            logger.error("executor.mcp", f"take_screenshot failed: {exc}")
            return None

    def shutdown(self):
        """Close the persistent session and stop the background loop."""
        self._session.shutdown()

    # ------------------------------------------------------------------
    # Async internals
    # ------------------------------------------------------------------

    async def _execute_async(
        self,
        operations: List[Dict[str, Any]],
        files: List[Dict[str, Any]],
        scene: Dict[str, Any] | None,
    ) -> ExecutionResult:
        session = await self._ensure_session()
        start = time.time()

        # 1. Create script files (if any).
        for f in files:
            fpath = f.get("path", "")
            content = f.get("content", "")
            if fpath:
                try:
                    await self._call_tool_safe(
                        session,
                        name="script_create",
                        arguments={
                            "path": res_path(fpath),
                            "content": content,
                        },
                    )
                except Exception as exc:
                    logger.warn(
                        "executor.mcp",
                        f"File creation failed for {fpath}: {exc}",
                    )

        # 2. Execute scene operations with bounded retry on transient failures.
        errors: List[str] = []
        results: List[Dict[str, Any]] = []
        MAX_BATCH_RETRIES = 2
        RETRY_DELAY_BASE = 0.5  # seconds

        if operations:
            for batch_attempt in range(MAX_BATCH_RETRIES + 1):
                try:
                    commands = translate_ops_to_commands(operations)
                    batch_result = await self._call_tool_safe(
                        session,
                        name=self.TOOL_BATCH_EXECUTE,
                        arguments={"commands": commands},
                    )

                    parsed = parse_tool_result(batch_result)
                    if isinstance(parsed, list):
                        results = parsed
                    elif isinstance(parsed, dict):
                        results = parsed.get("results", [])
                    results = [normalize_op_result(r) for r in results]
                    break  # success
                except (ConnectionError, TimeoutError, OSError) as exc:
                    if batch_attempt < MAX_BATCH_RETRIES:
                        delay = RETRY_DELAY_BASE * (2**batch_attempt)
                        logger.warn(
                            "executor.mcp",
                            f"batch_execute transient failure (attempt "
                            f"{batch_attempt + 1}/{MAX_BATCH_RETRIES + 1}): "
                            f"{type(exc).__name__}: {exc} — retrying in {delay}s",
                        )
                        await asyncio.sleep(delay)
                        await self._close_session()
                        session = await self._ensure_session()
                    else:
                        errors.append(f"batch_execute failed after {MAX_BATCH_RETRIES + 1} attempts: {exc}")
                except Exception as exc:
                    logger.warn(
                        "executor.mcp",
                        f"batch_execute failed ({type(exc).__name__}: {exc}) — "
                        f"falling back to per-op execution for "
                        f"{len(operations)} operations",
                    )
                    results = await self._execute_ops_individually(session, operations)
                    break

        # 3. Fetch logs for error parsing
        raw_logs: str | None = None
        try:
            logs_result = await self._call_tool_safe(
                session,
                name=self.TOOL_LOGS_READ,
                arguments={},
            )
            raw_logs = parse_tool_result_text(logs_result)
        except Exception as exc:
            logger.warn("executor.mcp", f"Logs read failed: {exc}")

        # 4. Fetch updated scene
        scene_snapshot: Dict[str, Any] | None = None
        try:
            hier_result = await self._call_tool_safe(
                session,
                name=self.TOOL_SCENE_HIERARCHY,
                arguments={},
            )
            scene_snapshot = unwrap_scene_hierarchy(parse_tool_result(hier_result))
        except Exception as exc:
            logger.warn("executor.mcp", f"Scene hierarchy failed: {exc}")

        # 5. Parse errors from logs
        if raw_logs and self._error_parser:
            parsed_errors = self._error_parser.parse_report_from_text(raw_logs)
            for pe in parsed_errors:
                errors.append(f"{pe.file}:{pe.line}: {pe.message}")

        elapsed = int((time.time() - start) * 1000)

        all_ok = len(errors) == 0 and all(r.get("success", False) for r in results)

        logger.info(
            "executor.mcp",
            f"MCP execution complete: {len(results)} results, {len(errors)} errors, {elapsed}ms",
        )

        return ExecutionResult(
            success=all_ok,
            results=results,
            errors=errors,
            scene_snapshot=scene_snapshot,
            raw_logs=raw_logs,
        )

    async def _get_scene_async(self) -> Dict[str, Any] | None:
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_SCENE_HIERARCHY,
            arguments={},
        )
        parsed = parse_tool_result(result)
        return unwrap_scene_hierarchy(parsed)

    async def _read_logs_async(self) -> str | None:
        """Fetch the raw Godot editor log text via MCP."""
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_LOGS_READ,
            arguments={},
        )
        return parse_tool_result_text(result)

    async def _execute_ops_individually(self, session, operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Send each operation one at a time as a fallback when batch fails.

        T3: Graceful adversarial — a single bad op (invalid path, unknown
        type) can cause the MCP server to reject the entire batch. This
        method sends each op as its own execute call so valid ops still
        apply. Slower but resilient.
        """
        results: List[Dict[str, Any]] = []
        for i, op in enumerate(operations):
            op_type = op.get("type", "unknown")
            try:
                commands = translate_ops_to_commands([op])
                batch_result = await self._call_tool_safe(
                    session,
                    name=self.TOOL_BATCH_EXECUTE,
                    arguments={"commands": commands},
                )
                parsed = parse_tool_result(batch_result)
                if isinstance(parsed, list):
                    for r in parsed:
                        results.append(normalize_op_result(r))
                elif isinstance(parsed, dict):
                    inner = parsed.get("results", [parsed])
                    for r in inner if isinstance(inner, list) else [inner]:
                        results.append(normalize_op_result(r))
                else:
                    results.append(
                        {
                            "command": op_type,
                            "success": True,
                            "status": "ok",
                            "result": str(parsed),
                        }
                    )
            except Exception as exc:
                logger.warn(
                    "executor.mcp",
                    f"Per-op {i} ({op_type}) failed: {type(exc).__name__}: {exc}",
                )
                results.append(
                    {
                        "command": op_type,
                        "success": False,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                try:
                    await self._close_session()
                    session = await self._ensure_session()
                except Exception:
                    pass  # will retry session on next op
        return results

    # ------------------------------------------------------------------
    # Serialization round-trip (one-time)
    # ------------------------------------------------------------------

    def resolve_property_types(self, sample_values: Dict[str, Any] | None = None) -> Dict[str, str]:
        """Perform a one-time round-trip to learn Godot property serialization.

        Calls ``node_get_properties`` on a reference node and records
        how Godot serializes Vector3, Color, resource paths, etc.
        Results are cached so the compiler can emit correct values.
        """
        logger.info("executor.mcp", "Resolving property serialization types")
        try:
            hints = self._run(self._resolve_properties_async())
            self._property_serialization = hints
            return hints
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"Property resolution failed: {type(exc).__name__}: {exc}",
            )
            return {}

    async def _resolve_node_properties_async(self, node_path: str) -> dict | None:
        """Fetch live properties for *node_path* via MCP."""
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_NODE_GET_PROPERTIES,
            arguments={"node_path": node_path},
        )
        props = parse_tool_result(result)
        if not isinstance(props, dict):
            return None
        return props

    async def _find_symbols_async(self, path: str) -> dict | None:
        """Find symbols in a GDScript file via MCP."""
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_SCRIPT_MANAGE,
            arguments={
                "op": "find_symbols",
                "params": {"path": res_path(path)},
            },
        )
        parsed = parse_tool_result(result)
        if not isinstance(parsed, dict):
            return None
        return parsed

    async def _search_filesystem_async(
        self,
        query: str,
        path: str,
        recursive: bool,
    ) -> dict | None:
        """Search the project filesystem via MCP."""
        session = await self._ensure_session()
        params: dict[str, Any] = {"name": query}
        if path and path != "res://":
            params["path"] = res_path(path)
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_FILESYSTEM_MANAGE,
            arguments={"op": "search", "params": params},
        )
        parsed = parse_tool_result(result)
        if not isinstance(parsed, dict):
            return None
        return parsed

    async def _get_performance_monitors_async(self, monitors: list[str] | None = None) -> dict | None:
        """Fetch live performance metrics via editor_manage/monitors_get."""
        session = await self._ensure_session()
        arguments: dict[str, Any] = {"op": "monitors_get"}
        if monitors is not None:
            arguments["params"] = {"monitors": monitors}
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_EDITOR_MANAGE,
            arguments=arguments,
        )
        parsed = parse_tool_result(result)
        if not isinstance(parsed, dict):
            return None
        return parsed

    async def _resolve_properties_async(self) -> Dict[str, str]:
        """Learn Godot property serialization types from the root node."""
        props = await self._resolve_node_properties_async("/root")
        if props is None:
            return {}

        hints: Dict[str, str] = {}
        for prop, value in props.items():
            if isinstance(value, dict):
                if "x" in value and "y" in value:
                    hints[prop] = "vector"
                elif "r" in value and "g" in value:
                    hints[prop] = "color"
            elif isinstance(value, str) and value.startswith("res://"):
                hints[prop] = "resource_path"
            else:
                hints[prop] = type(value).__name__

        logger.info("executor.mcp", "Property types resolved", hints=hints)
        return hints

    async def _run_project_async(self, mode: str = "main", scene: str = "") -> dict | None:
        """Launch via the dedicated project_run tool."""
        session = await self._ensure_session()
        arguments: dict[str, Any] = {"mode": mode}
        if scene:
            arguments["scene"] = scene
        result = await self._call_tool_safe(session, name=self.TOOL_PROJECT_RUN, arguments=arguments)
        parsed = parse_tool_result(result)
        return parsed if isinstance(parsed, dict) else None

    async def _stop_project_async(self) -> dict | None:
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_PROJECT_MANAGE,
            arguments={"op": "stop"},
        )
        parsed = parse_tool_result(result)
        return parsed if isinstance(parsed, dict) else None

    async def _game_eval_async(self, expression: str) -> str | None:
        """Evaluate GDScript in the running game."""
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_EDITOR_MANAGE,
            arguments={"op": "game_eval", "params": {"code": expression}},
        )
        parsed = parse_tool_result(result)
        return str(parsed) if parsed is not None else None

    async def _take_screenshot_async(self) -> str | None:
        """Capture the running game via editor_screenshot."""
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_EDITOR_SCREENSHOT,
            arguments={
                "source": "game",
                "include_image": False,
                "max_resolution": 640,
            },
        )
        parsed = parse_tool_result(result)
        if isinstance(parsed, dict):
            w = parsed.get("width", "?")
            h = parsed.get("height", "?")
            return f"{parsed.get('source', 'game')}:{w}x{h}"
        return str(parsed) if parsed is not None else None
