"""Scenario tests — migrated from scenarios.py into plug-in tests.

Each scenario runs apply_spec against the live scene and evaluates
machine-checkable assertions (node_exists, node_type, has_mesh, etc.).

Categories:
  geometry: cube_create, camera_create
  multi-node: batch_three
  scripting: script_attach
  editing: property_edit, delete_existing, delete_existing_bare, rename_existing
  composite: small_room, player_movement
  regression: no_dup_camera
  tool-call: 5 raw llama tool-call probes
"""

from __future__ import annotations

import time
from typing import Any

from ..catalog import register
from ..context import Context
from ..result import ScoredResult, Status
from ..test import Test

# ── Shared scene helpers ──────────────────────────────────────────


async def _get_scene_snapshot(ctx: Context) -> dict:
    """Flat path → {name, type} map of the live scene."""
    h = await ctx.godot_ai("scene_get_hierarchy", {"depth": 10})
    snap: dict = {}
    for n in h.get("nodes", []):
        if isinstance(n, dict) and n.get("path"):
            snap[n["path"]] = {"name": n.get("name", ""), "type": n.get("type", "")}
    return snap


def _resolve_root(snapshot: dict) -> str:
    """Find the live root path (depth=1)."""
    depth1 = [p for p in snapshot if p.count("/") == 1]
    return depth1[0] if len(depth1) == 1 else "/Main"


def _resolve_path(raw_path: str, root: str) -> str:
    """Replace hardcoded /Main prefix with the live root."""
    if raw_path.startswith("/Main/"):
        return root + raw_path[5:]
    if raw_path == "/Main":
        return root
    return raw_path


