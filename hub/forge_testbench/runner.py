"""Runner — the unified test engine.

One code path for single model, multi-model, and repeat-N runs.
Owns completion (never snapshots mid-run), is crash-resilient (a
crash marks status and continues), uses the proven transactional swap.

Properties that retire specific past bugs:
  - Owns completion → never snapshots a job mid-run (gauntlet bug).
  - Resilient → timeout/crash marks status, never aborts the sweep.
  - One swap path → transactional swap with VRAM pre-flight.
  - skip_cache honoured per test → variety tests run uncached.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable, Awaitable, Any

import httpx

from .context import Context
from .result import Result, Status
from .artifact import Artifact
from .catalog import get_suites

HOME = Path.home()
ENVFILE = HOME / ".config/forge-stack/stack.env"


def _read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        for line in ENVFILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


async def _sh(*cmd: str, timeout: float = 30.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"timeout after {timeout}s"
    return proc.returncode or 0, raw.decode(errors="replace")


# ── MCP helpers (wired into Context) ────────────────────────────

async def _godot_ai_call(tool: str, args: dict | None = None) -> Any:
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    async with streamablehttp_client("http://127.0.0.1:8000/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if tool == "__list__":
                return await s.list_tools()
            res = await s.call_tool(tool, args or {})
            return __import__("json").loads(res.content[0].text)


async def _devforge_call(
    prompt: str,
    planner: str = "",
    temperature: float = 0.2,
    skip_cache: bool = False,
    timeout_s: int = 300,
) -> dict:
    from datetime import timedelta
    from mcp.client.sse import sse_client
    from mcp import ClientSession

    async with sse_client("http://127.0.0.1:8001/sse", timeout=10,
                          sse_read_timeout=timeout_s + 30) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            args: dict = {"prompt": prompt, "temperature": temperature}
            if planner:
                args["planner"] = planner
            if skip_cache:
                args["skip_cache"] = True
            res = await s.call_tool(
                "apply_spec", args,
                read_timeout_seconds=timedelta(seconds=timeout_s),
            )
            return __import__("json").loads(res.content[0].text)


async def _read_artifact(artifact_id: str, timeout_s: int = 30) -> dict:
    from datetime import timedelta
    from mcp.client.sse import sse_client
    from mcp import ClientSession

    async with sse_client("http://127.0.0.1:8001/sse", timeout=10,
                          sse_read_timeout=timeout_s + 30) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(
                "read_artifact", {"artifact_id": artifact_id},
                read_timeout_seconds=timedelta(seconds=timeout_s),
            )
            return __import__("json").loads(res.content[0].text)


async def _devforge_raw_call(tool: str, args: dict, timeout_s: int = 60) -> dict:
    """Call any DevForge MCP tool generically."""
    from datetime import timedelta
    from mcp.client.sse import sse_client
    from mcp import ClientSession

    async with sse_client("http://127.0.0.1:8001/sse", timeout=10,
                          sse_read_timeout=timeout_s + 30) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(
                tool, args,
                read_timeout_seconds=timedelta(seconds=timeout_s),
            )
            return __import__("json").loads(res.content[0].text)


# ── Scene helpers ───────────────────────────────────────────────

# Bare probe scene: root + Camera3D + DirectionalLight3D — a "complete" 3D
# scene so completeness injects nothing and tests start from a known state.
PROBE_SCENE = "res://probe.tscn"
PROBE_BOUNCE_SCENE = "res://probe_bounce.tscn"
PROBE_BASE_SCENE = "res://scenes/main.tscn"
_PROBE_BASELINE = {"Main", "MainCamera", "DirectionalLight"}


async def _scene_reset() -> None:
    """Reset to a pristine disposable probe scene via the bounce trick.

    Godot keeps opened scenes in tabs with unsaved in-memory nodes. A direct
    scene_open on the active scene is a no-op. Opening a DIFFERENT scene first
    forces a real disk reload — the "bounce trick" from bench.py.
    """
    import uuid
    import json as _json

    # Fresh UIDs to bust the stale-tab cache
    bounce_uid = f"uid://cbounce{uuid.uuid4().hex[:12]}"
    probe_uid = f"uid://cprobe{uuid.uuid4().hex[:12]}"

    bounce_tscn = (
        f'[gd_scene format=3 uid="{bounce_uid}"]\n\n'
        '[node name="_bounce" type="Node3D"]\n'
    )
    probe_tscn = (
        f'[gd_scene format=3 uid="{probe_uid}"]\n\n'
        '[node name="Main" type="Node3D"]\n\n'
        '[node name="MainCamera" type="Camera3D" parent="."]\n'
        'transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 10)\n\n'
        '[node name="DirectionalLight" type="DirectionalLight3D" parent="."]\n'
        'transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 10, 0)\n'
    )

    try:
        await _godot_ai_call("filesystem_manage", {
            "op": "write_text",
            "params": {"path": PROBE_BOUNCE_SCENE, "content": bounce_tscn},
        })
        await _godot_ai_call("filesystem_manage", {
            "op": "write_text",
            "params": {"path": PROBE_SCENE, "content": probe_tscn},
        })
    except Exception:
        pass

    # Bounce
    try:
        await _godot_ai_call("scene_open", {"path": PROBE_BOUNCE_SCENE})
    except Exception:
        pass
    try:
        await _godot_ai_call("scene_open", {"path": PROBE_SCENE})
    except Exception:
        pass

    # Health check: confirm root is "Main" (not "Main2" from stale cache)
    try:
        h = await _godot_ai_call("scene_get_hierarchy", {"depth": 2})
        nodes = [n for n in h.get("nodes", []) if isinstance(n, dict)]
        roots = [n for n in nodes if n.get("path", "").count("/") == 1]
        if len(roots) != 1:
            raise RuntimeError(
                f"Probe health check FAILED: {len(roots)} roots found. "
                f"Close the probe.tscn tab in Godot and re-run."
            )
        root = roots[0]
        if root.get("name") != "Main":
            raise RuntimeError(
                f"Probe health check FAILED: root is '{root.get('name')}', "
                f"expected 'Main'. Close probe.tscn tab in Godot WITHOUT saving."
            )
        if root.get("type") != "Node3D":
            raise RuntimeError(
                f"Probe health check FAILED: root type is '{root.get('type')}', "
                f"expected 'Node3D'."
            )
        # Verify baseline children
        kids = [n for n in nodes
                if n.get("path", "").startswith(root["path"] + "/")
                and n.get("path", "").count("/") == 2]
        kid_names = {n.get("name") for n in kids}
        expected = _PROBE_BASELINE - {"Main"}
        missing = expected - kid_names
        if missing:
            raise RuntimeError(
                f"Probe health check FAILED: baseline nodes missing: {sorted(missing)}. "
                f"Present: {sorted(kid_names)}."
            )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(
            f"Probe health check FAILED: cannot read scene hierarchy: {e}"
        ) from e

    # Safety guard: confirm active scene is the probe
    try:
        st = await _godot_ai_call("editor_state", {})
        active = st.get("current_scene", "")
    except Exception:
        active = ""
    if active != PROBE_SCENE:
        raise RuntimeError(
            f"Probe reset ABORTED: active scene is '{active or '?'}', not "
            f"the disposable '{PROBE_SCENE}'. Refusing to modify a non-disposable scene."
        )

    # Clean non-baseline nodes
    try:
        h = await _godot_ai_call("scene_get_hierarchy", {"depth": 2})
        nodes = [n for n in h.get("nodes", []) if isinstance(n, dict)]
        roots = [n.get("path", "") for n in nodes if n.get("path", "").count("/") == 1]
        root_path = roots[0] if roots else "/Main"
        for n in nodes:
            path = n.get("path", "")
            if path.startswith(root_path + "/") and path.count("/") == 2 \
                    and n.get("name") not in _PROBE_BASELINE:
                try:
                    await _godot_ai_call("node_manage", {
                        "op": "delete", "params": {"path": path}})
                except Exception:
                    pass
    except Exception:
        pass


async def _scene_paths() -> set[str]:
    h = await _godot_ai_call("scene_get_hierarchy", {"depth": 10})
    return {n["path"] for n in h.get("nodes", []) if isinstance(n, dict) and n.get("path")}


async def _restore_main_scene() -> None:
    """Restore the editor to the real game scene after tests."""
    try:
        await _godot_ai_call("scene_open", {"path": PROBE_SCENE})
        await _godot_ai_call("scene_open", {"path": PROBE_BASE_SCENE})
    except Exception:
        pass


# ── Model swap ──────────────────────────────────────────────────

async def _swap_model(alias: str, emit: Callable[[str], None]) -> bool:
    """Transactional model swap. Returns True on success."""
    try:
        from forge_ops import swap_model as _transactional_swap
        emit(f"  swapping to {alias} (transactional: pre-flight + llama restart)...")
        code = await _transactional_swap(alias, emit)
        if code != 0:
            emit(f"  ✗ swap to {alias} failed (exit {code})")
            return False
        emit(f"  ✓ {alias} loaded and healthy")
        return True
    except Exception as exc:
        emit(f"  ✗ swap raised: {exc}")
        return False


# ── The Runner ──────────────────────────────────────────────────

class Runner:
    """Unified test runner. Handles single model, multi-model, and repeat-N."""

    def __init__(self, emit: Callable[[str], None] | None = None) -> None:
        self.emit = emit or (lambda s: None)

    def _log(self, msg: str) -> None:
        self.emit(msg)

    async def run(
        self,
        test_ids: list[str],
        models: list[str],
        *,
        repeat: int = 1,
        suite: str = "",
        dry: bool = False,
    ) -> Artifact:
        """Run tests across models with optional repeats.

        Args:
            test_ids: List of test ids to run.
            models: List of model aliases to sweep (single-element = single model).
            repeat: Number of times to run each repeatable test.
            suite: Suite name for the artifact.
            dry: If True, print what WOULD happen without executing.

        Returns:
            Artifact with all results.
        """
        from .catalog import CATALOG

        # Resolve test classes
        by_id: dict[str, type] = {t.id: t for t in CATALOG}
        test_classes = [by_id[tid] for tid in test_ids if tid in by_id]
        missing = [tid for tid in test_ids if tid not in by_id]
        if missing:
            self._log(f"⚠ Unknown test ids (skipping): {missing}")

        if not test_classes:
            self._log("No tests to run.")
            return Artifact(kind="single", suite=suite or "custom", models=models)

        self._log(f"═══ Forge Testbench ═══")
        self._log(f"Suite: {suite or 'custom'} | Models: {len(models)} | "
                  f"Tests: {len(test_classes)} | Repeat: {repeat}")
        self._log(f"Models: {', '.join(models)}")
        self._log(f"Tests: {', '.join(t.id for t in test_classes)}")
        self._log("")

        if dry:
            for model in models:
                self._log(f"[DRY] Model: {model}")
                for tc in test_classes:
                    n = repeat if tc.repeatable else 1
                    self._log(f"  [DRY]   {tc.id} ×{n}")
            return Artifact(kind="sweep" if len(models) > 1 else "single",
                           suite=suite or "custom", models=models)

        artifact = Artifact(
            kind="sweep" if len(models) > 1 else "single",
            suite=suite or "custom",
            models=models,
        )

        total_tests = sum(repeat if tc.repeatable else 1 for tc in test_classes)
        total_runs = total_tests * len(models)
        run_counter = 0

        for model in models:
            self._log(f"\n── Model: {model} ──")

            # Swap to model (skip first if already loaded)
            if len(models) > 1:
                ok = await _swap_model(model, self._log)
                if not ok:
                    self._log(f"  ✗ Skipping {model} — swap failed")
                    continue

            # Build context for this model
            env = _read_env()
            ctx = Context(
                model_alias=model,
                env=env,
                _apply_spec=lambda prompt, planner="", temperature=0.2,
                    skip_cache=False, timeout_s=300: _devforge_call(
                        prompt, planner=planner, temperature=temperature,
                        skip_cache=skip_cache, timeout_s=timeout_s),
                _read_artifact=_read_artifact,
                _devforge_raw=_devforge_raw_call,
                _godot_ai_call=_godot_ai_call,
                _llama=httpx.AsyncClient(timeout=httpx.Timeout(120)),
                _sh=_sh,
                data_dir="",
            )

            for tc in test_classes:
                test = tc()
                n = repeat if test.repeatable else 1
                ctx.skip_cache = test.skip_cache

                for run_i in range(1, n + 1):
                    run_counter += 1
                    self._log(f"\n▶ [{run_counter}/{total_runs}] "
                              f"{test.id} (run {run_i}/{n})")

                    t0 = time.time()

                    # Scene reset if needed
                    if test.needs_reset:
                        try:
                            await _scene_reset()
                        except RuntimeError as e:
                            self._log(f"  ✗ Scene reset failed: {e}")
                            artifact.add(Result(
                                test_id=test.id, category=test.category,
                                model=model, status="error",
                                suite=suite, ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                                run_index=run_i, repeat_count=n,
                                errors=[f"scene reset: {e}"],
                            ))
                            continue

                    # Run the test with timeout guard
                    try:
                        raw = await asyncio.wait_for(
                            test.run(ctx), timeout=test.timeout_s)
                    except asyncio.TimeoutError:
                        self._log(f"  ✗ Timeout after {test.timeout_s}s")
                        artifact.add(Result(
                            test_id=test.id, category=test.category,
                            model=model, status="error",
                            suite=suite, ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                            run_index=run_i, repeat_count=n,
                            errors=[f"timeout after {test.timeout_s}s"],
                            latency_ms=int((time.time() - t0) * 1000),
                        ))
                        continue
                    except Exception as e:
                        self._log(f"  ✗ Crashed: {type(e).__name__}: {e}")
                        artifact.add(Result(
                            test_id=test.id, category=test.category,
                            model=model, status="error",
                            suite=suite, ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                            run_index=run_i, repeat_count=n,
                            errors=[f"{type(e).__name__}: {e}"],
                            latency_ms=int((time.time() - t0) * 1000),
                        ))
                        continue

                    # Score (pure function)
                    try:
                        scored = test.score(raw)
                    except Exception as e:
                        self._log(f"  ✗ Scoring crashed: {type(e).__name__}: {e}")
                        artifact.add(Result(
                            test_id=test.id, category=test.category,
                            model=model, status="error",
                            suite=suite, ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                            run_index=run_i, repeat_count=n,
                            errors=[f"score(): {type(e).__name__}: {e}"],
                            latency_ms=int((time.time() - t0) * 1000),
                        ))
                        continue

                    latency_ms = int((time.time() - t0) * 1000)

                    # Handle expect_break inversion
                    status: Status = scored.status
                    if test.expect_break and status == "broke":
                        status = "ok"

                    result = Result(
                        test_id=test.id,
                        category=test.category,
                        model=model,
                        status=status,
                        suite=suite,
                        ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                        run_index=run_i,
                        repeat_count=n,
                        score=scored.score,
                        metrics=scored.metrics,
                        raw=scored.raw,
                        errors=scored.errors,
                        latency_ms=latency_ms,
                    )
                    artifact.add(result)

                    icon = {"ok": "✓", "partial": "~", "broke": "✗", "error": "✗"}
                    self._log(f"  [{icon.get(status, '?')} {status}] "
                              f"({latency_ms}ms) score={scored.score}")

        # Restore main scene
        await _restore_main_scene()

        # Persist
        out_dir = artifact.save()
        self._log(f"\n═══ Complete ═══")
        self._log(f"Results → {out_dir}/artifact.json")

        # Print summary
        summary_data = artifact.model_summary()
        for model, s in summary_data.items():
            c = s["counts"]
            self._log(f"  {model}: {c['ok']} ok / {c['partial']} partial / "
                      f"{c['broke']} broke / {c['error']} error  "
                      f"(avg score: {s['avg_score']})")

        return artifact


async def run(
    test_ids: list[str],
    models: list[str],
    *,
    repeat: int = 1,
    suite: str = "",
    dry: bool = False,
    emit: Callable[[str], None] | None = None,
) -> Artifact:
    """Convenience: create a Runner and run tests immediately."""
    r = Runner(emit=emit)
    return await r.run(test_ids, models, repeat=repeat, suite=suite, dry=dry)
