"""
forge_ops — transactional operations for the forge stack.

Implements the swap transaction (Phase 2), state reconciliation (Phase 3),
durable action log + failure classifier (Phase 4), and the shared
command-runner used by the hub. All mutating ops that touch the real
system go through here.

Public API:
    swap_model(fragment, emit) -> int   Transactional model swap with rollback
    get_free_vram() -> int              Actual free VRAM from /sys/class/drm
    check_drift() -> dict | None        Compare configured vs running model
    reconcile_model(emit) -> int        Restart llama to match stack.env
    record_action(...) -> None          Append durable JSONL action record
    classify_failure(output, logs) -> dict  Map error signals to plain-language cause + fix
    get_action_history(limit) -> list   Read recent action records
    run_cmd_capture(*cmd) -> (int, str) Subprocess helper
    get_service_logs(svc) -> str        Journal tail for diagnostics
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from forge_env import ENVFILE, read_env, write_env
from forge_models import GIB, RESERVE, find, plan_apply, vram_total

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

LLAMA_SERVICE = "forge-llama.service"
# display/desktop headroom kept free of the model (imported from forge_models)
HEALTH_POLL_ATTEMPTS = 60
HEALTH_POLL_INTERVAL = 2.0  # seconds between polls
CRASH_POLL_INTERVAL = 1.0  # faster poll for crash detection
EXPECTED_SWAP_DURATION = 60  # typical llama restart + model load

# Phase 4: durable action log
HUB_DIR = Path(__file__).parent
# D3: allow test suites to override the action-log directory via env var
# so pytest doesn't write to the live action log (test isolation).
RECORD_DIR = Path(os.environ.get("FORGE_ACTIONS_DIR", str(HUB_DIR / "data" / "actions")))


# ── Phase 4: failure classifier ──────────────────────────────────

# Each entry: (regex_pattern, human_cause, suggested_fix)
FAILURE_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"(?i)cudaMalloc.*out of memory",
        "Model too big for VRAM at this context size",
        "Lower the context size or pick a smaller model. Try: forge-model set <model> ctx=8192",
    ),
    (
        r"(?i)failed to parse grammar",
        "Grammar file is invalid or corrupted",
        "Check the GBNF grammar file in the DevForge directory. A syntax error in the grammar prevents any constrained generation.",
    ),
    (
        r"(?i)address already in use",
        "Port conflict — another process is using the llama port",
        "Check what's on the port: ss -tlnp | grep <port>. Stop the conflicting process or change LLAMA_PORT in stack.env.",
    ),
    (
        r"(?i)segfault|SIGSEGV|core.?dump(ed)?",
        "llama.cpp crashed (segfault) — usually a driver or model file issue",
        "Check: 1) ROCm/driver version compatible with llama.cpp build, 2) model file not truncated (verify checksum), 3) VRAM not exhausted.",
    ),
    (
        r"(?i)killed|OOM killer",
        "Process was killed by the Linux OOM killer",
        "System RAM exhausted. Close memory-heavy apps, lower batch-size, or pick a smaller model. Check: dmesg | grep -i oom",
    ),
    (
        r"(?i)cannot open|no such file|not found",
        "A required file is missing",
        "Verify the model path in stack.env exists. If it was moved, update MODEL in stack.env or symlink it back into ~/models.",
    ),
    (
        r"(?i)vram too low",
        "Model too big for available VRAM — swap refused by pre-flight check",
        "Close other GPU apps or lower the context size. Try: forge-model set <model> ctx=8192",
    ),
]


def classify_failure(output: str, logs: str = "") -> dict:
    """Map known error signals to plain-language cause + suggested fix.

    Returns {"cause": str, "fix": str} if a known pattern is found,
    or {"cause": "unknown", "fix": "check logs"} otherwise.
    """
    combined = f"{output}\n{logs}"
    for pattern, cause, fix in FAILURE_PATTERNS:
        if re.search(pattern, combined):
            return {"cause": cause, "fix": fix}
    return {"cause": "unknown", "fix": "check the logs for error messages"}


# ── Phase 4: durable action log ──────────────────────────────────


def record_action(
    action: str,
    argv: list[str],
    exit_code: int,
    duration_s: float,
    output: str = "",
    error: str = "",
    diagnostics: str = "",
) -> None:
    """Append a durable JSONL record for one completed action.

    One record per action. Never lost on hub restart. Readable with
    get_action_history(). The record includes everything needed to
    answer "what just went wrong?" without touching journalctl.
    """
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    # Rotate: one file per day to keep individual files small
    date_str = time.strftime("%Y-%m-%d")
    log_path = RECORD_DIR / f"actions-{date_str}.jsonl"

    record = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": time.time(),
        "action": action,
        "argv": argv,
        "exit_code": exit_code,
        "duration_s": round(duration_s, 1),
        "output": output[:4000],  # truncate very long outputs
        "error": error[:2000],
        "diagnostics": diagnostics[:2000],
    }
    # Add failure classification on non-zero exit
    if exit_code != 0:
        record["classification"] = classify_failure(f"{error}\n{output}", diagnostics)

    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")


def get_action_history(limit: int = 50) -> list[dict]:
    """Return recent action records, newest first.

    Reads the most recent daily files until limit is reached.
    """
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    # Read newest files first
    files = sorted(RECORD_DIR.glob("actions-*.jsonl"), reverse=True)[:10]
    for fpath in files:
        try:
            lines = fpath.read_text().strip().splitlines()
            # Read newest lines first within each file
            for line in reversed(lines):
                if not line:
                    continue
                records.append(json.loads(line))
                if len(records) >= limit:
                    break
        except Exception:
            continue
        if len(records) >= limit:
            break
    return records


# ── helpers ──────────────────────────────────────────────────────


async def run_cmd_capture(*cmd: str, timeout: float = 20.0) -> tuple[int, str]:
    """Run a short command; returns (exit_code, ansi-stripped stdout).

    Merges stderr into stdout so callers see the full output.  ANSI
    colour codes are stripped (important for journalctl/systemctl output).
    Accepts an optional *timeout* (seconds).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return 124, f"timeout after {timeout:.0f}s: {' '.join(cmd)}"
        return proc.returncode or 0, ANSI_RE.sub("", raw.decode(errors="replace"))
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0] if cmd else '?'}"