async def _eval_assertions(
    ctx: Context, before: dict, after: dict, raw: dict, assertions: list[dict], root: str
) -> list[dict]:
    """Evaluate post-condition assertions against live scene state."""
    results: list[dict] = []

    for a in assertions:
        atype = a["type"]
        path = _resolve_path(a.get("path", ""), root)
        try:
            if atype == "node_exists":
                ok = path in after
                msg = f"{path} exists (type={after[path].get('type')})" if ok else f"{path} NOT found"
                results.append(
                    {"status": "pass" if ok else "fail", "assertion": f"node_exists({path})", "message": msg}
                )

            elif atype == "node_not_exists":
                ok = path not in after
                msg = f"{path} correctly absent" if ok else f"{path} STILL exists"
                results.append(
                    {"status": "pass" if ok else "fail", "assertion": f"node_not_exists({path})", "message": msg}
                )

            elif atype == "node_type":
                node = after.get(path)
                expected = a.get("node_type", "")
                if node is None:
                    results.append(
                        {
                            "status": "fail",
                            "assertion": f"node_type({path}, {expected})",
                            "message": f"{path} not found",
                        }
                    )
                elif node.get("type") == expected:
                    results.append(
                        {
                            "status": "pass",
                            "assertion": f"node_type({path}, {expected})",
                            "message": f"{path} is {expected}",
                        }
                    )
                else:
                    results.append(
                        {
                            "status": "fail",
                            "assertion": f"node_type({path}, {expected})",
                            "message": f"{path} is {node.get('type')}, expected {expected}",
                        }
                    )

            elif atype == "has_mesh":
                try:
                    props = await ctx.godot_ai("node_get_properties", {"path": path})
                    plist = props.get("properties", props.get("data", props))
                    if isinstance(plist, list):
                        plist = {x.get("name"): x.get("value") for x in plist if isinstance(x, dict)}
                    if plist.get("mesh"):
                        results.append(
                            {"status": "pass", "assertion": f"has_mesh({path})", "message": f"{path} has mesh"}
                        )
                    else:
                        results.append(
                            {"status": "fail", "assertion": f"has_mesh({path})", "message": f"{path} has NO mesh"}
                        )
                except Exception as e:
                    results.append({"status": "error", "assertion": f"has_mesh({path})", "message": str(e)})

            elif atype == "has_script":
                try:
                    props = await ctx.godot_ai("node_get_properties", {"path": path})
                    plist = props.get("properties", props.get("data", props))
                    if isinstance(plist, list):
                        plist = {x.get("name"): x.get("value") for x in plist if isinstance(x, dict)}
                    script_val = plist.get("script")
                    if script_val and script_val != "None":
                        results.append(
                            {"status": "pass", "assertion": f"has_script({path})", "message": f"{path} has script"}
                        )
                    else:
                        results.append(
                            {"status": "fail", "assertion": f"has_script({path})", "message": f"{path} has NO script"}
                        )
                except Exception as e:
                    results.append({"status": "error", "assertion": f"has_script({path})", "message": str(e)})

            elif atype == "no_errors":
                errors = raw.get("errors", [])
                err_count = raw.get("error_count", len(errors))
                if err_count > 0:
                    results.append(
                        {"status": "fail", "assertion": "no_errors", "message": f"{err_count} error(s): {errors[:3]}"}
                    )
                else:
                    results.append({"status": "pass", "assertion": "no_errors", "message": "Zero errors"})

            elif atype == "no_duplicate_cameras":
                cam_count = sum(1 for n in after.values() if n.get("type") == "Camera3D")
                if cam_count <= 3:
                    results.append(
                        {"status": "pass", "assertion": "no_duplicate_cameras", "message": f"{cam_count} cameras (ok)"}
                    )
                else:
                    results.append(
                        {
                            "status": "fail",
                            "assertion": "no_duplicate_cameras",
                            "message": f"{cam_count} cameras — duplicate regression",
                        }
                    )

            elif atype == "no_extra_nodes":
                exclude = set(a.get("exclude", []))
                known = {"Main", "MainCamera", "DirectionalLight", "Ground"}
                new_nodes = [
                    p
                    for p in after
                    if after[p].get("name") not in exclude and after[p].get("name") not in known and p not in before
                ]
                if new_nodes:
                    results.append(
                        {
                            "status": "fail",
                            "assertion": f"no_extra_nodes(exclude={exclude})",
                            "message": f"Unrequested: {new_nodes}",
                        }
                    )
                else:
                    results.append(
                        {
                            "status": "pass",
                            "assertion": f"no_extra_nodes(exclude={exclude})",
                            "message": "No extra nodes",
                        }
                    )

            else:
                results.append({"status": "error", "assertion": atype, "message": f"Unknown assertion type: {atype}"})
        except Exception as e:
            results.append({"status": "error", "assertion": atype, "message": f"{type(e).__name__}: {e}"})

    return results


async def _scenario_run(ctx: Context, scenario: dict[str, Any]) -> dict[str, Any]:
    """Shared run() logic for all apply-spec scenarios."""
    t0 = time.time()

    # Seed nodes
    for sd in scenario.get("seed", []):
        await ctx.godot_ai(
            "node_create",
            {
                "type": sd.get("type", "Node3D"),
                "name": sd["name"],
                "parent_path": sd.get("parent", "/Main"),
            },
        )

    # Snapshots
    before = await _get_scene_snapshot(ctx)
    root = _resolve_root(before)

    # Apply spec
    raw = await ctx.apply_spec(scenario["prompt"], planner="")
    artifact = raw
    if raw.get("artifact_id"):
        try:
            artifact = await ctx.read_artifact(raw["artifact_id"])
        except Exception:
            pass

    after = await _get_scene_snapshot(ctx)

    # Assertions
    assertion_results = await _eval_assertions(ctx, before, after, artifact, scenario["assertions"], root)

    # Cleanup
    cleanup_errors: list[str] = []
    for op in scenario.get("cleanup", []):
        try:
            path = _resolve_path(op["path"], root)
            await ctx.godot_ai("batch_execute", {"commands": [{"command": "delete_node", "params": {"path": path}}]})
        except Exception as e:
            cleanup_errors.append(f"cleanup {path}: {e}")

    ms = int((time.time() - t0) * 1000)
    return {
        "before": {p: n["name"] for p, n in before.items()},
        "after": {p: n["name"] for p, n in after.items()},
        "root": root,
        "raw": raw,
        "artifact": artifact,
        "assertion_results": assertion_results,
        "cleanup_errors": cleanup_errors,
        "latency_ms": ms,
    }


