"""MCP client helpers — shared DevForge and godot-ai call wrappers.

Single place for every live consumer that talks to the DevForge MCP server or
godot-ai's MCP server.  Previously the forge_testbench runner, diagnostics.py,
and hub.py each re-implemented these with subtle differences.

Public API:
    devforge_call(tool, args)       -> dict   (any DevForge MCP tool)
    apply_spec(prompt, ...)         -> dict   (DevForge pipeline call)
    read_artifact(artifact_id, ...) -> dict   (DevForge artifact fetch)
    godot_ai_call(tool, args)       -> Any    (any godot-ai MCP tool)
"""

from __future__ import annotations

import json as _json
from datetime import timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

DEVFORGE_URL = "http://127.0.0.1:8001/sse"
GODOT_AI_URL = "http://127.0.0.1:8000/mcp"

# ── DevForge MCP calls ────────────────────────────────────────────


async def devforge_call(
    tool: str,
    args: dict | None = None,
    *,
    timeout_s: int = 60,
) -> dict:
    """Call any DevForge MCP tool and return the parsed JSON response."""
    async with sse_client(DEVFORGE_URL, timeout=10, sse_read_timeout=timeout_s + 30) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(
                tool,
                args or {},
                read_timeout_seconds=timedelta(seconds=timeout_s),
            )
            return _json.loads(res.content[0].text)


async def apply_spec(
    prompt: str,
    *,
    planner: str = "",
    temperature: float = 0.2,
    skip_cache: bool = False,
    timeout_s: int = 300,
) -> dict:
    """Call DevForge apply_spec and return the response dict."""
    args: dict = {"prompt": prompt, "temperature": temperature}
    if planner:
        args["planner"] = planner
    if skip_cache:
        args["skip_cache"] = True
    return await devforge_call("apply_spec", args, timeout_s=timeout_s)


async def read_artifact(artifact_id: str, timeout_s: int = 30) -> dict:
    """Call DevForge read_artifact and return the full payload."""
    return await devforge_call(
        "read_artifact",
        {"artifact_id": artifact_id},
        timeout_s=timeout_s,
    )


# ── godot-ai MCP calls ─────────────────────────────────────────────


async def godot_ai_call(tool: str, args: dict | None = None) -> Any:
    """Call any godot-ai MCP tool and return the parsed response.

    Uses Streamable HTTP transport (no SSE).  Opens a fresh connection
    per call — the executor inside DevForge holds the persistent session;
    external callers like the hub just need one-shot calls.
    """
    async with streamablehttp_client(GODOT_AI_URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if tool == "__list__":
                return await s.list_tools()
            res = await s.call_tool(tool, args or {})
            return _json.loads(res.content[0].text)
