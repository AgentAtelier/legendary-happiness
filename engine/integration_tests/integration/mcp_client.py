"""Shared MCP client for DevForge integration tests.

Connects to the DevForge MCP server via SSE and calls:
    - apply_spec — run the full pipeline
    - get_scene — fetch current Godot scene hierarchy
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class MCPClient:
    """Lightweight MCP client for calling DevForge tools over SSE."""

    def __init__(self, mcp_url: str = "http://localhost:8001/sse", timeout: float = 180.0):
        self._mcp_url = mcp_url
        self._timeout = timeout

    async def apply_spec(self, prompt: str, scene: dict | None = None) -> dict:
        """Call DevForge's apply_spec tool via MCP SSE."""
        arguments = {"prompt": prompt}
        if scene:
            arguments["scene_tree"] = scene
        result = await self._call_tool("apply_spec", arguments)
        if isinstance(result, dict):
            return result
        return {"raw": str(result), "errors": ["Non-dict response from apply_spec"]}

    async def read_artifact(self, artifact_id: str, section: str | None = None) -> dict:
        """Fetch full details of a previous apply_spec result."""
        arguments = {"artifact_id": artifact_id}
        if section:
            arguments["section"] = section
        result = await self._call_tool("read_artifact", arguments)
        if isinstance(result, dict):
            return result
        return {"error": str(result)}

    async def get_scene(self) -> dict:
        """Fetch current scene hierarchy from Godot via DevForge."""
        result = await self._call_tool("get_scene", {})
        if isinstance(result, dict):
            return result
        return {}

    async def _call_tool(self, name: str, arguments: dict) -> Any:
        """Call an MCP tool with timeout."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async def _call():
            async with sse_client(self._mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        name=name,
                        arguments=arguments,
                    )
                    return _parse_tool_result(result)

        return await asyncio.wait_for(_call(), timeout=self._timeout)


def _parse_tool_result(result) -> Any:
    """Extract JSON from MCP CallToolResult.

    MCP results come as CallToolResult with a list of content blocks
    (TextContent). We try JSON first, then plain text, then raw.
    """
    if result is None:
        return None

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