def _compute_score(assertion_results: list[dict]) -> tuple[Status, int, list[str]]:
    """Compute status + score + errors from assertion results."""
    passes = sum(1 for a in assertion_results if a["status"] == "pass")
    fails = sum(1 for a in assertion_results if a["status"] == "fail")
    errors = sum(1 for a in assertion_results if a["status"] == "error")
    total = max(len(assertion_results), 1)
    score = round(passes / total * 100)

    err_msgs = [a["message"] for a in assertion_results if a["status"] in ("fail", "error")]

    if errors:
        return "error", score, err_msgs
    if fails:
        return "partial" if score >= 50 else "broke", score, err_msgs
    return "ok", 100, []


# ── Scenario tests ──────────────────────────────────────────────


@register
class ScenarioCubeCreate(Test):
    id = "scenario.cube_create"
    category = "scenario"
    title = "Cube create"
    description = "Basic MeshInstance3D + BoxMesh creation at center."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": "Create a MeshInstance3D named TestCube with a BoxMesh in the center of the scene at position 0,0,0.",
                "seed": [],
                "assertions": [
                    {"type": "node_exists", "path": "/Main/TestCube"},
                    {"type": "node_type", "path": "/Main/TestCube", "node_type": "MeshInstance3D"},
                    {"type": "has_mesh", "path": "/Main/TestCube"},
                    {"type": "no_errors"},
                ],
                "cleanup": [{"path": "/Main/TestCube"}],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


@register
class ScenarioCameraCreate(Test):
    id = "scenario.camera_create"
    category = "scenario"
    title = "Camera create"
    description = "Camera3D with position and rotation."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": "Create a Camera3D named TestCam at position 0,2,10 looking at the origin.",
                "seed": [],
                "assertions": [
                    {"type": "node_exists", "path": "/Main/TestCam"},
                    {"type": "node_type", "path": "/Main/TestCam", "node_type": "Camera3D"},
                    {"type": "no_errors"},
                ],
                "cleanup": [{"path": "/Main/TestCam"}],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


@register
class ScenarioBatchThree(Test):
    id = "scenario.batch_three"
    category = "scenario"
    title = "Batch three nodes"
    description = "Three MeshInstance3D nodes with BoxMesh in one apply_spec call."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": "Create three MeshInstance3D nodes with BoxMesh: BlockA at 0,0,0, BlockB at 2,0,0, BlockC at -2,0,0.",
                "seed": [],
                "assertions": [
                    {"type": "node_exists", "path": "/Main/BlockA"},
                    {"type": "node_exists", "path": "/Main/BlockB"},
                    {"type": "node_exists", "path": "/Main/BlockC"},
                    {"type": "node_type", "path": "/Main/BlockA", "node_type": "MeshInstance3D"},
                    {"type": "node_type", "path": "/Main/BlockB", "node_type": "MeshInstance3D"},
                    {"type": "node_type", "path": "/Main/BlockC", "node_type": "MeshInstance3D"},
                    {"type": "no_extra_nodes", "exclude": ["BlockA", "BlockB", "BlockC"]},
                    {"type": "no_errors"},
                ],
                "cleanup": [{"path": "/Main/BlockA"}, {"path": "/Main/BlockB"}, {"path": "/Main/BlockC"}],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


