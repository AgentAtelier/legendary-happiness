"""Unit tests for GodotAIMCPExecutor persistent Streamable HTTP session.

Tests cover:
  - Session reuse across calls (no reconnect on second use)
  - Circuit breaker triggers after threshold failures
  - Circuit breaker resets on successful reconnect
  - Tool failure invalidates session (_call_tool_safe)
  - streamable_http_client context manager cleanup verification
  - Exponential backoff doubling

All transport is mocked — no godot-ai server is required.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from devforge.execution.godot_ai_mcp import GodotAIMCPExecutor
from devforge.execution.interface import ExecutionResult


# ── Fixtures ──────────────────────────────────────────────────────

class _MockContent:
    """Fake MCP text content block."""
    def __init__(self, text: str):
        self.text = text
        self.type = "text"


class _MockCallToolResult:
    """Fake MCP CallToolResult object."""
    def __init__(self, text: str = '{"results": [{"success": true}]}'):
        self.content = [_MockContent(text)]
        self.isError = False


def _make_mock_session():
    """Create a mock ClientSession that returns canned tool results."""
    session = AsyncMock()
    session.call_tool = AsyncMock(return_value=_MockCallToolResult())
    session.initialize = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.fixture
def mock_transport():
    """Patch streamable_http_client and ClientSession at their source modules.

    These are imported LOCALLY inside _ensure_session() via:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

    So we must patch the source modules, not godot_ai_mcp.
    """
    mock_session = _make_mock_session()

    mock_read = AsyncMock()
    mock_write = AsyncMock()
    mock_read.aclose = AsyncMock()
    mock_write.aclose = AsyncMock()

    mock_transport_ctx = AsyncMock()
    # streamable_http_client yields (read, write, get_session_id)
    mock_transport_ctx.__aenter__ = AsyncMock(
        return_value=(mock_read, mock_write, MagicMock())
    )
    mock_transport_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "mcp.client.streamable_http.streamable_http_client", return_value=mock_transport_ctx,
    ) as mock_streamable_http_client, patch(
        "mcp.ClientSession", return_value=mock_session,
    ):
        yield {
            "transport_client": mock_streamable_http_client,
            "session": mock_session,
            "read": mock_read,
            "write": mock_write,
            "transport_ctx": mock_transport_ctx,
        }


def _run_on_loop(executor, coro):
    """Run a coroutine on the executor's event loop and return result."""
    future = asyncio.run_coroutine_threadsafe(coro, executor._loop)
    return future.result(timeout=5.0)


def _shutdown(executor):
    """Safely shut down an executor and its background loop."""
    try:
        executor.shutdown()
    except Exception:
        pass


# ── Tests: session reuse ──────────────────────────────────────────

def test_session_reuse_across_calls(mock_transport):
    """Second call to _ensure_session reuses the same session object."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    try:
        session1 = _run_on_loop(executor, executor._ensure_session())
        session2 = _run_on_loop(executor, executor._ensure_session())

        assert session1 is session2, (
            "_ensure_session should return the same session object on "
            "subsequent calls — no reconnect expected"
        )
        assert mock_transport["transport_client"].call_count == 1, (
            "streamable_http_client should be called exactly once"
        )
    finally:
        _shutdown(executor)


def test_session_reuse_after_successful_tool_call(mock_transport):
    """After a successful execute(), session stays alive for next call."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    try:
        result = executor.execute(
            operations=[{"type": "add_node", "name": "Test"}],
            files=[],
        )
        assert result.success, f"Expected success, got errors: {result.errors}"
        assert executor._mcp_session is not None
        assert executor._mcp_failures == 0
        assert mock_transport["transport_client"].call_count == 1
    finally:
        _shutdown(executor)


# ── Tests: circuit breaker ────────────────────────────────────────

def test_circuit_breaker_not_triggered_below_threshold(mock_transport):
    """A few failures don't open the circuit."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    executor._mcp_failure_threshold = 100
    try:
        for _ in range(3):
            executor._mcp_failures += 1
            executor._mcp_session = None

        session = _run_on_loop(executor, executor._ensure_session())
        assert session is not None
        assert executor._mcp_next_retry_mono == 0.0
    finally:
        _shutdown(executor)


def test_circuit_breaker_triggers_after_threshold(mock_transport):
    """After threshold failures, _ensure_session raises ConnectionError."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    executor._mcp_failure_threshold = 2
    try:
        executor._mcp_failures = executor._mcp_failure_threshold
        executor._mcp_session = None
        executor._record_mcp_failure()

        assert executor._mcp_next_retry_mono > time.monotonic(), (
            "Circuit breaker should have set a future retry time"
        )

        with pytest.raises(ConnectionError, match="circuit open"):
            _run_on_loop(executor, executor._ensure_session())
    finally:
        _shutdown(executor)


