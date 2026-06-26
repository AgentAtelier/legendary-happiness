"""DevForge Server — Year 1 Stable Prototype.

This is the main entry point. Run with:
    uvicorn devforge.platform.server.server:app --reload --port 8000

The pipeline:
    1. Godot plugin sends POST /generate with prompt + scene_tree
    2. Context assembler builds LLM context
    3. Architecture planner (LLM) generates delta
    4. Architecture compiler (deterministic) converts to IR steps
    5. Operation generator compiles IR to Godot operations
    6. Completeness checker injects required nodes
    7. Validator filters invalid operations
    8. Repair engine fixes common issues
    9. Server returns {files, operations} to Godot
    10. Godot executes and sends POST /report with results
"""

from __future__ import annotations

import time
import traceback
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from devforge.compilation.pipeline.engine import PipelineEngine
from devforge.execution import DevForgePluginExecutor, ExecutionResult, Executor, GodotAIMCPExecutor
from devforge.infrastructure.llm.router import LLMRouter
from devforge.infrastructure.logger import logger
from devforge.infrastructure.runtime_config import RuntimeConfig, get_config, set_config
from devforge.knowledge.system_graph.graph_updater import GraphUpdater
from devforge.knowledge.system_graph.system_graph import SystemGraph
from devforge.platform.monitor import monitor
from devforge.reasoning.ai.planning.lru_cache import LRUPlanCache

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# App Setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

