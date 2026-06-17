"""Integration smoke test — verifies full chain works end-to-end.

Flow: MCP Client → DevForge MCP Server → Pipeline → GodotAIMCPExecutor → godot-ai → Godot

Prerequisites (all must be running):
    - llama.cpp on localhost:8080
    - godot-ai MCP server on localhost:8000/mcp
    - Godot editor with a scene open
    - DevForge MCP server started separately (see run_integration_test.sh)

Usage:
    python tests/integration/test_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Add project root to path for shared imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.integration.mcp_client import MCPClient

# ── Smoke test prompts ────────────────────────────────────────

# Prompt 1: Minimal — creates one node, verifies the chain works
PROMPT_SINGLE_NODE = "Add a Camera3D named MainCamera to the root of the scene."

# Prompt 2: Incremental — builds on Prompt 1, tests entity recognition
PROMPT_ADD_LIGHT = "Add a DirectionalLight3D to the scene for lighting."

# Prompt 3: Multi-entity — tests connections and compound structures
PROMPT_PLAYER = (
    "Add a CharacterBody3D named Player with a CollisionShape3D (capsule shape) "
    "and a MeshInstance3D (capsule mesh). Attach a SpringArm3D child with a Camera3D "
    "for third-person view."
)


# ── Test Runner ────────────────────────────────────────────────

class SmokeTest:
    """Runs the integration smoke tests."""

    def __init__(self, mcp_url: str = "http://localhost:8001/sse"):
        self._client = MCPClient(mcp_url)
        self._results: list[dict] = []

    async def run(self):
        """Run all smoke tests."""
        print("=" * 60)
        print("DevForge Integration Smoke Test")
        print("=" * 60)
        print(f"MCP URL: {self._client._mcp_url}")
        print()

        tests = [
            ("Prompt 1: Single Node", self._test_single_node),
            ("Prompt 2: Add Light", self._test_add_light),
            ("Prompt 3: Multi-Entity Player", self._test_player),
        ]

        passed = 0
        failed = 0

        for name, test_fn in tests:
            print(f"\n{'─' * 60}")
            print(f"▶ {name}")
            print(f"{'─' * 60}")

            result = {"ok": False, "error": "Unknown error"}
            start = time.time()
            try:
                result = await test_fn()
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            elapsed = time.time() - start

            ok = result.get("ok", False)
            if ok:
                passed += 1
                print(f"  ✅ PASS ({elapsed:.1f}s)")
            else:
                failed += 1
                print(f"  ❌ FAIL ({elapsed:.1f}s)")
                if "error" in result and result["error"]:
                    print(f"     Error: {result['error']}")

            if "details" in result:
                for line in result["details"]:
                    print(f"     {line}")

            self._results.append({"name": name, "result": result})

        # ── Summary ──
        print(f"\n{'=' * 60}")
        print(f"Results: {passed} passed, {failed} failed, "
              f"{passed + failed} total")
        print(f"{'=' * 60}")

        return failed == 0

    # ── Individual tests ──

    async def _test_single_node(self) -> dict:
        """Prompt 1: Add a single Camera3D node."""
        summary = await self._client.apply_spec(PROMPT_SINGLE_NODE)
        artifact_id = summary.get("artifact_id", "")
        full = await self._client.read_artifact(artifact_id) if artifact_id else {}

        errors = full.get("errors", [])
        operations = full.get("operations", [])
        files = full.get("files", [])
        execution = full.get("execution", {})

        return {
            "ok": len(errors) == 0 and len(operations) > 0,
            "details": [
                f"Operations generated: {len(operations)}",
                f"Files generated: {len(files)}",
                f"Pipeline errors: {len(errors)}",
                f"Execution success: {execution.get('success', 'N/A')}",
                f"Ops: {[op.get('type', '?') for op in operations]}",
            ],
            "error": "; ".join(errors) if errors else None,
        }

    async def _test_add_light(self) -> dict:
        """Prompt 2: Add a DirectionalLight3D (incremental)."""
        summary = await self._client.apply_spec(PROMPT_ADD_LIGHT)
        artifact_id = summary.get("artifact_id", "")
        full = await self._client.read_artifact(artifact_id) if artifact_id else {}

        errors = full.get("errors", [])
        operations = full.get("operations", [])

        # Check that completeness checker added nothing extra
        # (Camera3D already exists from Prompt 1)
        completeness_ops = [
            op for op in operations
            if op.get("type") == "add_node"
            and op.get("node_type") in ("Camera3D", "CollisionShape3D")
        ]

        return {
            "ok": len(errors) == 0 and len(operations) > 0,
            "details": [
                f"Operations: {len(operations)}",
                f"Completeness auto-injects: {len(completeness_ops)}",
                f"Errors: {len(errors)}",
            ],
            "error": "; ".join(errors) if errors else None,
        }

    async def _test_player(self) -> dict:
        """Prompt 3: Create full player entity."""
        summary = await self._client.apply_spec(PROMPT_PLAYER)
        artifact_id = summary.get("artifact_id", "")
        full = await self._client.read_artifact(artifact_id) if artifact_id else {}

        errors = full.get("errors", [])
        operations = full.get("operations", [])
        files = full.get("files", [])

        # Check expected operations
        op_types = [op.get("type") for op in operations]
        has_add_node = "add_node" in op_types
        has_attach_script = "attach_script" in op_types

        # Check that a Player.gd script was generated
        has_player_script = any(
            "player" in f.get("path", "").lower() for f in files
        )

        return {
            "ok": (
                len(errors) == 0
                and len(operations) >= 3  # at least: player + collision + mesh + camera
                and has_add_node
            ),
            "details": [
                f"Operations: {len(operations)} ({', '.join(set(op_types))})",
                f"Files: {len(files)}",
                f"Has player script: {has_player_script}",
                f"Has attach_script: {has_attach_script}",
                f"Errors: {len(errors)}",
            ],
            "error": "; ".join(errors) if errors else None,
        }


# ── Main ───────────────────────────────────────────────────────

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="DevForge Integration Smoke Test")
    parser.add_argument(
        "--mcp-url",
        default="http://localhost:8000/mcp",
        help="DevForge MCP server URL (default: http://localhost:8000/mcp)",
    )
    parser.add_argument(
        "--prompt",
        help="Run a single custom prompt instead of the test suite",
    )
    args = parser.parse_args()

    if args.prompt:
        # Single custom prompt mode
        client = MCPClient(args.mcp_url)
        print(f"Running custom prompt: {args.prompt}")
        result = await client.apply_spec(args.prompt)
        artifact_id = result.get("artifact_id", "")
        if artifact_id:
            full = await client.read_artifact(artifact_id)
            print(json.dumps(full, indent=2))
        else:
            print(json.dumps(result, indent=2))
    else:
        # Full smoke test
        test = SmokeTest(args.mcp_url)
        ok = await test.run()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
