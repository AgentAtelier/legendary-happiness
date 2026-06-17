"""Forgeborn "First Cold" Game Build — Incremental Prompt Sequence.

Builds the full game scene through a sequence of natural-language prompts,
each running through the complete DevForge pipeline → godot-ai → Godot chain.

The game: A third-person walk across a cold, fog-bound field. Warmth drains
in the open and recovers near a campfire. Reach the cabin before you freeze.

Usage:
    python tests/integration/test_forgeborn.py
    python tests/integration/test_forgeborn.py --start-at 3    # resume from step 3
    python tests/integration/test_forgeborn.py --dry-run        # just print prompts
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Add project root to path for shared imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.integration.mcp_client import MCPClient

# ── Prompt Sequence ────────────────────────────────────────────

# Each step is a (label, prompt) pair.
# Prompts are designed to be incremental — each builds on previous state.

FORGEBORN_PROMPTS = [
    # ── Phase 1: Scene Foundation ──
    (
        "1. Scene Setup",
        "Create the main game scene: a Node3D root named Main. "
        "Add a StaticBody3D named Ground with a MeshInstance3D plane and CollisionShape3D. "
        "Add a DirectionalLight3D with a cold pale color for the sun. "
        "Add a WorldEnvironment node for atmosphere.",
    ),

    # ── Phase 2: Player Character ──
    (
        "2. Player Character",
        "Add a CharacterBody3D named Player to the scene. "
        "Give it a capsule MeshInstance3D and capsule CollisionShape3D. "
        "Add a SpringArm3D child with a Camera3D for third-person view. "
        "Create a Player.gd script with WASD movement (speed 4.0) and gravity.",
    ),

    # ── Phase 3: UI Layer ──
    (
        "3. UI — Warmth Bar",
        "Add a CanvasLayer named UI with a ProgressBar named WarmthBar (max value 100, "
        "current value 100). Position it at the top of the screen.",
    ),

    # ── Phase 4: Campfire ──
    (
        "4. Campfire with Heat Zone",
        "Add a Node3D named Campfire with an OmniLight3D child (warm orange light). "
        "Add an Area3D child named HeatZone with a sphere CollisionShape3D (radius 6). "
        "Create a Campfire.gd script that connects HeatZone's body_entered and "
        "body_exited signals to call set_near_fire(true/false) on any body that has that method.",
    ),

    # ── Phase 5: Warmth System ──
    (
        "5. Warmth System",
        "Update Player.gd: add a warmth variable (starts at 100), cold_rate (4/sec lost in open), "
        "warm_rate (12/sec gained near fire). In _process: drain warmth by cold_rate*delta if not "
        "near_fire, or recover by warm_rate*delta if near_fire. Update the WarmthBar value. "
        "Add a set_near_fire(bool) method. Add a near_fire bool variable. "
        "If warmth reaches 0, change scene to res://Froze.tscn.",
    ),

    # ── Phase 6: Win Condition ──
    (
        "6. Cabin — Win Condition",
        "Add an Area3D named Cabin with a box MeshInstance3D and box CollisionShape3D. "
        "Create a simple script that connects body_entered: when a body enters that has "
        "set_near_fire method, change scene to res://Made_It.tscn.",
    ),

    # ── Phase 7: End Screens ──
    (
        "7. Win/Lose Screens",
        "Create Froze.tscn: a scene with a CanvasLayer containing a Label that says 'You froze.' "
        "centered on screen, white text on dark background. "
        "Create Made_It.tscn: same structure but the Label says 'You made it.'",
    ),

    # ── Phase 8: Atmosphere Tuning ──
    (
        "8. Atmosphere",
        "Set up the WorldEnvironment fog: enabled, density 0.03, pale grey-blue color. "
        "Set tonemap to Filmic with slightly low exposure. "
        "Set DirectionalLight3D to a low angle, pale cold color, energy 0.6, shadows on.",
    ),
]


# ── Builder ────────────────────────────────────────────────────

class ForgebornBuilder:
    """Builds the Forgeborn game by running the prompt sequence."""

    def __init__(self, mcp_url: str = "http://localhost:8000/mcp"):
        self._client = MCPClient(mcp_url)
        self._results: list[dict] = []
        self._scene: dict | None = None

    async def build(self, start_at: int = 0, dry_run: bool = False,
                    stop_on_failure: bool = False):
        """Run all prompts in sequence, starting from start_at (0-indexed)."""
        print("=" * 70)
        print("Forgeborn — First Cold — Game Build")
        print("=" * 70)
        print(f"Steps: {len(FORGEBORN_PROMPTS)} total, starting at {start_at + 1}")
        print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
        print()

        total_start = time.time()

        for i, (label, prompt) in enumerate(FORGEBORN_PROMPTS):
            if i < start_at:
                print(f"  ⏭  SKIP: {label}")
                continue

            print(f"\n{'─' * 70}")
            print(f"▶ Step {i + 1}/{len(FORGEBORN_PROMPTS)}: {label}")
            print(f"{'─' * 70}")
            print(f"  Prompt: {prompt[:120]}{'...' if len(prompt) > 120 else ''}")

            if dry_run:
                print(f"  [DRY RUN] would call apply_spec with this prompt\n")
                self._results.append({"label": label, "dry_run": True})
                continue

            start = time.time()
            try:
                summary = await self._client.apply_spec(prompt, self._scene)
                elapsed = time.time() - start

                # Fetch full details via read_artifact for logging
                artifact_id = summary.get("artifact_id", "")
                if artifact_id:
                    full = await self._client.read_artifact(artifact_id)
                else:
                    full = {}

                errors = full.get("errors", [])
                ops = full.get("operations", [])
                files = full.get("files", [])
                execution = full.get("execution", {})
                exec_ok = execution.get("success", True) if execution else True

                ok = len(errors) == 0 and exec_ok

                if ok:
                    print(f"  ✅ OK ({elapsed:.1f}s) — "
                          f"{len(ops)} ops, {len(files)} files")
                else:
                    print(f"  ⚠️  ISSUES ({elapsed:.1f}s)")
                    for err in errors:
                        print(f"     Error: {err}")
                    if not exec_ok:
                        exec_errors = execution.get("errors", [])
                        for ee in exec_errors:
                            print(f"     Exec: {ee}")

                # Show operations
                for op in ops[:5]:
                    op_type = op.get("type", "?")
                    op_name = op.get("name", op.get("node_type", ""))
                    print(f"     └─ {op_type}: {op_name}")
                if len(ops) > 5:
                    print(f"     └─ ... and {len(ops) - 5} more")

                # Refresh scene after each step
                try:
                    self._scene = await self._client.get_scene()
                except Exception:
                    pass

                self._results.append({
                    "label": label,
                    "ok": ok,
                    "elapsed": elapsed,
                    "ops_count": len(ops),
                    "files_count": len(files),
                    "errors": errors,
                })

            except Exception as exc:
                elapsed = time.time() - start
                print(f"  ❌ CRASH ({elapsed:.1f}s): {exc}")
                self._results.append({
                    "label": label,
                    "ok": False,
                    "elapsed": elapsed,
                    "ops_count": 0,
                    "files_count": 0,
                    "error": str(exc),
                })

            # Stop on failure if flag is set
            if stop_on_failure and not ok:
                print(f"\n  ⛔ Stopping: step failed and --stop-on-failure is set")
                break

        # ── Summary ──
        total_elapsed = time.time() - total_start
        ok_count = sum(1 for r in self._results if r.get("ok"))
        fail_count = len(self._results) - ok_count

        print(f"\n{'=' * 70}")
        print(f"Build complete: {ok_count}/{len(self._results)} steps OK "
              f"({total_elapsed:.0f}s total)")
        print(f"{'=' * 70}")

        return fail_count == 0


# ── Main ───────────────────────────────────────────────────────

async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Forgeborn 'First Cold' Game Build"
    )
    parser.add_argument(
        "--mcp-url",
        default="http://localhost:8000/mcp",
        help="DevForge MCP server URL",
    )
    parser.add_argument(
        "--start-at",
        type=int,
        default=0,
        help="Start from step N (0-indexed, default: 0)",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop the build on the first failed step",
    )
    args = parser.parse_args()

    builder = ForgebornBuilder(args.mcp_url)
    ok = await builder.build(start_at=args.start_at, dry_run=args.dry_run,
                             stop_on_failure=args.stop_on_failure)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