def test_circuit_breaker_backoff_expires(mock_transport):
    """After the backoff window passes, reconnection is allowed."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    executor._mcp_failure_threshold = 2
    try:
        executor._mcp_failures = executor._mcp_failure_threshold
        executor._mcp_session = None
        executor._mcp_next_retry_mono = time.monotonic() - 10.0
        executor._mcp_backoff_ms = 1000

        session = _run_on_loop(executor, executor._ensure_session())
        assert session is not None
        assert executor._mcp_failures == 0  # reset on success
    finally:
        _shutdown(executor)


def test_circuit_breaker_resets_on_successful_reconnect(mock_transport):
    """After a successful reconnect, failure counter and backoff reset."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    executor._mcp_failure_threshold = 3
    try:
        executor._mcp_failures = 2
        executor._mcp_session = None
        executor._mcp_backoff_ms = 8000
        executor._mcp_next_retry_mono = time.monotonic() - 1.0

        _run_on_loop(executor, executor._ensure_session())

        assert executor._mcp_failures == 0, "Failure counter should reset"
        assert executor._mcp_backoff_ms == 1000, "Backoff should reset to initial"
        assert executor._mcp_next_retry_mono == 0.0, "Retry timer should clear"
    finally:
        _shutdown(executor)


# ── Tests: tool failure invalidates session ───────────────────────

def test_call_tool_safe_closes_session_on_failure(mock_transport):
    """When session.call_tool() raises, the session is closed."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    try:
        _run_on_loop(executor, executor._ensure_session())
        assert executor._mcp_session is not None

        # Override call_tool to raise on the stored session
        executor._mcp_session.call_tool.side_effect = ConnectionError("SSE dropped")

        try:
            _run_on_loop(
                executor,
                executor._call_tool_safe(
                    executor._mcp_session,
                    name="batch_execute",
                    arguments={"ops": []},
                ),
            )
        except ConnectionError:
            pass

        assert executor._mcp_session is None, (
            "Session should be None after _call_tool_safe failure"
        )
        assert executor._mcp_failures >= 1, (
            "Failure counter should be incremented"
        )
        # Verify sse_ctx cleanup was called
        assert mock_transport["transport_ctx"].__aexit__.called, (
            "streamable_http_client context manager should be __aexit__'d on close"
        )
    finally:
        _shutdown(executor)


def test_session_reconnects_after_call_tool_safe_failure(mock_transport):
    """After _call_tool_safe kills the session, next call reconnects."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    try:
        _run_on_loop(executor, executor._ensure_session())

        # Kill the session via _call_tool_safe
        executor._mcp_session.call_tool.side_effect = ConnectionError("boom")
        try:
            _run_on_loop(
                executor,
                executor._call_tool_safe(
                    executor._mcp_session, name="test", arguments={},
                ),
            )
        except ConnectionError:
            pass

        # Session should be dead now
        assert executor._mcp_session is None

        # On reconnect, ClientSession is called again — but the mock always
        # returns the same object. Verify that streamable_http_client was called again
        # (a new transport was opened) rather than comparing session identities.
        first_call_count = mock_transport["transport_client"].call_count

        next_session = _run_on_loop(executor, executor._ensure_session())
        assert next_session is not None
        assert mock_transport["transport_client"].call_count > first_call_count, (
            "streamable_http_client should be called again for reconnect"
        )
    finally:
        _shutdown(executor)


# ── Tests: _record_mcp_failure edge cases ─────────────────────────