async def get_service_logs(svc: str) -> str:
    """Get recent error/warning lines from a service journal for diagnostics."""
    _, out = await run_cmd_capture(
        "journalctl",
        "--user",
        "-u",
        f"forge-{svc}.service",
        "-n",
        "20",
        "--no-pager",
        "-o",
        "cat",
    )
    return out.strip()


def get_free_vram() -> int:
    """Query ACTUAL free VRAM from /sys/class/drm at this moment.

    Returns free bytes, or vram_total() as fallback if /sys is unreadable.
    """
    for p in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
        try:
            total = int(p.read_text().strip())
            used_file = p.with_name("mem_info_vram_used")
            if used_file.exists():
                used = int(used_file.read_text().strip())
                return total - used
        except OSError:
            continue
    return vram_total()


async def _service_is_failed() -> bool:
    code, _ = await run_cmd_capture(
        "systemctl",
        "--user",
        "is-failed",
        LLAMA_SERVICE,
    )
    return code == 0


# ── Phase 3: drift detection ─────────────────────────────────────


async def check_drift(port: str = "8002") -> dict | None:
    """Compare configured (stack.env) versus running (/props) model state."""
    env = read_env(ENVFILE)
    configured_alias = env.get("MODEL_ALIAS")
    ll_args = env.get("LLAMA_ARGS", "")
    ctx_match = re.search(r"--ctx-size\s+(\d+)", ll_args)
    configured_ctx = int(ctx_match.group(1)) if ctx_match else None

    running_alias: str | None = None
    running_ctx: int | None = None

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            props = await client.get(f"http://127.0.0.1:{port}/props")
            if props.status_code == 200:
                pdata = props.json()
                running_alias = (
                    pdata.get("model_alias")
                    or (pdata.get("default_generation_settings") or {}).get("model_alias")
                    or (pdata.get("default_generation_settings") or {}).get("model")
                )
                running_ctx = pdata.get("n_ctx") or (pdata.get("default_generation_settings") or {}).get("n_ctx")
            else:
                return None
    except httpx.RequestError:
        return None

    code, svc_state = await run_cmd_capture(
        "systemctl",
        "--user",
        "is-active",
        LLAMA_SERVICE,
    )
    if svc_state.strip() != "active":
        return None

    drifted = (configured_alias and running_alias and configured_alias != running_alias) or (
        configured_ctx and running_ctx and configured_ctx != running_ctx
    )

    reason = None
    if drifted:
        parts = []
        if configured_alias != running_alias:
            parts.append(f"configured: {configured_alias}, running: {running_alias}")
        if configured_ctx != running_ctx:
            parts.append(f"configured ctx {configured_ctx}, running ctx {running_ctx}")
        reason = "; ".join(parts) if parts else "unknown drift"

    return {
        "drift": drifted,
        "configured_alias": configured_alias,
        "running_alias": running_alias,
        "configured_ctx": configured_ctx,
        "running_ctx": running_ctx,
        "reason": reason,
    }


