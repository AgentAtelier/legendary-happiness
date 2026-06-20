"""quest_compare — multi-model comparison runner.

Given a room prompt, a list of model fragments, and a scene-name prefix:
    1. Records the currently-loaded model to restore later.
    2. For each fragment: swaps the model via the hub API, waits for
       /health, runs ``python -m foundry quest``, and captures the spec.
    3. Prints a side-by-side comparison table.
    4. Restores the original model.

Usage::
    cd foundry && .venv/bin/python -m quest_compare \\
        --prompt "a hermit's shack" \\
        --models qwen3 merged-22b cydonia \\
        --prefix compare_test

Output: four scenes <prefix>_<alias>.tscn plus the comparison table.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

HUB_URL = "http://127.0.0.1:8003"
LLAMA_URL = "http://127.0.0.1:8002"
HUB_CSRF_HEADER = "x-forge-hub"
HEALTH_POLL_ATTEMPTS = 60
HEALTH_POLL_INTERVAL = 2.0

LLAMA_SERVICE = "forge-llama.service"


def _get_current_model() -> Optional[str]:
    """Query the hub for the currently-loaded model alias.

    Uses ``/api/models`` — it returns the active model's ``alias`` at the
    top level (and a ``current`` flag per model).  ``/api/status`` only
    returns a ``raw`` text blob with no structured alias, so reading it
    here always yielded ``None`` and the original model was never restored.
    """
    try:
        r = requests.get(f"{HUB_URL}/api/models", timeout=5)
        r.raise_for_status()
        data = r.json()
        alias = data.get("alias")
        if alias:
            return alias
        for m in data.get("models", []):
            if m.get("current"):
                return m.get("alias")
        return None
    except requests.RequestException as e:
        print(f"[quest_compare] WARNING: cannot read current model: {e}")
        return None


def _swap_model(fragment: str) -> bool:
    """Swap to *fragment* via the hub API.  Returns True on success."""
    print(f"  [swap] sending swap request for '{fragment}'...")
    try:
        r = requests.post(
            f"{HUB_URL}/api/swap",
            json={"fragment": fragment},
            headers={HUB_CSRF_HEADER: "1"},
            timeout=10,
        )
        r.raise_for_status()
        job_id = r.json().get("job")
        if not job_id:
            print(f"  [swap] ERROR: no job_id in response: {r.text}")
            return False
    except requests.RequestException as e:
        print(f"  [swap] ERROR: swap request failed: {e}")
        return False

    # ── Stream the job output and wait for completion ───────────
    seen_done_event = False
    exit_code = None
    session = requests.Session()
    last_line_idx = 0
    all_lines: list[str] = []

    try:
        response = session.get(
            f"{HUB_URL}/api/stream/{job_id}",
            stream=True,
            timeout=300,
        )
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            if raw_line.startswith("event: done"):
                seen_done_event = True
            elif seen_done_event and raw_line.startswith("data: "):
                # Exit code arrives as a data line right after event:done
                try:
                    exit_code = int(raw_line[6:])
                except ValueError:
                    pass
                # Still append so all_lines has the full picture
                all_lines.append(raw_line[6:])
                break
            elif raw_line.startswith("data: "):
                line = raw_line[6:]
                all_lines.append(line)
                # Print new lines as they arrive
                while last_line_idx < len(all_lines):
                    print(f"  [swap]   {all_lines[last_line_idx]}")
                    last_line_idx += 1
    except requests.RequestException as e:
        print(f"  [swap] ERROR: stream failed: {e}")
        return False

    if exit_code is None:
        # Fallback: last non-empty data line might be the exit code
        for line in reversed(all_lines):
            stripped = line.strip()
            try:
                exit_code = int(stripped)
                break
            except ValueError:
                continue

    if exit_code is None:
        print(f"  [swap] ERROR: could not determine exit code from stream")
        return False

    if exit_code != 0:
        print(f"  [swap] ERROR: swap returned exit code {exit_code}")
        return False

    print(f"  [swap] swap to '{fragment}' complete")
    return True


def _wait_for_health(expected_alias: Optional[str] = None) -> bool:
    """Poll llama /health until it responds 200. Optionally verify the
    running model alias matches *expected_alias* via /props.

    Returns True on success.
    """
    print("  [health] waiting for llama /health...")
    for attempt in range(1, HEALTH_POLL_ATTEMPTS + 1):
        try:
            r = requests.get(f"{LLAMA_URL}/health", timeout=3)
            if r.status_code == 200:
                if expected_alias:
                    # Verify the running model matches
                    try:
                        pr = requests.get(f"{LLAMA_URL}/props", timeout=3)
                        if pr.status_code == 200:
                            pdata = pr.json()
                            running = (
                                pdata.get("model_alias")
                                or (pdata.get("default_generation_settings") or {}).get("model_alias", "")
                            )
                            if running and running != expected_alias:
                                print(f"  [health] WARNING: running model {running!r} != expected {expected_alias!r}")
                    except requests.RequestException:
                        pass
                print(f"  [health] llama healthy (attempt {attempt})")
                return True
        except requests.RequestException:
            pass
        time.sleep(HEALTH_POLL_INTERVAL)
    print(f"  [health] ERROR: llama did not become healthy after "
          f"{HEALTH_POLL_ATTEMPTS * HEALTH_POLL_INTERVAL:.0f}s")
    return False


def _run_quest(prompt: str, scene: str) -> Tuple[bool, str, dict]:
    """Run ``python -m foundry quest`` and capture the spec.

    The quest command scaffolds into ``builds/<scene>/``.
    Returns ``(ok, stdout, spec_dict)``.
    """
    cmd = [
        sys.executable, "-m", "foundry", "quest",
        "--request", prompt,
        "--scene", scene,
    ]
    print(f"  [quest] running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    stdout = result.stdout

    if result.returncode != 0:
        print(f"  [quest] ERROR: quest command failed (exit {result.returncode})")
        print(f"  [quest] stderr: {result.stderr[:500]}")
        return False, stdout, {}

    spec = _parse_quest_output(stdout)
    print(f"  [quest] spec captured: {spec}")
    return True, stdout, spec


def _parse_quest_output(stdout: str) -> dict:
    """Extract npc_role, target, and the dialogue lines from quest stdout.

    The ``quest`` command prints the dialogue indented by two spaces
    (``  greet: ...``).  Each line here is stripped first, then matched on
    the bare ``greet:``/``ask:``/``wrong:``/``thank:`` prefix — matching the
    *indented* prefix after stripping never fired, so the dialogue was
    silently dropped from the comparison table.
    """
    spec: dict = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("[quest] NPC role:"):
            spec["npc_role"] = line.split(":", 1)[1].strip()
        elif line.startswith("[quest] Target entity:"):
            spec["target"] = line.split(":", 1)[1].strip()
        else:
            for key in ("greet", "ask", "wrong", "thank"):
                if line.startswith(f"{key}:"):
                    spec[key] = line.split(":", 1)[1].strip()
                    break
    return spec


def _check_model_fit(alias: str) -> dict:
    """Check a model's VRAM fit status via the hub API.

    Returns {"status": str, "need_gb": float, "ctx": int} or {} on failure.
    """
    try:
        r = requests.get(
            f"{HUB_URL}/api/models",
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        models = data.get("models", [])
        for m in models:
            if m.get("alias") == alias:
                fit = m.get("fit", {})
                return {
                    "status": fit.get("status", "?"),
                    "need_gb": fit.get("need_gb", 0.0),
                    "ctx": fit.get("ctx", 0),
                }
    except requests.RequestException as e:
        print(f"  [fit] WARNING: cannot check fit for {alias}: {e}")
    return {}


def _pre_configure_27b() -> bool:
    """Pre-configure qwen3-6-27b with ctx=8192 for 16 GB VRAM fit.

    Runs ``forge-model set qwen3-6-27b ctx=8192``.  Returns True if the
    command succeeds.
    """
    from pathlib import Path as _P
    HOME = _P.home()
    fm = str(HOME / ".local/bin/forge-model")
    if not _P(fm).exists():
        print("[27b-fit] forge-model CLI not found, skipping pre-config")
        return True  # not fatal — the VRAM pre-flight will catch the spill

    print("[27b-fit] pre-configuring qwen3-6-27b ctx=8192...")
    result = subprocess.run(
        [fm, "set", "qwen3-6-27b", "ctx=8192"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        print("[27b-fit] ctx=8192 set")
        return True
    # ctx=8192 may still be too large — try 4096
    print(f"[27b-fit] ctx=8192 failed (exit {result.returncode}), trying ctx=4096...")
    result2 = subprocess.run(
        [fm, "set", "qwen3-6-27b", "ctx=4096"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result2.returncode == 0:
        print("[27b-fit] ctx=4096 set")
        return True
    print(f"[27b-fit] ERROR: ctx=4096 also failed (exit {result2.returncode})")
    return False


def _reset_failed_llama() -> None:
    """Run ``systemctl --user reset-failed forge-llama.service``.

    Clears the start-limit-hit state so a prior OOM doesn't block recovery.
    """
    subprocess.run(
        ["systemctl", "--user", "reset-failed", LLAMA_SERVICE],
        capture_output=True,
        timeout=10,
    )


def _resolve_model_alias(fragment: str) -> str:
    """Query the hub for the alias of a model fragment."""
    try:
        r = requests.get(
            f"{HUB_URL}/api/models/search",
            params={"q": fragment},
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        matches = data.get("matches", [])
        if len(matches) == 1:
            return matches[0]["alias"]
        if matches:
            # Return first match's alias (best-effort)
            return matches[0]["alias"]
    except requests.RequestException:
        pass
    return fragment  # fallback: use fragment as-is


def _build_comparison_table(results: list[dict]) -> str:
    """Build a side-by-side Markdown comparison table from per-model results."""
    if not results:
        return "(no results)"

    columns = ["npc_role", "target", "greet", "ask", "wrong", "thank"]
    header_cols = ["Model"] + columns
    col_widths = [max(len(h), 12) for h in header_cols]

    # Measure column widths
    for r in results:
        spec = r.get("spec", {})
        for i, col in enumerate(columns):
            width = len(str(spec.get(col, "?")))
            col_widths[i + 1] = max(col_widths[i + 1], width)

    divider = "-" * (sum(col_widths) + len(col_widths) * 3 + 1)

    def fmt_row(vals: list[str]) -> str:
        cells = [v.ljust(w) for v, w in zip(vals, col_widths)]
        return "| " + " | ".join(cells) + " |"

    lines = [divider]
    lines.append(fmt_row(header_cols))
    lines.append(divider)

    for r in results:
        alias = r.get("alias", "?")
        spec = r.get("spec", {})
        row = [alias] + [str(spec.get(c, "?")) for c in columns]
        lines.append(fmt_row(row))

    lines.append(divider)

    # Error summary
    errors = [r for r in results if r.get("error")]
    if errors:
        lines.append("")
        lines.append("**Errors:**")
        for r in errors:
            lines.append(f"- **{r['alias']}**: {r['error']}")

    return "\n".join(lines)


def run_compare(
    prompt: str,
    fragments: list[str],
    prefix: str,
    dry_run: bool = False,
    original_model: Optional[str] = None,
) -> int:
    """Run the full multi-model comparison.

    Returns 0 on success, 1 on failure.
    """
    # ── 0. Pre-configure 27B if it's among the fragments ──────
    if any("27b" in f.lower() or "qwen3-6-27b" in f.lower() for f in fragments):
        _pre_configure_27b()

    # ── 1. Record current model ────────────────────────────────
    if original_model is None:
        original_model = _get_current_model()
    if original_model:
        print(f"[quest_compare] Original model: {original_model}")
    else:
        print("[quest_compare] WARNING: could not determine original model")
        print("[quest_compare] Will not be able to restore. Set --original to override.")

    if dry_run:
        print("[quest_compare] Dry run — would compare:")
        for frag in fragments:
            print(f"  {frag}")
        return 0

    # ── 2. Run each model ───────────────────────────────────────
    results: list[dict] = []
    all_ok = True

    for fragment in fragments:
        print(f"\n{'=' * 60}")
        print(f"[quest_compare] Testing model: {fragment}")
        print(f"{'=' * 60}")

        # Resolve alias for scene naming
        alias = _resolve_model_alias(fragment)
        alias_slug = alias.replace(" ", "-").replace("/", "-")[:40]
        scene_name = f"{prefix}_{alias_slug}"

        result: dict = {
            "fragment": fragment,
            "alias": alias,
            "scene": scene_name,
            "spec": {},
            "error": None,
        }

        # 2a. VRAM pre-flight: skip if model spills
        fit = _check_model_fit(alias)
        if fit.get("status") == "spills":
            gb = fit.get("need_gb", 0.0)
            ctx = fit.get("ctx", 0)
            msg = (
                f"VRAM pre-flight: {alias} spills (~{gb} GiB needed "
                f"at ctx={ctx}) — skipping"
            )
            print(f"  [fit] {msg}")
            result["error"] = msg
            results.append(result)
            all_ok = False
            continue

        # 2b. Swap model.  Reset the service's failed/start-limit state
        # FIRST: systemd allows only StartLimitBurst restarts per interval
        # (3 / 2min on forge-llama), so the 4th rapid swap is otherwise
        # refused with 'start-limit-hit' even when VRAM is fine.
        _reset_failed_llama()
        if not _swap_model(fragment):
            result["error"] = "swap failed"
            results.append(result)
            all_ok = False
            continue

        # 2c. Wait for /health
        if not _wait_for_health():
            result["error"] = "health check failed"
            results.append(result)
            all_ok = False
            continue

        # 2d. Run quest generation
        ok, stdout, spec = _run_quest(prompt, scene_name)
        if not ok:
            result["error"] = "quest generation failed"
            result["spec"] = spec
            results.append(result)
            all_ok = False
            continue

        result["spec"] = spec
        results.append(result)

    # ── 3. Print comparison table ──────────────────────────────
    print(f"\n{'=' * 60}")
    print("[quest_compare] COMPARISON TABLE")
    print(f"{'=' * 60}")
    print(_build_comparison_table(results))

    # ── 4. Restore original model ──────────────────────────────
    if original_model:
        # Safe restore: clear start-limit-hit so a prior OOM
        # doesn't block recovery.
        print("\n[quest_compare] Resetting failed state on llama service...")
        _reset_failed_llama()

        print(f"[quest_compare] Restoring original model: {original_model}")
        if _swap_model(original_model):
            _wait_for_health(expected_alias=original_model)
            print(f"[quest_compare] Original model restored.")
        else:
            print("[quest_compare] ERROR: failed to restore original model!")
            all_ok = False
    else:
        print("\n[quest_compare] No original model recorded — skipping restore.")

    # ── Summary ─────────────────────────────────────────────────
    ok_count = sum(1 for r in results if not r.get("error"))
    print(f"\n[quest_compare] Done. {ok_count}/{len(results)} models succeeded.")
    for r in results:
        status = "OK" if not r.get("error") else f"FAIL ({r['error']})"
        print(f"  {r['alias']}: {status}")

    return 0 if all_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m quest_compare",
        description="Multi-model quest comparison runner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Example:
            cd foundry && .venv/bin/python -m quest_compare \\
                --prompt "a hermit's shack with worn furniture" \\
                --models qwen3 merged-22b \\
                --prefix compare_test
        """),
    )
    parser.add_argument(
        "--prompt", required=True,
        help="Room prompt for the quest (e.g. 'a hermit's shack')"
    )
    parser.add_argument(
        "--models", required=True, nargs="+",
        help="Model fragments to compare (e.g. qwen3 merged-22b cydonia)"
    )
    parser.add_argument(
        "--prefix", required=True,
        help="Scene name prefix (produces <prefix>_<alias>.tscn)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be done without swapping or generating"
    )
    parser.add_argument(
        "--original", default=None,
        help="Model to restore after run (default: auto-detect from hub)"
    )
    args = parser.parse_args()

    return run_compare(
        prompt=args.prompt,
        fragments=args.models,
        prefix=args.prefix,
        dry_run=args.dry_run,
        original_model=args.original,
    )


if __name__ == "__main__":
    sys.exit(main())