app = FastAPI(title="DevForge Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Startup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_config = get_config()
_llm = LLMRouter.get()
_system_graph = SystemGraph()
_graph_updater = GraphUpdater(_system_graph)

# Phase 10: plan cache and grammar for performance
_plan_cache = LRUPlanCache(max_entries=100)
_grammar_path = None  # Will be set from config or discovered

# Pipeline engine (shared with MCP server)
_engine: PipelineEngine | None = None

# Executor (backend selected via config / env)
_executor: Executor | None = None

# State
_session_log: list[dict[str, Any]] = []


def _create_executor(config: RuntimeConfig) -> Executor:
    """Instantiate the executor backend from config."""
    backend = config.executor_backend

    if backend == "godot_ai_mcp":
        logger.info("server", f"Using godot-ai MCP executor: {config.godot_ai_mcp_url}")
        return GodotAIMCPExecutor(mcp_url=config.godot_ai_mcp_url)

    logger.info("server", "Using DevForge plugin executor (default)")
    return DevForgePluginExecutor()


@app.on_event("startup")
def startup():
    global _executor, _engine
    config = get_config()

    if config.llm_backend == "claude":
        _llm.configure_claude()
    elif config.llm_backend == "mock":
        _llm.configure_mock()
    else:
        # ── Safety (S3): auto-generate grammar from GODOT_NODE_TYPES
        grammar_path = config.llama_grammar_path
        if not grammar_path:
            from devforge.knowledge.scene.godot_node_types import generate_grammar_file

            grammar_path = generate_grammar_file()
            logger.info("server", "Generated grammar from GODOT_NODE_TYPES", path=grammar_path)

        _llm.configure_llama(
            endpoint=config.llama_endpoint,
            grammar_path=grammar_path,
            temperature=config.llama_temperature,
            max_tokens=config.llama_max_tokens,
            timeout_s=config.llm_timeout_s,
            prompt_template=config.llm_prompt_template,
        )

        # Verify the grammar is enforced before accepting requests.
        # GBNF enforcement is unreliable across model families /
        # quantizations, so we warn instead of refusing to start.
        if not _llm._backend.selftest_grammar():
            logger.warn(
                "server",
                "Grammar self-test FAILED — llama.cpp is not enforcing "
                "the GBNF grammar.  Generation will proceed without "
                "grammar constraints; post-generation validation will "
                "catch malformed output.",
            )

        # Clamp the context budget to the server's real window
        # (must happen before the engine builds its ContextAssembler)
        from devforge.infrastructure.llm.llama_client import apply_server_limits

        apply_server_limits(config, _llm._backend)

    _executor = _create_executor(config)

    # Phase 10: discover grammar path for planner
    grammar_path = config.llama_grammar_path or None
    if not grammar_path:
        # Try default location
        import os

        default_grammar = os.path.join(
            os.path.dirname(__file__), "..", "..", "reasoning", "prompts", "arch_planner.gbnf"
        )
        if os.path.exists(default_grammar):
            grammar_path = default_grammar

    _engine = PipelineEngine(
        llm=_llm,
        system_graph=_system_graph,
        config=config,
        plan_cache=_plan_cache,
        grammar_path=grammar_path,
    )

    # Phase 6 (N3): Cache warming — pre-populate with pattern deltas
    warmed = _plan_cache.warm_from_patterns()
    if warmed > 0:
        logger.info("server", f"Plan cache warmed with {warmed} pattern entries")

    # One-time: resolve Godot property serialization types
    # (Vector3, Color, resource paths) so compiler emits correct values.
    hints = _executor.resolve_property_types({})
    if hints:
        config.property_serialization = hints
        set_config(config)
        logger.info("server", "Property serialization hints stored in config", hints=hints)

    logger.info(
        "server",
        "DevForge server started",
        backend=_llm.backend_name,
        executor=_executor.backend_name,
        game_root=str(config.game_root),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Request/Response Models
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GenerateRequest(BaseModel):
    prompt: str
    scene_tree: dict[str, Any] = Field(default_factory=dict)
    temperature: float | None = None
    planner: str | None = None
    skip_cache: bool = False


class ReportRequest(BaseModel):
    prompt: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    scene: dict[str, Any] = Field(default_factory=dict)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Health
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@app.get("/")
def health():
    return {
        "status": "ok",
        "service": "DevForge Server",
        "llm_backend": _llm.backend_name,
        "llm_configured": _llm.is_configured,
        "session_ops": len(_session_log),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Generate
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@app.post("/generate")
def generate(req: GenerateRequest):
    trace = monitor.begin_trace(req.prompt)
    start = time.time()

    try:
        if _engine is None:
            raise RuntimeError("Pipeline engine not initialized")

        # ── Phases 1-7: Shared Pipeline Engine ──
        monitor.log_step(trace, "pipeline")
        pipeline = _engine.run_pipeline(
            req.prompt,
            req.scene_tree,
            temperature=req.temperature,
            planner=req.planner,
            skip_cache=req.skip_cache,
        )

        # Phase 10: Record per-stage latencies in trace
        for stage_name, stage_ms in pipeline.stage_latencies.items():
            monitor.log_step(trace, stage_name, {"elapsed_ms": round(stage_ms, 1)})

        if pipeline.errors and not pipeline.operations:
            # Pipeline failed entirely (e.g. LLM not configured)
            monitor.end_trace(trace, status="error")
            return {
                "files": [],
                "operations": [],
                "error": "; ".join(pipeline.errors),
                "trace_id": trace.trace_id,
            }

        scene_tree = pipeline.scene_tree
        files = pipeline.files
        operations = pipeline.operations

        monitor.log_step(
            trace,
            "pipeline_result",
            {
                "files": len(files),
                "operations": len(operations),
            },
        )

        # ── Phase 8: Execute ──
        monitor.log_step(trace, "execution")
        exec_result = (
            _executor.execute(operations, files, scene_tree)
            if _executor
            else ExecutionResult(success=True, results=[], errors=["Executor not initialized"])
        )

        if exec_result.errors:
            monitor.log_warning(trace, "execution_errors", {"errors": exec_result.errors})

        # ── Track state ──
        _engine.update_history(req.prompt)

        elapsed = time.time() - start

        session_entry = {
            "trace_id": trace.trace_id,
            "prompt": req.prompt,
            "files_count": len(files),
            "ops_count": len(operations),
            "elapsed_ms": int(elapsed * 1000),
        }
        _session_log.append(session_entry)

        monitor.end_trace(
            trace,
            status="complete",
            files_count=len(files),
            ops_count=len(operations),
            cache_hits=pipeline.cache_stats.get("hits", 0),
            cache_misses=pipeline.cache_stats.get("misses", 0),
            cache_hit_rate=pipeline.cache_stats.get("hit_rate", 0),
        )

        executor_name = _executor.backend_name if _executor else "uninitialized"

        logger.info(
            "server",
            "Generate complete",
            files=len(files),
            operations=len(operations),
            executor=executor_name,
            elapsed_ms=int(elapsed * 1000),
        )

        return {
            "files": files,
            "operations": operations,
            "trace_id": trace.trace_id,
            "executor": executor_name,
            "execution": exec_result.to_dict(),
        }

    except Exception as exc:
        tb = traceback.format_exc()
        monitor.log_error(trace, f"Generate failed: {exc}")
        monitor.end_trace(trace, status="error")

        logger.error("server", f"Generate failed: {exc}\n{tb}")

        return {
            "files": [],
            "operations": [],
            "error": str(exc),
            "trace_id": trace.trace_id,
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Report
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@app.post("/report")
def report(req: ReportRequest):
    successes = 0
    failures = 0

    for r in req.results:
        if r.get("success", False):
            successes += 1
            # Update system graph with successful operations
            op = r.get("operation", {})
            if op:
                _graph_updater.apply_operation(op)
        else:
            failures += 1

    # Feed results to plugin executor for context tracking
    if isinstance(_executor, DevForgePluginExecutor):
        _executor.apply_report(req.results, req.scene)

    logger.info("server", f"Report: {successes} ok, {failures} failed")

    return {
        "received": len(req.results),
        "successes": successes,
        "failures": failures,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Status & Debug Endpoints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@app.get("/status")
def status():
    return {
        "system_graph": _system_graph.to_dict(),
        "session": {
            "total_requests": len(_session_log),
            "recent": _session_log[-5:] if _session_log else [],
        },
        "monitor": monitor.get_stats(),
        "cache": _plan_cache.stats() if _plan_cache else {},
        "grammar": bool(_engine.grammar) if _engine else False,
    }


@app.get("/perf")
def perf():
    """Phase 10: Per-stage performance stats."""
    perf_stats = monitor.get_perf_stats()
    cache_stats = _plan_cache.stats() if _plan_cache else {}
    return {
        **perf_stats,
        "cache": cache_stats,
        "grammar": bool(_engine.grammar) if _engine else False,
    }


@app.get("/traces")
def traces(limit: int = 50):
    return {"traces": monitor.get_traces(limit)}


@app.get("/logs")
def logs(limit: int = 100, component: str | None = None):
    return {"logs": logger.get_recent(limit)}
