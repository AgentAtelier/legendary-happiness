"""forge-hub shootout — comprehensive pipeline test across all models.

Runs the same medium-complexity "Interactive Collectible Arena" prompt
against every available model sequentially, then scores the results
with machine-checkable static + runtime assertions.

Usage:
  python shootout.py                  # list available models
  python shootout.py --all            # run all models
  python shootout.py --model qwen3    # run one model
  python shootout.py --all-planners   # run all models, both arch + ops planner
  python shootout.py --list           # list past shootouts
  python shootout.py --last           # show latest results
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

# Reuse MCP plumbing from scenarios.py
from scenarios import (
    _godot_ai_call,
    _devforge_call,
    _get_scene_snapshot,
    DATA_DIR,
)

HOME = Path.home()
STACK_ENV = HOME / ".config/forge-stack/stack.env"
SHOOTOUT_DIR = DATA_DIR / "shootouts"
SHOOTOUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Planner mode switching (for --all-planners A/B comparison) ──


def _set_planner_mode(mode: str) -> None:
    """Set DEVFORGE_PLANNER env var in stack.env. mode='' removes it."""
    lines = STACK_ENV.read_text().splitlines() if STACK_ENV.exists() else []
    new_lines: list[str] = []
    found = False
    for line in lines:
        if line.strip().startswith("DEVFORGE_PLANNER="):
            found = True
            if mode:
                new_lines.append(f"DEVFORGE_PLANNER={mode}")
        else:
            new_lines.append(line)
    if not found and mode:
        new_lines.append(f"DEVFORGE_PLANNER={mode}")
    STACK_ENV.write_text("\n".join(new_lines) + "\n")


async def _restart_devforge(emit: Callable[[str], None]) -> bool:
    """Restart forge-devforge service and wait for MCP to be healthy."""
    emit("  restarting DevForge service...")
    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        "--user",
        "restart",
        "forge-devforge.service",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    await proc.wait()
    for _ in range(30):
        await asyncio.sleep(1)
        try:
            tools = await _devforge_call("__list__", timeout_s=10)
            tl = tools.tools if hasattr(tools, "tools") else tools
            if hasattr(tl, "__iter__") and len(list(tl)) > 0:
                emit("  DevForge healthy after restart")
                return True
        except Exception:
            pass
    emit("  DevForge did not become healthy within 30s")
    return False


# ── Scene isolation ──────────────────────────────────────────────
# The shootout runs in a DISPOSABLE scene, never the real game. Before
# every model run we rewrite this file to the canonical baseline below
# and force a fresh disk re-read, so no model can contaminate the next
# one — and project_run(autosave) can never persist junk into main.tscn.
SHOOTOUT_SCENE = "res://shootout.tscn"
# Bounce scene: opening a *different* scene first forces scene_open to
# re-read SHOOTOUT_SCENE from disk (scene_open is a no-op if the target
# is already the active scene). Also where we leave the editor when done.
BASE_SCENE = "res://scenes/main.tscn"

# Canonical baseline written to SHOOTOUT_SCENE before each run. Root is a
# Node3D named "Main" (+ Camera3D + Ground) so the prompt's "/Main" paths
# resolve exactly as they would against the real game scene.
SHOOTOUT_SCENE_TSCN = """[gd_scene format=3 uid="uid://cshoot0utbench01"]

[node name="Main" type="Node3D"]