@register
class ScenarioScriptAttach(Test):
    id = "scenario.script_attach"
    category = "scenario"
    title = "Script create + attach"
    description = "Create GDScript + attach to node."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": "Create a MeshInstance3D with BoxMesh named ScriptedCube at 0,0,0, then create a new GDScript that rotates it slowly around the Y axis, and attach it as a script.",
                "seed": [],
                "assertions": [
                    {"type": "node_exists", "path": "/Main/ScriptedCube"},
                    {"type": "node_type", "path": "/Main/ScriptedCube", "node_type": "MeshInstance3D"},
                    {"type": "has_script", "path": "/Main/ScriptedCube"},
                    {"type": "no_duplicate_cameras"},
                    {"type": "no_errors"},
                ],
                "cleanup": [{"path": "/Main/ScriptedCube"}],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


@register
class ScenarioPropertyEdit(Test):
    id = "scenario.property_edit"
    category = "scenario"
    title = "Property edit"
    description = "Node creation with subsequent property edit (scale)."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": "Create a simple MeshInstance3D with BoxMesh called PropTarget at 0,0,0, then set its scale to 2,2,2.",
                "seed": [],
                "assertions": [
                    {"type": "node_exists", "path": "/Main/PropTarget"},
                    {"type": "node_type", "path": "/Main/PropTarget", "node_type": "MeshInstance3D"},
                    {"type": "no_errors"},
                ],
                "cleanup": [{"path": "/Main/PropTarget"}],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


@register
class ScenarioDeleteExisting(Test):
    id = "scenario.delete_existing"
    category = "scenario"
    title = "Delete existing node"
    description = "Delete a node that already exists (noun-phrase phrasing)."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": "Delete the Target node from the scene.",
                "seed": [{"name": "Target", "type": "MeshInstance3D", "parent": "/Main"}],
                "assertions": [
                    {"type": "node_not_exists", "path": "/Main/Target"},
                    {"type": "no_errors"},
                ],
                "cleanup": [{"path": "/Main/Target"}],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


@register
class ScenarioDeleteExistingBare(Test):
    id = "scenario.delete_existing_bare"
    category = "scenario"
    title = "Delete existing (bare name)"
    description = "Delete an existing node — bare-name phrasing (extractor stress)."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": "Delete Gizmo.",
                "seed": [{"name": "Gizmo", "type": "MeshInstance3D", "parent": "/Main"}],
                "assertions": [
                    {"type": "node_not_exists", "path": "/Main/Gizmo"},
                    {"type": "no_errors"},
                ],
                "cleanup": [{"path": "/Main/Gizmo"}],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


@register
class ScenarioRenameExisting(Test):
    id = "scenario.rename_existing"
    category = "scenario"
    title = "Rename existing node"
    description = "Rename a node that already exists."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": "Rename the Origin node to Renamed.",
                "seed": [{"name": "Origin", "type": "MeshInstance3D", "parent": "/Main"}],
                "assertions": [
                    {"type": "node_exists", "path": "/Main/Renamed"},
                    {"type": "node_not_exists", "path": "/Main/Origin"},
                    {"type": "no_errors"},
                ],
                "cleanup": [{"path": "/Main/Renamed"}, {"path": "/Main/Origin"}],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


@register
class ScenarioSmallRoom(Test):
    id = "scenario.small_room"
    category = "scenario"
    title = "Small room"
    description = "Multi-object scene: 4 walls + light."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": (
                    "Build a small room: four MeshInstance3D cubes (WallFront, WallBack, WallLeft, WallRight) "
                    "forming walls at positions 0,0,5 / 0,0,-5 / -5,0,0 / 5,0,0 with scale 10,3,0.5 for each wall. "
                    "Add a DirectionalLight3D called RoomLight at 0,5,0 with light_energy 0.6."
                ),
                "seed": [],
                "assertions": [
                    {"type": "node_exists", "path": "/Main/WallFront"},
                    {"type": "node_exists", "path": "/Main/WallBack"},
                    {"type": "node_exists", "path": "/Main/WallLeft"},
                    {"type": "node_exists", "path": "/Main/WallRight"},
                    {"type": "node_exists", "path": "/Main/RoomLight"},
                    {"type": "no_duplicate_cameras"},
                    {"type": "no_errors"},
                ],
                "cleanup": [
                    {"path": "/Main/WallFront"},
                    {"path": "/Main/WallBack"},
                    {"path": "/Main/WallLeft"},
                    {"path": "/Main/WallRight"},
                    {"path": "/Main/RoomLight"},
                ],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


