from __future__ import annotations

import time
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from devforge.platform.monitor import monitor
from devforge.platform.monitor.dashboard_api import router as dashboard_router

from devforge.knowledge.state.world_state import WorldState

from devforge.knowledge.system_graph.system_graph import SystemGraph
from devforge.knowledge.system_graph.graph_updater import GraphUpdater as SystemGraphUpdater
from devforge.knowledge.system_graph.snapshot_manager import ArchitectureSnapshotManager
from devforge.knowledge.system_graph.dependency_resolver import DependencyResolver

from devforge.compilation.pipeline.context_assembler import ContextAssembler
from devforge.compilation.pipeline.execution_planner import ExecutionPlanner
from devforge.compilation.pipeline.operation_generator import OperationGenerator
from devforge.compilation.pipeline.validator import OperationValidator
from devforge.compilation.pipeline.completeness import CompletenessChecker

from devforge.knowledge.ai.planning.planning_orchestrator import PlanningOrchestrator

from devforge.compilation.pipeline.architecture_validator import ArchitectureValidator

from devforge.compilation.pipeline.context_assembler import ContextAssembler

from devforge.infrastructure.llm.router import LLMRouter
from devforge.infrastructure.runtime_config import get_config


# ── Retry configuration ────────────────────────────────────────
# Mirrors the escalating retry pattern from PipelineEngine.
# Attempt 1 is full prompt; attempts 2+ feed error back;
# final attempt trims context to arch+scene only.
# Retry count comes from RuntimeConfig.max_plan_retries (default 3).


# ------------------------------------------------------------
# Setup
# ------------------------------------------------------------

app = FastAPI(title="DevForge Server")

app.include_router(dashboard_router)

LLMRouter.configure_llama()

# Correct repo root
REPO_ROOT = Path(__file__).resolve().parents[3]

GAME_ROOT = REPO_ROOT / "dev-forge"

DEVFORGE_DIR = REPO_ROOT / ".devforge"
DEVFORGE_DIR.mkdir(exist_ok=True)

GRAPH_FILE = DEVFORGE_DIR / "system_graph.json"


# ------------------------------------------------------------
# Static files (UI)
# ------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/dashboard")
def dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/favicon.ico")
def favicon():
    path = STATIC_DIR / "favicon.ico"
    if path.exists():
        return FileResponse(path)
    return {}


# ------------------------------------------------------------
# Core runtime systems
# ------------------------------------------------------------

_world_state = WorldState.load(REPO_ROOT)

# ------------------------------------------------------------
# System Graph
# ------------------------------------------------------------

_system_graph = SystemGraph()

if GRAPH_FILE.exists():
    try:
        with open(GRAPH_FILE) as f:
            data = json.load(f)
            _system_graph.load_dict(data)
    except Exception:
        pass

_system_graph_updater = SystemGraphUpdater(_system_graph)

# Architecture intelligence
_dependency_resolver = DependencyResolver(_system_graph)
_snapshot_manager = ArchitectureSnapshotManager()

# Planning systems
_planner = PlanningOrchestrator()
_execution_planner = ExecutionPlanner(_system_graph)

# Generation
_operation_generator = OperationGenerator()
_validator = OperationValidator()
_completeness = CompletenessChecker()

# Architecture QA
_arch_validator = ArchitectureValidator()

# Incremental context
_context_assembler = ContextAssembler(
    GAME_ROOT,
    system_graph=_system_graph,
)

_session_log: list[dict[str, Any]] = []
_recent_prompts: list[str] = []


# ------------------------------------------------------------
# Request Models
# ------------------------------------------------------------


class GenerateRequest(BaseModel):
    prompt: str
    scene_tree: dict[str, Any]


class ReportRequest(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list)


# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------


def _dedupe_files(files: list[dict]) -> list[dict]:

    seen = set()
    result = []

    for f in files:
        path = f.get("path")

        if not path:
            continue

        if path in seen:
            continue

        seen.add(path)
        result.append(f)

    return result


def _dedupe_operations(ops: list[dict]) -> list[dict]:

    seen = set()
    result = []

    for op in ops:
        key = tuple(sorted(op.items()))

        if key in seen:
            continue

        seen.add(key)
        result.append(op)

    return result


def _save_graph():

    try:
        with open(GRAPH_FILE, "w") as f:
            json.dump(_system_graph.to_dict(), f, indent=2)
    except Exception:
        pass


# ------------------------------------------------------------
# Health
# ------------------------------------------------------------


@app.get("/")
def health():

    return {
        "status": "DevForge server running",
        "dashboard": "http://localhost:8000/dashboard",
        "session_ops": len(_session_log),
    }


# ------------------------------------------------------------
# Generate
# ------------------------------------------------------------