def test_record_mcp_failure_below_threshold_does_not_open_circuit():
    """_record_mcp_failure below threshold doesn't set backoff timer."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    executor._mcp_failure_threshold = 5
    try:
        executor._mcp_failures = 3
        executor._record_mcp_failure()

        assert executor._mcp_next_retry_mono == 0.0, (
            "Below threshold, no backoff should be set"
        )
        assert executor._mcp_failures == 4
    finally:
        _shutdown(executor)


def test_record_mcp_failure_exponential_backoff(mock_transport):
    """Backoff doubles each time the circuit opens."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    executor._mcp_failure_threshold = 2
    try:
        executor._mcp_failures = executor._mcp_failure_threshold
        executor._record_mcp_failure()
        assert executor._mcp_backoff_ms == 2000  # doubled from 1000

        executor._mcp_next_retry_mono = 0.0
        executor._mcp_failures = executor._mcp_failure_threshold
        executor._record_mcp_failure()
        assert executor._mcp_backoff_ms == 4000  # doubled again

        executor._mcp_next_retry_mono = 0.0
        executor._mcp_failures = executor._mcp_failure_threshold
        executor._record_mcp_failure()
        assert executor._mcp_backoff_ms == 8000
    finally:
        _shutdown(executor)


# ── Tests: execute() with mocked transport ────────────────────────

def test_execute_returns_success_result(mock_transport):
    """execute() returns ExecutionResult with success=True on clean run."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    try:
        result = executor.execute(
            operations=[
                {"type": "add_node", "name": "Camera", "node_type": "Camera3D"},
            ],
            files=[],
        )

        assert isinstance(result, ExecutionResult)
        assert result.success, f"Expected success, got: {result.errors}"
        assert len(result.results) > 0
    finally:
        _shutdown(executor)


def test_get_scene_returns_dict(mock_transport):
    """get_scene() returns a dict from the mocked hierarchy tool."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    # godot-ai wraps the hierarchy as {"root": ..., "nodes": [...]} —
    # _unwrap_scene_hierarchy must extract the tree from nodes[0].
    mock_transport["session"].call_tool.return_value = _MockCallToolResult(
        '{"root": {"name": "Main", "type": "Node3D"},'
        ' "nodes": [{"name": "Main", "type": "Node3D", "children": []}],'
        ' "total_count": 1}'
    )
    try:
        scene = executor.get_scene()
        assert isinstance(scene, dict)
        assert scene["name"] == "Main"
        assert scene["children"] == []
    finally:
        _shutdown(executor)


# ── Tests: mid-execution session death ──────────────────────────

def test_execute_reconnects_after_mid_execution_session_death(mock_transport):
    """After the session dies mid-execute, the next execute() reconnects.

    Simulates the transport dropping between tool calls inside a single
    ``_execute_async`` call: batch_execute raises ConnectionError, which
    ``_call_tool_safe`` catches, closes the session, and re-raises. The
    execute() returns an error result. The next execute() must reconnect
    and succeed.
    """
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    try:
        # ── First execute: session dies during batch_execute ──
        # Set up call_tool to succeed for create_file (no files, so skipped),
        # then fail on batch_execute.
        mock_transport["session"].call_tool.side_effect = ConnectionError(
            "SSE transport dropped during batch_execute"
        )

        result1 = executor.execute(
            operations=[
                {"type": "add_node", "name": "Camera", "node_type": "Camera3D"},
            ],
            files=[],
        )

        # First execute should report failure
        assert not result1.success, (
            "First execute should fail when session dies mid-execution"
        )
        assert len(result1.errors) > 0, "Error messages should be recorded"
        assert executor._mcp_session is None, (
            "Session should be closed after _call_tool_safe caught the error"
        )
        assert executor._mcp_failures >= 1, (
            "Failure counter should be incremented"
        )

        # ── Second execute: must reconnect and succeed ──
        # Reset the mock to succeed
        mock_transport["session"].call_tool.side_effect = None
        mock_transport["session"].call_tool.return_value = _MockCallToolResult()

        result2 = executor.execute(
            operations=[
                {"type": "add_node", "name": "Light", "node_type": "DirectionalLight3D"},
            ],
            files=[],
        )

        assert result2.success, (
            f"Second execute should succeed after reconnect, got: {result2.errors}"
        )
        assert executor._mcp_session is not None, (
            "A new session should be established"
        )
        # Failure counter should be reset after successful reconnect
        assert executor._mcp_failures == 0, (
            "Failure counter should reset on successful reconnect"
        )
        # streamable_http_client must be called again for the reconnect.
        # NOTE: with the C8 per-operation retry (MAX_BATCH_RETRIES=2,
        # reconnecting between attempts), a permanently-failing first execute
        # opens >1 transport on its own, so assert "reconnect happened"
        # (>= 2) rather than an exact count brittle to the retry depth.
        assert mock_transport["transport_client"].call_count >= 2, (
            "streamable_http_client should be called again for the reconnect"
        )
    finally:
        _shutdown(executor)