# ── Phase 3: reconcile ───────────────────────────────────────────


async def reconcile_model(emit: Callable[[str], None]) -> int:
    """Restart llama to match stack.env."""
    t0 = time.time()
    emit("reconciling: restarting llama to match stack.env...")
    code, out = await run_cmd_capture(
        "systemctl",
        "--user",
        "restart",
        LLAMA_SERVICE,
    )
    if code != 0:
        emit(f"restart failed (exit {code}): {out[:200]}")
        record_action(
            "reconcile", ["systemctl", "restart", "forge-llama"], 1, time.time() - t0, output=out, error=f"exit {code}"
        )
        return 1

    env = read_env(ENVFILE)
    port = env.get("LLAMA_PORT", "8002")
    expected_alias = env.get("MODEL_ALIAS", "?")

    async with httpx.AsyncClient(timeout=3.0) as client:
        for attempt in range(1, HEALTH_POLL_ATTEMPTS + 1):
            emit(f"waiting for /health (attempt {attempt}/{HEALTH_POLL_ATTEMPTS})...")

            if await _service_is_failed():
                logs = await get_service_logs("llama")
                emit(f"llama crashed during reconcile. Logs:\n{logs}")
                record_action(
                    "reconcile",
                    ["systemctl", "restart", "forge-llama"],
                    1,
                    time.time() - t0,
                    error="llama crashed",
                    diagnostics=logs,
                )
                return 1

            try:
                health = await client.get(f"http://127.0.0.1:{port}/health")
                if health.status_code == 200:
                    props = await client.get(f"http://127.0.0.1:{port}/props")
                    if props.status_code == 200:
                        pdata = props.json()
                        actual = pdata.get("model_alias") or (pdata.get("default_generation_settings") or {}).get(
                            "model_alias", ""
                        )
                        emit(f"reconciled: running {actual} (configured: {expected_alias})")
                        exit_code = 1 if (actual and expected_alias and actual != expected_alias) else 0
                        record_action(
                            "reconcile",
                            ["systemctl", "restart", "forge-llama"],
                            exit_code,
                            time.time() - t0,
                            output=f"running={actual} configured={expected_alias}",
                        )
                        return exit_code
            except httpx.RequestError:
                pass
            await asyncio.sleep(HEALTH_POLL_INTERVAL)

    record_action(
        "reconcile", ["systemctl", "restart", "forge-llama"], 1, time.time() - t0, error="timeout waiting for /health"
    )
    emit(f"timeout after {HEALTH_POLL_ATTEMPTS * HEALTH_POLL_INTERVAL:.0f}s")
    return 1


# ── Phase 2: transactional swap ──────────────────────────────────