@app.post("/generate")
def generate(req: GenerateRequest):

    trace = monitor.begin_trace(req.prompt)

    try:
        start = time.time()

        scene_tree = req.scene_tree

        if scene_tree.get("name") != "root":
            scene_tree = {
                "name": "root",
                "type": "Node",
                "children": [scene_tree],
            }

        # Snapshot before planning
        _snapshot_manager.create_snapshot(_system_graph, "before_plan")

        # ------------------------------------------------
        # Context assembly
        # ------------------------------------------------

        assembler = ContextAssembler(
            GAME_ROOT,
            system_graph=_system_graph,
            history=_recent_prompts,
        )

        context = assembler.assemble(scene_tree, req.prompt)

        context += "\n\n" + _incremental_context.build_context()

        # ------------------------------------------------
        # Planning — with escalating retry
        # ------------------------------------------------

        steps = None
        retry_errors: list[str] = []
        retry_prompt = req.prompt
        retry_context = context

        max_retries = get_config().max_plan_retries
        for attempt in range(1, max_retries + 1):
            try:
                steps = _planner.plan(
                    prompt=retry_prompt,
                    context=retry_context,
                    llm=LLMRouter.generate,
                )
                if steps:
                    break
                retry_errors.append("Planner returned empty steps")
            except (RuntimeError, ValueError) as exc:
                retry_errors.append(str(exc))

            if attempt == max_retries:
                monitor.log_error(
                    trace,
                    f"Planning failed after {attempt} attempts: " + "; ".join(retry_errors),
                )
                monitor.end_trace(trace, status="error")
                return {
                    "files": [],
                    "operations": [],
                    "error": f"Planning failed: {'; '.join(retry_errors)}",
                }

            # Escalation: trim context on retry, feed back error
            retry_prompt = f"{req.prompt}\n\nThe previous plan failed: {retry_errors[-1]}. Fix only those issues."
            retry_context = assembler.assemble(scene_tree, retry_prompt, minimal=(attempt >= 2))
            monitor.log_step(
                trace,
                f"planning_retry_{attempt}",
                {"context_chars": len(retry_context)},
            )

        steps = _execution_planner.plan_execution(steps)

        # ------------------------------------------------
        # Operation generation
        # ------------------------------------------------

        result = _operation_generator.generate_from_steps(
            steps=steps,
            scene=scene_tree,
        )

        files = result.get("files", [])
        operations = result.get("operations", [])

        files = _dedupe_files(files)
        operations = _dedupe_operations(operations)

        operations = _completeness.enforce(
            files,
            operations,
            scene_tree,
        )

        # ------------------------------------------------
        # Validation
        # ------------------------------------------------

        operations, errors = _validator.validate(
            operations,
            scene_tree,
            files,
        )

        if errors:
            monitor.log_warning(trace, "validation_failed", {"errors": errors})

        # ------------------------------------------------
        # Architecture validation
        # ------------------------------------------------

        arch_issues = _arch_validator.validate(_system_graph)

        if arch_issues:
            _snapshot_manager.restore_last(_system_graph)

            monitor.log_warning(trace, "architecture_rollback", {"issues": arch_issues})

        # ------------------------------------------------
        # Track files
        # ------------------------------------------------

        for f in files:
            path = f.get("path")

            if path:
                _world_state.register_file(path, created_by_step="prompt")

        _world_state.save(REPO_ROOT)

        for op in operations:
            _incremental_context.record_operation(op)

        _recent_prompts.append(req.prompt)

        if len(_recent_prompts) > 5:
            _recent_prompts.pop(0)

        elapsed = time.time() - start

        session_entry = {
            "timestamp": time.time(),
            "trace_id": trace.trace_id,
            "prompt": req.prompt,
            "files": files,
            "operations": operations,
            "elapsed_ms": int(elapsed * 1000),
        }

        _session_log.append(session_entry)

        monitor.end_trace(
            trace,
            status="complete",
            files_count=len(files),
            ops_count=len(operations),
        )

        return {
            "files": files,
            "operations": operations,
        }

    except Exception as exc:
        monitor.log_error(trace, f"Generate failed: {exc}")

        monitor.end_trace(trace, status="error")

        return {"files": [], "operations": []}


# ------------------------------------------------------------
# Report
# ------------------------------------------------------------


@app.post("/report")
def report(req: ReportRequest):

    successes = 0
    failures = 0

    for r in req.results:
        status = r.get("status")

        if status == "ok":
            successes += 1
        else:
            failures += 1

    if _session_log:
        last = _session_log[-1]

        if successes > 0:
            for op in last.get("operations", []):
                _system_graph_updater.apply_operation(op)

        _save_graph()

    return {
        "received": len(req.results),
        "successes": successes,
        "failures": failures,
    }


# ------------------------------------------------------------
# Status
# ------------------------------------------------------------


@app.get("/status")
def status():

    return {
        "world_state": _world_state.get_summary(),
        "system_graph": {
            "nodes": len(_system_graph.nodes),
            "edges": len(_system_graph.edges),
        },
        "snapshots": _snapshot_manager.list_snapshots(),
        "session": {
            "total_requests": len(_session_log),
            "recent": _session_log[-5:] if _session_log else [],
        },
    }