def test_execute_handles_partial_failure_then_reconnects(mock_transport):
    """When batch_execute fails but create_file succeeded, still reconnects.

    The session dies on the second tool call (batch_execute). The first
    call (create_file) may have succeeded. The session is still killed,
    and the next execute() reconnects cleanly.
    """
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    try:
        # call_tool succeeds for create_file, fails for batch_execute
        call_count = 0

        def _fail_on_second(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # create_file succeeds
                return _MockCallToolResult('{"ok": true}')
            # batch_execute fails
            raise ConnectionError("SSE dropped on batch_execute")

        mock_transport["session"].call_tool.side_effect = _fail_on_second

        result1 = executor.execute(
            operations=[{"type": "add_node", "name": "X", "node_type": "Node3D"}],
            files=[{"path": "test.gd", "content": "extends Node"}],
        )

        assert not result1.success
        assert executor._mcp_session is None
        assert executor._mcp_failures >= 1, (
            "Failure counter should be incremented after mid-execution death"
        )

        # ── Reconnect and succeed ──
        mock_transport["session"].call_tool.side_effect = None
        mock_transport["session"].call_tool.return_value = _MockCallToolResult()

        result2 = executor.execute(
            operations=[{"type": "add_node", "name": "Y", "node_type": "Node3D"}],
            files=[],
        )

        assert result2.success, f"Second execute should succeed: {result2.errors}"
        # >= 2 (not == 2): the C8 per-op retry reconnects between attempts, so a
        # failing first execute opens more than one transport before the second
        # execute's reconnect. Assert "reconnect happened", not an exact count.
        assert mock_transport["transport_client"].call_count >= 2
    finally:
        _shutdown(executor)


# ── Tests: circuit breaker from accumulated tool-call failures ──

def test_circuit_breaker_opens_from_accumulated_tool_failures(mock_transport):
    """Tool-call failures during execute() push counter past threshold.

    When ``_call_tool_safe`` failures within a single ``execute()``
    push ``_mcp_failures`` past the threshold, and the subsequent
    reconnection attempt also fails, the combined count opens the
    circuit breaker.  This verifies that tool-call failures aren't
    silently reset — they contribute to the circuit decision.
    """
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    executor._mcp_failure_threshold = 2  # lower for fast test
    try:
        # ── Step 1: accumulate failures via tool calls ──
        # All tool calls fail → _call_tool_safe increments counter
        # No files, so: batch_execute + logs_read + scene_hierarchy
        # = 3 failures -> _mcp_failures = 3 (past threshold of 2)
        mock_transport["session"].call_tool.side_effect = ConnectionError("tool-call failure")

        result1 = executor.execute(
            operations=[{"type": "add_node", "name": "X", "node_type": "Node3D"}],
            files=[],
        )

        assert not result1.success
        assert executor._mcp_session is None
        assert executor._mcp_failures >= 2, (
            f"Expected counter past threshold (2) from accumulated "
            f"tool-call failures, got {executor._mcp_failures}"
        )

        # ── Step 2: reconnect attempt also fails → circuit opens ──
        # Make streamable_http_client's context manager raise on __aenter__
        mock_transport["transport_ctx"].__aenter__.side_effect = ConnectionError(
            "godot-ai unreachable"
        )

        # _ensure_session will fail → _record_mcp_failure called
        # -> counter goes 3→4 -> circuit opens with backoff
        with pytest.raises(ConnectionError, match="godot-ai unreachable"):
            _run_on_loop(executor, executor._ensure_session())

        assert executor._mcp_failures >= executor._mcp_failure_threshold, (
            "Counter should be at or past threshold"
        )
        assert executor._mcp_next_retry_mono > time.monotonic(), (
            "Circuit breaker should have set a future retry time"
        )
        assert executor._mcp_backoff_ms >= 2000, (
            "Backoff should have doubled from the initial 1000ms"
        )

        # ── Step 3: immediate retry is blocked by circuit ──
        with pytest.raises(ConnectionError, match="circuit open"):
            _run_on_loop(executor, executor._ensure_session())

        # ── Step 4: after backoff expires, retry succeeds ──
        # Reset mocks and expire the backoff
        mock_transport["transport_ctx"].__aenter__.side_effect = None
        mock_transport["session"].call_tool.side_effect = None
        mock_transport["session"].call_tool.return_value = _MockCallToolResult()
        executor._mcp_next_retry_mono = time.monotonic() - 10.0

        session = _run_on_loop(executor, executor._ensure_session())
        assert session is not None
        assert executor._mcp_failures == 0, (
            "Counter should reset after successful reconnect"
        )

        # ── Step 5: now execute() works end-to-end ──
        result2 = executor.execute(
            operations=[{"type": "add_node", "name": "Y", "node_type": "Node3D"}],
            files=[],
        )
        assert result2.success, f"Execute should succeed after circuit reset: {result2.errors}"
    finally:
        _shutdown(executor)


# ── Tests: concurrent _ensure_session ─────────────────────────────

def test_concurrent_ensure_session_only_connects_once(mock_transport):
    """Two racing _ensure_session tasks produce exactly one connection."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    try:
        async def two_racers():
            # First, kill the session
            executor._mcp_session = None
            # Race two _ensure_session calls
            s1, s2 = await asyncio.gather(
                executor._ensure_session(),
                executor._ensure_session(),
            )
            return s1, s2

        session_a, session_b = _run_on_loop(executor, two_racers())

        # Both should get the same session object
        assert session_a is session_b, (
            "Racing _ensure_session calls should return the same session"
        )
        # Only one transport connection
        assert mock_transport["transport_client"].call_count == 1
    finally:
        _shutdown(executor)


# ── Tests: shutdown ───────────────────────────────────────────────

def test_shutdown_stops_background_loop(mock_transport):
    """shutdown() closes the session and stops the event loop."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    executor.shutdown()

    executor._thread.join(timeout=2.0)
    # loop.stop() stops run_forever but doesn't close the loop.
    # is_running() is the correct signal here.
    assert not executor._loop.is_running(), (
        "Event loop should not be running after shutdown"
    )


def test_shutdown_idempotent(mock_transport):
    """shutdown() is safe to call multiple times."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    executor.shutdown()
    executor.shutdown()  # no-op, should not raise
    assert not executor._loop.is_running()


# ── Tests: op → godot-ai plugin command translation ──────────────
# Audited against godot-ai's plugin.gd dispatcher registry (June 2026):
# batch_execute dispatches on PLUGIN command names (attach_script,
# create_node, ...), not the category-prefixed MCP tool names
# (script_attach, node_create, ...). Node targets are read from `path`.

def test_translate_uses_plugin_command_names():
    """Every op maps to a command registered in godot-ai's dispatcher."""
    commands = GodotAIMCPExecutor._translate_ops_to_commands([
        {"type": "add_node", "parent": "/root/Main",
         "node_type": "Camera3D", "name": "Cam"},
        {"type": "set_property", "node": "/root/Main/Cam",
         "property": "fov", "value": 90},
        {"type": "attach_script", "node": "/root/Main/Cam",
         "script": "scripts/cam.gd"},
        {"type": "connect_signal", "source": "/root/Main/Btn",
         "signal": "pressed", "target": "/root/Main", "method": "_on_pressed"},
    ])

    assert commands == [
        {"command": "create_node", "params": {
            "parent_path": "/root/Main", "type": "Camera3D", "name": "Cam"}},
        {"command": "set_property", "params": {
            "path": "/root/Main/Cam", "property": "fov", "value": 90}},
        {"command": "attach_script", "params": {
            "path": "/root/Main/Cam", "script_path": "res://scripts/cam.gd"}},
        {"command": "connect_signal", "params": {
            "path": "/root/Main/Btn", "signal": "pressed",
            "target": "/root/Main", "method": "_on_pressed"}},
    ]


def test_res_path_normalization():
    """Project-relative script paths gain the res:// prefix exactly once."""
    assert GodotAIMCPExecutor._res_path("scripts/a.gd") == "res://scripts/a.gd"
    assert GodotAIMCPExecutor._res_path("res://scripts/a.gd") == "res://scripts/a.gd"
    assert GodotAIMCPExecutor._res_path("/scripts/a.gd") == "res://scripts/a.gd"


def test_script_create_sends_res_path(mock_transport):
    """File creation calls the script_create TOOL with a res:// path."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    try:
        result = executor.execute(
            operations=[],
            files=[{"path": "scripts/player.gd", "content": "extends Node"}],
        )
        assert result.success, result.errors
        # execute() also fetches the scene snapshot afterwards — find
        # the script_create call among all tool calls.
        creates = [
            c for c in mock_transport["session"].call_tool.call_args_list
            if c.kwargs.get("name") == "script_create"
        ]
        assert len(creates) == 1
        assert creates[0].kwargs["arguments"]["path"] == "res://scripts/player.gd"
    finally:
        _shutdown(executor)


# ── Tests: read_logs (WO-003) ────────────────────────────────────

def test_read_logs_returns_text(mock_transport):
    """read_logs() returns the log text from the mocked logs_read tool."""
    import json
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    log_msg = "player.gd:42 - Invalid call. Nonexistent function 'move' in base 'Node3D'."
    mock_transport["session"].call_tool.return_value = _MockCallToolResult(
        json.dumps(log_msg)
    )
    try:
        logs = executor.read_logs()
        assert logs is not None
        assert "player.gd" in logs
        assert "Invalid call" in logs
    finally:
        _shutdown(executor)


def test_read_logs_returns_none_on_failure(mock_transport):
    """read_logs() returns None when the transport fails."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    mock_transport["session"].call_tool.side_effect = ConnectionError("logs_read failed")
    try:
        logs = executor.read_logs()
        assert logs is None
    finally:
        _shutdown(executor)


# ── Tests: resolve_node_properties (WO-004) ──────────────────────

def test_resolve_node_properties_returns_dict(mock_transport):
    """resolve_node_properties() returns a property dict from mocked transport."""
    import json
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    props = {"current": True, "fov": 75.0, "near": 0.05}
    mock_transport["session"].call_tool.return_value = _MockCallToolResult(
        json.dumps(props)
    )
    try:
        result = executor.resolve_node_properties("/root/Main/Camera")
        assert result is not None
        assert result["current"] is True
        assert result["fov"] == 75.0
    finally:
        _shutdown(executor)


def test_resolve_node_properties_returns_none_on_failure(mock_transport):
    """resolve_node_properties() returns None when transport fails."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    mock_transport["session"].call_tool.side_effect = ConnectionError("down")
    try:
        result = executor.resolve_node_properties("/root/Main/Camera")
        assert result is None
    finally:
        _shutdown(executor)


# ── Tests: get_performance_monitors (WO-010) ─────────────────────

def test_get_performance_monitors_returns_dict(mock_transport):
    """get_performance_monitors() returns a metrics dict from mocked transport."""
    import json
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    metrics = {"time/fps": 60.0, "rendering/total_draw_calls": 120}
    mock_transport["session"].call_tool.return_value = _MockCallToolResult(
        json.dumps(metrics)
    )
    try:
        result = executor.get_performance_monitors()
        assert result is not None
        assert result["time/fps"] == 60.0
        assert result["rendering/total_draw_calls"] == 120
    finally:
        _shutdown(executor)


def test_get_performance_monitors_returns_none_on_failure(mock_transport):
    """get_performance_monitors() returns None when transport fails."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    mock_transport["session"].call_tool.side_effect = ConnectionError("down")
    try:
        result = executor.get_performance_monitors()
        assert result is None
    finally:
        _shutdown(executor)


def test_get_performance_monitors_wire_shape(mock_transport):
    """Perf monitors go through editor_manage with op monitors_get.

    Wire shapes in this block are audited against godot-ai's registered
    MCP tools — manage-style tools take {"op": ..., "params": {...}}.
    The original implementation guessed nonexistent tool names; these
    tests pin the verified contracts.
    """
    import json
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    mock_transport["session"].call_tool.return_value = _MockCallToolResult(
        json.dumps({"time/fps": 60.0})
    )
    try:
        result = executor.get_performance_monitors(monitors=["time/fps"])
        assert result is not None
        assert result["time/fps"] == 60.0
        call = mock_transport["session"].call_tool.call_args_list[-1]
        assert call.kwargs["name"] == "editor_manage"
        assert call.kwargs["arguments"]["op"] == "monitors_get"
        assert call.kwargs["arguments"]["params"]["monitors"] == ["time/fps"]
    finally:
        _shutdown(executor)


def test_game_eval_wire_shape(mock_transport):
    """game_eval is an editor_manage op; the handler param is 'code'."""
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    mock_transport["session"].call_tool.return_value = _MockCallToolResult('"42"')
    try:
        result = executor.game_eval("1 + 41")
        assert result is not None
        call = mock_transport["session"].call_tool.call_args_list[-1]
        assert call.kwargs["name"] == "editor_manage"
        assert call.kwargs["arguments"]["op"] == "game_eval"
        assert call.kwargs["arguments"]["params"]["code"] == "1 + 41"
    finally:
        _shutdown(executor)


def test_take_screenshot_wire_shape(mock_transport):
    """Screenshots use the dedicated editor_screenshot tool, source=game."""
    import json
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    mock_transport["session"].call_tool.return_value = _MockCallToolResult(
        json.dumps({"source": "game", "width": 640, "height": 360})
    )
    try:
        result = executor.take_screenshot()
        assert result == "game:640x360"
        call = mock_transport["session"].call_tool.call_args_list[-1]
        assert call.kwargs["name"] == "editor_screenshot"
        assert call.kwargs["arguments"]["source"] == "game"
        assert call.kwargs["arguments"]["include_image"] is False
    finally:
        _shutdown(executor)


def test_run_project_wire_shape(mock_transport):
    """Launching uses the dedicated project_run tool (project_manage has no run op)."""
    import json
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    mock_transport["session"].call_tool.return_value = _MockCallToolResult(
        json.dumps({"status": "running"})
    )
    try:
        result = executor.run_project()
        assert result == {"status": "running"}
        call = mock_transport["session"].call_tool.call_args_list[-1]
        assert call.kwargs["name"] == "project_run"
        assert call.kwargs["arguments"]["mode"] == "main"
    finally:
        _shutdown(executor)


def test_stop_project_wire_shape(mock_transport):
    """Stopping uses project_manage with op 'stop' (not 'stop_project')."""
    import json
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    mock_transport["session"].call_tool.return_value = _MockCallToolResult(
        json.dumps({"status": "stopped"})
    )
    try:
        result = executor.stop_project()
        assert result == {"status": "stopped"}
        call = mock_transport["session"].call_tool.call_args_list[-1]
        assert call.kwargs["name"] == "project_manage"
        assert call.kwargs["arguments"]["op"] == "stop"
    finally:
        _shutdown(executor)


def test_find_symbols_wire_shape(mock_transport):
    """find_symbols nests its path under params (manage-tool convention)."""
    import json
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    mock_transport["session"].call_tool.return_value = _MockCallToolResult(
        json.dumps({"functions": ["take_damage"]})
    )
    try:
        result = executor.find_symbols("scripts/player.gd")
        assert result == {"functions": ["take_damage"]}
        call = mock_transport["session"].call_tool.call_args_list[-1]
        assert call.kwargs["name"] == "script_manage"
        assert call.kwargs["arguments"]["op"] == "find_symbols"
        assert call.kwargs["arguments"]["params"]["path"] == "res://scripts/player.gd"
        assert "path" not in call.kwargs["arguments"]  # must be nested, not flat
    finally:
        _shutdown(executor)


def test_search_filesystem_wire_shape(mock_transport):
    """Filesystem search uses op 'search' with a 'name' param."""
    import json
    executor = GodotAIMCPExecutor(mcp_url="http://test/mcp")
    mock_transport["session"].call_tool.return_value = _MockCallToolResult(
        json.dumps({"files": ["res://scripts/player.gd"]})
    )
    try:
        result = executor.search_filesystem("player")
        assert result == {"files": ["res://scripts/player.gd"]}
        call = mock_transport["session"].call_tool.call_args_list[-1]
        assert call.kwargs["name"] == "filesystem_manage"
        assert call.kwargs["arguments"]["op"] == "search"
        assert call.kwargs["arguments"]["params"]["name"] == "player"
    finally:
        _shutdown(executor)


def test_batch_result_status_ok_counts_as_success():
    """godot-ai batch results use status:'ok', never a 'success' key.

    Regression: ExecutionResult counted every applied op as a failure
    (success_count=0) while overall success stayed True — apply_spec
    reported 'applied: 0' for operations that visibly landed in Godot.
    """
    norm = GodotAIMCPExecutor._normalize_op_result
    ok = norm({"command": "create_node", "status": "ok", "data": {}})
    assert ok["success"] is True
    err = norm({"command": "create_node", "status": "error",
                "error": "no parent"})
    assert err["success"] is False
    # already-normalized results pass through untouched
    assert norm({"success": False, "status": "ok"})["success"] is False
    # non-dict results survive
    assert norm("text-result") == "text-result"

    from devforge.execution.interface import ExecutionResult
    result = ExecutionResult(
        success=True,
        results=[norm({"command": "create_node", "status": "ok"}),
                 norm({"command": "create_node", "status": "ok"})],
        errors=[],
    )
    assert result.success_count == 2
    assert result.failure_count == 0


def test_unwrap_scene_hierarchy_rebuilds_flat_list():
    """godot-ai ≥2.7 returns a FLAT nodes list (children_count, no
    'children' array).

    Regression: nodes[0] was returned as-is, so the whole pipeline planned
    against a bare root — the planner saw an empty scene and the
    completeness checker injected duplicate Camera3D/DirectionalLight3D
    on every apply (observed live June 12, 2026).
    """
    unwrap = GodotAIMCPExecutor._unwrap_scene_hierarchy
    flat = {
        "root": "",
        "nodes": [
            {"children_count": 3, "name": "Main", "path": "/Main", "type": "Node3D"},
            {"children_count": 0, "name": "Camera3D", "path": "/Main/Camera3D", "type": "Camera3D"},
            {"children_count": 0, "name": "Sun", "path": "/Main/Sun", "type": "DirectionalLight3D"},
            {"children_count": 1, "name": "Ground", "path": "/Main/Ground", "type": "StaticBody3D"},
            {"children_count": 0, "name": "CollisionShape3D",
             "path": "/Main/Ground/CollisionShape3D", "type": "CollisionShape3D"},
        ],
        "total_count": 5,
    }
    tree = unwrap(flat)
    assert tree["name"] == "Main" and tree["type"] == "Node3D"
    child_types = {c["type"] for c in tree["children"]}
    assert child_types == {"Camera3D", "DirectionalLight3D", "StaticBody3D"}
    ground = next(c for c in tree["children"] if c["name"] == "Ground")
    assert ground["children"][0]["type"] == "CollisionShape3D"

    # Old nested shape still passes through untouched
    nested = {"nodes": [{"name": "Main", "type": "Node3D", "children": []}]}
    assert unwrap(nested)["children"] == []

    # Orphaned entries (parent outside the depth/pagination window)
    # attach to the root instead of vanishing
    orphan = {
        "nodes": [
            {"name": "Main", "path": "/Main", "type": "Node3D", "children_count": 0},
            {"name": "Deep", "path": "/Main/Missing/Deep", "type": "Node3D", "children_count": 0},
        ]
    }
    tree = unwrap(orphan)
    assert [c["name"] for c in tree["children"]] == ["Deep"]


def test_completeness_no_duplicates_and_default_mesh():
    """With a real (nested) scene tree the completeness checker must NOT
    re-inject Camera3D/DirectionalLight3D, and a newly added bare
    MeshInstance3D must receive a default BoxMesh so it is visible."""
    from devforge.compilation.pipeline.completeness import CompletenessChecker

    scene = {
        "name": "Main", "type": "Node3D",
        "children": [
            {"name": "Camera3D", "type": "Camera3D", "children": []},
            {"name": "Sun", "type": "DirectionalLight3D", "children": []},
        ],
    }
    ops = [{"type": "add_node", "parent": "/root/Main",
            "node_type": "MeshInstance3D", "name": "CenterCube"}]
    out = CompletenessChecker().enforce([], ops, scene)

    types_added = [o.get("node_type") for o in out if o.get("type") == "add_node"]
    assert "Camera3D" not in types_added, "duplicate camera injected"
    assert "DirectionalLight3D" not in types_added, "duplicate light injected"

    mesh_ops = [o for o in out if o.get("type") == "set_property"
                and o.get("property") == "mesh"]
    assert len(mesh_ops) == 1
    assert mesh_ops[0]["node"] == "/root/Main/CenterCube"
    assert mesh_ops[0]["value"]["__class__"] == "BoxMesh"

    # If the plan already sets a mesh, don't double-inject
    ops2 = [
        {"type": "add_node", "parent": "/root/Main",
         "node_type": "MeshInstance3D", "name": "Orb"},
        {"type": "set_property", "node": "/root/Main/Orb",
         "property": "mesh", "value": {"__class__": "SphereMesh"}},
    ]
    out2 = CompletenessChecker().enforce([], ops2, scene)
    mesh_ops2 = [o for o in out2 if o.get("type") == "set_property"
                 and o.get("property") == "mesh"]
    assert len(mesh_ops2) == 1