async def swap_model(fragment: str, emit: Callable[[str], None]) -> int:
    """Transactional model swap with pre-flight VRAM check and rollback."""
    t0 = time.time()
    env_snapshot = read_env(ENVFILE)
    port = env_snapshot.get("LLAMA_PORT", "8002")
    action_argv = ["swap", fragment]
    all_output: list[str] = []

    def _emit(s: str) -> None:
        all_output.append(s)
        emit(s)

    try:
        _emit("checking VRAM...")
        try:
            plan = plan_apply(fragment)
            if "error" in plan:
                raise RuntimeError(plan["error"])
        except Exception as e:
            _emit(f"error: {e}")
            record_action("swap", action_argv, 1, time.time() - t0, error=str(e))
            return 1

        need_bytes = int(plan["model"]["fit"]["need_gb"] * GIB)
        free_bytes = get_free_vram()
        # The CURRENT llama model gets unloaded before the new one loads, so
        # its VRAM will be freed. Look up the current model's fit.need_gb
        # (not the new model's) — using the new model's size as proxy
        # overestimates reclaim when swapping small→big and would OOM.
        reclaim = need_bytes  # fallback if lookup fails
        current_alias = env_snapshot.get("MODEL_ALIAS", "")
        if current_alias:
            try:
                cur = find(current_alias)
                reclaim = int(cur["fit"]["need_gb"] * GIB)
            except Exception:
                pass  # fallback to need_bytes proxy
        # available-after-swap, capped at total minus display headroom
        available = min(free_bytes + reclaim, vram_total()) - RESERVE
        if need_bytes > available:
            fatal = (
                f"VRAM too low: model needs ~{need_bytes / GIB:.1f} GiB, "
                f"but only ~{available / GIB:.1f} GiB will be available after "
                f"unloading the current model. Close other GPU apps or lower "
                f"context: forge-model set {plan['model']['alias']} ctx=8192"
            )
            _emit(f"error: {fatal}")
            record_action("swap", action_argv, 1, time.time() - t0, error=fatal)
            return 1

        _emit(f"VRAM ok: ~{available / GIB:.1f} GiB available after unload, model needs ~{need_bytes / GIB:.1f} GiB")
        _emit("snapshot taken")

        updates = {
            "MODEL": plan["model"]["path"],
            "MODEL_ALIAS": plan["model"]["alias"],
            "DEVFORGE_PROMPT_TEMPLATE": plan["model"]["template"],
            "LLAMA_ARGS": plan["llama_args"],
        }

        _emit("writing config...")
        write_env(ENVFILE, updates)

        _emit("restarting llama...")
        code, out = await run_cmd_capture(
            "systemctl",
            "--user",
            "restart",
            LLAMA_SERVICE,
        )
        if code != 0:
            raise RuntimeError(f"systemctl restart failed (exit {code}): {out[:200]}")

        async with httpx.AsyncClient(timeout=3.0) as client:
            for attempt in range(1, HEALTH_POLL_ATTEMPTS + 1):
                _emit(f"waiting for /health (attempt {attempt}/{HEALTH_POLL_ATTEMPTS})...")

                if await _service_is_failed():
                    logs = await get_service_logs("llama")
                    raise RuntimeError(f"Llama service crashed during startup.\n{logs}")

                try:
                    health = await client.get(f"http://127.0.0.1:{port}/health")
                    if health.status_code == 200:
                        props = await client.get(f"http://127.0.0.1:{port}/props")
                        if props.status_code == 200:
                            pdata = props.json()
                            actual_alias = (
                                pdata.get("model_alias")
                                or (pdata.get("default_generation_settings") or {}).get("model_alias")
                                or ""
                            )
                            if actual_alias and actual_alias != updates["MODEL_ALIAS"]:
                                raise RuntimeError(
                                    f"Model mismatch: expected {updates['MODEL_ALIAS']}, got {actual_alias}"
                                )
                            _emit(f"verified: model={updates['MODEL_ALIAS']}")
                            # Parity with `stack model`: DevForge bakes the prompt
                            # template AND its context budget in at startup, so a
                            # template/ctx change requires restarting it — otherwise
                            # the pipeline keeps prompting in the old format.
                            if plan.get("devforge_restart") == "1":
                                _emit("template/context changed — restarting devforge...")
                                await run_cmd_capture(
                                    "systemctl",
                                    "--user",
                                    "restart",
                                    "forge-devforge.service",
                                )
                            record_action(
                                "swap", action_argv, 0, time.time() - t0, output=f"model={updates['MODEL_ALIAS']}"
                            )
                            return 0
                except httpx.RequestError:
                    pass
                await asyncio.sleep(HEALTH_POLL_INTERVAL)

            raise RuntimeError(f"Timeout after {HEALTH_POLL_ATTEMPTS * HEALTH_POLL_INTERVAL:.0f}s waiting for /health")

    except RuntimeError as e:
        _emit(f"error: {e}")
        _emit("rollback: restoring previous config...")
        write_env(ENVFILE, env_snapshot)
        await run_cmd_capture("systemctl", "--user", "restart", LLAMA_SERVICE)

        logs = await get_service_logs("llama")
        diagnostics_str = ""
        if logs:
            for line in logs.splitlines():
                if re.search(r"(?i)(error|fail|fatal|oom|cudaMalloc|core.?dump(ed)?|segfault|killed)", line):
                    _emit(f"  [diagnostic] {line}")
                    diagnostics_str += line + "\n"

        _emit("rollback complete — previous model restored")
        record_action("swap", action_argv, 1, time.time() - t0, error=str(e), diagnostics=diagnostics_str.strip())
        return 1

    except Exception as e:
        _emit(f"unexpected error: {type(e).__name__}: {e}")
        _emit("rollback: restoring previous config...")
        try:
            write_env(ENVFILE, env_snapshot)
            await run_cmd_capture("systemctl", "--user", "restart", LLAMA_SERVICE)
        except Exception:
            _emit("WARNING: rollback failed — manual recovery needed")
        _emit("rollback complete")
        record_action("swap", action_argv, 1, time.time() - t0, error=f"{type(e).__name__}: {e}")
        return 1
