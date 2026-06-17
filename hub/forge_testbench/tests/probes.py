"""Probe tests — migrated from bench.py into plug-in tests.

Each test owns both run() and score(). The runner injects Context so
tests never reach into global state. score() is a pure function of the
raw observations from run().

Categories:
  Layer 1 (llama): throughput, context, grammar, thinking, tools
  Layer 2 (devforge): plan, compile, execute, completeness, validate, roundtrip
  Layer 3 (godot-ai): latency, fidelity
  Layer 4 (runtime): launch
  Layer 5 (odysseus): persona, retrieval
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..catalog import register
from ..context import Context
from ..metric import Metric
from ..result import ScoredResult, Status
from ..test import Test

HOME = Path.home()
PRESETS = HOME / "dev/ai/odysseus/data/presets.json"
APPDB = HOME / "dev/ai/odysseus/data/app.db"
PLUGIN_CFG = HOME / "dev/games/rpg/addons/godot_ai/plugin.cfg"
ODY_CONTAINER = "odysseus-odysseus-1"

CUBE_PROMPT = "create a cube in the middle of the existing ground"
DEVFORGE_PROBE_PROMPT = (
    "Add a CharacterBody3D named Hero as a child of the scene root. "
    "Give Hero a Camera3D child named Eye and a MeshInstance3D child named Body."
)
PROBE_EXPECTED = {"Hero", "Eye", "Body"}


def _probe_verdict_to_status(verdict: str) -> Status:
    """Map old probe verdicts to universal status."""
    return {
        "works": "ok",
        "degraded": "partial",
        "broken": "broke",
        "skip": "ok",  # skip is not a failure
    }.get(verdict, "error")


# ═══════════════════════════════════════════════════════════════════
# Layer 1: llama probes
# ═══════════════════════════════════════════════════════════════════


@register
class ProbeLlamaThroughput(Test):
    id = "probe.llama.throughput"
    category = "probe"
    title = "Generation throughput"
    description = "Tokens/sec and time-to-first-token for a fixed completion."
    suites = ["everything", "llama-layer", "fast"]
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        port = ctx.env.get("LLAMA_PORT", "8002")
        payload = {
            "prompt": (
                "<|im_start|>user\nWrite one paragraph about a blacksmith's forge.<|im_end|>\n<|im_start|>assistant\n"
            ),
            "n_predict": 200,
            "temperature": 0.7,
        }
        r = await ctx.llama_post(f"http://127.0.0.1:{port}/completion", payload, timeout=120)
        t = r.get("timings", {})
        return {
            "tok_per_sec": round(t.get("predicted_per_second", 0), 1),
            "gen_tok": t.get("predicted_n"),
            "prompt_tok": t.get("prompt_n"),
            "ttft_ms": round(t.get("prompt_ms", 0)),
            "gen_ms": round(t.get("predicted_ms", 0)),
        }

    def score(self, raw: dict) -> ScoredResult:
        tps = raw.get("tok_per_sec", 0)
        if not tps:
            return ScoredResult(
                self.id,
                "broke",
                metrics={
                    "throughput": Metric(float(tps), "tok_s", True, "throughput"),
                    "ttft": Metric(raw.get("ttft_ms", 0), "ms", False, "TTFT"),
                },
                raw=raw,
                errors=["no timings — server did not generate"],
            )
        verdict = "works" if tps >= 15 else ("degraded" if tps >= 5 else "broken")
        return ScoredResult(
            self.id,
            _probe_verdict_to_status(verdict),
            score=min(round(tps / 30 * 100), 100) if tps > 0 else 0,
            metrics={
                "throughput": Metric(float(tps), "tok_s", True, "throughput"),
                "ttft": Metric(raw.get("ttft_ms", 0), "ms", False, "TTFT"),
                "gen_tokens": Metric(raw.get("gen_tok", 0), "count", True, "gen tokens"),
            },
            raw=raw,
        )


@register
class ProbeLlamaContext(Test):
    id = "probe.llama.context"
    category = "probe"
    title = "Context window actually loaded"
    description = "The n_ctx in memory vs what stack.env configured (catches silent clamping)."
    suites = ["everything", "llama-layer", "fast"]

    async def run(self, ctx: Context) -> dict:
        port = ctx.env.get("LLAMA_PORT", "8002")
        p = await ctx.llama_get(f"http://127.0.0.1:{port}/props", timeout=10)
        alias = p.get("model_alias")
        want = ctx.env.get("MODEL_ALIAS")
        loaded = (p.get("default_generation_settings") or {}).get("n_ctx") or p.get("n_ctx") or 0
        m = re.search(r"--ctx-size\s+(\d+)", ctx.env.get("LLAMA_ARGS", ""))
        configured = int(m.group(1)) if m else None
        km = re.search(r"--cache-type-k\s+(\S+)", ctx.env.get("LLAMA_ARGS", ""))
        return {
            "n_ctx_loaded": loaded,
            "configured_ctx": configured,
            "kv_cache": km.group(1) if km else "f16",
            "model_alias": alias,
            "expected_alias": want,
        }

    def score(self, raw: dict) -> ScoredResult:
        alias = raw.get("model_alias")
        want = raw.get("expected_alias")
        loaded = raw.get("n_ctx_loaded", 0)
        configured = raw.get("configured_ctx")

        if alias != want:
            return ScoredResult(
                self.id,
                "broke",
                metrics={
                    "context": Metric(loaded, "count", True, "loaded ctx"),
                    "match": Metric.boolean(False, "model matches"),
                },
                raw=raw,
                errors=[f"serving '{alias}', config wants '{want}'"],
            )
        if configured and loaded < configured:
            return ScoredResult(
                self.id,
                "partial",
                score=round(loaded / max(configured, 1) * 100),
                metrics={
                    "context": Metric(loaded, "count", True, "loaded ctx"),
                    "configured": Metric(configured, "count", True, "configured ctx"),
                },
                raw=raw,
            )
        return ScoredResult(
            self.id,
            "ok",
            score=100,
            metrics={
                "context": Metric(loaded, "count", True, "loaded ctx"),
                "kv_cache": Metric(raw.get("kv_cache", "f16"), "bool", True, "KV cache"),
            },
            raw=raw,
        )


@register
class ProbeLlamaGrammar(Test):
    id = "probe.llama.grammar"
    category = "probe"
    title = "Grammar enforcement"
    description = "Does the server hold output to a GBNF grammar? The planner depends on it."
    suites = ["everything", "llama-layer", "fast"]
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        port = ctx.env.get("LLAMA_PORT", "8002")
        payload = {
            "prompt": "<|im_start|>user\nPick a word.<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 8,
            "temperature": 1.2,
            "grammar": 'root ::= "FORGE" | "ANVIL"',
        }
        r = await ctx.llama_post(f"http://127.0.0.1:{port}/completion", payload, timeout=60)
        out = r.get("content", "")
        honored = out.strip() in ("FORGE", "ANVIL")
        return {"raw_output": out.strip(), "honored": honored}

    def score(self, raw: dict) -> ScoredResult:
        honored = raw.get("honored", False)
        out = raw.get("raw_output", "")
        if honored:
            return ScoredResult(
                self.id,
                "ok",
                score=100,
                metrics={
                    "enforced": Metric.boolean(True, "grammar enforced"),
                },
                raw=raw,
            )
        return ScoredResult(
            self.id,
            "broke",
            score=0,
            metrics={
                "enforced": Metric.boolean(False, "grammar enforced"),
            },
            raw=raw,
            errors=[f"grammar NOT enforced → {out!r} — DevForge plans run unconstrained"],
        )


@register
class ProbeLlamaThinking(Test):
    id = "probe.llama.thinking"
    category = "probe"
    title = "Answer vs hidden reasoning"
    description = "Content chars vs reasoning chars — catches the thinking-trap (empty answer)."
    suites = ["everything", "llama-layer"]

    async def run(self, ctx: Context) -> dict:
        port = ctx.env.get("LLAMA_PORT", "8002")
        is_qwen = "qwen" in ctx.model_alias.lower()
        content_msg = "Name one Godot 3D node type in one word." + (" /no_think" if is_qwen else "")
        payload = {
            "model": ctx.model_alias,
            "temperature": 0.2,
            "max_tokens": 400,
            "messages": [{"role": "user", "content": content_msg}],
        }
        r = await ctx.llama_post(f"http://127.0.0.1:{port}/v1/chat/completions", payload, timeout=120)
        ch = r["choices"][0]
        content = ch["message"].get("content") or ""
        reasoning = ch["message"].get("reasoning_content") or ""
        return {
            "content_chars": len(content),
            "reasoning_chars": len(reasoning),
            "finish_reason": ch.get("finish_reason"),
            "content_sample": content[:80],
            "model_is_qwen": is_qwen,
        }

    def score(self, raw: dict) -> ScoredResult:
        content_len = raw.get("content_chars", 0)
        reasoning_len = raw.get("reasoning_chars", 0)
        is_qwen = raw.get("model_is_qwen", False)

        if content_len < 3:
            return ScoredResult(
                self.id,
                "broke",
                score=0,
                metrics={
                    "content_chars": Metric(content_len, "count", True, "answer chars"),
                    "reasoning_chars": Metric(reasoning_len, "count", False, "reasoning leak"),
                },
                raw=raw,
                errors=[f"empty answer ({reasoning_len} chars reasoning) — thinking trap"],
            )
        if is_qwen and reasoning_len > 50:
            return ScoredResult(
                self.id,
                "partial",
                score=60,
                metrics={
                    "content_chars": Metric(content_len, "count", True, "answer chars"),
                    "reasoning_chars": Metric(reasoning_len, "count", False, "reasoning leak"),
                },
                raw=raw,
            )
        return ScoredResult(
            self.id,
            "ok",
            score=100,
            metrics={
                "content_chars": Metric(content_len, "count", True, "answer chars"),
                "reasoning_chars": Metric(reasoning_len, "count", False, "reasoning leak"),
            },
            raw=raw,
        )


@register
class ProbeLlamaTools(Test):
    id = "probe.llama.tools"
    category = "probe"
    title = "Native tool calling"
    description = "Does the model emit a structured tool call for an obvious tool task?"
    suites = ["everything", "llama-layer"]

    async def run(self, ctx: Context) -> dict:
        port = ctx.env.get("LLAMA_PORT", "8002")
        payload = {
            "model": ctx.model_alias,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": "Read the scene hierarchy."}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "scene_get_hierarchy",
                        "description": "list scene nodes",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        }
        r = await ctx.llama_post(f"http://127.0.0.1:{port}/v1/chat/completions", payload, timeout=180)
        ch = r["choices"][0]
        calls = ch["message"].get("tool_calls") or []
        name = calls[0]["function"]["name"] if calls else None
        text = ch["message"].get("content") or ""
        return {
            "emitted_tool_call": bool(calls),
            "tool_name": name,
            "finish_reason": ch.get("finish_reason"),
            "text_content": text,
        }

    def score(self, raw: dict) -> ScoredResult:
        calls = raw.get("emitted_tool_call", False)
        name = raw.get("tool_name")
        text = raw.get("text_content", "")

        if calls:
            return ScoredResult(
                self.id,
                "ok",
                score=100,
                metrics={
                    "tool_call": Metric.boolean(True, "emitted tool call"),
                },
                raw=raw,
            )
        if "scene_get_hierarchy" in text:
            return ScoredResult(
                self.id,
                "partial",
                score=40,
                metrics={
                    "tool_call": Metric.boolean(False, "emitted tool call"),
                },
                raw=raw,
            )
        return ScoredResult(
            self.id,
            "broke",
            score=0,
            metrics={
                "tool_call": Metric.boolean(False, "emitted tool call"),
            },
            raw=raw,
            errors=["no tool intent — unsuitable for agent mode"],
        )


# ═══════════════════════════════════════════════════════════════════
# Layer 2: DevForge probes
# ═══════════════════════════════════════════════════════════════════

# Pipeline cache — one real apply_spec feeds all Layer-2 probes (matching
# bench.py's single-LLM-call approach). Clear before each testbench session.
_PIPELINE_CACHE: dict = {"data": None}


def reset_pipeline_cache() -> None:
    """Clear the pipeline cache so the next DevForge probe run gets a fresh
    apply_spec call. Called by the runner at the start of each run().
    """
    _PIPELINE_CACHE["data"] = None


async def _capture_pipeline(ctx: Context) -> dict:
    """Run the fixed DevForge prompt and capture all stages.

    Uses a module-level cache so the plan/compile/execute/completeness probes
    all read from ONE pipeline run — matching bench.py's proven approach.
    """
    if _PIPELINE_CACHE["data"] is not None:
        return _PIPELINE_CACHE["data"]
    t0 = time.time()
    before = set()
    try:
        h = await ctx.godot_ai("scene_get_hierarchy", {"depth": 10})
        before = {n["path"] for n in h.get("nodes", []) if isinstance(n, dict) and n.get("path")}
    except Exception:
        pass

    raw = await ctx.apply_spec(DEVFORGE_PROBE_PROMPT)
    apply_ms = int((time.time() - t0) * 1000)

    artifact = raw
    aid = raw.get("artifact_id")
    if aid:
        try:
            artifact = await ctx.read_artifact(aid)
        except Exception:
            pass

    after = set()
    try:
        h = await ctx.godot_ai("scene_get_hierarchy", {"depth": 10})
        after = {n["path"] for n in h.get("nodes", []) if isinstance(n, dict) and n.get("path")}
    except Exception:
        pass

    data = {
        "raw": raw,
        "artifact": artifact,
        "before": sorted(before),
        "after": sorted(after),
        "apply_ms": apply_ms,
    }
    _PIPELINE_CACHE["data"] = data
    return data


@register
class ProbeDevforgePlan(Test):
    id = "probe.devforge.plan"
    category = "probe"
    title = "Planner architecture delta"
    description = "The entities/types the planner produces for a fixed prompt."
    suites = ["everything", "devforge-layer", "chain-health"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _capture_pipeline(ctx)

    def score(self, raw: dict) -> ScoredResult:
        art = raw.get("artifact", {}) if isinstance(raw.get("artifact"), dict) else {}
        delta = art.get("arch_delta", {}) or {}
        entities = delta.get("entities", []) or []
        names = [e.get("name") for e in entities if isinstance(e, dict)]
        stages = art.get("stage_latencies", {}) or {}
        apply_ms = raw.get("apply_ms", 0)

        metrics = {
            "entities": Metric(len(entities), "count", True, "planned entities"),
            "planning_ms": Metric(stages.get("architecture_planning", 0), "ms", False, "planning time"),
            "apply_ms": Metric(apply_ms, "ms", False, "apply time"),
        }

        if not entities:
            return ScoredResult(
                self.id,
                "broke",
                score=0,
                metrics=metrics,
                raw=raw,
                errors=["planner produced an EMPTY delta (0 entities)"],
            )
        if len(entities) < 3:
            return ScoredResult(self.id, "partial", score=round(len(entities) / 3 * 100), metrics=metrics, raw=raw)
        score = 100 if apply_ms <= 60000 else 70
        return ScoredResult(self.id, "ok" if score >= 70 else "partial", score=score, metrics=metrics, raw=raw)


@register
class ProbeDevforgeCompile(Test):
    id = "probe.devforge.compile"
    category = "probe"
    title = "Compiler operations + parent paths"
    description = "The add_node ops the compiler emits and whether they parent under /root/Main."
    suites = ["everything", "devforge-layer", "chain-health"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _capture_pipeline(ctx)

    def score(self, raw: dict) -> ScoredResult:
        art = raw.get("artifact", {}) if isinstance(raw.get("artifact"), dict) else {}
        ops = [o for o in art.get("operations", []) if isinstance(o, dict)]
        adds = [o for o in ops if o.get("type") == "add_node"]
        scaffold = {"MainCamera", "DirectionalLight"}
        requested = [o for o in adds if o.get("name") not in scaffold]
        parents = {o.get("name"): o.get("parent") for o in adds}
        bad = {n: p for n, p in parents.items() if p and not str(p).startswith("/root/Main")}
        covered = sorted({o.get("name") for o in requested} & PROBE_EXPECTED)

        metrics = {
            "ops": Metric(len(requested), "count", True, "requested ops"),
            "coverage": Metric.ratio(len(covered) / max(len(PROBE_EXPECTED), 1), "compile coverage"),
        }

        if bad:
            return ScoredResult(self.id, "partial", score=50, metrics=metrics, raw=raw)
        if not requested:
            return ScoredResult(
                self.id, "broke", score=0, metrics=metrics, raw=raw, errors=["compiler emitted ONLY scaffolding"]
            )
        if set(covered) >= PROBE_EXPECTED:
            return ScoredResult(self.id, "ok", score=100, metrics=metrics, raw=raw)
        return ScoredResult(
            self.id, "partial", score=round(len(covered) / max(len(PROBE_EXPECTED), 1) * 100), metrics=metrics, raw=raw
        )


@register
class ProbeDevforgeExecute(Test):
    id = "probe.devforge.execute"
    category = "probe"
    title = "Full apply_spec execution"
    description = "ops applied, errors, and the actual nodes added to the scene."
    suites = ["everything", "devforge-layer", "chain-health"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _capture_pipeline(ctx)

    def score(self, raw: dict) -> ScoredResult:
        r = raw.get("raw", {})
        art = raw.get("artifact", {}) if isinstance(raw.get("artifact"), dict) else {}
        applied = r.get("applied", 0)
        errors = r.get("errors") or []
        before = set(raw.get("before", []))
        after = set(raw.get("after", []))
        added = sorted(after - before)
        added_names = {p.rsplit("/", 1)[-1] for p in added}
        built = sorted(added_names & PROBE_EXPECTED)

        metrics = {
            "applied": Metric(applied, "count", True, "applied ops"),
            "errors": Metric(len(errors), "count", False, "errors"),
            "nodes_added": Metric(len(added), "count", True, "nodes added"),
            "coverage": Metric.ratio(len(built) / max(len(PROBE_EXPECTED), 1), "execution coverage"),
        }

        if errors:
            return ScoredResult(
                self.id,
                "broke" if not added else "partial",
                score=round(len(built) / max(len(PROBE_EXPECTED), 1) * 100),
                metrics=metrics,
                raw=raw,
            )
        if set(built) >= PROBE_EXPECTED:
            return ScoredResult(self.id, "ok", score=100, metrics=metrics, raw=raw)
        if built:
            return ScoredResult(
                self.id,
                "partial",
                score=round(len(built) / max(len(PROBE_EXPECTED), 1) * 100),
                metrics=metrics,
                raw=raw,
            )
        return ScoredResult(self.id, "partial", score=10, metrics=metrics, raw=raw)


@register
class ProbeDevforgeCompleteness(Test):
    id = "probe.devforge.completeness"
    category = "probe"
    title = "Completeness injector parents"
    description = "Auto-injected camera/light must use a valid /root/Main parent (regression guard)."
    suites = ["everything", "devforge-layer", "chain-health"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        return await _capture_pipeline(ctx)

    def score(self, raw: dict) -> ScoredResult:
        art = raw.get("artifact", {}) if isinstance(raw.get("artifact"), dict) else {}
        ops = [o for o in art.get("operations", []) if isinstance(o, dict)]
        injected = [
            o
            for o in ops
            if o.get("type") == "add_node"
            and o.get("node_type") in ("DirectionalLight3D", "Camera3D")
            and o.get("name") in ("DirectionalLight", "MainCamera")
        ]
        parents = {o.get("name"): o.get("parent") for o in injected}
        bad = {n: p for n, p in parents.items() if p and not str(p).startswith("/root/Main")}

        if bad:
            return ScoredResult(
                self.id,
                "broke",
                score=0,
                metrics={"injected": Metric(len(injected), "count", True, "injected nodes")},
                raw=raw,
                errors=[f"invalid parents: {bad}"],
            )
        if not injected:
            return ScoredResult(
                self.id, "partial", score=50, metrics={"injected": Metric(0, "count", True, "injected nodes")}, raw=raw
            )
        return ScoredResult(
            self.id,
            "ok",
            score=100,
            metrics={
                "injected": Metric(len(injected), "count", True, "injected nodes"),
                "valid_parents": Metric.boolean(True, "valid parents"),
            },
            raw=raw,
        )


@register
class ProbeDevforgeValidate(Test):
    id = "probe.devforge.validate"
    category = "probe"
    title = "Validator accept/reject"
    description = "Deterministic: accepts a valid op, rejects a nonexistent parent. No LLM."
    suites = ["everything", "devforge-layer", "chain-health", "fast"]

    async def run(self, ctx: Context) -> dict:
        scene = {"name": "Main", "type": "Node3D", "children": []}
        ops = [
            {"type": "add_node", "parent": "/root/Main", "node_type": "Node3D", "name": "Good"},
            {"type": "add_node", "parent": "/root/Ghost", "node_type": "Node3D", "name": "Bad"},
        ]
        return await ctx.devforge_call(
            "validate_spec",
            {"operations": ops, "scene_tree": scene},
            timeout_s=30,
        )

    def score(self, raw: dict) -> ScoredResult:
        valid_n = raw.get("valid_count", 0)
        err_n = raw.get("error_count", 0)
        errors = raw.get("errors", [])
        caught = any("Ghost" in str(e) for e in errors)

        if valid_n == 1 and caught:
            return ScoredResult(
                self.id,
                "ok",
                score=100,
                metrics={
                    "valid_count": Metric(valid_n, "count", True, "accepted"),
                    "error_count": Metric(err_n, "count", False, "rejected"),
                },
                raw=raw,
            )
        if valid_n == 2:
            return ScoredResult(
                self.id,
                "partial",
                score=50,
                metrics={
                    "valid_count": Metric(valid_n, "count", True, "accepted"),
                    "error_count": Metric(err_n, "count", False, "rejected"),
                },
                raw=raw,
            )
        return ScoredResult(
            self.id,
            "broke",
            score=0,
            metrics={
                "valid_count": Metric(valid_n, "count", True, "accepted"),
                "error_count": Metric(err_n, "count", False, "rejected"),
            },
            raw=raw,
            errors=[f"validator rejected the valid op (valid={valid_n})"],
        )


@register
class ProbeDevforgeRoundtrip(Test):
    id = "probe.devforge.roundtrip"
    category = "probe"
    title = "Scene view parity"
    description = "DevForge's scene tree matches godot-ai's for the same live scene."
    suites = ["everything", "devforge-layer", "fast"]

    async def run(self, ctx: Context) -> dict:
        # Godot scene paths
        h = await ctx.godot_ai("scene_get_hierarchy", {"depth": 10})
        godot_nodes = len([n for n in h.get("nodes", []) if isinstance(n, dict)])

        # DevForge scene via ctx
        d = await ctx.devforge_call("get_scene", {}, timeout_s=30)

        scene = d.get("scene", d)

        def _count(node):
            n = 1
            for ch in node.get("children") or []:
                n += _count(ch)
            return n

        df_n = _count(scene) if isinstance(scene, dict) and scene.get("name") else 0
        return {
            "devforge_nodes": df_n,
            "godot_nodes": godot_nodes,
            "devforge_root": scene.get("name") if isinstance(scene, dict) else None,
        }

    def score(self, raw: dict) -> ScoredResult:
        df_n = raw.get("devforge_nodes", 0)
        gd_n = raw.get("godot_nodes", 0)

        metrics = {
            "devforge_nodes": Metric(df_n, "count", True, "DevForge nodes"),
            "godot_nodes": Metric(gd_n, "count", True, "Godot nodes"),
        }

        if df_n == 0:
            return ScoredResult(
                self.id, "broke", score=0, metrics=metrics, raw=raw, errors=["DevForge returned no scene tree"]
            )
        if df_n == gd_n:
            return ScoredResult(self.id, "ok", score=100, metrics=metrics, raw=raw)
        return ScoredResult(
            self.id, "partial", score=round(min(df_n, gd_n) / max(df_n, gd_n, 1) * 100), metrics=metrics, raw=raw
        )


# ═══════════════════════════════════════════════════════════════════
# Layer 3: godot-ai probes
# ═══════════════════════════════════════════════════════════════════


@register
class ProbeGodotaiLatency(Test):
    id = "probe.godotai.latency"
    category = "probe"
    title = "Write round-trip latency"
    description = "Time to create + verify + delete a node through the editor bridge."
    suites = ["everything", "godotai-layer", "fast"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        await ctx.godot_ai("node_create", {"parent_path": "/Main", "type": "Node3D", "name": "ProbePing"})
        create_ms = int((time.time() - t0) * 1000)

        h = await ctx.godot_ai("scene_get_hierarchy", {"depth": 10})
        verified = any(n.get("path") == "/Main/ProbePing" for n in h.get("nodes", []) if isinstance(n, dict))

        t1 = time.time()
        await ctx.godot_ai("node_manage", {"op": "delete", "params": {"path": "/Main/ProbePing"}})
        delete_ms = int((time.time() - t1) * 1000)

        return {"create_ms": create_ms, "delete_ms": delete_ms, "verified": verified}

    def score(self, raw: dict) -> ScoredResult:
        create_ms = raw.get("create_ms", 0)
        delete_ms = raw.get("delete_ms", 0)
        verified = raw.get("verified", False)
        rt = create_ms + delete_ms

        metrics = {
            "create_ms": Metric(create_ms, "ms", False, "create"),
            "delete_ms": Metric(delete_ms, "ms", False, "delete"),
            "roundtrip_ms": Metric(rt, "ms", False, "round-trip"),
        }

        if not verified:
            return ScoredResult(self.id, "broke", score=0, metrics=metrics, raw=raw)
        if rt < 1500:
            return ScoredResult(self.id, "ok", score=100, metrics=metrics, raw=raw)
        if rt < 5000:
            return ScoredResult(self.id, "partial", score=60, metrics=metrics, raw=raw)
        return ScoredResult(self.id, "broke", score=20, metrics=metrics, raw=raw)


@register
class ProbeGodotaiFidelity(Test):
    id = "probe.godotai.fidelity"
    category = "probe"
    title = "Scene tree fidelity"
    description = "The editor returns a faithful, walkable hierarchy with a named root."
    suites = ["everything", "godotai-layer", "fast"]

    async def run(self, ctx: Context) -> dict:
        h = await ctx.godot_ai("scene_get_hierarchy", {"depth": 10})
        nodes = [n for n in h.get("nodes", []) if isinstance(n, dict)]
        root = nodes[0].get("name") if nodes else None
        return {
            "node_count": len(nodes),
            "root": root,
            "has_more": h.get("has_more"),
            "sample": [n.get("path") for n in nodes[:5]],
        }

    def score(self, raw: dict) -> ScoredResult:
        nodes = raw.get("node_count", 0)
        root = raw.get("root")

        metrics = {
            "nodes": Metric(nodes, "count", True, "scene nodes"),
        }

        if not nodes:
            return ScoredResult(
                self.id,
                "broke",
                score=0,
                metrics=metrics,
                raw=raw,
                errors=["empty hierarchy — no scene or broken editor link"],
            )
        if root != "Main":
            return ScoredResult(self.id, "partial", score=40, metrics=metrics, raw=raw)
        return ScoredResult(self.id, "ok", score=100, metrics=metrics, raw=raw)


# ═══════════════════════════════════════════════════════════════════
# Layer 4: runtime
# ═══════════════════════════════════════════════════════════════════


@register
class ProbeRuntimeLaunch(Test):
    id = "probe.runtime.launch"
    category = "probe"
    title = "Game actually runs"
    description = "Launches the disposable scene and reads FPS — proves the project boots."
    suites = ["everything", "runtime-layer"]
    needs_reset = True
    timeout_s = 600

    async def run(self, ctx: Context) -> dict:
        import asyncio as aio

        launched = False
        fps = 0
        capture_ready = False
        polls = 0
        try:
            await ctx.godot_ai("project_run", {"mode": "custom", "scene": "res://probe.tscn", "autosave": False})
            launched = True
            for polls in range(1, 7):
                await aio.sleep(1.5)
                try:
                    st = await ctx.godot_ai("editor_state", {})
                    capture_ready = bool(st.get("game_capture_ready"))
                except Exception:
                    pass
                try:
                    mon = await ctx.godot_ai(
                        "editor_manage",
                        {
                            "op": "monitors_get",
                            "params": {"monitors": ["time/fps"]},
                        },
                    )
                    mdata = mon.get("data", mon)
                    if isinstance(mdata, dict):
                        fps = mdata.get("time/fps", 0) or 0
                except Exception:
                    pass
                if fps and fps > 0:
                    break
        except Exception as e:
            return {"error": str(e), "launched": launched, "fps": fps}
        finally:
            try:
                await ctx.godot_ai("project_manage", {"op": "stop"})
            except Exception:
                pass
        return {
            "launched": launched,
            "fps": fps,
            "capture_ready": capture_ready,
            "polls": polls,
        }

    def score(self, raw: dict) -> ScoredResult:
        if raw.get("error"):
            return ScoredResult(
                self.id,
                "broke",
                score=0,
                metrics={
                    "fps": Metric(0, "count", True, "FPS"),
                },
                raw=raw,
                errors=[raw["error"]],
            )

        fps = raw.get("fps", 0)
        launched = raw.get("launched", False)
        metrics = {
            "fps": Metric(fps, "count", True, "FPS"),
            "launched": Metric.boolean(launched, "launched"),
        }

        if fps and fps > 0:
            return ScoredResult(self.id, "ok", score=100, metrics=metrics, raw=raw)
        if launched:
            return ScoredResult(self.id, "partial", score=40, metrics=metrics, raw=raw)
        return ScoredResult(self.id, "broke", score=0, metrics=metrics, raw=raw)


# ═══════════════════════════════════════════════════════════════════
# Layer 5: odysseus probes
# ═══════════════════════════════════════════════════════════════════


@register
class ProbeOdyPersona(Test):
    id = "probe.odysseus.persona"
    category = "probe"
    title = "Live persona is the real prompt"
    description = "The active persona is the full strategy prompt with MCP/no_think, not a husk."
    suites = ["everything", "odysseus-layer", "fast"]

    async def run(self, ctx: Context) -> dict:
        try:
            c = json.loads(PRESETS.read_text()).get("custom", {})
        except Exception as e:
            return {"error": str(e)}

        sp = c.get("system_prompt") or ""
        suf = c.get("inject_suffix", "") or ""
        temp = float(c.get("temperature", 1.0))
        return {
            "enabled": bool(c.get("enabled")),
            "system_prompt_chars": len(sp),
            "temperature": temp,
            "has_mcp": "mcp" in suf.lower(),
            "has_nothink": "/no_think" in suf,
            "character_name": c.get("character_name"),
        }

    def score(self, raw: dict) -> ScoredResult:
        if raw.get("error"):
            return ScoredResult(self.id, "broke", score=0, raw=raw, errors=[raw["error"]])

        enabled = raw.get("enabled", False)
        sp_chars = raw.get("system_prompt_chars", 0)
        temp = raw.get("temperature", 1.0)
        has_mcp = raw.get("has_mcp", False)
        has_nothink = raw.get("has_nothink", False)

        metrics = {
            "enabled": Metric.boolean(enabled, "enabled"),
            "prompt_chars": Metric(sp_chars, "count", True, "prompt size"),
            "temp": Metric(temp, "ratio", False, "temperature"),
        }

        if not enabled or sp_chars < 1000:
            return ScoredResult(
                self.id,
                "broke",
                score=0,
                metrics=metrics,
                raw=raw,
                errors=[f"persona husk — enabled={enabled}, prompt={sp_chars} chars"],
            )

        minor = []
        if not has_mcp:
            minor.append("'MCP' missing (tool retrieval won't run)")
        if not has_nothink:
            minor.append("/no_think missing")
        if temp > 0.35:
            minor.append(f"temp {temp} > 0.35")

        if minor:
            return ScoredResult(self.id, "partial", score=60, metrics=metrics, raw=raw)
        return ScoredResult(self.id, "ok", score=100, metrics=metrics, raw=raw)


@register
class ProbeOdyRetrieval(Test):
    id = "probe.odysseus.retrieval"
    category = "probe"
    title = "Tool retrieval surfaces apply_spec"
    description = "Odysseus's tool index returns apply_spec for a build request (else the model can't build)."
    suites = ["everything", "odysseus-layer"]
    timeout_s = 120

    async def run(self, ctx: Context) -> dict:
        try:
            c = json.loads(PRESETS.read_text()).get("custom", {})
        except Exception:
            c = {}
        query = f"{c.get('inject_prefix', '')} {CUBE_PROMPT} {c.get('inject_suffix', '')}".strip()
        script = (
            "import sys, json; sys.path.insert(0, '/app')\n"
            "out = {}\n"
            "try:\n"
            "    from src.tool_index import get_tool_index, COLLECTION_NAME\n"
            "    from src.embedding_lanes import build_embedding_lanes\n"
            "    mcp_in_coll = False; counts = {}\n"
            "    for ln in build_embedding_lanes(COLLECTION_NAME):\n"
            "        try:\n"
            "            ids = ln.collection.get().get('ids', [])\n"
            "            counts[ln.name] = len(ids)\n"
            "            if any('apply_spec' in str(i) or str(i).startswith('mcp__') for i in ids): mcp_in_coll = True\n"
            "        except Exception: pass\n"
            "    out['lane_counts'] = counts; out['mcp_in_collection'] = mcp_in_coll\n"
            "    idx = get_tool_index()\n"
            f"    out['retrieved'] = sorted(idx.get_tools_for_query({query!r}, 8)) if idx else []\n"
            "except Exception as e:\n"
            "    out['error'] = type(e).__name__ + ': ' + str(e)[:160]\n"
            "print(json.dumps(out))\n"
        )
        code, out = await ctx.sh("docker", "exec", ODY_CONTAINER, "python", "-c", script, timeout=90)
        if code != 0:
            return {"error": f"probe failed in container: {out.strip()[:200]}"}
        try:
            return json.loads(out.strip().splitlines()[-1])
        except Exception:
            return {"error": f"unparseable: {out.strip()[:200]}"}

    def score(self, raw: dict) -> ScoredResult:
        if raw.get("error"):
            return ScoredResult(self.id, "broke", score=0, raw=raw, errors=[raw["error"]])

        tools = raw.get("retrieved", [])
        mcp = [t for t in tools if t.startswith("mcp__")]
        apply_present = "mcp__devforge__apply_spec" in tools
        mcp_in_coll = raw.get("mcp_in_collection")

        metrics = {
            "tools_retrieved": Metric(len(tools), "count", True, "tools retrieved"),
            "mcp_tools": Metric(len(mcp), "count", True, "MCP tools in top-k"),
            "apply_spec": Metric.boolean(apply_present, "apply_spec present"),
        }

        if apply_present:
            return ScoredResult(self.id, "ok", score=100, metrics=metrics, raw=raw)
        if not mcp_in_coll:
            return ScoredResult(self.id, "partial", score=50, metrics=metrics, raw=raw)
        if mcp:
            return ScoredResult(self.id, "partial", score=30, metrics=metrics, raw=raw)
        return ScoredResult(
            self.id,
            "broke",
            score=0,
            metrics=metrics,
            raw=raw,
            errors=["MCP tools indexed but none retrieved for a build query"],
        )
