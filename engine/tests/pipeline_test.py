#!/usr/bin/env python3
"""
pipeline_test.py — end-to-end test of the Odysseus → DevForge → godot-ai → Godot chain.

Phase 1-3: transport probe (connect, initialize, tools/list) — no LLM spend.
Phase 4:   read-only probe (get_scene) — proves the godot-ai leg.
Phase 5:   write test (apply_spec) — the canonical "Add a Camera3D named
           MainCamera" prompt. Needs llama.cpp + a live Godot editor.

DevForge's mcp_server.py runs `mcp.run(transport="sse")`. The SSE transport
delivers ALL server→client JSON-RPC traffic (including tool results) over the
persistent GET /sse stream; the POST /messages/ endpoint only carries
client→server messages and returns 202 with an empty body. A hand-rolled
client that reads the POST response body therefore never sees a result —
use the official client, which keeps the stream open and routes replies.

Run:  .venv/bin/python tests/pipeline_test.py [--skip-apply]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import timedelta

from mcp import ClientSession
from mcp.client.sse import sse_client

DEVFORGE = "http://127.0.0.1:8001"
PROMPT = "Add a Camera3D named MainCamera to the current scene"
APPLY_TIMEOUT_S = 240  # apply_spec prefill can take 30-90s on a fresh prefix


def _content_text(result) -> str:
    """Flatten a CallToolResult's content blocks to one string."""
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


async def run_phases(session: ClientSession, skip_apply: bool) -> int:
    print("[2/5] initialize...")
    info = await session.initialize()
    print(f"  server = {info.serverInfo.name} {info.serverInfo.version} "
          f"(protocol {info.protocolVersion})")

    print("[3/5] tools/list...")
    listed = await session.list_tools()
    names = sorted(t.name for t in listed.tools)
    has_apply = "apply_spec" in names
    has_scene = "get_scene" in names
    print(f"  {len(names)} tools exposed. "
          f"apply_spec={'yes' if has_apply else 'NO'}  "
          f"get_scene={'yes' if has_scene else 'NO'}")
    if not (has_apply and has_scene):
        print(f"  FAIL: required tools missing. saw: {names[:20]}")
        return 3

    print("[4/5] get_scene (read-only probe)...")
    t0 = time.time()
    scene = await session.call_tool(
        "get_scene", {}, read_timeout_seconds=timedelta(seconds=30))
    print(f"  elapsed: {time.time() - t0:.2f}s  isError={scene.isError}")
    print(f"  -> {_content_text(scene)[:500]}")
    if scene.isError:
        print("  FAIL: get_scene errored — is the Godot editor + godot-ai "
              "plugin running? (stack godot)")
        return 4
    print()

    if skip_apply:
        print("[5/5] apply_spec skipped (--skip-apply)")
        return 0

    print(f"[5/5] apply_spec({PROMPT!r})...")
    t0 = time.time()
    applied = await session.call_tool(
        "apply_spec", {"prompt": PROMPT},
        read_timeout_seconds=timedelta(seconds=APPLY_TIMEOUT_S))
    text = _content_text(applied)
    print(f"  elapsed: {time.time() - t0:.2f}s  isError={applied.isError}")
    try:
        parsed = json.loads(text)
        print(f"  parsed: {json.dumps(parsed, indent=2)[:1500]}")
    except (json.JSONDecodeError, TypeError):
        print(f"  -> {text[:1500]}")
    return 5 if applied.isError else 0


async def main() -> int:
    skip_apply = "--skip-apply" in sys.argv
    print(f"[pipeline_test] target = {DEVFORGE}")
    print(f"[pipeline_test] prompt = {PROMPT!r}")
    print()

    print("[1/5] opening SSE session...")
    try:
        async with sse_client(f"{DEVFORGE}/sse", timeout=10,
                              sse_read_timeout=APPLY_TIMEOUT_S + 60) as (read, write):
            print("  connected")
            async with ClientSession(read, write) as session:
                return await run_phases(session, skip_apply)
    except Exception as e:
        print(f"  FAIL: transport error against {DEVFORGE}/sse — {e!r}")
        return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
