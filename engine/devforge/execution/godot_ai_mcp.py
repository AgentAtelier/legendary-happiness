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
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Dict, List

from devforge.execution.interface import Executor, ExecutionResult
from devforge.reasoning.ai.repair.error_parser import ErrorParser
from devforge.infrastructure.logger import logger


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
    TOOL_EDITOR_MANAGE = "editor_manage"          # ops: monitors_get, game_eval, state, ...
    TOOL_EDITOR_SCREENSHOT = "editor_screenshot"  # dedicated tool, source="game"|"viewport"
    TOOL_SCRIPT_MANAGE = "script_manage"          # ops: read, detach, find_symbols
    TOOL_FILESYSTEM_MANAGE = "filesystem_manage"  # ops: read_text, write_text, reimport, search
    TOOL_PROJECT_RUN = "project_run"              # dedicated tool: mode, scene, autosave
    TOOL_PROJECT_MANAGE = "project_manage"        # ops: stop, settings_get, settings_set

    # DevForge operation type -> godot-ai command mapping
    # batch_execute dispatches on the PLUGIN command names registered in
    # godot-ai's plugin.gd dispatcher — NOT the MCP tool names (which are
    # category-prefixed, e.g. the `script_attach` TOOL wraps the
    # `attach_script` plugin command). Audited against plugin.gd June 2026.
    _OP_TO_COMMAND: dict[str, str] = {
        "add_node": "create_node",
        "set_property": "set_property",
        "attach_script": "attach_script",
        "connect_signal": "connect_signal",
        "remove_node": "delete_node",
        "rename_node": "rename_node",
    }
    # Field name remapping for the params dict. The plugin handlers read
    # the target node from `path` (via _resolve_node / McpScenePath).
    _FIELD_MAP: dict[str, dict[str, str]] = {
        "add_node": {"parent": "parent_path", "node_type": "type"},
        "set_property": {"node": "path"},
        "attach_script": {"node": "path", "script": "script_path"},
        "connect_signal": {"source": "path"},
        "remove_node": {"node": "path"},
        "rename_node": {"node": "path"},
    }
    # Fields to drop from params (already consumed)
    _DROP_FIELDS: set[str] = {"type"}

    def __init__(self, mcp_url: str = "http://localhost:8000/mcp"):
        self._mcp_url = mcp_url
        self._error_parser = ErrorParser()
        self._property_serialization: Dict[str, Dict[str, str]] = {}

        # ── Persistent MCP session ───────────────────────────
        # Instead of opening a fresh connection per call,
        # we hold one session open across all execute() and
        # get_scene() calls.  A circuit breaker prevents hot-
        # retry death spirals on a dead godot-ai server.
        self._mcp_read: Any = None
        self._mcp_write: Any = None
        self._mcp_session: Any = None
        self._transport_ctx: Any = None  # the streamable_http_client context manager for cleanup
        self._mcp_lock = asyncio.Lock()

        # Circuit breaker state (mirrors EditorBridgeCircuitBreaker pattern)
        self._mcp_failures: int = 0
        self._mcp_failure_threshold: int = 5
        self._mcp_backoff_ms: int = 1000
        self._mcp_max_backoff_ms: int = 30_000
        self._mcp_next_retry_mono: float = 0.0

        # FIX (Issue 1): FastMCP invokes sync tool functions on the server's
        # event-loop thread. Calling asyncio.run() from inside that loop raises
        # "cannot be called from a running event loop". We give the executor its
        # own dedicated background event loop running in a daemon thread, then
        # dispatch coroutines onto it via run_coroutine_threadsafe().
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread: threading.Thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="godot-mcp-loop",
        )
        self._thread.start()
        logger.info("executor.mcp", "Started dedicated MCP event-loop thread (persistent session)")

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
            # FIX (Issue 1, bonus): log exc_type so future errors are not all
            # bucketed as a generic "MCP connection error".
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
        """Fetch the raw Godot editor log text.

        Returns the log text as a string, or None if the live editor
        is unavailable or the call fails.
        """
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
        """Fetch live properties for a single scene node.

        Calls godot-ai's ``node_get_properties`` tool for *node_path*
        (e.g. "/root/Main/Player") and returns a dict of property
        names to their current values.  Returns None on failure.
        """
        logger.info("executor.mcp", f"Resolving properties for {node_path}")
        try:
            return self._run(self._resolve_node_properties_async(node_path))
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"Property resolution failed for {node_path}: "
                f"{type(exc).__name__}: {exc}",
            )
            return None

    def get_performance_monitors(
        self, monitors: list[str] | None = None
    ) -> dict | None:
        """Fetch live performance metrics from the Godot editor.

        Calls godot-ai's ``performance_monitors_get`` tool.  If
        *monitors* is None, returns all available metrics.  Pass a
        list of metric names (e.g. ["time/fps", "memory/static/usage"])
        to get only those.

        Returns a dict mapping metric name → current value, or None
        on failure.
        """
        logger.info("executor.mcp", "Fetching performance monitors")
        try:
            return self._run(self._get_performance_monitors_async(monitors))
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"Performance monitors fetch failed: "
                f"{type(exc).__name__}: {exc}",
            )
            return None

    def find_symbols(self, path: str) -> dict | None:
        """Find symbols in a GDScript file.

        Calls godot-ai's ``script_manage`` tool with op ``find_symbols``.
        Returns a dict with class_name, extends, signals, functions,
        and @export vars for the script at *path*.
        """
        logger.info("executor.mcp", f"Finding symbols in {path}")
        try:
            return self._run(self._find_symbols_async(path))
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"find_symbols failed for {path}: "
                f"{type(exc).__name__}: {exc}",
            )
            return None

    def search_filesystem(
        self, query: str, path: str = "res://", recursive: bool = True,
    ) -> dict | None:
        """Search the project filesystem for files matching *query*.

        Calls godot-ai's ``filesystem_manage`` tool with op ``search_filesystem``.
        Returns a dict with matching file paths and metadata.
        """
        logger.info("executor.mcp", f"Searching filesystem for '{query}'")
        try:
            return self._run(
                self._search_filesystem_async(query, path, recursive)
            )
        except Exception as exc:
            logger.error(
                "executor.mcp",
                f"search_filesystem failed for '{query}': "
                f"{type(exc).__name__}: {exc}",
            )
            return None

    @property
    def backend_name(self) -> str:
        return "godot_ai_mcp"

    # ------------------------------------------------------------------
    # Background-loop dispatch helper
    # ------------------------------------------------------------------

    def _run(self, coro, timeout: float = 480.0):
        """Run a coroutine on the executor's dedicated event loop.

        Returns the coroutine's result, raising any exception it raised
        after ``timeout`` seconds. Safe to call from any thread, including
        the FastMCP event-loop thread.

        Timeout tree: llama_client allows 120s per LLM call with 2 attempts
        (=240s per planner call), and the pipeline retries up to 3 planner
        calls (=720s worst case). This outer MCP-call timeout must exceed the
        inner retry chain plus overhead (transport reconnect, scene fetch, logs)
        so a retrying planner isn't killed by the executor before it finishes.
        480s covers 2 full planner calls with overhead, a reasonable floor.
        """
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    # ------------------------------------------------------------------
    # Persistent session management
    # ------------------------------------------------------------------

    async def _ensure_session(self):
        """Return a live MCP session, creating or reconnecting as needed.

        Must run on ``self._loop``.  Uses an asyncio.Lock to serialize
        concurrent reconnection attempts.  The circuit breaker prevents
        hot-retry death spirals when godot-ai is unreachable.
        """
        if self._mcp_session is not None:
            return self._mcp_session

        async with self._mcp_lock:
            # Double-check after acquiring the lock
            if self._mcp_session is not None:
                return self._mcp_session

            # Circuit breaker: don't hammer a dead server
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client

            now = time.monotonic()
            if now < self._mcp_next_retry_mono:
                wait_ms = int((self._mcp_next_retry_mono - now) * 1000)
                raise ConnectionError(
                    f"MCP session circuit open after {self._mcp_failures} "
                    f"consecutive failures — retry in {wait_ms}ms"
                )

            # Tear down any stale transport state
            await self._close_session()

            try:
                transport_ctx = streamable_http_client(self._mcp_url)
                read, write, _ = await transport_ctx.__aenter__()
                session = ClientSession(read, write)
                await session.__aenter__()
                await session.initialize()

                self._transport_ctx = transport_ctx
                self._mcp_read = read
                self._mcp_write = write
                self._mcp_session = session

                # Reset circuit on successful connection
                self._mcp_failures = 0
                self._mcp_backoff_ms = 1000
                self._mcp_next_retry_mono = 0.0

                logger.info("executor.mcp", "Persistent MCP session established")
                return self._mcp_session

            except Exception as exc:
                self._record_mcp_failure()
                raise ConnectionError(
                    f"Failed to establish MCP session to {self._mcp_url}: {exc}"
                ) from exc

    async def _close_session(self):
        """Close the persistent MCP session and its transport."""
        if self._mcp_session is not None:
            try:
                await self._mcp_session.__aexit__(None, None, None)
            except Exception:
                pass
            self._mcp_session = None

        # Close the streamable HTTP transport context manager
        if self._transport_ctx is not None:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._transport_ctx = None

        self._mcp_read = None
        self._mcp_write = None

    async def _call_tool_safe(self, session, name: str, arguments: dict) -> Any:
        """Call a tool on the persistent session, invalidating on failure.

        If the call fails with a transport-level error, the session is
        closed so the next call reconnects.  Tool-level errors (valid
        MCP responses with isError=True) are returned normally.
        """
        try:
            return await session.call_tool(name=name, arguments=arguments)
        except Exception:
            await self._close_session()
            self._mcp_failures += 1
            raise

    def _record_mcp_failure(self):
        """Record a transport failure and possibly open the circuit.

        After ``_mcp_failure_threshold`` consecutive failures, the
        circuit opens for an exponentially-growing backoff window.
        Also clears ``_mcp_session`` so the next call reconnects.
        """
        self._mcp_failures += 1
        if self._mcp_failures >= self._mcp_failure_threshold:
            self._mcp_session = None
            mono = time.monotonic()
            current_backoff = self._mcp_backoff_ms
            self._mcp_next_retry_mono = mono + current_backoff / 1000.0
            self._mcp_backoff_ms = min(
                current_backoff * 2, self._mcp_max_backoff_ms
            )
            logger.warn(
                "executor.mcp",
                f"MCP session circuit OPEN after {self._mcp_failures} "
                f"failures — backoff {current_backoff}ms",
            )

    def run_project(self, mode: str = "main", scene: str = "") -> dict | None:
        """Launch the game from the Godot editor.

        Calls godot-ai's dedicated ``project_run`` tool. *mode* is
        ``"main"`` (main scene) or ``"current"``; *scene* optionally
        names a specific .tscn. Returns a status dict or None on failure.
        """
        logger.info("executor.mcp", f"Launching project (mode={mode})")
        try:
            return self._run(self._run_project_async(mode, scene))
        except Exception as exc:
            logger.error("executor.mcp", f"run_project failed: {exc}")
            return None

    def stop_project(self) -> dict | None:
        """Stop the running game.

        Calls godot-ai's ``project_manage`` tool with op ``stop``.
        Returns a dict with stop status or None on failure.
        """
        logger.info("executor.mcp", "Stopping project")
        try:
            return self._run(self._stop_project_async())
        except Exception as exc:
            logger.error("executor.mcp", f"stop_project failed: {exc}")
            return None

    def game_eval(self, expression: str) -> str | None:
        """Evaluate a GDScript expression in the running game.

        Calls godot-ai's ``editor_manage`` tool with op ``game_eval``
        (handler parameter is ``code``). Returns the result as a string
        or None on failure.
        """
        logger.info("executor.mcp", f"Evaluating: {expression[:80]}")
        try:
            return self._run(self._game_eval_async(expression))
        except Exception as exc:
            logger.error("executor.mcp", f"game_eval failed: {exc}")
            return None

    def take_screenshot(self) -> str | None:
        """Capture a screenshot of the running game.

        Calls godot-ai's ``editor_screenshot`` tool with
        ``source="game"`` and ``include_image=False``. Returns a compact
        identifier like ``"game:640x360"`` (godot-ai returns image data,
        not file paths) or None on failure.
        """
        logger.info("executor.mcp", "Taking screenshot")
        try:
            return self._run(self._take_screenshot_async())
        except Exception as exc:
            logger.error("executor.mcp", f"take_screenshot failed: {exc}")
            return None

    def shutdown(self):
        """Close the persistent session and stop the background loop.

        Call this when the executor is no longer needed (e.g. server
        shutdown).  Safe to call multiple times.
        """
        if self._loop.is_running():
            try:
                self._run(self._close_session(), timeout=5.0)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("executor.mcp", "MCP executor shut down")

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

        # 1. Create script files (if any). Empty content is valid —
        # script_create creates a blank file; only a missing path skips.
        for f in files:
            path = f.get("path", "")
            content = f.get("content", "")
            if path:
                try:
                    await self._call_tool_safe(session,
                        name="script_create",
                        arguments={
                            "path": self._res_path(path),
                            "content": content,
                        },
                    )
                except Exception as exc:
                    logger.warn("executor.mcp",
                                f"File creation failed for {path}: {exc}")

        # 2. Execute scene operations with bounded retry on transient failures.
        # C8: godot-ai can drop calls during editor importing, WS blips, or
        # project-scan pauses. A single failure doesn't mean the plan is wrong
        # — it's usually a transport hiccup. Retry with backoff.
        errors: List[str] = []
        results: List[Dict[str, Any]] = []
        MAX_BATCH_RETRIES = 2
        RETRY_DELAY_BASE = 0.5  # seconds

        if operations:
            for batch_attempt in range(MAX_BATCH_RETRIES + 1):
                try:
                    commands = self._translate_ops_to_commands(operations)
                    batch_result = await self._call_tool_safe(session,
                        name=self.TOOL_BATCH_EXECUTE,
                        arguments={"commands": commands},
                    )

                    # Parse batch result — may be a list of per-op results
                    parsed = self._parse_tool_result(batch_result)
                    if isinstance(parsed, list):
                        results = parsed
                    elif isinstance(parsed, dict):
                        results = parsed.get("results", [])
                    results = [self._normalize_op_result(r) for r in results]
                    break  # success
                except (ConnectionError, TimeoutError, OSError) as exc:
                    if batch_attempt < MAX_BATCH_RETRIES:
                        delay = RETRY_DELAY_BASE * (2 ** batch_attempt)
                        logger.warn(
                            "executor.mcp",
                            f"batch_execute transient failure (attempt "
                            f"{batch_attempt + 1}/{MAX_BATCH_RETRIES + 1}): "
                            f"{type(exc).__name__}: {exc} — retrying in {delay}s",
                        )
                        await asyncio.sleep(delay)
                        # Reconnect session before retry
                        await self._close_session()
                        session = await self._ensure_session()
                    else:
                        errors.append(
                            f"batch_execute failed after "
                            f"{MAX_BATCH_RETRIES + 1} attempts: {exc}"
                        )
                except Exception as exc:
                    # T3: Graceful adversarial — don't lose all ops when the
                    # batch fails. Fall back to sending each op individually
                    # so valid ops still apply; only the bad one(s) error out.
                    logger.warn(
                        "executor.mcp",
                        f"batch_execute failed ({type(exc).__name__}: {exc}) — "
                        f"falling back to per-op execution for "
                        f"{len(operations)} operations",
                    )
                    results = await self._execute_ops_individually(
                        session, operations
                    )
                    # Per-op errors are already populated in results by the
                    # individual calls, so break here with whatever we got.
                    break

        # 3. Fetch logs for error parsing
        raw_logs: str | None = None
        try:
            logs_result = await self._call_tool_safe(session, 
                name=self.TOOL_LOGS_READ,
                arguments={},
            )
            raw_logs = self._parse_tool_result_text(logs_result)
        except Exception as exc:
            logger.warn("executor.mcp", f"Logs read failed: {exc}")

        # 4. Fetch updated scene
        scene_snapshot: Dict[str, Any] | None = None
        try:
            hier_result = await self._call_tool_safe(session, 
                name=self.TOOL_SCENE_HIERARCHY,
                arguments={},
            )
            scene_snapshot = self._unwrap_scene_hierarchy(
                self._parse_tool_result(hier_result)
            )
        except Exception as exc:
            logger.warn("executor.mcp", f"Scene hierarchy failed: {exc}")

        # 5. Parse errors from logs
        if raw_logs and self._error_parser:
            parsed_errors = self._error_parser.parse_report_from_text(raw_logs)
            for pe in parsed_errors:
                errors.append(f"{pe.file}:{pe.line}: {pe.message}")

        elapsed = int((time.time() - start) * 1000)

        # Determine overall success (results are normalized: every dict
        # carries an explicit "success" bool — same default as
        # ExecutionResult.success_count, so summary and counts agree)
        all_ok = (
            len(errors) == 0
            and all(r.get("success", False) for r in results)
        )

        logger.info(
            "executor.mcp",
            f"MCP execution complete: {len(results)} results, "
            f"{len(errors)} errors, {elapsed}ms",
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

        result = await self._call_tool_safe(session, 
            name=self.TOOL_SCENE_HIERARCHY,
            arguments={},
        )
        parsed = self._parse_tool_result(result)
        return self._unwrap_scene_hierarchy(parsed)

    async def _read_logs_async(self) -> str | None:
        """Fetch the raw Godot editor log text via MCP."""
        session = await self._ensure_session()
        result = await self._call_tool_safe(session,
            name=self.TOOL_LOGS_READ,
            arguments={},
        )
        return self._parse_tool_result_text(result)

    @staticmethod
    def _unwrap_scene_hierarchy(parsed: Any) -> Dict[str, Any] | None:
        """Extract the tree root from godot-ai's wrapped response.

        godot-ai's ``scene_get_hierarchy`` returns::

            {"root": "", "nodes": [...], "total_count": N, ...}

        Since at least 2.7.x the ``nodes`` list is FLAT — each entry has
        ``path`` and a numeric ``children_count`` but NO nested
        ``children`` array.  Taking ``nodes[0]`` as-is (the old behavior)
        handed the pipeline a bare root: the planner saw an empty scene,
        the validator validated against nothing, and the completeness
        checker re-injected Camera3D/DirectionalLight3D duplicates on
        every apply (observed live June 12, 2026).  Rebuild the nested
        tree from the paths instead.
        """
        if not isinstance(parsed, dict):
            return None
        nodes = parsed.get("nodes", [])
        if nodes and isinstance(nodes[0], dict):
            first = nodes[0]
            if "children" not in first and isinstance(first.get("path"), str):
                tree = GodotAIMCPExecutor._tree_from_flat(nodes)
                if tree is not None:
                    return tree
            return first
        root = parsed.get("root")
        if isinstance(root, dict):
            return root
        # Fallback: an unwrapped response that already IS the tree
        if "name" in parsed or "type" in parsed:
            return parsed
        return None

    @staticmethod
    def _tree_from_flat(nodes: list) -> Dict[str, Any] | None:
        """Rebuild a nested {name, type, children} tree from godot-ai's
        flat ``nodes`` list, linking children to parents via ``path``.
        Parents precede children in the walk order; entries whose parent
        falls outside the (possibly paginated/depth-limited) window attach
        to the root so no scanned node is silently dropped."""
        by_path: Dict[str, Dict[str, Any]] = {}
        root: Dict[str, Any] | None = None
        for n in nodes:
            if not isinstance(n, dict):
                continue
            path = n.get("path")
            if not isinstance(path, str) or not path:
                continue
            entry = {
                "name": n.get("name", ""),
                "type": n.get("type", ""),
                "children": [],
            }
            by_path[path] = entry
            parent_path = path.rsplit("/", 1)[0]
            parent = by_path.get(parent_path)
            if parent is not None:
                parent["children"].append(entry)
            elif root is None:
                root = entry
            else:
                root["children"].append(entry)
        return root

    async def _execute_ops_individually(
        self, session, operations: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
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
                commands = self._translate_ops_to_commands([op])
                batch_result = await self._call_tool_safe(
                    session,
                    name=self.TOOL_BATCH_EXECUTE,
                    arguments={"commands": commands},
                )
                parsed = self._parse_tool_result(batch_result)
                if isinstance(parsed, list):
                    for r in parsed:
                        results.append(self._normalize_op_result(r))
                elif isinstance(parsed, dict):
                    inner = parsed.get("results", [parsed])
                    for r in (inner if isinstance(inner, list) else [inner]):
                        results.append(self._normalize_op_result(r))
                else:
                    results.append({
                        "command": op_type,
                        "success": True,
                        "status": "ok",
                        "result": str(parsed),
                    })
            except Exception as exc:
                logger.warn(
                    "executor.mcp",
                    f"Per-op {i} ({op_type}) failed: {type(exc).__name__}: {exc}",
                )
                results.append({
                    "command": op_type,
                    "success": False,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                # Reconnect session after transport failure
                try:
                    await self._close_session()
                    session = await self._ensure_session()
                except Exception:
                    pass  # will retry session on next op
        return results

    # ------------------------------------------------------------------
    # Serialization round-trip (one-time)
    # ------------------------------------------------------------------

    def resolve_property_types(
        self, sample_values: Dict[str, Any] | None = None
    ) -> Dict[str, str]:
        """Perform a one-time round-trip to learn Godot property serialization.

        Calls ``node_get_properties`` on a reference node and records
        how Godot serializes Vector3, Color, resource paths, etc.
        Results are cached so the compiler can emit correct values.

        Note: ignores ``sample_values`` and fetches live from Godot.
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

    async def _resolve_node_properties_async(
        self, node_path: str
    ) -> dict | None:
        """Fetch live properties for *node_path* via MCP."""
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_NODE_GET_PROPERTIES,
            arguments={"node_path": node_path},
        )
        props = self._parse_tool_result(result)
        if not isinstance(props, dict):
            return None
        return props

    async def _find_symbols_async(self, path: str) -> dict | None:
        """Find symbols in a GDScript file via MCP.

        script_manage is a manage-style tool: kwargs go under "params".
        """
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_SCRIPT_MANAGE,
            arguments={
                "op": "find_symbols",
                "params": {"path": self._res_path(path)},
            },
        )
        parsed = self._parse_tool_result(result)
        if not isinstance(parsed, dict):
            return None
        return parsed

    async def _search_filesystem_async(
        self, query: str, path: str, recursive: bool,
    ) -> dict | None:
        """Search the project filesystem via MCP.

        filesystem_manage's op is "search" with params name/type/path/
        offset/limit. The search is always recursive server-side —
        *recursive* is accepted for API compatibility and ignored.
        """
        session = await self._ensure_session()
        params: dict[str, Any] = {"name": query}
        if path and path != "res://":
            params["path"] = self._res_path(path)
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_FILESYSTEM_MANAGE,
            arguments={"op": "search", "params": params},
        )
        parsed = self._parse_tool_result(result)
        if not isinstance(parsed, dict):
            return None
        return parsed

    async def _get_performance_monitors_async(
        self, monitors: list[str] | None = None
    ) -> dict | None:
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
        parsed = self._parse_tool_result(result)
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

    async def _run_project_async(
        self, mode: str = "main", scene: str = ""
    ) -> dict | None:
        """Launch via the dedicated project_run tool (NOT project_manage,
        whose only lifecycle op is "stop")."""
        session = await self._ensure_session()
        arguments: dict[str, Any] = {"mode": mode}
        if scene:
            arguments["scene"] = scene
        result = await self._call_tool_safe(
            session, name=self.TOOL_PROJECT_RUN, arguments=arguments
        )
        parsed = self._parse_tool_result(result)
        return parsed if isinstance(parsed, dict) else None

    async def _stop_project_async(self) -> dict | None:
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session, name=self.TOOL_PROJECT_MANAGE, arguments={"op": "stop"}
        )
        parsed = self._parse_tool_result(result)
        return parsed if isinstance(parsed, dict) else None

    async def _game_eval_async(self, expression: str) -> str | None:
        """Evaluate GDScript in the running game.

        game_eval is an op of editor_manage; the handler's parameter is
        named ``code``.
        """
        session = await self._ensure_session()
        result = await self._call_tool_safe(
            session,
            name=self.TOOL_EDITOR_MANAGE,
            arguments={"op": "game_eval", "params": {"code": expression}},
        )
        parsed = self._parse_tool_result(result)
        return str(parsed) if parsed is not None else None

    async def _take_screenshot_async(self) -> str | None:
        """Capture the running game via editor_screenshot.

        include_image=False keeps base64 payloads out of the smoke-run
        loop — the metadata (dimensions/source) is the receipt. Returns
        a compact identifier string, not a file path (godot-ai returns
        image data, not paths).
        """
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
        parsed = self._parse_tool_result(result)
        if isinstance(parsed, dict):
            w = parsed.get("width", "?")
            h = parsed.get("height", "?")
            return f"{parsed.get('source', 'game')}:{w}x{h}"
        return str(parsed) if parsed is not None else None

    # ------------------------------------------------------------------
    # Operation format translation
    # ------------------------------------------------------------------

    @classmethod
    def _translate_ops_to_commands(
        cls, operations: List[Dict[str, Any]]
    ) -> list[dict]:
        """Convert DevForge flat operations to godot-ai nested commands.

        DevForge generates flat dicts like::

            {"type": "add_node", "parent": "/root/Main",
             "node_type": "Camera3D", "name": "MainCamera"}

        godot-ai's ``batch_execute`` expects::

            {"command": "create_node",
             "params": {"parent_path": "/root/Main",
                       "type": "Camera3D", "name": "MainCamera"}}
        """
        commands: list[dict] = []
        for op in operations:
            op_type = op.get("type", "")
            command_name = cls._OP_TO_COMMAND.get(op_type)
            if command_name is None:
                logger.warn(
                    "executor.mcp",
                    f"Unknown operation type '{op_type}' — skipping",
                )
                continue

            field_map = cls._FIELD_MAP.get(op_type, {})
            params: dict[str, Any] = {}
            for key, value in op.items():
                if key in cls._DROP_FIELDS:
                    continue
                mapped_key = field_map.get(key, key)
                params[mapped_key] = value

            # godot-ai validates resource paths as res:// URIs
            if "script_path" in params:
                params["script_path"] = cls._res_path(params["script_path"])

            commands.append({"command": command_name, "params": params})

        return commands

    @staticmethod
    def _res_path(path: str) -> str:
        """Normalize a project-relative path to the res:// form godot-ai
        requires (its path validator rejects anything else)."""
        if path.startswith("res://"):
            return path
        return f"res://{path.lstrip('/')}"

    # ------------------------------------------------------------------
    # Tool result parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_op_result(r: Any) -> Any:
        """Ensure a per-op batch result carries an explicit ``success`` bool.

        godot-ai's batch_execute reports per-command outcomes as
        ``{"command": ..., "status": "ok"|"error", ...}`` — it never sends
        a ``success`` key. ExecutionResult.success_count/failure_count
        require one, so without normalization every applied op counts as
        a failure while the overall result still says success.
        """
        if not isinstance(r, dict) or "success" in r:
            return r
        status = str(r.get("status", "")).lower()
        r["success"] = status in ("ok", "success") and "error" not in r
        return r

    @staticmethod
    def _parse_tool_result(result) -> Any:
        """Extract the value from an MCP tool call result.

        MCP results come as CallToolResult with a list of content blocks.
        We try JSON first, then plain text.
        """
        if result is None:
            return None

        # Result may have a .content attribute (list of TextContent blocks)
        content = getattr(result, "content", None)
        if content is None:
            return result

        if not content:
            return None

        # Single content block
        if len(content) == 1:
            text = getattr(content[0], "text", None)
            if text is not None:
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
            return content[0]

        # Multiple content blocks — try each
        texts = []
        for block in content:
            text = getattr(block, "text", None)
            if text is not None:
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    texts.append(text)

        return texts[0] if len(texts) == 1 else texts

    @staticmethod
    def _parse_tool_result_text(result) -> str | None:
        """Extract plain text from an MCP tool result."""
        text = GodotAIMCPExecutor._parse_tool_result(result)
        if isinstance(text, str):
            return text
        if isinstance(text, (list, dict)):
            return json.dumps(text)
        return str(text) if text is not None else None