@register
class ScenarioPlayerMovement(Test):
    id = "scenario.player_movement"
    category = "scenario"
    title = "Player with movement"
    description = "Player + script + camera child — full game-object pattern."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": (
                    "Add a player character to the scene: a MeshInstance3D with CapsuleMesh named Player "
                    "at position 0,1,0. Create a GDScript attached to Player that listens for WASD keyboard input "
                    "and moves Player along X/Z axes at 5 units per second using _process(delta). "
                    "Add a Camera3D named PlayerCam as a child of Player at position 0,1.5,5."
                ),
                "seed": [],
                "assertions": [
                    {"type": "node_exists", "path": "/Main/Player"},
                    {"type": "node_type", "path": "/Main/Player", "node_type": "MeshInstance3D"},
                    {"type": "has_mesh", "path": "/Main/Player"},
                    {"type": "has_script", "path": "/Main/Player"},
                    {"type": "node_exists", "path": "/Main/Player/PlayerCam"},
                    {"type": "no_duplicate_cameras"},
                    {"type": "no_errors"},
                ],
                "cleanup": [{"path": "/Main/Player"}],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


@register
class ScenarioNoDupCamera(Test):
    id = "scenario.no_dup_camera"
    category = "scenario"
    title = "No duplicate cameras"
    description = "Regression: creating a single node must NOT duplicate cameras/lights."
    suites = ["everything", "scenarios-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _scenario_run(
            ctx,
            {
                "prompt": "Create a simple red MeshInstance3D cube named RedBlock at position 0,0,0.",
                "seed": [],
                "assertions": [
                    {"type": "node_exists", "path": "/Main/RedBlock"},
                    {"type": "no_duplicate_cameras"},
                    {"type": "no_errors"},
                ],
                "cleanup": [{"path": "/Main/RedBlock"}],
            },
        )

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("assertion_results", [])
        status, score, errors = _compute_score(results)
        return ScoredResult(self.id, status, score=score, raw=raw, errors=errors)


# ═══════════════════════════════════════════════════════════════════
# Tool-call probes — raw llama chat/completions without DevForge
# ═══════════════════════════════════════════════════════════════════


async def _llama_chat(ctx: Context, messages: list[dict], tools: list[dict], timeout: int = 120) -> dict:
    """Raw llama /v1/chat/completions call."""
    port = ctx.env.get("LLAMA_PORT", "8002")
    payload = {
        "model": ctx.model_alias,
        "messages": messages,
        "tools": tools,
        "temperature": 0.2,
    }
    return await ctx.llama_post(f"http://127.0.0.1:{port}/v1/chat/completions", payload, timeout=timeout)


def _tool_call_score(expected: str | None, raw: dict) -> tuple[Status, int]:
    """Score a tool-call probe: did the model call the expected tool?"""
    choice = raw.get("choices", [{}])[0]
    finish = choice.get("finish_reason", "")
    tool_calls = choice.get("message", {}).get("tool_calls", [])
    called = tool_calls[0]["function"]["name"] if tool_calls else None

    if finish == "stop" and expected is None:
        return "ok", 100
    if called == expected:
        return "ok", 100
    if expected is None and called is not None:
        return "partial", 30
    if called is None and expected is not None:
        return "broke", 0
    return "broke", 0


