"""DevForge pre-flight check — run before a session, like a pilot's checklist.

Verifies the local stack matches what the pipeline expects:

  - llama.cpp reachable; context-budget math fits the server's real n_ctx
  - grammar generation works
  - godot-ai MCP and DevForge MCP ports
  - game_root and dependencies

Read-only by default (safe to run anytime). ``--warm`` additionally sends
two tiny generations through llama.cpp, which:

  1. warms the model (relevant when llama-server runs ``--no-warmup``),
  2. primes the KV cache with the planner's static prompt prefix, and
  3. MEASURES whether prefix cache reuse actually works — Gemma's
     sliding-window attention can silently defeat llama.cpp's
     ``cache_prompt`` (fix: add ``--swa-full`` to llama-server).

Run with: python -m devforge.doctor [--warm]
Exits nonzero if any check FAILS (warnings don't fail the run).
"""

from __future__ import annotations

import sys
import urllib.parse
import urllib.request

PASS = "\033[32mPASS\033[0m"
WARN = "\033[33mWARN\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_failures = 0


def _report(status: str, name: str, detail: str = "") -> None:
    global _failures
    if status is FAIL:
        _failures += 1
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def _http_alive(url: str, timeout: float = 3.0) -> bool:
    """True if anything HTTP answers at *url* (any status code counts)."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True  # server answered, just not 2xx — it's alive
    except Exception:
        return False


def check_config():
    from devforge.infrastructure.runtime_config import RuntimeConfig

    config = RuntimeConfig.from_env()
    errs = config.validate()
    if errs:
        _report(FAIL, "Runtime config", "; ".join(errs))
    else:
        _report(
            PASS,
            "Runtime config",
            f"backend={config.llm_backend}, budget={config.context_token_budget}, timeout={config.llm_timeout_s}s",
        )
    return config


def check_llama(config):
    from devforge.infrastructure.llm.llama_client import LlamaClient
    from devforge.infrastructure.runtime_config import (
        MIN_USEFUL_CONTEXT_TOKENS,
        PROMPT_OVERHEAD_TOKENS,
        effective_context_budget,
    )

    client = LlamaClient(endpoint=config.llama_endpoint, timeout_s=config.llm_timeout_s)
    props = client.server_props()
    if not props:
        _report(FAIL, "llama.cpp /props", f"unreachable at {config.llama_endpoint} — is llama-server running?")
        return None

    n_ctx = props["n_ctx"]
    _report(PASS, "llama.cpp server", f"alias='{props['model_alias']}', n_ctx={n_ctx}, slots={props['total_slots']}")

    # ── Prompt-template vs model-alias heuristic check ──────
    # WARN only: the user may have a deliberate reason (e.g. testing).
    alias_lower = props.get("model_alias", "").lower()
    configured_template = config.llm_prompt_template

    _MISMATCH_TABLE = {
        "gemma": ["qwen", "yi", "internlm", "chatml"],
        "chatml": ["gemma"],
    }
    mismatch_hints = _MISMATCH_TABLE.get(configured_template, [])
    for hint in mismatch_hints:
        if hint in alias_lower:
            _report(
                WARN,
                "Prompt template mismatch",
                f"model alias '{props['model_alias']}' vs prompt template "
                f"'{configured_template}' — set DEVFORGE_PROMPT_TEMPLATE",
            )
            break

    effective = effective_context_budget(n_ctx, config.llama_max_tokens, config.context_token_budget)
    math_line = (
        f"n_ctx {n_ctx} - generation {config.llama_max_tokens} "
        f"- overhead {PROMPT_OVERHEAD_TOKENS} → context budget {effective}"
    )
    if effective < MIN_USEFUL_CONTEXT_TOKENS:
        _report(
            WARN,
            "Context budget",
            math_line + f" (< {MIN_USEFUL_CONTEXT_TOKENS}: raise --ctx-size or lower DEVFORGE_LLAMA_MAX_TOKENS)",
        )
    elif effective < config.context_token_budget:
        _report(PASS, "Context budget", math_line + " (auto-clamped at startup)")
    else:
        _report(PASS, "Context budget", math_line)

    if props["total_slots"] > 1:
        _report(
            WARN,
            "Server slots",
            f"--parallel {props['total_slots']} splits the KV cache; "
            "DevForge serializes requests — --parallel 1 gives the "
            "largest per-request window",
        )
    return client


def check_grammar():
    try:
        from devforge.knowledge.scene.godot_node_types import generate_grammar_file

        path = generate_grammar_file()
        _report(PASS, "Grammar generation", path)
    except Exception as exc:
        _report(FAIL, "Grammar generation", str(exc))


def check_godot_ai(config):
    if _http_alive(config.godot_ai_mcp_url):
        _report(PASS, "godot-ai MCP", config.godot_ai_mcp_url)
    else:
        _report(
            WARN,
            "godot-ai MCP",
            f"no answer at {config.godot_ai_mcp_url} — live execution "
            "and integration tests unavailable (unit pipeline still works)",
        )


def check_devforge_mcp():
    url = "http://localhost:8001/"
    if _http_alive(url):
        _report(PASS, "DevForge MCP", "something is listening on port 8001")
    else:
        _report(WARN, "DevForge MCP", "port 8001 not answering — start with python -m devforge.platform.mcp_server")


def check_game_root(config):
    from pathlib import Path

    root = Path(config.game_root)
    if root.is_dir():
        _report(PASS, "game_root", str(root.resolve()))
    else:
        _report(WARN, "game_root", f"{config.game_root} does not exist — code context will be empty")


def check_deps():
    missing = []
    for mod in ("yaml", "fastapi", "mcp", "requests", "httpx"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        _report(FAIL, "Dependencies", f"missing: {', '.join(missing)} — pip install -r devforge/requirements.txt")
    else:
        _report(PASS, "Dependencies", "all imports resolve")


def warm_and_probe_cache(client) -> None:
    """Warm the model AND measure prefix-cache reuse.

    Sends the planner's real static prefix twice. llama.cpp reports
    ``timings.prompt_n`` = tokens it had to (re)process. If the second
    call reprocesses nearly everything, ``cache_prompt`` isn't reusing
    the prefix — on Gemma models the usual cause is sliding-window
    attention, fixed by adding ``--swa-full`` to llama-server.
    """
    import json
    import urllib.request

    from devforge.compilation.pipeline.architecture_planner import ArchitecturePlanner

    # The genuine static prefix: template with empty context/request,
    # so the KV cache primed here is reused by the first real request.
    prompt = ArchitecturePlanner()._build_prompt(context="", prompt="")
    payload = {
        "prompt": f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n",
        "n_predict": 1,
        "cache_prompt": True,
        "temperature": 0.0,
    }

    def call() -> dict:
        req = urllib.request.Request(
            f"{client.endpoint}/completion",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=client.timeout_s) as resp:
            return json.loads(resp.read()).get("timings", {})

    try:
        t1 = call()
        t2 = call()
    except Exception as exc:
        _report(WARN, "Warmup/cache probe", f"failed: {exc}")
        return

    n1 = t1.get("prompt_n", 0)
    ms1 = t1.get("prompt_ms", 0.0)
    n2 = t2.get("prompt_n", 0)
    ms2 = t2.get("prompt_ms", 0.0)
    _report(PASS, "Model warmed", f"static prefix primed ({n1} tokens, {ms1:.0f}ms prefill)")

    if n1 > 0 and n2 <= max(8, n1 * 0.1):
        _report(PASS, "Prompt-cache reuse", f"second call reprocessed only {n2}/{n1} tokens ({ms2:.0f}ms)")
    else:
        _report(
            WARN,
            "Prompt-cache reuse",
            f"second call reprocessed {n2}/{n1} tokens — prefix reuse "
            "is NOT working. On Gemma this is usually sliding-window "
            "attention: add --swa-full to llama-server (costs VRAM, "
            "buys big prefill savings per turn)",
        )


def main(argv: list[str]) -> int:
    warm = "--warm" in argv

    print("DevForge pre-flight check")
    print("─" * 50)
    config = check_config()
    client = check_llama(config)
    check_grammar()
    check_godot_ai(config)
    check_devforge_mcp()
    check_game_root(config)
    check_deps()
    if client and warm:
        warm_and_probe_cache(client)
    elif client:
        print("  (run with --warm to warm the model and measure prompt-cache reuse)")

    print("─" * 50)
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("All checks passed (warnings above, if any, are advisory).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