[node name="Camera3D" type="Camera3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 8)
current = true

[node name="Ground" type="StaticBody3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -0.5, 0)
"""

# ── File logging ─────────────────────────────────────────────────
# Each shootout writes a companion .log file alongside its .json scorecard.

_LOG_FILE: Path | None = None


def _log_open(ts: str) -> None:
    """Open a log file for the current shootout run."""
    global _LOG_FILE
    _LOG_FILE = SHOOTOUT_DIR / f"shootout-{ts}.log"
    _LOG_FILE.write_text(f"=== SHOOTOUT LOG {ts} ===\n\n")


def _log_write(line: str) -> None:
    """Append a timestamped line to the current log file."""
    global _LOG_FILE
    if _LOG_FILE:
        stamp = time.strftime("%H:%M:%S")
        try:
            with open(_LOG_FILE, "a") as f:
                f.write(f"[{stamp}] {line}\n")
        except OSError:
            pass


def _log_error(exc: Exception, context: str = "") -> None:
    """Log an exception with full traceback."""
    tb = traceback.format_exc()
    _log_write(f"ERROR {context}: {type(exc).__name__}: {exc}")
    for line in tb.splitlines():
        _log_write(f"  TRACE: {line}")


# ── The prompt — exact specification for the arena ───────────────

SHOOTOUT_PROMPT = """Build an interactive collectible arena in the Godot scene.

1. Create a Node3D named "Arena" as a child of /Main.

2. Under Arena, create a MeshInstance3D named "Player" with a CapsuleMesh.
   Position it at (0, 1, 0).
   Create a GDScript file named "player_movement.gd" and attach it to Player.
   The script should: listen for WASD keyboard input using Input.get_vector()
   or Input.is_key_pressed(), and move Player along X and Z axes at 5 units per
   second in _process(delta).
   Create a Camera3D named "PlayerCamera" as a child of Player at
   position (0, 1.5, 5).

3. Under Arena, create a Node3D named "Collectibles".
   Under it, create five Area3D nodes, each with a CollisionShape3D child
   using SphereShape3D (radius 0.5) and a MeshInstance3D child with SphereMesh:
   - Coin_Red at (-4, 0.5, 0), material albedo color red (1, 0, 0, 1)
   - Coin_Green at (0, 0.5, 4), material albedo color green (0, 1, 0, 1)
   - Coin_Blue at (4, 0.5, 0), material albedo color blue (0, 0, 1, 1)
   - Coin_Gold at (0, 0.5, -4), material albedo color gold (1, 0.8, 0, 1)
   - Coin_Purple at (0, 1.5, 0), material albedo color purple (0.5, 0, 1, 1)

4. Create a GDScript named "collectible.gd" and attach it to each coin.
   The script should: connect the body_entered signal to a function
   _on_body_entered(body), and in that function, call queue_free() on itself.
   It should also find the ScoreLabel node and increment a score variable.

5. Under Arena, create a CanvasLayer named "UI".
   Under it, create a Label named "ScoreLabel" with text "Score: 0"
   and position at the top-left of the screen (anchor_left=0, anchor_top=0,
   offset_left=20, offset_top=20)."""

# ── Model list (from forge_models) ───────────────────────────────

MODELS_TO_TEST = [
    {"file": "Qwen3-14B-Q6_K.gguf", "alias": "qwen3-14b-q6-k", "label": "Qwen3 14B"},
    {
        "file": "gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
        "alias": "gemma-4-12b-it-qat-ud-q4-k-xl",
        "label": "Gemma 4 12B QAT",
    },
    {
        "file": "gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf",
        "alias": "gemma-4-26b-a4b-it-qat-ud-q4-k-xl",
        "label": "Gemma 4 26B MoE",
    },
    {
        "file": "Gemma-4-12B-OBLITERATED.Q6_K.gguf",
        "alias": "gemma-4-12b-obliterated-q6-k",
        "label": "Gemma 4 12B Obliterated",
    },
    {
        "file": "Cydonia-Redux-22B-v1e-Q4_K_M.gguf",
        "alias": "cydonia-redux-22b-v1e-q4-k-m",
        "label": "Cydonia Redux 22B",
    },
]


# ── Pre-flight checks ────────────────────────────────────────────


async def preflight_check(emit: Callable[[str], None] | None = None) -> dict:
    """Verify all prerequisites before running the shootout.

    Returns: {ok: bool, issues: [str], checks: {name: status}}
    """
    import httpx

    def log(msg: str) -> None:
        if emit:
            emit(msg)

    issues: list[str] = []
    checks: dict[str, str] = {}

    # 1. Check godot-ai MCP connection + prepare the disposable scene.
    # We write a pristine shootout.tscn and open it ourselves — the
    # benchmark must run in its own throwaway scene, never the real game.
    log("preflight: checking godot-ai MCP...")
    try:
        await _reset_scene()
        snap = await _get_scene_snapshot()
        checks["godot_ai_mcp"] = "ok"
        log(f"  godot-ai: {len(snap)} nodes in scene")

        # Verify the baseline scene opened: expect a Node3D root named "Main".
        node_names = {snap.get(p, {}).get("name", "") for p in snap}
        if "Main" in node_names:
            checks["godot_project"] = "ok"
            log(f"  project: shootout scene ready ({SHOOTOUT_SCENE})")
        else:
            node_list = sorted(node_names)[:10]
            checks["godot_project"] = "warn"
            msg = f"shootout scene missing its 'Main' root — nodes: {node_list}. Could not open {SHOOTOUT_SCENE}."
            issues.append(msg)
            log(f"  ⚠ {msg}")
    except Exception as e:
        checks["godot_ai_mcp"] = "fail"
        msg = f"godot-ai MCP unreachable: {e}. Is the Godot editor open with the rpg project?"
        issues.append(msg)
        log(f"  ❌ {msg}")

    # 2. Check DevForge MCP
    log("preflight: checking DevForge MCP...")
    try:
        # Just list tools to verify connection
        tools = await _devforge_call("__list__", timeout_s=10)
        # list_tools() returns ListToolsResult with .tools attribute
        tool_list = tools.tools if hasattr(tools, "tools") else (tools if hasattr(tools, "__iter__") else [])
        tool_names = [t.name for t in tool_list]
        if "apply_spec" in tool_names:
            checks["devforge"] = "ok"
            log(f"  DevForge: {len(tool_names)} tools available")
        else:
            checks["devforge"] = "warn"
            issues.append("DevForge connected but apply_spec tool not found")
            log("  ⚠ DevForge connected but apply_spec missing")
    except Exception as e:
        checks["devforge"] = "fail"
        msg = f"DevForge MCP unreachable: {e}"
        issues.append(msg)
        log(f"  ❌ {msg}")

    # 3. Check llama /health
    log("preflight: checking llama...")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://127.0.0.1:8002/health")
            if r.status_code == 200:
                checks["llama"] = "ok"
                log("  llama: healthy")
            else:
                checks["llama"] = "fail"
                issues.append(f"llama returned {r.status_code}")
                log(f"  ❌ llama returned {r.status_code}")
    except Exception as e:
        checks["llama"] = "fail"
        msg = f"llama unreachable: {e}"
        issues.append(msg)
        log(f"  ❌ {msg}")

    # 4. Check models available
    log("preflight: scanning models...")
    models = await _resolve_models()
    checks["models_available"] = "ok" if models else "fail"
    if models:
        log(f"  models: {len(models)} available")
    else:
        issues.append("No models passed VRAM check")
        log("  ❌ No models available")

    ok = len(issues) == 0
    status = "✅ All checks passed" if ok else f"❌ {len(issues)} issue(s) found"
    log(f"\npreflight: {status}")

    return {"ok": ok, "issues": issues, "checks": checks}


# ── Model resolution ─────────────────────────────────────────────


async def _resolve_models(model_filter: str | None = None) -> list[dict]:
    """Resolve which models are actually present and fit in VRAM.

    If model_filter is provided, only return models matching that alias/file fragment.
    """
    from forge_models import scan as _scan, GIB, vram_total, RESERVE
    from forge_ops import get_free_vram

    all_models = _scan()
    by_file = {m["file"]: m for m in all_models}

    resolved = []
    free_vram = get_free_vram()
    available = vram_total() - RESERVE

    candidates = MODELS_TO_TEST
    if model_filter:
        q = model_filter.lower()
        candidates = [
            m for m in MODELS_TO_TEST if q in m["alias"].lower() or q in m["file"].lower() or q in m["label"].lower()
        ]

    for m in candidates:
        found = by_file.get(m["file"])
        if not found:
            continue
        need_gb = found.get("fit", {}).get("need_gb", 0)
        if need_gb * GIB > available:
            continue
        # Use forge-model's REAL derived alias for the swap, not the hardcoded
        # one — they drifted (e.g. "…-qat-ud-q4-k-xl" vs "…-qat-q4-k-xl"), which
        # made the swap fragment resolve to nothing and 4/5 models report fake 0s.
        resolved.append({**m, "alias": found.get("alias", m["alias"]), "model": found})
    return resolved


async def _wait_for_healthy(llama_port: str = "8002", timeout: float = 60.0) -> bool:
    """Wait for llama /health to return 200 after a swap."""
    import httpx

    t0 = time.time()
    async with httpx.AsyncClient(timeout=3.0) as client:
        while time.time() - t0 < timeout:
            try:
                r = await client.get(f"http://127.0.0.1:{llama_port}/health")
                if r.status_code == 200:
                    await asyncio.sleep(2)
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)
    return False


async def _swap_model(alias: str, emit: Callable[[str], None]) -> bool:
    """Swap to a model via the hub's internal swap_model. Returns True on success."""
    from forge_ops import swap_model as _swap

    emit(f"  swapping to {alias}...")
    exit_code = await _swap(alias, emit)
    if exit_code != 0:
        emit(f"  swap FAILED (exit={exit_code})")
        return False

    emit(f"  waiting for llama to be healthy...")
    healthy = await _wait_for_healthy()
    if not healthy:
        emit(f"  llama did not become healthy within timeout")
        return False

    emit(f"  llama healthy, model={alias}")
    return True


# ── Static assertions (run after apply_spec) ─────────────────────


async def _run_static_assertions(artifact: dict) -> list[dict]:
    """Run 15 static checks against the scene. Returns assertion results list."""
    results: list[dict] = []
    snapshot = await _get_scene_snapshot()

    def check(status: str, label: str, msg: str) -> dict:
        return {"status": status, "assertion": label, "message": msg}

    def exists(path: str) -> bool:
        return path in snapshot

    def node_type(path: str) -> str:
        return snapshot.get(path, {}).get("type", "")

    # Fetch Player properties once (used by checks 3 and 4)
    player_props = {}
    try:
        props = await _godot_ai_call("node_get_properties", {"path": "/Main/Arena/Player"})
        pdata = props.get("data", props)
        plist = pdata.get("properties", pdata)
        if isinstance(plist, list):
            player_props = {x.get("name"): x.get("value") for x in plist if isinstance(x, dict)}
    except Exception:
        pass

    # 1. Arena exists
    results.append(
        check(
            "pass" if exists("/Main/Arena") else "fail",
            "arena_exists",
            "/Main/Arena" + (" found" if exists("/Main/Arena") else " missing"),
        )
    )

    # 2. Player is MeshInstance3D
    results.append(
        check(
            "pass" if node_type("/Main/Arena/Player") == "MeshInstance3D" else "fail",
            "player_type",
            f"Player type = {node_type('/Main/Arena/Player')}",
        )
    )

    # 3. Player has mesh
    has_mesh = bool(player_props.get("mesh"))
    results.append(
        check("pass" if has_mesh else "fail", "player_mesh", "Player has mesh" if has_mesh else "Player has NO mesh")
    )

    # 4. Player has script
    has_script = bool(player_props.get("script") and player_props.get("script") != "None")
    results.append(
        check(
            "pass" if has_script else "fail",
            "player_script",
            "Player has script" if has_script else "Player has NO script",
        )
    )

    # 5. PlayerCamera is Camera3D
    results.append(
        check(
            "pass" if node_type("/Main/Arena/Player/PlayerCamera") == "Camera3D" else "fail",
            "player_camera",
            f"PlayerCamera type = {node_type('/Main/Arena/Player/PlayerCamera')}",
        )
    )

    # 6. All 5 coins exist
    coin_names = ["Coin_Red", "Coin_Green", "Coin_Blue", "Coin_Gold", "Coin_Purple"]
    for name in coin_names:
        path = f"/Main/Arena/Collectibles/{name}"
        results.append(
            check(
                "pass" if exists(path) else "fail",
                f"coin_{name.lower()}_exists",
                f"{name} {'found' if exists(path) else 'missing'}",
            )
        )

    # 7. Coins are Area3D
    for name in coin_names:
        path = f"/Main/Arena/Collectibles/{name}"
        results.append(
            check(
                "pass" if node_type(path) == "Area3D" else "fail",
                f"coin_{name.lower()}_type",
                f"{name} type = {node_type(path)}",
            )
        )

    # 8. Each coin has CollisionShape3D child
    collider_ok = True
    for name in coin_names:
        coin_path = f"/Main/Arena/Collectibles/{name}"
        has_collider = any(p.startswith(coin_path + "/") and "CollisionShape" in node_type(p) for p in snapshot)
        if not has_collider:
            collider_ok = False
            break
    results.append(
        check(
            "pass" if collider_ok else "fail",
            "coins_collision",
            "All coins have CollisionShape3D" if collider_ok else "Missing CollisionShape3D on >=1 coin",
        )
    )

    # 9. Each coin has MeshInstance3D child with mesh
    mesh_child_ok = True
    for name in coin_names:
        coin_path = f"/Main/Arena/Collectibles/{name}"
        has_mesh_child = any(p.startswith(coin_path + "/") and node_type(p) == "MeshInstance3D" for p in snapshot)
        if not has_mesh_child:
            mesh_child_ok = False
            break
    results.append(
        check(
            "pass" if mesh_child_ok else "fail",
            "coins_mesh",
            "All coins have MeshInstance3D children" if mesh_child_ok else "Missing MeshInstance3D on >=1 coin",
        )
    )

    # 10. CanvasLayer exists
    results.append(
        check(
            "pass" if node_type("/Main/Arena/UI") == "CanvasLayer" else "fail",
            "ui_canvas",
            f"UI type = {node_type('/Main/Arena/UI')}",
        )
    )

    # 11. ScoreLabel exists
    has_label = exists("/Main/Arena/UI/ScoreLabel")
    results.append(
        check("pass" if has_label else "fail", "ui_label", "ScoreLabel found" if has_label else "ScoreLabel missing")
    )

    # 12. ScoreLabel text contains "Score" and "0"
    try:
        props = await _godot_ai_call("node_get_properties", {"path": "/Main/Arena/UI/ScoreLabel"})
        pdata = props.get("data", props)
        plist = pdata.get("properties", pdata)
        if isinstance(plist, list):
            plist = {x.get("name"): x.get("value") for x in plist if isinstance(x, dict)}
        text = str(plist.get("text", ""))
        text_ok = "Score" in text and "0" in text
        results.append(
            check(
                "pass" if text_ok else "fail",
                "score_text",
                f"Label text = '{text}'" + (" (ok)" if text_ok else " (expected 'Score: 0')"),
            )
        )
    except Exception:
        results.append(check("error", "score_text", "Property fetch failed"))

    # 13. No duplicate cameras
    cam_count = sum(1 for p, n in snapshot.items() if n.get("type") == "Camera3D")
    results.append(
        check(
            "pass" if cam_count <= 2 else "fail",
            "no_dup_cameras",
            f"{cam_count} Camera3D nodes" + (" (ok)" if cam_count <= 2 else " TOO MANY"),
        )
    )

    # 14. No scene pollution — allow the completeness injector's auto-added nodes
    known = {
        "root",
        "Main",
        "Camera3D",
        "DirectionalLight3D",
        "World",
        "Ground",
        "Arena",
        "DirectionalLight",
        "MainCamera",
    }
    unexpected = []
    for p in snapshot:
        name = snapshot[p].get("name", "")
        if name not in known and not p.startswith("/Main/Arena/"):
            unexpected.append(f"{p}({snapshot[p].get('type', '?')})")
    results.append(
        check(
            "pass" if not unexpected else "fail",
            "no_pollution",
            "Clean scene" if not unexpected else f"Unexpected: {unexpected[:5]}",
        )
    )

    # 15. Pipeline errors
    errors = artifact.get("errors", [])
    error_count = artifact.get("error_count", len(errors))
    results.append(
        check(
            "pass" if error_count == 0 else "fail",
            "no_errors",
            f"{error_count} pipeline errors" if error_count > 0 else "Zero pipeline errors",
        )
    )

    return results


# ── Runtime assertions (run after starting the game) ─────────────


async def _run_runtime_assertions(emit: Callable[[str], None], files: list | None = None) -> list[dict]:
    """Verify the game boots and the GENERATED scripts implement the request.

    We check the artifact's own generated `.gd` content rather than reading
    fixed res:// paths: the model names scripts freely (e.g. playermovement.gd,
    not player_movement.gd), so a hardcoded path used to miss every time AND
    surface as an opaque 'unhandled errors in a TaskGroup'. FPS is polled (the
    editor monitor often reads 0 even while the game runs).
    """
    results: list[dict] = []
    files = files or []

    def check(status: str, label: str, msg: str) -> dict:
        return {"status": status, "assertion": label, "message": msg}

    # All generated GDScript concatenated, for intent checks.
    scripts = [f for f in files if isinstance(f, dict) and str(f.get("path", "")).endswith(".gd")]
    code = "\n".join(str(f.get("content", "")) for f in scripts)

    def has(*subs) -> bool:
        return any(s in code for s in subs)

    # 1. Launch the disposable scene from DISK (autosave=False never touches the
    # real game) and poll for FPS / capture readiness.
    emit("  launching game...")
    fps = 0
    capture = False
    launched = False
    try:
        await _godot_ai_call(
            "project_run",
            {
                "mode": "custom",
                "scene": SHOOTOUT_SCENE,
                "autosave": False,
            },
        )
        launched = True
        for _ in range(6):  # ~9s
            await asyncio.sleep(1.5)
            try:
                st = await _godot_ai_call("editor_state", {})
                capture = bool(st.get("game_capture_ready"))
            except Exception:
                pass
            try:
                mon = await _godot_ai_call(
                    "editor_manage", {"op": "monitors_get", "params": {"monitors": ["time/fps"]}}
                )
                md = mon.get("data", mon)
                if isinstance(md, dict):
                    fps = md.get("time/fps", 0) or 0
            except Exception:
                pass
            if fps and fps > 0:
                break
    except Exception as e:
        results.append(check("error", "game_runs", f"failed to launch: {e}"))
    finally:
        try:
            await _godot_ai_call("project_manage", {"op": "stop"})
        except Exception:
            pass
    if launched:
        # Credit a clean launch even when the FPS monitor reads 0 (a known
        # editor capture quirk) — don't false-fail every model on it.
        game_ok = bool(fps and fps > 0) or capture
        results.append(
            check(
                "pass" if game_ok else "fail",
                "game_runs",
                f"FPS={fps}"
                + (" (running)" if fps else (" (launched, capture ready)" if capture else " (launched, FPS unread)")),
            )
        )

    # 2-7. Generated-script intent checks (across ALL generated .gd files).
    results.append(
        check(
            "pass" if scripts else "fail",
            "scripts_created",
            f"{len(scripts)} script(s) generated" if scripts else "no scripts generated",
        )
    )
    results.append(
        check(
            "pass" if "_process" in code or "_physics_process" in code else "fail",
            "movement_process",
            "_process present" if "_process" in code else "_process NOT found",
        )
    )
    results.append(
        check(
            "pass" if has("Input.", "get_vector", "is_key_pressed") else "fail",
            "movement_input",
            "input handling present" if has("Input.", "get_vector", "is_key_pressed") else "no Input calls",
        )
    )
    results.append(
        check(
            "pass" if has("body_entered", "_on_body") else "fail",
            "collect_handler",
            "body_entered handler present" if has("body_entered", "_on_body") else "no signal handler",
        )
    )
    results.append(
        check(
            "pass" if "queue_free" in code else "fail",
            "collect_qfree",
            "queue_free present" if "queue_free" in code else "queue_free NOT found",
        )
    )
    results.append(
        check(
            "pass" if has("ScoreLabel") or "score" in code.lower() else "fail",
            "collect_score",
            "score tracking present" if (has("ScoreLabel") or "score" in code.lower()) else "no score tracking",
        )
    )

    return results


# ── Cleanup ──────────────────────────────────────────────────────


async def _write_baseline_scene() -> None:
    """Rewrite SHOOTOUT_SCENE to the canonical baseline on disk.

    Idempotent overwrite — guarantees a pristine base scene every run no
    matter what a previous run (or project_run autosave) left behind.
    Goes through the editor's filesystem so it triggers a rescan.
    """
    await _godot_ai_call(
        "filesystem_manage",
        {
            "op": "write_text",
            "params": {"path": SHOOTOUT_SCENE, "content": SHOOTOUT_SCENE_TSCN},
        },
    )


async def _open_fresh(scene: str = SHOOTOUT_SCENE) -> None:
    """Open `scene` with a forced disk re-read.

    scene_open is a no-op when the target is already the active scene (it
    preserves unsaved in-memory mutations), so we bounce through BASE_SCENE
    first to discard any model edits and re-read `scene` clean from disk.
    """
    bounce = BASE_SCENE if scene != BASE_SCENE else SHOOTOUT_SCENE
    try:
        await _godot_ai_call("scene_open", {"path": bounce})
    except Exception:
        pass
    await _godot_ai_call("scene_open", {"path": scene})


async def _reset_scene() -> None:
    """Reset to a pristine shootout scene: rewrite baseline + fresh open."""
    await _write_baseline_scene()
    await _open_fresh(SHOOTOUT_SCENE)


async def _with_heartbeat(coro, emit: Callable[[str], None], label: str, interval: float = 4.0):
    """Await `coro` while emitting an elapsed-time heartbeat.

    The long, silent phases (model swap, the 40s+ planner inside apply_spec)
    used to look frozen — no output for tens of seconds. This ticks every
    `interval` seconds so the UI shows continuous "still working (Ns)" signal.
    """
    t0 = time.time()
    task = asyncio.ensure_future(coro)
    while True:
        done, _ = await asyncio.wait({task}, timeout=interval)
        if done:
            break
        emit(f"  …{label} still running ({int(time.time() - t0)}s)")
    return await task


# ── Failure attribution ──────────────────────────────────────────


def _attribute_failures(
    static_results: list[dict], runtime_results: list[dict], arch_delta: dict, operations: list, files: list
) -> list[dict]:
    """Cross-reference failed assertions against pipeline artifact to
    attribute each failure to a pipeline stage (plan / compile / execute).

    Returns a list of {assertion, stage, reason} dicts for every failure.
    """
    attributions: list[dict] = []
    all_assertions = static_results + runtime_results
    failures = [a for a in all_assertions if a.get("status") not in ("pass", "skip")]

    delta_entities = {e.get("name"): e for e in arch_delta.get("entities", []) if isinstance(e, dict)}
    delta_systems = {s.get("name"): s for s in arch_delta.get("systems", []) if isinstance(s, dict)}

    for a in failures:
        assertion_id = a.get("assertion", "")
        stage = "unknown"
        reason = ""

        if assertion_id in ("coins_collision", "coins_mesh"):
            if not delta_entities:
                stage, reason = "plan", "planner produced NO entities at all"
            elif not any(name.startswith("Coin_") for name in delta_entities):
                stage, reason = "plan", "planner did not include any Coin_* entities"
            else:
                stage, reason = "compile", "planner had coins but child nodes may be missing"

        elif assertion_id.startswith("coin_") and not assertion_id.startswith("coins_"):
            coin = assertion_id.removeprefix("coin_").removesuffix("_exists").removesuffix("_type")
            if not delta_entities:
                stage, reason = "plan", "planner produced NO entities at all"
            elif coin.capitalize() not in delta_entities:
                stage, reason = "plan", f"planner did not include {coin} in entities: {sorted(delta_entities)}"
            elif not any(
                o.get("type") == "add_node" and coin.capitalize() in str(o.get("name", "")) for o in operations
            ):
                stage, reason = "compile", f"planner had {coin} but compiler produced no add_node for it"
            else:
                stage, reason = "execute", f"node was compiled but may have failed to execute"

        elif assertion_id == "player_type":
            e = delta_entities.get("Player", {})
            if not e:
                stage, reason = "plan", "planner did not include Player entity"
            elif e.get("type") != "MeshInstance3D":
                stage, reason = "plan", f"planner gave Player type={e.get('type')}, expected MeshInstance3D"
            else:
                stage, reason = "compile", "planner had correct type but compiler may have changed it"

        elif assertion_id == "player_mesh":
            e = delta_entities.get("Player", {})
            if not e:
                stage, reason = "plan", "planner did not include Player"
            elif not e.get("props", {}).get("mesh"):
                stage, reason = "plan", "planner did not set mesh prop on Player"
            else:
                stage, reason = "compile", "planner set mesh but compiler didn't emit SetPropertyStep"

        elif assertion_id in ("player_script", "player_camera"):
            if not delta_systems and not delta_entities.get("Player"):
                stage, reason = "plan", "planner produced no entities/systems"
            elif assertion_id == "player_camera" and "PlayerCamera" not in delta_entities:
                stage, reason = "plan", "planner did not include PlayerCamera entity"
            elif assertion_id == "player_script":
                movement_systems = [
                    s
                    for n, s in delta_systems.items()
                    if any(kw in n.lower() for kw in ("movement", "player", "input"))
                ]
                if not movement_systems:
                    stage, reason = "plan", "planner did not create a movement/player system"
                elif not files:
                    stage, reason = "compile", "planner had system but no scripts were generated"
                else:
                    stage, reason = "execute", "script was created but may not have attached"

        elif assertion_id == "arena_exists":
            if not delta_entities:
                stage, reason = "plan", "planner produced NO entities"
            elif "Arena" not in delta_entities:
                stage, reason = "plan", "planner did not include Arena entity"
            else:
                stage, reason = "execute", "Arena was planned but did not appear in scene"

        elif assertion_id == "ui_canvas" or assertion_id == "ui_label":
            if "UI" not in delta_entities:
                stage, reason = "plan", "planner did not include UI entity"
            elif assertion_id == "ui_label" and "ScoreLabel" not in delta_entities:
                stage, reason = "plan", "planner did not include ScoreLabel"
            else:
                stage, reason = "execute", "UI nodes were planned but not created"

        elif assertion_id == "score_text":
            if "ScoreLabel" not in delta_entities:
                stage, reason = "plan", "planner did not include ScoreLabel"
            elif not (delta_entities.get("ScoreLabel", {}).get("props", {}).get("text")):
                stage, reason = "plan", "planner did not set text prop on ScoreLabel"
            else:
                stage, reason = "execute", "ScoreLabel text was planned but property not set in editor"

        elif assertion_id in ("movement_process", "movement_input"):
            if not any(f for f in files if isinstance(f, dict) and str(f.get("path", "")).endswith(".gd")):
                stage, reason = "compile", "no GDScript files were generated at all"
            else:
                stage, reason = "compile", f"scripts exist but missing {assertion_id} content"

        elif assertion_id in ("collect_handler", "collect_qfree", "collect_score"):
            if not any(f for f in files if isinstance(f, dict) and "collect" in str(f.get("path", "")).lower()):
                stage, reason = "compile", "no collectible script was generated"
            else:
                stage, reason = "compile", f"collectible script exists but missing {assertion_id} content"

        elif assertion_id == "no_pollution":
            stage, reason = "completeness", "completeness checker injected unexpected nodes"

        elif assertion_id == "no_errors":
            stage, reason = "pipeline", "pipeline errors (see raw_apply_spec.errors)"

        elif assertion_id == "game_runs":
            stage, reason = "runtime", "game failed to launch or FPS unreadable"

        elif assertion_id == "scripts_created":
            stage, reason = "compile", "no scripts were generated"

        if reason:
            attributions.append(
                {
                    "assertion": assertion_id,
                    "stage": stage,
                    "reason": reason,
                }
            )

    return attributions


# ── Single model test ────────────────────────────────────────────


async def _test_one_model(m: dict, emit: Callable[[str], None], swap: bool = True, planner_mode: str = "arch") -> dict:
    """Run the full test against one model. Returns result dict."""
    alias = m["alias"]
    label = m["label"]

    model_result: dict = {
        "model_alias": alias,
        "model_label": label,
        "planner_mode": planner_mode,
        "status": "error",
        "static_assertions": [],
        "runtime_assertions": [],
        "static_score": 0,
        "runtime_score": 0,
        "total_score": 0,
        "max_score": 100,
        "ms_total": 0,
        "errors": [],
        "raw_apply_spec": None,
        "raw_artifact": None,
        "scene_before": None,
        "scene_after": None,
        # Pipeline diagnostics from artifact
        "plan_retries": 0,
        "repair_count": 0,
        "completeness_added": 0,
        "stage_latencies": {},
        "failure_attribution": [],  # cross-reference per failing assertion
    }
    t_model = time.time()

    _log_write(f"START: {label} ({alias})")

    try:
        if swap:
            _log_write(f"  swap: starting...")
            if not await _swap_model(alias, emit):
                _log_write(f"  swap: FAILED — model never tested")
                model_result["errors"].append("swap failed — model was not tested")
                # 'untested' is NOT 'scored 0' — exclude it from rankings so a
                # harness/VRAM swap failure can't masquerade as a model that
                # built nothing.
                model_result["status"] = "untested"
                return model_result
            _log_write(f"  swap: OK")

        _log_write(f"  reset: pristine shootout scene")
        await _reset_scene()

        # Capture scene before
        try:
            snap_before = await _get_scene_snapshot()
            model_result["scene_before"] = {p: n.get("type", "?") for p, n in snap_before.items()}
            _log_write(f"  scene_before: {len(snap_before)} nodes")
        except Exception as e:
            _log_error(e, "scene_before snapshot")

        # apply_spec
        emit("[shootout:phase] apply_spec")
        emit(f"  applying spec...")
        _log_write(f"  apply_spec: sending prompt ({len(SHOOTOUT_PROMPT)} chars)...")
        try:
            raw = await _with_heartbeat(
                _devforge_call(
                    "apply_spec",
                    {
                        "prompt": SHOOTOUT_PROMPT,
                    },
                    timeout_s=300,
                ),
                emit,
                "apply_spec (planning + executing)",
            )
            _log_write(f"  apply_spec: raw response received, keys={list(raw.keys())[:10]}")
            model_result["raw_apply_spec"] = _safe_serialize(raw)
            artifact = raw
            artifact_id = raw.get("artifact_id", "")
            if artifact_id:
                _log_write(f"  apply_spec: reading artifact {artifact_id}")
                try:
                    artifact = await _devforge_call(
                        "read_artifact",
                        {
                            "artifact_id": artifact_id,
                        },
                        timeout_s=30,
                    )
                    model_result["raw_artifact"] = _safe_serialize(artifact)
                    _log_write(f"  apply_spec: artifact loaded, keys={list(artifact.keys())[:10]}")
                except Exception as e2:
                    _log_error(e2, "read_artifact")
                    artifact = raw
            else:
                _log_write(f"  apply_spec: NO artifact_id in response — model may have returned no plan")
        except Exception as e:
            _log_error(e, "apply_spec")
            model_result["errors"].append(f"apply_spec failed: {type(e).__name__}: {e}")
            model_result["status"] = "error"
            return model_result  # outer finally resets the scene

        error_count = artifact.get("error_count", len(artifact.get("errors", [])))
        applied_count = artifact.get("applied_count", artifact.get("applied", "?"))
        op_count = len(artifact.get("operations", []))
        # Capture pipeline diagnostics from artifact
        model_result["plan_retries"] = artifact.get("plan_retries", 0)
        model_result["repair_count"] = artifact.get("repair_count", 0)
        model_result["completeness_added"] = artifact.get("completeness_added", 0)
        model_result["stage_latencies"] = artifact.get("stage_latencies", {})
        _log_write(f"  apply_spec: done — applied={applied_count}, ops={op_count}, errors={error_count}")
        _log_write(
            f"  diagnostics: plan_retries={model_result['plan_retries']}, "
            f"repair={model_result['repair_count']}, "
            f"completeness_added={model_result['completeness_added']}"
        )
        emit(f"  apply_spec done — {applied_count} applied, {op_count} ops, {error_count} errors")

        # Capture scene after
        try:
            snap_after = await _get_scene_snapshot()
            model_result["scene_after"] = {p: n.get("type", "?") for p, n in snap_after.items()}
            _log_write(f"  scene_after: {len(snap_after)} nodes")
        except Exception as e:
            _log_error(e, "scene_after snapshot")

        # static assertions
        emit("[shootout:phase] static_assertions")
        emit(f"  static assertions...")
        _log_write(f"  static: running {23} checks...")
        static_results = await _run_static_assertions(artifact)
        model_result["static_assertions"] = static_results
        static_pass = sum(1 for a in static_results if a["status"] == "pass")
        static_fail = sum(1 for a in static_results if a["status"] == "fail")
        static_err = sum(1 for a in static_results if a["status"] == "error")
        static_total = len(static_results)
        model_result["static_score"] = round(static_pass / max(static_total, 1) * 68)
        _log_write(f"  static: {static_pass}p/{static_fail}f/{static_err}e = {model_result['static_score']}/68")
        for a in static_results:
            if a["status"] != "pass":
                _log_write(f"    [{a['status']}] {a['assertion']}: {a['message']}")
        emit(f"  static: {static_pass}/{static_total} pass ({model_result['static_score']}/68)")

        # runtime assertions
        emit("[shootout:phase] runtime_assertions")
        emit(f"  runtime assertions...")
        _log_write(f"  runtime: running checks...")
        runtime_results = await _run_runtime_assertions(emit, files=artifact.get("files", []))
        model_result["runtime_assertions"] = runtime_results
        runtime_pass = sum(1 for a in runtime_results if a["status"] == "pass")
        runtime_fail = sum(1 for a in runtime_results if a["status"] == "fail")
        runtime_err = sum(1 for a in runtime_results if a["status"] == "error")
        runtime_total = len(runtime_results)
        model_result["runtime_score"] = round(runtime_pass / max(runtime_total, 1) * 32)
        _log_write(f"  runtime: {runtime_pass}p/{runtime_fail}f/{runtime_err}e = {model_result['runtime_score']}/32")
        for a in runtime_results:
            if a["status"] != "pass":
                _log_write(f"    [{a['status']}] {a['assertion']}: {a['message']}")
        emit(f"  runtime: {runtime_pass}/{runtime_total} pass ({model_result['runtime_score']}/32)")

        model_result["total_score"] = model_result["static_score"] + model_result["runtime_score"]
        model_result["status"] = (
            "pass" if model_result["total_score"] >= 60 else ("fail" if model_result["total_score"] >= 30 else "error")
        )

        # Cross-reference failures against pipeline artifact for attribution
        delta = artifact.get("arch_delta", {}) or {}
        model_result["failure_attribution"] = _attribute_failures(
            static_results, runtime_results, delta, artifact.get("operations", []), artifact.get("files", [])
        )

    except Exception as e:
        _log_error(e, f"shootout crashed for {label}")
        model_result["errors"].append(f"shootout crashed: {type(e).__name__}: {e}")
        model_result["status"] = "error"

    finally:
        _log_write(f"  reset: restoring pristine shootout scene")
        await _reset_scene()
        model_result["ms_total"] = int((time.time() - t_model) * 1000)
        _log_write(
            f"  DONE: [{model_result['status']}] score={model_result['total_score']}/100 ({model_result['ms_total']}ms)"
        )
        emit(f"  [{model_result['status']}] score={model_result['total_score']}/100 ({model_result['ms_total']}ms)")

    return model_result


# ── Shootout runner ──────────────────────────────────────────────


async def run_shootout(
    emit: Callable[[str], None] | None = None,
    model_filter: str | None = None,
    skip_preflight: bool = False,
    all_planners: bool = False,
) -> dict:
    """Run the full shootout against all (or one) available models.

    Args:
        emit: Progress callback
        model_filter: Optional alias fragment to run a single model
        skip_preflight: Skip pre-flight checks
        all_planners: Run each model through both arch and ops planner modes

    Returns a composite scorecard with per-model results + rankings.
    """

    def log(msg: str) -> None:
        if emit:
            emit(msg)

    ts = time.strftime("%Y%m%d-%H%M%S")
    _log_open(ts)

    def log(msg: str) -> None:
        _log_write(msg)
        if emit:
            emit(msg)

    if all_planners:
        log("=== FORGE MODEL SHOOTOUT (A/B: arch + ops planner) ===")
    else:
        log("=== FORGE MODEL SHOOTOUT ===")
    log(f"Scene: {SHOOTOUT_SCENE}")

    # Pre-flight checks
    if not skip_preflight:
        pf = await preflight_check(emit)
        if not pf["ok"]:
            log("\n❌ Pre-flight checks failed — aborting")
            return {"error": "preflight failed", "preflight": pf}

    models = await _resolve_models(model_filter)
    total = len(models)
    log(f"Models to test: {total}")
    if not models:
        log("No models available — aborting")
        return {"error": "no models available", "models_tested": 0}

    for m in models:
        log(f"  • {m['label']} ({m['alias']})")

    results: list[dict] = []
    t_start = time.time()
    out = SHOOTOUT_DIR / f"shootout-{ts}.json"

    def _build_scorecard(done: bool) -> dict:
        # Rank only models that actually ran; list untested ones separately so a
        # swap/VRAM failure never appears as a 0-score competitor.
        tested = [r for r in results if r["status"] != "untested"]
        untested = [r["model_alias"] for r in results if r["status"] == "untested"]
        ranked = sorted(tested, key=lambda r: r["total_score"], reverse=True)
        regression_flags = _detect_regressions(ranked)
        planner_comparison = _compare_planners(results) if all_planners else None
        return {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "log_ts": ts,
            "scene": SHOOTOUT_SCENE,
            "model_filter": model_filter,
            # Live progress so a partial/aborted run is still interpretable.
            "status": "complete" if done else "running",
            "models_planned": total,
            "models_done": len(results),
            "models_tested": len([r for r in results if r.get("static_assertions")]),
            "untested": untested,
            "total_ms": int((time.time() - t_start) * 1000),
            "results": results,
            "all_planners": all_planners,
            "planner_comparison": planner_comparison,
            "regression_flags": regression_flags,
            "rankings": [
                {
                    "rank": i + 1,
                    "model": r["model_label"],
                    "alias": r["model_alias"],
                    "score": r["total_score"],
                    "status": r["status"],
                    "planner_mode": r.get("planner_mode", "arch"),
                }
                for i, r in enumerate(ranked)
            ],
        }

    def _persist(done: bool) -> dict:
        """Write the scorecard to disk NOW so output always exists, even if a
        later model hangs or the run is killed mid-way."""
        card = _build_scorecard(done)
        out.write_text(json.dumps(card, indent=2))
        return card

    # Write an initial (empty) scorecard up-front: the output file exists from
    # the very first second, so there is always something to inspect.
    _persist(done=False)

    for i, m in enumerate(models):
        alias = m["alias"]
        label = m["label"]

        log(f"\n── [{i + 1}/{total}] {label} ({alias}) ──")
        log(f"[shootout:model] {i + 1}/{total} {label}")

        planner_modes = ["arch", "ops"] if all_planners else ["arch"]
        needs_swap = True
        for pmode in planner_modes:
            swap_needed = needs_swap and (pmode == "arch")
            if pmode == "ops":
                log(f"  ── switching to ops planner ──")
                _set_planner_mode("ops")
                if not await _restart_devforge(emit):
                    log(f"  [shootout:error] DevForge restart failed for {pmode} planner")
                    r = {
                        "model_alias": alias,
                        "model_label": label,
                        "planner_mode": "ops",
                        "status": "untested",
                        "errors": ["DevForge restart failed for ops planner"],
                        "total_score": 0,
                        "max_score": 100,
                    }
                    results.append(r)
                    _persist(done=False)
                    continue
                log(f"  ops planner active — running test")

            r = await _test_one_model(m, emit, swap=swap_needed, planner_mode=pmode)
            results.append(r)
            _persist(done=False)  # checkpoint after every model/planner
            log(f"[shootout:scored] {i + 1}/{total} {label} [{pmode}] = {r['total_score']}/100 ({r['status']})")

        # Restore arch planner default after ops run
        if all_planners:
            _set_planner_mode("")
            await _restart_devforge(emit)
            log(f"  restored arch planner default")

    # Leave the editor on the user's real game scene, not our throwaway.
    try:
        await _open_fresh(BASE_SCENE)
        log(f"restored editor scene → {BASE_SCENE}")
    except Exception as e:
        log(f"⚠ could not restore {BASE_SCENE}: {e}")

    scorecard = _persist(done=True)
    log("[shootout:done]")
    log(f"\n→ saved {out.name}")
    log(f"Total: {scorecard['total_ms'] / 1000:.0f}s for {scorecard['models_tested']} models")

    return scorecard


# ── Regression detection ──────────────────────────────────────


def _detect_regressions(results: list[dict]) -> list[dict]:
    """Detect models that regressed vs their previous best score.

    Compares each model's total_score against its best score in all
    previous shootouts. Flags any model that dropped more than 10 points.
    """
    regressions: list[dict] = []
    previous_shootouts = list_shootouts()
    # Build per-alias best across all previous shootouts
    best_prev: dict[str, tuple[int, str]] = {}  # alias -> (best_score, ts)
    for ps in previous_shootouts:
        for r in ps.get("rankings", []):
            alias = r.get("alias", "")
            score = r.get("score", 0)
            if alias and score > best_prev.get(alias, (0, ""))[0]:
                best_prev[alias] = (score, ps.get("ts", "?"))

    for r in results:
        alias = r.get("model_alias", "")
        if not alias or r.get("status") == "untested":
            continue
        current = r.get("total_score", 0)
        prev_best, prev_ts = best_prev.get(alias, (0, ""))
        if prev_best == 0:
            continue  # no previous data — can't detect regression
        delta = current - prev_best
        if delta < -10:
            regressions.append(
                {
                    "model": r.get("model_label", alias),
                    "alias": alias,
                    "planner_mode": r.get("planner_mode", "arch"),
                    "current_score": current,
                    "previous_best": prev_best,
                    "previous_ts": prev_ts,
                    "delta": delta,
                }
            )
    return regressions


def _compare_planners(results: list[dict]) -> dict | None:
    """Side-by-side comparison of arch vs ops planner results per model."""
    arch_results = {r["model_alias"]: r for r in results if r.get("planner_mode") == "arch"}
    ops_results = {r["model_alias"]: r for r in results if r.get("planner_mode") == "ops"}
    if not ops_results:
        return None
    rows: list[dict] = []
    for alias in sorted(set(arch_results) | set(ops_results)):
        arch = arch_results.get(alias, {})
        ops = ops_results.get(alias, {})
        arch_score = arch.get("total_score", 0)
        ops_score = ops.get("total_score", 0)
        delta = ops_score - arch_score
        rows.append(
            {
                "model_alias": alias,
                "model_label": arch.get("model_label", ops.get("model_label", alias)),
                "arch_score": arch_score,
                "ops_score": ops_score,
                "delta": delta,
                "winner": "arch" if delta < 0 else ("ops" if delta > 0 else "tie"),
            }
        )
    return {
        "rows": rows,
        "summary": f"arch avg: {sum(r['arch_score'] for r in rows) / max(len(rows), 1):.0f}, "
        f"ops avg: {sum(r['ops_score'] for r in rows) / max(len(rows), 1):.0f}",
    }


# ── Safe serialization helper ────────────────────────────────────

MAX_LOG_VALUE_LEN = 2000


def _safe_serialize(obj: Any, depth: int = 0) -> Any:
    """Serialize an object for storage in scorecard JSON, truncating large values."""
    if depth > 4:
        return "<max depth>"
    if isinstance(obj, dict):
        return {str(k)[:200]: _safe_serialize(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_serialize(v, depth + 1) for v in obj[:50]]
    if isinstance(obj, str) and len(obj) > MAX_LOG_VALUE_LEN:
        return obj[:MAX_LOG_VALUE_LEN] + f"... <truncated, {len(obj)} chars total>"
    if isinstance(obj, (int, float, bool, type(None))):
        return obj
    return str(obj)[:MAX_LOG_VALUE_LEN]


# ── Scorecard management ─────────────────────────────────────────


def list_shootouts() -> list[dict]:
    """Return all saved shootout scorecards."""
    cards = []
    for f in sorted(SHOOTOUT_DIR.glob("shootout-*.json"), reverse=True):
        try:
            d = json.loads(f.read_text())
            cards.append(
                {
                    "file": f.name,
                    "ts": d.get("ts"),
                    "log_ts": d.get("log_ts"),
                    "models_tested": d.get("models_tested"),
                    "rankings": d.get("rankings", []),
                }
            )
        except Exception:
            continue
    return cards


def get_latest_shootout() -> dict | None:
    """Return the most recent shootout scorecard."""
    cards = list_shootouts()
    if not cards:
        return None
    fp = SHOOTOUT_DIR / cards[0]["file"]
    try:
        return json.loads(fp.read_text())
    except Exception:
        return None


# ── CLI entry point ──────────────────────────────────────────────


def _cli_emit(line: str) -> None:
    print(line)


def main() -> None:
    """CLI entry point for standalone shootout runs."""
    args = sys.argv[1:]

    if not args or "--list" in args:
        cards = list_shootouts()
        if cards:
            print(f"Past shootouts ({len(cards)}):")
            for c in cards[:10]:
                top = c["rankings"][0] if c["rankings"] else {"model": "?", "score": "?"}
                print(
                    f"  {c['file']:30s}  {c['ts']}  {c['models_tested']} models  🥇 {top['model']} ({top['score']}/100)"
                )
        else:
            print("No past shootouts found.")
            print("\nAvailable models:")
            for m in MODELS_TO_TEST:
                print(f"  {m['label']:25s}  {m['alias']}")
            print("\nRun: python shootout.py --all     # test all models")
            print("     python shootout.py --model X  # test one model")
        return

    if "--last" in args:
        latest = get_latest_shootout()
        if latest:
            print(json.dumps(latest, indent=2))
        else:
            print("No past shootouts.")
        return

    if "--check" in args:
        asyncio.run(preflight_check(_cli_emit))
        return

    model_filter = None
    for i, arg in enumerate(args):
        if arg == "--model" and i + 1 < len(args):
            model_filter = args[i + 1]

    if "--all" in args or model_filter or "--all-planners" in args:
        all_planners = "--all-planners" in args
        label = model_filter or "all models"
        if all_planners:
            label += " (arch + ops planner)"
        print(f"Starting shootout: {label}")
        print("Make sure Godot editor is open with the test_project and shootout.tscn is loaded.\n")
        asyncio.run(run_shootout(_cli_emit, model_filter=model_filter, all_planners=all_planners))
    else:
        print("Usage: python shootout.py [--all | --all-planners | --model <fragment> | --list | --last | --check]")
        print("\nAvailable models:")
        for m in MODELS_TO_TEST:
            print(f"  {m['label']:25s}  {m['alias']}")


if __name__ == "__main__":
    main()