@register
class ScenarioToolSceneHierarchy(Test):
    id = "scenario.tool_scene_hierarchy"
    category = "scenario"
    title = "Tool call: scene hierarchy"
    description = "Should call scene_get_hierarchy for a tree-read request."
    suites = ["everything", "scenarios-v1"]

    async def run(self, ctx: Context) -> dict:
        return await _llama_chat(
            ctx,
            [{"role": "user", "content": "Show me the scene tree."}],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "mcp__godot-ai__scene_get_hierarchy",
                        "description": "List all nodes",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

    def score(self, raw: dict) -> ScoredResult:
        status, score = _tool_call_score("mcp__godot-ai__scene_get_hierarchy", raw)
        return ScoredResult(self.id, status, score=score, raw=raw)


@register
class ScenarioToolCreateCube(Test):
    id = "scenario.tool_create_cube"
    category = "scenario"
    title = "Tool call: create cube"
    description = "Should call apply_spec for a cube request."
    suites = ["everything", "scenarios-v1"]

    async def run(self, ctx: Context) -> dict:
        return await _llama_chat(
            ctx,
            [{"role": "user", "content": "Create a cube in the scene."}],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "mcp__devforge__apply_spec",
                        "description": "Build or modify the Godot scene",
                        "parameters": {
                            "type": "object",
                            "properties": {"prompt": {"type": "string"}},
                            "required": ["prompt"],
                        },
                    },
                }
            ],
        )

    def score(self, raw: dict) -> ScoredResult:
        status, score = _tool_call_score("mcp__devforge__apply_spec", raw)
        return ScoredResult(self.id, status, score=score, raw=raw)


@register
class ScenarioToolCreateLight(Test):
    id = "scenario.tool_create_light"
    category = "scenario"
    title = "Tool call: add light"
    description = "Should call apply_spec for a light request."
    suites = ["everything", "scenarios-v1"]

    async def run(self, ctx: Context) -> dict:
        return await _llama_chat(
            ctx,
            [{"role": "user", "content": "Add a directional light to the scene."}],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "mcp__devforge__apply_spec",
                        "description": "Build or modify the Godot scene",
                        "parameters": {
                            "type": "object",
                            "properties": {"prompt": {"type": "string"}},
                            "required": ["prompt"],
                        },
                    },
                }
            ],
        )

    def score(self, raw: dict) -> ScoredResult:
        status, score = _tool_call_score("mcp__devforge__apply_spec", raw)
        return ScoredResult(self.id, status, score=score, raw=raw)


@register
class ScenarioToolDeleteNode(Test):
    id = "scenario.tool_delete_node"
    category = "scenario"
    title = "Tool call: delete node"
    description = "Should call batch_execute for a delete request."
    suites = ["everything", "scenarios-v1"]

    async def run(self, ctx: Context) -> dict:
        return await _llama_chat(
            ctx,
            [{"role": "user", "content": "Delete the node at path /Main/TestCube."}],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "mcp__godot-ai__batch_execute",
                        "description": "Execute commands on the Godot scene",
                        "parameters": {
                            "type": "object",
                            "properties": {"commands": {"type": "array", "items": {"type": "object"}}},
                            "required": ["commands"],
                        },
                    },
                }
            ],
        )

    def score(self, raw: dict) -> ScoredResult:
        status, score = _tool_call_score("mcp__godot-ai__batch_execute", raw)
        return ScoredResult(self.id, status, score=score, raw=raw)


@register
class ScenarioToolNone(Test):
    id = "scenario.tool_none"
    category = "scenario"
    title = "Tool call: no false positive"
    description = "Should NOT call any tool for a non-Godot query."
    suites = ["everything", "scenarios-v1"]

    async def run(self, ctx: Context) -> dict:
        return await _llama_chat(
            ctx,
            [{"role": "user", "content": "What's the weather like today?"}],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "mcp__godot-ai__scene_get_hierarchy",
                        "description": "List all nodes",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

    def score(self, raw: dict) -> ScoredResult:
        status, score = _tool_call_score(None, raw)
        return ScoredResult(self.id, status, score=score, raw=raw)
