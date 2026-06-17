"""forge-hub scenario suite — per-model scoring with machine-checkable assertions.

Stream A of the forge-grunt-work-roadmap. Answers the central question:
"is a failure the *model*, the *setup*, or *DevForge*?"

Two axes:
  1. apply_spec scenarios — LLM pipeline writes to the live scene, then
     assertions check correctness. Covers the real workload.
  2. Raw tool-call scoring — the same intents through the llama API without
     DevForge in the loop, isolating *model* capability.

Scorecards are persisted to data/scorecards/<model>-<config-hash>.json so
models/configs can be compared over time.

SCENE DISCIPLINE (P2+P3 fix, June 14): every scenario run builds into the
DISPOSABLE probe scene (res://probe.tscn), NEVER the user's main.tscn. This
is the same discipline the gauntlet follows (bench._probe_scene_reset). Before
the suite runs, the probe scene is reset to a pristine baseline; after the
suite completes, the editor is restored to the real game scene.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import httpx

import bench  # reuse the disposable probe-scene reset + env read (P2+P3 fix)

DATA_DIR = Path(__file__).parent / "data"
SCORECARD_DIR = DATA_DIR / "scorecards"
SCORECARD_DIR.mkdir(parents=True, exist_ok=True)

# ── MCP helpers (ported from bench.py for standalone use) ──────────

HOME = Path.home()
ENVFILE = HOME / ".config/forge-stack/stack.env"

# Import shared env parser to avoid duplication (Rule 5).
try:
    from forge_env import read_env as _forge_read_env

    def read_env(path: Path | None = None) -> dict[str, str]:
        return _forge_read_env(path or ENVFILE)
except ImportError:
    # Fallback for when running standalone (not in the hub package).
    def read_env(path: Path | None = None) -> dict[str, str]:
        env: dict[str, str] = {}
        fp = path or ENVFILE
        try:
            for line in fp.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
        except OSError:
            pass
        return env


async def _godot_ai_call(tool: str, args: dict | None = None) -> Any:
    from mcp.client.streamable_http import streamable_http_client
    from mcp import ClientSession

    async with streamable_http_client("http://127.0.0.1:8000/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if tool == "__list__":
                return await s.list_tools()
            res = await s.call_tool(tool, args or {})
            return json.loads(res.content[0].text)


async def _devforge_call(tool: str, args: dict | None = None, timeout_s: int = 240) -> Any:
    from datetime import timedelta
    from mcp.client.sse import sse_client
    from mcp import ClientSession

    async with sse_client("http://127.0.0.1:8001/sse", timeout=10, sse_read_timeout=timeout_s + 30) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if tool == "__list__":
                return await s.list_tools()
            res = await s.call_tool(tool, args or {}, read_timeout_seconds=timedelta(seconds=timeout_s))
            return json.loads(res.content[0].text)


# ── Scene helper: snapshot + restore ──────────────────────────────


def _resolve_root(snapshot: dict) -> str:
    """Find the live scene root path from a snapshot dict.

    The root is the unique path at depth 1 (e.g. /Main, /Main2).
    Returns "/Main" as fallback if the snapshot is empty or has no clear root.

    Tier 2.4: root-agnostic assertions. Instead of hardcoding "/Main" in every
    assertion, we resolve the live root and build paths dynamically.
    """
    depth1 = [p for p in snapshot if p.count("/") == 1]
    if len(depth1) == 1:
        return depth1[0]
    return "/Main"


def _resolve_path(raw_path: str, root: str) -> str:
    """Replace the "/Main" prefix in a raw assertion path with the live root.

    Handles both top-level paths ("/Main/X" → "/{root}/X") and nested paths
    ("/Main/X/Y" → "/{root}/X/Y"). If raw_path does NOT start with "/Main",
    it's returned unchanged (defense-in-depth: root-agnostic but tolerant).
    """
    if raw_path.startswith("/Main/"):
        return root + raw_path[5:]  # strip "/Main" and re-prefix
    if raw_path == "/Main":
        return root
    return raw_path


async def _get_scene_snapshot() -> dict:
    """Get the current scene hierarchy as a flat path → {name, type} map."""
    h = await _godot_ai_call("scene_get_hierarchy", {"depth": 10})
    nodes = h.get("nodes", [])
    snapshot: dict[str, dict] = {}
    for n in nodes:
        if isinstance(n, dict) and n.get("path"):
            snapshot[n["path"]] = {
                "name": n.get("name", ""),
                "type": n.get("type", ""),
            }
    return snapshot


def _diff_snapshots(before: dict, after: dict) -> list[str]:
    """Return list of paths that differ between two snapshots."""
    changes = []
    all_paths = set(before.keys()) | set(after.keys())
    for p in sorted(all_paths):
        b = before.get(p)
        a = after.get(p)
        if b is None:
            changes.append(f"+{p} ({a.get('type') if a else '?'})")
        elif a is None:
            changes.append(f"-{p} ({b.get('type') if b else '?'})")
        elif b.get("type") != a.get("type"):
            changes.append(f"~{p} ({b.get('type')}→{a.get('type')})")
    return changes


# ── Scenario Definition ───────────────────────────────────────────


class ScenarioAssertion:
    """A post-condition check against the live scene."""

    type: str  # node_exists, node_type, has_mesh, no_extra_nodes, no_errors
    path: str = ""  # node path for node-level checks
    node_type: str = ""  # expected Godot type
    exclude: list[str] = []  # paths to exclude from no_extra_nodes


class Scenario:
    """One test scenario: prompt → apply_spec → assertions → cleanup."""

    def __init__(
        self,
        id: str,
        category: str,
        prompt: str,
        description: str,
        assertions: list[dict],
        cleanup: list[dict],
        timeout: int = 240,
        tags: list[str] | None = None,
        seed: list[dict] | None = None,
    ):
        self.id = id
        self.category = category
        self.prompt = prompt
        self.description = description
        self.assertions_raw = assertions
        self.cleanup_raw = cleanup
        self.timeout = timeout
        self.tags = tags or []
        # seed: nodes to pre-create (via node_create) BEFORE the prompt runs,
        # so a scenario can test edits (delete/rename) on an EXISTING node
        # instead of the contrived "create then edit it" — which conflates
        # creation, intent-extraction and same-batch ordering into one signal.
        # Each entry: {"name": str, "type": "Node3D", "parent": "/Main"}.
        self.seed = seed or []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "prompt": self.prompt,
            "description": self.description,
            "assertions": self.assertions_raw,
            "cleanup": self.cleanup_raw,
            "timeout": self.timeout,
            "tags": self.tags,
            "seed": self.seed,
        }


# ── Scenario Catalog ──────────────────────────────────────────────


SCENARIOS: list[Scenario] = [
    # ── Geometry (basic primitives) ────────────────────────────
    Scenario(
        "cube_create",
        "geometry",
        prompt="Create a MeshInstance3D named TestCube with a BoxMesh in the center of the scene at position 0,0,0.",
        description="Basic MeshInstance3D + BoxMesh creation",
        assertions=[
            {"type": "node_exists", "path": "/Main/TestCube"},
            {"type": "node_type", "path": "/Main/TestCube", "node_type": "MeshInstance3D"},
            {"type": "has_mesh", "path": "/Main/TestCube"},
            {"type": "no_errors"},
        ],
        cleanup=[{"type": "delete_node", "path": "/Main/TestCube"}],
    ),
    Scenario(
        "camera_create",
        "geometry",
        prompt="Create a Camera3D named TestCam at position 0,2,10 looking at the origin.",
        description="Camera3D with position and rotation",
        assertions=[
            {"type": "node_exists", "path": "/Main/TestCam"},
            {"type": "node_type", "path": "/Main/TestCam", "node_type": "Camera3D"},
            {"type": "no_errors"},
        ],
        cleanup=[{"type": "delete_node", "path": "/Main/TestCam"}],
    ),
    # ── Multi-node batch ───────────────────────────────────────
    Scenario(
        "batch_three",
        "multi-node",
        prompt="Create three MeshInstance3D nodes with BoxMesh: BlockA at 0,0,0, BlockB at 2,0,0, BlockC at -2,0,0.",
        description="Three nodes in one apply_spec call",
        assertions=[
            {"type": "node_exists", "path": "/Main/BlockA"},
            {"type": "node_exists", "path": "/Main/BlockB"},
            {"type": "node_exists", "path": "/Main/BlockC"},
            {"type": "node_type", "path": "/Main/BlockA", "node_type": "MeshInstance3D"},
            {"type": "node_type", "path": "/Main/BlockB", "node_type": "MeshInstance3D"},
            {"type": "node_type", "path": "/Main/BlockC", "node_type": "MeshInstance3D"},
            {"type": "no_extra_nodes", "exclude": ["BlockA", "BlockB", "BlockC"]},
            {"type": "no_errors"},
        ],
        cleanup=[
            {"type": "delete_node", "path": "/Main/BlockA"},
            {"type": "delete_node", "path": "/Main/BlockB"},
            {"type": "delete_node", "path": "/Main/BlockC"},
        ],
    ),
    # ── Script creation + attachment ───────────────────────────
    Scenario(
        "script_attach",
        "scripting",
        prompt="Create a MeshInstance3D with BoxMesh named ScriptedCube at 0,0,0, then create a new GDScript that rotates it slowly around the Y axis, and attach it as a script.",
        description="Create GDScript + attach to node",
        assertions=[
            {"type": "node_exists", "path": "/Main/ScriptedCube"},
            {"type": "node_type", "path": "/Main/ScriptedCube", "node_type": "MeshInstance3D"},
            {"type": "has_script", "path": "/Main/ScriptedCube"},
            {"type": "no_duplicate_cameras"},
            {"type": "no_errors"},
        ],
        cleanup=[{"type": "delete_node", "path": "/Main/ScriptedCube"}],
    ),
    # ── Property modification ──────────────────────────────────
    Scenario(
        "property_edit",
        "editing",
        prompt="Create a simple MeshInstance3D with BoxMesh called PropTarget at 0,0,0, then set its scale to 2,2,2.",
        description="Node creation with subsequent property edit",
        assertions=[
            {"type": "node_exists", "path": "/Main/PropTarget"},
            {"type": "node_type", "path": "/Main/PropTarget", "node_type": "MeshInstance3D"},
            {"type": "no_errors"},
        ],
        cleanup=[{"type": "delete_node", "path": "/Main/PropTarget"}],
    ),
    # ── Edit operations on EXISTING nodes (the realistic case) ──
    # These seed a node, then ask the model to edit it — isolating the
    # delete/rename capability from creation + same-batch ordering, so a
    # failure points at one cause (intent extraction / op / executor).
    Scenario(
        "delete_existing",
        "editing",
        prompt="Delete the Target node from the scene.",
        description="Delete a node that already exists (noun-phrase phrasing)",
        seed=[{"name": "Target", "type": "MeshInstance3D", "parent": "/Main"}],
        assertions=[
            {"type": "node_not_exists", "path": "/Main/Target"},
            {"type": "no_errors"},
        ],
        cleanup=[{"type": "delete_node", "path": "/Main/Target"}],
    ),
    Scenario(
        "delete_existing_bare",
        "editing",
        prompt="Delete Gizmo.",
        description="Delete an existing node — bare-name phrasing (extractor stress)",
        seed=[{"name": "Gizmo", "type": "MeshInstance3D", "parent": "/Main"}],
        assertions=[
            {"type": "node_not_exists", "path": "/Main/Gizmo"},
            {"type": "no_errors"},
        ],
        cleanup=[{"type": "delete_node", "path": "/Main/Gizmo"}],
    ),
    Scenario(
        "rename_existing",
        "editing",
        prompt="Rename the Origin node to Renamed.",
        description="Rename a node that already exists",
        seed=[{"name": "Origin", "type": "MeshInstance3D", "parent": "/Main"}],
        assertions=[
            {"type": "node_exists", "path": "/Main/Renamed"},
            {"type": "node_not_exists", "path": "/Main/Origin"},
            {"type": "no_errors"},
        ],
        cleanup=[{"type": "delete_node", "path": "/Main/Renamed"}, {"type": "delete_node", "path": "/Main/Origin"}],
    ),
    # ── Small room (composite) ─────────────────────────────────
    Scenario(
        "small_room",
        "composite",
        prompt="Build a small room: four MeshInstance3D cubes (WallFront, WallBack, WallLeft, WallRight) forming walls at positions 0,0,5 / 0,0,-5 / -5,0,0 / 5,0,0 with scale 10,3,0.5 for each wall. Add a DirectionalLight3D called RoomLight at 0,5,0 with light_energy 0.6.",
        description="Multi-object scene: walls + light",
        assertions=[
            {"type": "node_exists", "path": "/Main/WallFront"},
            {"type": "node_exists", "path": "/Main/WallBack"},
            {"type": "node_exists", "path": "/Main/WallLeft"},
            {"type": "node_exists", "path": "/Main/WallRight"},
            {"type": "node_exists", "path": "/Main/RoomLight"},
            {"type": "no_duplicate_cameras"},
            {"type": "no_errors"},
        ],
        cleanup=[
            {"type": "delete_node", "path": "/Main/WallFront"},
            {"type": "delete_node", "path": "/Main/WallBack"},
            {"type": "delete_node", "path": "/Main/WallLeft"},
            {"type": "delete_node", "path": "/Main/WallRight"},
            {"type": "delete_node", "path": "/Main/RoomLight"},
        ],
    ),
    # ── Player with movement (complex composite) ───────────────
    Scenario(
        "player_movement",
        "composite",
        prompt="Add a player character to the scene: a MeshInstance3D with CapsuleMesh named Player at position 0,1,0. Create a GDScript attached to Player that listens for WASD keyboard input and moves Player along X/Z axes at 5 units per second using _process(delta). Add a Camera3D named PlayerCam as a child of Player at position 0,1.5,5.",
        description="Player + script + camera child — full game-object pattern",
        assertions=[
            {"type": "node_exists", "path": "/Main/Player"},
            {"type": "node_type", "path": "/Main/Player", "node_type": "MeshInstance3D"},
            {"type": "has_mesh", "path": "/Main/Player"},
            {"type": "has_script", "path": "/Main/Player"},
            {"type": "node_exists", "path": "/Main/Player/PlayerCam"},
            {"type": "no_duplicate_cameras"},
            {"type": "no_errors"},
        ],
        cleanup=[{"type": "delete_node", "path": "/Main/Player"}],
    ),
    # ── Regression: no duplicate cameras ───────────────────────
    Scenario(
        "no_dup_camera",
        "regression",
        prompt="Create a simple red MeshInstance3D cube named RedBlock at position 0,0,0.",
        description="Regression: creating a single node must NOT duplicate cameras/lights",
        assertions=[
            {"type": "node_exists", "path": "/Main/RedBlock"},
            {"type": "no_duplicate_cameras"},
            {"type": "no_errors"},
        ],
        cleanup=[{"type": "delete_node", "path": "/Main/RedBlock"}],
    ),
]

SCENARIO_BY_ID = {s.id: s for s in SCENARIOS}


# ── Assertion Evaluation ──────────────────────────────────────────


async def _eval_assertions(
    snapshot_before: dict, snapshot_after: dict, artifact: dict, assertions: list[dict], root: str = "/Main"
) -> list[dict]:
    """Evaluate each assertion against the live scene state. Returns list of
    {status: pass|fail|error, message: str} results.

    Tier 2.4: all assertion paths are resolved relative to the LIVE scene root
    (not hardcoded "/Main"). This prevents the whole suite from producing
    misleading failures when Godot auto-suffixes the root node.

    Tier 1.3: the `no_errors` assertion now surfaces per-op execution errors
    from the artifact's `execution.results` block, naming the EXACT op that
    failed — not just `error_count`.
    """

    results: list[dict] = []
    after = snapshot_after

    for a in assertions:
        atype = a["type"]
        path = _resolve_path(a.get("path", ""), root)

        try:
            if atype == "node_exists":
                if path in after:
                    results.append(
                        {
                            "status": "pass",
                            "assertion": f"node_exists({path})",
                            "message": f"{path} exists (type={after[path].get('type')})",
                        }
                    )
                else:
                    results.append(
                        {
                            "status": "fail",
                            "assertion": f"node_exists({path})",
                            "message": f"{path} NOT found in scene. Present: {sorted(after.keys())[:20]}",
                        }
                    )

            elif atype == "node_not_exists":
                if path not in after:
                    results.append(
                        {
                            "status": "pass",
                            "assertion": f"node_not_exists({path})",
                            "message": f"{path} correctly absent",
                        }
                    )
                else:
                    results.append(
                        {
                            "status": "fail",
                            "assertion": f"node_not_exists({path})",
                            "message": f"{path} STILL exists (type={after[path].get('type')})",
                        }
                    )

            elif atype == "node_type":
                expected_type = a.get("node_type", "")
                node = after.get(path)
                if node is None:
                    results.append(
                        {
                            "status": "fail",
                            "assertion": f"node_type({path}, {expected_type})",
                            "message": f"{path} not found",
                        }
                    )
                elif node.get("type") == expected_type:
                    results.append(
                        {
                            "status": "pass",
                            "assertion": f"node_type({path}, {expected_type})",
                            "message": f"{path} is {expected_type}",
                        }
                    )
                else:
                    results.append(
                        {
                            "status": "fail",
                            "assertion": f"node_type({path}, {expected_type})",
                            "message": f"{path} is {node.get('type')}, expected {expected_type}",
                        }
                    )

            elif atype == "has_mesh":
                try:
                    props = await _godot_ai_call("node_get_properties", {"path": path})
                    pdata = props.get("data", props)
                    plist = pdata.get("properties", pdata)
                    if isinstance(plist, list):
                        plist = {x.get("name"): x.get("value") for x in plist if isinstance(x, dict)}
                    if plist.get("mesh"):
                        results.append(
                            {
                                "status": "pass",
                                "assertion": f"has_mesh({path})",
                                "message": f"{path} has mesh assigned",
                            }
                        )
                    else:
                        results.append(
                            {
                                "status": "fail",
                                "assertion": f"has_mesh({path})",
                                "message": f"{path} has NO mesh — invisible-node regression",
                            }
                        )
                except Exception as e:
                    results.append(
                        {
                            "status": "error",
                            "assertion": f"has_mesh({path})",
                            "message": f"Property fetch failed: {e}",
                        }
                    )

            elif atype == "has_script":
                try:
                    props = await _godot_ai_call("node_get_properties", {"path": path})
                    pdata = props.get("data", props)
                    plist = pdata.get("properties", pdata)
                    if isinstance(plist, list):
                        plist = {x.get("name"): x.get("value") for x in plist if isinstance(x, dict)}
                    script_val = plist.get("script")
                    if script_val and script_val != "None":
                        results.append(
                            {
                                "status": "pass",
                                "assertion": f"has_script({path})",
                                "message": f"{path} has script assigned",
                            }
                        )
                    else:
                        results.append(
                            {
                                "status": "fail",
                                "assertion": f"has_script({path})",
                                "message": f"{path} has NO script attached",
                            }
                        )
                except Exception as e:
                    results.append(
                        {
                            "status": "error",
                            "assertion": f"has_script({path})",
                            "message": f"Property fetch failed: {e}",
                        }
                    )

            elif atype == "no_extra_nodes":
                exclude = set(a.get("exclude", []))
                # Baseline nodes always present in the baked probe scene
                known_prefixes = {"root", "Main", "MainCamera", "DirectionalLight", "Ground"}
                new_nodes = []
                for p in after:
                    name = after[p].get("name", "")
                    if name in exclude:
                        continue
                    if name in known_prefixes:
                        continue
                    # Check if this path existed before
                    if p not in snapshot_before:
                        new_nodes.append(p)
                if new_nodes:
                    results.append(
                        {
                            "status": "fail",
                            "assertion": f"no_extra_nodes(exclude={exclude})",
                            "message": f"Unrequested nodes added: {new_nodes}",
                        }
                    )
                else:
                    results.append(
                        {
                            "status": "pass",
                            "assertion": f"no_extra_nodes(exclude={exclude})",
                            "message": "No extra nodes beyond excluded set",
                        }
                    )

            elif atype == "no_duplicate_cameras":
                cam_count = 0
                for p, n in after.items():
                    if n.get("type") == "Camera3D":
                        cam_count += 1
                # Allow baseline camera + any cameras the scenario created.
                # With the baked baseline (MainCamera + DirectionalLight), 2
                # cameras is normal: the baked MainCamera + one created by the scenario.
                if cam_count <= 3:
                    results.append(
                        {
                            "status": "pass",
                            "assertion": "no_duplicate_cameras",
                            "message": f"{cam_count} Camera3D nodes (ok)",
                        }
                    )
                else:
                    results.append(
                        {
                            "status": "fail",
                            "assertion": "no_duplicate_cameras",
                            "message": f"{cam_count} Camera3D nodes — duplicate-camera regression",
                        }
                    )

            elif atype == "no_errors":
                errors = artifact.get("errors", [])
                error_count = artifact.get("error_count", len(errors))
                # Tier 1.3: surface per-op execution errors from the artifact's
                # execution block. This turns "3 pipeline errors" into
                # "set_property material_override on DirectionalLight3D: property not found"
                # — actionable, not just a count.
                exec_data = artifact.get("execution", {}) if isinstance(artifact, dict) else {}
                exec_errors = exec_data.get("errors", []) if isinstance(exec_data, dict) else []
                exec_results = exec_data.get("results", []) if isinstance(exec_data, dict) else []
                failed_ops = [r for r in exec_results if isinstance(r, dict) and r.get("status") == "fail"]
                if error_count > 0 or exec_errors or failed_ops:
                    # Build a diagnostic message that names the exact failing ops
                    parts = []
                    if error_count > 0:
                        parts.append(f"{error_count} pipeline error(s): {errors[:3]}")
                    if exec_errors:
                        parts.append(f"{len(exec_errors)} execution error(s): {exec_errors[:2]}")
                    if failed_ops:
                        op_details = []
                        for fo in failed_ops[:3]:
                            op_type = fo.get("op", {}).get("type", "?") if isinstance(fo.get("op"), dict) else "?"
                            op_msg = fo.get("message", str(fo))
                            op_details.append(f"{op_type}: {op_msg}")
                        parts.append(f"{len(failed_ops)} failed op(s): {op_details}")
                    results.append(
                        {
                            "status": "fail",
                            "assertion": "no_errors",
                            "message": "; ".join(parts),
                        }
                    )
                else:
                    results.append(
                        {
                            "status": "pass",
                            "assertion": "no_errors",
                            "message": "Zero pipeline + execution errors",
                        }
                    )

            else:
                results.append(
                    {
                        "status": "error",
                        "assertion": atype,
                        "message": f"Unknown assertion type: {atype}",
                    }
                )

        except Exception as e:
            results.append(
                {
                    "status": "error",
                    "assertion": atype,
                    "message": f"Assertion evaluation crashed: {type(e).__name__}: {e}",
                }
            )

    return results


# ── Cleanup ────────────────────────────────────────────────────────


async def _run_cleanup(cleanup_ops: list[dict], root: str = "/Main") -> list[str]:
    """Execute cleanup operations. Returns list of error messages (empty = success).

    Tier 2.4: cleanup paths are resolved relative to the live scene root."""
    errors: list[str] = []
    for op in cleanup_ops:
        if op["type"] == "delete_node":
            path = _resolve_path(op["path"], root)
            try:
                await _godot_ai_call(
                    "batch_execute", {"commands": [{"command": "delete_node", "params": {"path": path}}]}
                )
            except Exception as e:
                errors.append(f"Cleanup delete {path}: {e}")
    return errors


# ── Scenario Runner ────────────────────────────────────────────────


async def run_scenario(scenario: Scenario, emit: Callable[[str], None] | None = None) -> dict:
    """Run one scenario: snapshot → apply_spec → assertions → cleanup → result.

    Returns: {
        scenario_id, status: pass|fail|error, ms, assertions: [...],
        errors: [...], cleanup_errors: [...]
    }
    """
    t0 = time.time()

    def log(msg: str) -> None:
        if emit:
            emit(msg)

    result: dict = {
        "scenario_id": scenario.id,
        "category": scenario.category,
        "status": "error",
        "ms": 0,
        "assertions": [],
        "errors": [],
        "cleanup_errors": [],
        "stage_latencies": {},
    }

    snapshot_before: dict = {}
    snapshot_after: dict = {}
    artifact: dict = {}
    root: str = "/Main"

    try:
        # 0. Seed: pre-create nodes so the scenario can test edits on an
        # EXISTING node (delete/rename a real node) rather than the contrived
        # create-then-edit. Seeds are created before the before-snapshot so
        # they're part of the baseline the assertions account for.
        if scenario.seed:
            pre = await _get_scene_snapshot()
            seed_root = _resolve_root(pre)
            for sd in scenario.seed:
                await _godot_ai_call(
                    "node_create",
                    {
                        "type": sd.get("type", "Node3D"),
                        "name": sd["name"],
                        "parent_path": _resolve_path(sd.get("parent", "/Main"), seed_root),
                    },
                )
            log(f"  seeded {len(scenario.seed)} node(s): {[s['name'] for s in scenario.seed]}")

        # 1. Snapshot before
        log(f"  snapshot before...")
        snapshot_before = await _get_scene_snapshot()
        log(f"  {len(snapshot_before)} nodes in scene")
        root = _resolve_root(snapshot_before)
        if root != "/Main":
            log(f"  (live root is '{root}', not '/Main' — using root-agnostic paths)")

        # 2. Run apply_spec
        log(f"  apply_spec: {scenario.prompt[:80]}...")
        try:
            raw = await _devforge_call(
                "apply_spec",
                {
                    "prompt": scenario.prompt,
                },
                timeout_s=scenario.timeout,
            )
            artifact_id = raw.get("artifact_id", "")
            if artifact_id:
                try:
                    artifact = await _devforge_call(
                        "read_artifact",
                        {
                            "artifact_id": artifact_id,
                        },
                        timeout_s=30,
                    )
                except Exception:
                    artifact = raw
            else:
                artifact = raw
        except Exception as e:
            result["errors"].append(f"apply_spec failed: {e}")
            result["status"] = "error"
            result["ms"] = int((time.time() - t0) * 1000)
            # Still run cleanup
            ce = await _run_cleanup(scenario.cleanup_raw)
            result["cleanup_errors"] = ce
            return result

        log(
            f"  applied={artifact.get('applied', artifact.get('applied_count', '?'))} "
            f"errors={artifact.get('error_count', 0)}"
        )

        # 3. Snapshot after
        log(f"  snapshot after...")
        snapshot_after = await _get_scene_snapshot()
        log(f"  {len(snapshot_after)} nodes after apply")

        # 4. Diff
        diff = _diff_snapshots(snapshot_before, snapshot_after)
        if diff:
            log(f"  scene changes: {diff[:5]}")
        else:
            log(f"  (scene unchanged)")

        # 5. Evaluate assertions (root-agnostic)
        log(f"  evaluating {len(scenario.assertions_raw)} assertions...")
        assertion_results = await _eval_assertions(
            snapshot_before, snapshot_after, artifact, scenario.assertions_raw, root=root
        )
        result["assertions"] = assertion_results

        # Tier 2.5: surface stage_latencies from the artifact
        stages = artifact.get("stage_latencies", {}) if isinstance(artifact, dict) else {}
        if stages:
            result["stage_latencies"] = stages
        # B3: surface truncated flag from artifact for A/B thinking-config comparison
        truncated = artifact.get("truncated", False) if isinstance(artifact, dict) else False
        result["truncated"] = truncated

        # Determine overall status
        if any(a["status"] == "fail" for a in assertion_results):
            result["status"] = "fail"
        elif any(a["status"] == "error" for a in assertion_results):
            result["status"] = "error"
        else:
            result["status"] = "pass"

    except Exception as e:
        result["errors"].append(f"Scenario runner crashed: {type(e).__name__}: {e}")
        result["status"] = "error"

    finally:
        # N5: auto-capture logs on failure for immediate diagnostic data
        if result["status"] in ("fail", "error"):
            try:
                plugin_logs = await _godot_ai_call("logs_read", {"source": "plugin", "count": 15})
                result["plugin_logs"] = (plugin_logs.get("lines", []) if isinstance(plugin_logs, dict) else [])[:15]
            except Exception:
                pass
        # ALWAYS cleanup (root-agnostic)
        log(f"  cleanup ({len(scenario.cleanup_raw)} ops)...")
        ce = await _run_cleanup(scenario.cleanup_raw, root=root)
        result["cleanup_errors"] = ce
        if ce:
            log(f"  cleanup issues: {ce}")

        result["ms"] = int((time.time() - t0) * 1000)
        log(f"  done [{result['status']}] ({result['ms']}ms)")

    return result


# ── Full suite runner ──────────────────────────────────────────────


def _config_hash() -> str:
    """Hash the current config (model alias + template + ctx + thinking) so scorecards
    are unique per configuration. Includes LLAMA_ARG_CHAT_TEMPLATE_KWARGS so A/B runs
    with/without enable_thinking produce separate scorecards."""
    env = read_env(ENVFILE)
    key = f"{env.get('MODEL_ALIAS', '?')}|{env.get('DEVFORGE_PROMPT_TEMPLATE', '?')}|{env.get('LLAMA_ARGS', '?')}|{env.get('LLAMA_ARG_CHAT_TEMPLATE_KWARGS', '')}"
    return hashlib.sha1(key.encode()).hexdigest()[:8]


async def run_suite(scenario_ids: list[str], emit: Callable[[str], None] | None = None) -> dict:
    """Run a selection of scenarios and return a scorecard.

    P2+P3 fix (June 14): all scenarios build into the disposable probe scene
    (res://probe.tscn), matching the gauntlet's scene discipline. The real
    main.tscn is NEVER modified.

    Returns dict with: ts, model, template, config_hash, scenarios: [...],
    summary: {pass, fail, error, total, pass_rate}
    """

    def log(msg: str) -> None:
        if emit:
            emit(msg)

    # P2+P3: switch to the disposable probe scene before running anything.
    # This is MANDATORY — if the probe scene can't be opened, abort the suite
    # rather than silently mutating the user's real main.tscn.
    # Now with bounce-scene reload (Tier 1.2) and root health check (Tier 1.1).
    # Returns a scorecard-shaped error so the hub endpoint doesn't KeyError
    # on result["summary"]["fail"].
    try:
        log("[scenarios] Switching to disposable probe scene...")
        await bench._probe_scene_reset()
    except RuntimeError as e:
        log(f"[scenarios] FATAL: Could not switch to probe scene: {e}")
        log("[scenarios] Aborting suite — probe scene is mandatory for write safety.")
        return {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": "?",
            "template": "?",
            "config_hash": "?",
            "scenarios": [],
            "summary": {"pass": 0, "fail": 0, "error": 0, "total": 0, "pass_rate": 0, "total_ms": 0, "avg_ms": 0},
            "error": f"probe scene unavailable: {e}",
        }

    env = read_env()
    model = env.get("MODEL_ALIAS", "?")
    template = env.get("DEVFORGE_PROMPT_TEMPLATE", "?")
    chash = _config_hash()

    log(f"Scenario suite: {len(scenario_ids)} scenarios")
    log(f"Model: {model}, template: {template}, config: {chash}")

    results: list[dict] = []
    for sid in scenario_ids:
        s = SCENARIO_BY_ID.get(sid)
        if not s:
            log(f"  ✗ unknown scenario: {sid}")
            continue
        log(f"▶ {sid} — {s.description}")
        # Per-scenario isolation is handled by each scenario's own `cleanup`
        # (delete_node) — NOT by re-resetting the probe scene between
        # scenarios. The Round-2 per-scenario `_probe_scene_reset()` was
        # reverted (6/14): on an already-active probe tab `scene_open` is a
        # no-op, so the reset left the scene in a bare/degraded state, and
        # apply_spec then built nothing (light_create/script_attach/small_room
        # all came back `Present: ['/Main']`). The suite-start reset above +
        # per-scenario cleanup is the proven-stable discipline.
        r = await run_scenario(s)
        results.append(r)

    summary = {
        "pass": sum(1 for r in results if r["status"] == "pass"),
        "fail": sum(1 for r in results if r["status"] == "fail"),
        "error": sum(1 for r in results if r["status"] == "error"),
        "total": len(results),
    }
    summary["pass_rate"] = round(summary["pass"] / max(summary["total"], 1), 4)
    total_ms = sum(r["ms"] for r in results)
    summary["total_ms"] = total_ms
    summary["avg_ms"] = round(total_ms / max(summary["total"], 1))

    scorecard = {
        "kind": "scenarios",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": model,
        "template": template,
        "config_hash": chash,
        "scenarios": results,
        "summary": summary,
    }

    # Persist
    out = SCORECARD_DIR / f"{model}-{chash}.json"
    out.write_text(json.dumps(scorecard, indent=2))
    log(f"→ saved {out.name}")

    # P2+P3: restore the real game scene after the suite completes
    try:
        await bench._godot_ai_call("scene_open", {"path": bench.PROBE_BASE_SCENE})
        log("[scenarios] Restored real game scene")
    except Exception:
        pass

    return scorecard


# ── Raw tool-call scoring (second axis) ───────────────────────────


TOOL_CALL_PROBES = [
    {
        "id": "tool_scene_hierarchy",
        "intent": "Read the scene hierarchy",
        "messages": [{"role": "user", "content": "Show me the scene tree."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "mcp__godot-ai__scene_get_hierarchy",
                    "description": "List all nodes in the current scene tree",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        "expect_tool": "mcp__godot-ai__scene_get_hierarchy",
    },
    {
        "id": "tool_create_cube",
        "intent": "Create a cube",
        "messages": [{"role": "user", "content": "Create a cube in the scene."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "mcp__devforge__apply_spec",
                    "description": "Build or modify the Godot scene from a natural-language request. Creates nodes, meshes, scripts.",
                    "parameters": {
                        "type": "object",
                        "properties": {"prompt": {"type": "string", "description": "What to build"}},
                        "required": ["prompt"],
                    },
                },
            }
        ],
        "expect_tool": "mcp__devforge__apply_spec",
    },
    {
        "id": "tool_create_light",
        "intent": "Add a directional light",
        "messages": [{"role": "user", "content": "Add a directional light to the scene."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "mcp__devforge__apply_spec",
                    "description": "Build or modify the Godot scene. Creates nodes, meshes, lights, scripts.",
                    "parameters": {
                        "type": "object",
                        "properties": {"prompt": {"type": "string"}},
                        "required": ["prompt"],
                    },
                },
            }
        ],
        "expect_tool": "mcp__devforge__apply_spec",
    },
    {
        "id": "tool_delete_node",
        "intent": "Delete a node",
        "messages": [{"role": "user", "content": "Delete the node at path /Main/TestCube."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "mcp__godot-ai__batch_execute",
                    "description": "Execute commands on the Godot scene: create_node, delete_node, set_property, etc.",
                    "parameters": {
                        "type": "object",
                        "properties": {"commands": {"type": "array", "items": {"type": "object"}}},
                        "required": ["commands"],
                    },
                },
            }
        ],
        "expect_tool": "mcp__godot-ai__batch_execute",
    },
    {
        "id": "tool_none",
        "intent": "Ambiguous non-Godot request (should NOT call a Godot tool)",
        "messages": [{"role": "user", "content": "What's the weather like today?"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "mcp__godot-ai__scene_get_hierarchy",
                    "description": "List all nodes in the current scene",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        "expect_tool": None,  # should not call any tool
    },
]


async def _llama_chat_call(messages: list[dict], tools: list[dict], timeout: int = 120) -> dict:
    """Make a raw llama /v1/chat/completions call for tool-call probing."""
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    payload = {
        "model": env.get("MODEL_ALIAS", "model"),
        "messages": messages,
        "tools": tools,
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload)
    return r.json()


async def run_tool_call_probe(probe: dict) -> dict:
    """Run a single tool-call probe. Returns {
        probe_id, status: pass|fail|error, called_tool, expected_tool,
        finish_reason, tokens, ms
    }"""
    t0 = time.time()
    result = {
        "probe_id": probe["id"],
        "intent": probe["intent"],
        "status": "error",
        "called_tool": None,
        "expected_tool": probe.get("expect_tool"),
        "finish_reason": None,
        "tokens": 0,
        "ms": 0,
        "detail": "",
    }

    try:
        raw = await _llama_chat_call(probe["messages"], probe["tools"])
        choice = raw.get("choices", [{}])[0]
        finish = choice.get("finish_reason", "")
        result["finish_reason"] = finish
        result["tokens"] = raw.get("usage", {}).get("total_tokens", 0)

        called = None
        if finish == "tool_calls":
            tcs = choice.get("message", {}).get("tool_calls", [])
            if tcs:
                called = tcs[0]["function"]["name"]
                result["called_tool"] = called

        expected = probe.get("expect_tool")
        if finish == "stop" and expected is None:
            result["status"] = "pass"
            result["detail"] = "Correctly did NOT call a tool"
        elif called == expected:
            result["status"] = "pass"
            result["detail"] = f"Called {called}"
        elif expected is None and called is not None:
            result["status"] = "fail"
            result["detail"] = f"Called {called} but should not call any tool"
        elif called is None and expected is not None:
            result["status"] = "fail"
            result["detail"] = f"No tool call (finish={finish}), expected {expected}"
        else:
            result["status"] = "fail"
            result["detail"] = f"Called {called}, expected {expected}"

    except Exception as e:
        result["status"] = "error"
        result["detail"] = f"{type(e).__name__}: {e}"

    result["ms"] = int((time.time() - t0) * 1000)
    return result


async def run_tool_call_suite(emit: Callable[[str], None] | None = None) -> dict:
    """Run all tool-call probes. Returns {probes: [...], summary: {...}}."""

    def log(msg: str) -> None:
        if emit:
            emit(msg)

    log(f"Tool-call suite: {len(TOOL_CALL_PROBES)} probes")
    results = []
    for p in TOOL_CALL_PROBES:
        log(f"  ▶ {p['id']}")
        r = await run_tool_call_probe(p)
        results.append(r)
        log(f"    [{r['status']}] {r['detail']}")

    summary = {
        "pass": sum(1 for r in results if r["status"] == "pass"),
        "fail": sum(1 for r in results if r["status"] == "fail"),
        "error": sum(1 for r in results if r["status"] == "error"),
        "total": len(results),
    }
    summary["pass_rate"] = round(summary["pass"] / max(summary["total"], 1), 4)

    return {"probes": results, "summary": summary}


# ── Scorecard comparison ───────────────────────────────────────────


def list_scorecards() -> list[dict]:
    """Return all saved scorecards with summary info."""
    cards = []
    for f in sorted(SCORECARD_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(f.read_text())
            cards.append(
                {
                    "file": f.name,
                    "ts": d.get("ts"),
                    "model": d.get("model"),
                    "template": d.get("template"),
                    "config_hash": d.get("config_hash"),
                    "summary": d.get("summary"),
                }
            )
        except Exception:
            continue
    return cards


def get_scorecard(model: str | None = None, config_hash: str | None = None) -> dict | None:
    """Get the most recent scorecard matching filters, or None."""
    cards = list_scorecards()
    for c in cards:
        if model and c["model"] != model:
            continue
        if config_hash and c["config_hash"] != config_hash:
            continue
        # Load full card
        fp = SCORECARD_DIR / c["file"]
        try:
            return json.loads(fp.read_text())
        except Exception:
            continue
    return None


def compare_scorecards(card1_model: str, card2_model: str) -> dict:
    """Side-by-side comparison of the latest scorecards for two models."""
    c1 = get_scorecard(model=card1_model)
    c2 = get_scorecard(model=card2_model)

    if not c1 and not c2:
        return {"error": "No scorecards found for either model"}

    scenarios = SCENARIOS
    rows = []
    for s in scenarios:
        r1 = next((r for r in (c1 or {}).get("scenarios", []) if r["scenario_id"] == s.id), None)
        r2 = next((r for r in (c2 or {}).get("scenarios", []) if r["scenario_id"] == s.id), None)
        rows.append(
            {
                "scenario_id": s.id,
                "category": s.category,
                "description": s.description,
                "model_a": {
                    "status": r1["status"] if r1 else "no data",
                    "ms": r1["ms"] if r1 else 0,
                    "assertions_pass": sum(1 for a in (r1.get("assertions", []) if r1 else []) if a["status"] == "pass")
                    if r1
                    else 0,
                    "assertions_total": len(r1.get("assertions", []) if r1 else []),
                }
                if r1
                else None,
                "model_b": {
                    "status": r2["status"] if r2 else "no data",
                    "ms": r2["ms"] if r2 else 0,
                    "assertions_pass": sum(1 for a in (r2.get("assertions", []) if r2 else []) if a["status"] == "pass")
                    if r2
                    else 0,
                    "assertions_total": len(r2.get("assertions", []) if r2 else []),
                }
                if r2
                else None,
            }
        )

    return {
        "model_a": card1_model,
        "model_b": card2_model,
        "summary_a": c1.get("summary") if c1 else None,
        "summary_b": c2.get("summary") if c2 else None,
        "rows": rows,
    }
