"""MCP session — persistent connection, circuit-breaker, and background event loop.

Wraps the godot-ai MCP Streamable HTTP transport so the executor doesn't
own the session lifecycle directly.  Extracted from ``godot_ai_mcp.py``
during the Phase 1A split.

Usage::

    session = MCPSession(mcp_url="http://localhost:8000/mcp")
    coro_result = session.run_coro(_some_async_fn())
    # inside async:
    mcp_sess = await session.ensure()
    result = await session.call_tool_safe(mcp_sess, "tool_name", {...})
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from devforge.infrastructure.logger import logger


class MCPSession:
    """Persistent MCP session to godot-ai with circuit-breaker backoff.

    Holds one Streamable HTTP connection open across all tool calls.
    Runs on its own dedicated background event loop so sync callers
    (FastMCP tool handlers) can dispatch coroutines via
    ``run_coroutine_threadsafe``.
    """

    def __init__(self, mcp_url: str = "http://localhost:8000/mcp") -> None:
        self._mcp_url = mcp_url

        # ── Session state ──────────────────────────────────────
        self._read: Any = None
        self._write: Any = None
        self._session: Any = None
        self._transport_ctx: Any = None  # streamable_http_client context manager for cleanup
        self._lock = asyncio.Lock()

        # ── Circuit breaker state ──────────────────────────────
        self._failures: int = 0
        self._failure_threshold: int = 5
        self._backoff_ms: int = 1000
        self._max_backoff_ms: int = 30_000
        self._next_retry_mono: float = 0.0

        # ── Dedicated background event loop ────────────────────
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread: threading.Thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="godot-mcp-loop",
        )
        self._thread.start()
        logger.info("executor.mcp", "Started dedicated MCP event-loop thread (persistent session)")

    # ── Coroutine dispatch ─────────────────────────────────────────

    def run_coro(self, coro, timeout: float = 480.0):
        """Run a coroutine on the dedicated event loop; return its result.

        Timeout tree: llama_client allows 120s per LLM call with 2 attempts
        (=240s per planner call), and the pipeline retries up to 3 planner
        calls (=720s worst case). This outer MCP-call timeout must exceed the
        inner retry chain plus overhead (transport reconnect, scene fetch, logs)
        so a retrying planner isn't killed by the executor before it finishes.
        480s covers 2 full planner calls with overhead.
        """
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    # ── Session lifecycle ──────────────────────────────────────────

    async def ensure(self):
        """Return a live MCP session, creating or reconnecting as needed.

        Must run on ``self._loop``.  Uses an asyncio.Lock to serialize
        concurrent reconnection attempts.  The circuit breaker prevents
        hot-retry death spirals when godot-ai is unreachable.
        """
        if self._session is not None:
            return self._session

        async with self._lock:
            # Double-check after acquiring the lock
            if self._session is not None:
                return self._session

            # Circuit breaker: don't hammer a dead server
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client

            now = time.monotonic()
            if now < self._next_retry_mono:
                wait_ms = int((self._next_retry_mono - now) * 1000)
                raise ConnectionError(
                    f"MCP session circuit open after {self._failures} consecutive failures — retry in {wait_ms}ms"
                )

            # Tear down any stale transport state
            await self._close()

            try:
                transport_ctx = streamable_http_client(self._mcp_url)
                read, write, _ = await transport_ctx.__aenter__()
                session = ClientSession(read, write)
                await session.__aenter__()
                await session.initialize()

                self._transport_ctx = transport_ctx
                self._read = read
                self._write = write
                self._session = session

                # Reset circuit on successful connection
                self._failures = 0
                self._backoff_ms = 1000
                self._next_retry_mono = 0.0

                logger.info("executor.mcp", "Persistent MCP session established")
                return self._session

            except Exception as exc:
                self._record_failure()
                raise ConnectionError(f"Failed to establish MCP session to {self._mcp_url}: {exc}") from exc

    async def _close(self):
        """Close the persistent MCP session and its transport."""
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None

        # Close the streamable HTTP transport context manager
        if self._transport_ctx is not None:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._transport_ctx = None

        self._read = None
        self._write = None

    async def call_tool_safe(self, session, name: str, arguments: dict) -> Any:
        """Call a tool on the persistent session, invalidating on failure.

        If the call fails with a transport-level error, the session is
        closed so the next call reconnects.  Tool-level errors (valid
        MCP responses with isError=True) are returned normally.
        """
        try:
            return await session.call_tool(name=name, arguments=arguments)
        except Exception:
            await self._close()
            self._failures += 1
            raise

    def _record_failure(self):
        """Record a transport failure and possibly open the circuit.

        After ``_failure_threshold`` consecutive failures, the
        circuit opens for an exponentially-growing backoff window.
        Also clears ``_session`` so the next call reconnects.
        """
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._session = None
            mono = time.monotonic()
            current_backoff = self._backoff_ms
            self._next_retry_mono = mono + current_backoff / 1000.0
            self._backoff_ms = min(current_backoff * 2, self._max_backoff_ms)
            logger.warn(
                "executor.mcp",
                f"MCP session circuit OPEN after {self._failures} failures — backoff {current_backoff}ms",
            )

    def shutdown(self):
        """Close the persistent session and stop the background loop.

        Call this when the executor is no longer needed (e.g. server
        shutdown).  Safe to call multiple times.
        """
        if self._loop.is_running():
            try:
                self.run_coro(self._close(), timeout=5.0)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("executor.mcp", "MCP executor shut down")
