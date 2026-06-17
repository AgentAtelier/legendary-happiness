"""DevForge MCP Server — exposes the pipeline as MCP tools.

Run with::

    mcp dev devforge/platform/mcp_server.py --transport sse

Or programmatically::

    python -c "from devforge.platform.mcp_server import mcp; mcp.run(transport='sse')"

This exposes three tools that Odysseus or any MCP client can call:

    apply_spec   — run the full pipeline and return operations
    validate_spec — validate a set of operations against a scene
    get_scene    — return the current scene hierarchy

Registered in Odysseus via its admin Settings UI (not a static JSON file).
"""

from __future__ import annotations

# ── MCP Server ──────────────────────────────────────────────────
import os as _os
import threading
import uuid
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

from devforge.auditing.scene_doctor import SceneDoctor
from devforge.companion.companion import DesignCompanion
from devforge.compilation.pipeline.engine import PipelineEngine
from devforge.dialogue.dialogue import validate_dialogue_file
from devforge.execution import DevForgePluginExecutor, Executor, GodotAIMCPExecutor
from devforge.forge.template_engine import instantiate_template, list_templates, load_template, preview_template
from devforge.harness.scaffolder import scaffold_file
from devforge.infrastructure.llm.router import LLMRouter
from devforge.infrastructure.logger import logger
from devforge.infrastructure.runtime_config import get_config
from devforge.journal.journal import Journal
from devforge.knowledge.artifact_store import ArtifactStore
from devforge.knowledge.scene.scene_store import SceneStore
from devforge.knowledge.system_graph.system_graph import SystemGraph
from devforge.lint.linter import lint_file as run_lint_file
from devforge.lore.lorekeeper import (
    list_schemas as lore_list_schemas,
    load_data_file,
    load_schema,
    validate_data,
    validate_integrity,
)
from devforge.mapper.signal_mapper import SignalMapper
from devforge.navigator.navigator import search_project
from devforge.operations.batch_filter import build_batch_ops, match_nodes, parse_query
from devforge.polish.polish_pass import run_polish_pass
from devforge.quests.validator import validate_quest_file
from devforge.reasoning.ai.planning.lru_cache import LRUPlanCache
from devforge.refactorer.refactorer import SceneRefactorer, list_extractable
from devforge.runner.smoke_runner import SmokeRunner, build_poi
from devforge.sentinel.sentinel import PerformanceSentinel
from devforge.simulator.simulator import evaluate_encounter
from devforge.triage.triage import triage_text

mcp = FastMCP(
    "DevForge",
    host=_os.environ.get("MCP_HOST", "127.0.0.1"),
    port=int(_os.environ.get("MCP_PORT", "8001")),
)

# ── Shared pipeline engine ──────────────────────────────────────
_config = get_config()
_llm = LLMRouter.get()
_system_graph = SystemGraph()
_scene_store: SceneStore | None = None
_artifact_store: ArtifactStore | None = None
_journal: Journal | None = None
_sentinel: PerformanceSentinel | None = None
_engine: PipelineEngine | None = None
_executor: Executor | None = None

# ── Pipeline serialisation (M3) ────────────────────────────────
# Concurrent apply_spec calls share one engine, system_graph, and
# assembler history.  Because turns are seconds-long and the shared
# state is large, serialisation is correct here — a threading.Lock
# ensures only one pipeline runs at a time.
#
# C5: Lock acquisition has a timeout so a wedged pipeline call fails
# loudly (raises RuntimeError) instead of hanging the server forever.
_pipeline_lock = threading.Lock()
_LOCK_TIMEOUT = 300  # seconds — longer than worst-case apply_spec


def _acquire_pipeline_lock():
    """Acquire the pipeline lock with a timeout."""
    if not _pipeline_lock.acquire(timeout=_LOCK_TIMEOUT):
        raise RuntimeError(
            f"Pipeline lock acquisition timed out after {_LOCK_TIMEOUT}s — "
            f"a prior apply_spec call may be wedged. Restart DevForge."
        )


def _acquire_pipeline_lock_ctx():
    """Context manager wrapper for pipeline lock with timeout."""
    return _TimedLockContext()


class _TimedLockContext:
    def __enter__(self):
        _acquire_pipeline_lock()
        return self

    def __exit__(self, *args):
        _pipeline_lock.release()


def _init():
    """Lazy-init the engine, executor, and scene store on first tool call.

    Thread-safe: only one caller initialises; others wait on the lock
    and then return immediately when _engine is already set.
    """
    global _engine, _executor, _scene_store, _artifact_store, _journal, _sentinel

    if _engine is not None:
        return

    with _acquire_pipeline_lock_ctx():
        # Double-check after acquiring the lock
        if _engine is not None:
            return

        config = _config

        # Grammar path is set when the llama backend is configured below; the
        # PipelineEngine needs it so the ArchitecturePlanner constrains its
        # output. Without this the planner ran UNCONSTRAINED (the instance
        # grammar on the llama client did not survive the router), so the
        # model free-generated for ~50s and returned empty deltas.
        grammar_path: str | None = None

        # Configure LLM
        if config.llm_backend == "claude":
            _llm.configure_claude()
        elif config.llm_backend == "mock":
            _llm.configure_mock()
        else:
            # ── Safety (S3): generate GBNF grammar from GODOT_NODE_TYPES
            # at startup so the grammar and validator can never drift.
            # Refuse to start the llama backend without a grammar — the
            # default is constrained generation; env vars can loosen it,
            # never the other way around.
            grammar_path = config.llama_grammar_path
            if not grammar_path:
                from devforge.knowledge.scene.godot_node_types import generate_grammar_file

                grammar_path = generate_grammar_file()
                logger.info("mcp_server", "Generated grammar from GODOT_NODE_TYPES", path=grammar_path)

            _llm.configure_llama(
                endpoint=config.llama_endpoint,
                grammar_path=grammar_path,
                temperature=config.llama_temperature,
                max_tokens=config.llama_max_tokens,
                timeout_s=config.llm_timeout_s,
                prompt_template=config.llm_prompt_template,
            )

            # ── Safety (S3): verify the grammar is actually enforced.
            # A broken GBNF is silently ignored by llama.cpp — this test
            # catches that failure at startup.  However, GBNF enforcement
            # is unreliable across model families / quantizations, so we
            # warn instead of refusing to start.  Post-generation JSON
            # validation in the pipeline still catches malformed output.
            if not _llm._backend.selftest_grammar():
                logger.warn(
                    "mcp_server",
                    "Grammar self-test FAILED — llama.cpp is not enforcing "
                    "the GBNF grammar.  Generation will proceed without "
                    "grammar constraints; post-generation validation will "
                    "catch malformed output.",
                )

            # Clamp the context budget to the server's real window
            # (must happen before the engine builds its ContextAssembler)
            from devforge.infrastructure.llm.llama_client import apply_server_limits

            apply_server_limits(config, _llm._backend)

        # Executor
        backend = config.executor_backend
        if backend == "godot_ai_mcp":
            _executor = GodotAIMCPExecutor(mcp_url=config.godot_ai_mcp_url)
        elif backend == "devforge_plugin":
            # Plugin executor is not usable over MCP — fail loudly rather
            # than silently producing operations that can't be applied.
            raise RuntimeError(
                "executor_backend='devforge_plugin' is not supported via MCP. "
                "Set DEVFORGE_EXECUTOR_BACKEND=godot_ai_mcp to use the "
                "godot-ai MCP backend for execution."
            )
        else:
            _executor = DevForgePluginExecutor()

        # Scene store — tracks scene version for staleness detection.
        # Every pipeline run fetches fresh scene + version through this;
        # before execution, the scene is rechecked and the plan is re-run
        # if the world moved during planning.
        _scene_store = SceneStore()

        # Artifact store — caches full pipeline results so apply_spec can
        # return a compact summary instead of the full payload.  The LLM
        # fetches details on demand via read_artifact.
        _artifact_store = ArtifactStore()

        # Progress journal — append-only event log (WO-007).
        # Every tool that reads or mutates the scene emits a timestamped
        # entry, giving the user a time-series history of their project.
        _journal = Journal()

        # Performance sentinel — in-memory sample ring buffer (WO-010).
        # Collects Godot performance metrics on demand so the user can
        # profile their game during development.
        _sentinel = PerformanceSentinel()

        # Plan cache with pattern warming
        _plan_cache = LRUPlanCache(max_entries=100)
        _plan_cache.warm_from_patterns()

        # Pipeline engine
        _engine = PipelineEngine(
            llm=_llm,
            system_graph=_system_graph,
            config=config,
            plan_cache=_plan_cache,
            grammar_path=grammar_path,
        )

        logger.info(
            "mcp_server", "DevForge MCP server initialized", backend=_llm.backend_name, executor=_executor.backend_name
        )


# ── Tools ───────────────────────────────────────────────────────


@mcp.tool()
def apply_spec(
    prompt: str,
    scene_tree: Dict[str, Any] | None = None,
    temperature: float | None = None,
    planner: str | None = None,
    skip_cache: bool = False,
) -> Dict[str, Any]:
    """Build or modify the Godot scene from a natural-language request.

    Creates, modifies, or deletes nodes, meshes, cubes, boxes, spheres
    (MeshInstance3D with meshes), lights (DirectionalLight3D, OmniLight3D),
    cameras, ground/floor planes, materials, collision shapes, GDScript
    scripts — plans, validates, executes in the live Godot editor, and
    verifies the result in one call.

    If the scene changes between planning and execution (e.g. the
    user saved in Godot or another agent modified the scene), the
    tool automatically replans against the fresh snapshot so the
    operations are never applied to a stale world model.

    Use this for ANY scene modification request: "create a cube",
    "add a light above the ground", "delete the player node",
    "attach a rotation script to the cube", "move the camera to
    position 5,2,10".

    Arguments (literal JSON you can pass):
        {
          "prompt": "Add a red cube (MeshInstance3D with BoxMesh) in the center of the ground plane at position 0,0,0",
          "scene_tree": {"name": "Main", "type": "Node3D", "children": [...]},
          "temperature": 0.2,
          "planner": "layout",
          "skip_cache": false
        }

    Set ``temperature`` to override the default (0.2) per-call — useful
    for gauntlet runs where you want low-temperature deterministic output.
    Omit to use the pipeline's configured default.

    Set ``planner`` to "layout" to route spatial room-building prompts
    through the deterministic spatial compiler (greybox assets, AABB
    collision avoidance).  Set ``planner`` to "building" to route to
    the BSP multi-room building engine (split trees → walled rooms).
    Set ``planner`` to "scatter" for outdoor garden/forest placement.
    Set ``planner`` to "ssp" for semantic room generation with
    archetype defaults.  Set ``planner`` to "room" for Intent Descriptor
    room generation (richer LLM brief).  Omit to use the pipeline's
    configured default (usually "arch", the LLM-driven architecture
    planner).

    Set ``skip_cache`` to true to bypass the plan cache — required for
    repeat-diversity diagnostics (Move 1) to avoid cache replay.

    Returns a summary dict — compact so it doesn't bloat context.
    Call ``read_artifact`` with the returned artifact_id to get full
    file contents, operation details, and execution diagnostics.

        {
          "artifact_id": "a1b2c3d4e5f6",
          "applied": 3,
          "operations_total": 3,
          "files": ["scripts/guard.gd"],
          "errors": [],
          "error_count": 0,
          "scene_version": 12,
          "has_full_detail": true
        }
    """
    _init()

    # Generate turn_id for per-turn token budget tracking (Phase 2).
    # All LLM calls within this apply_spec carry this ID so the gateway
    # can enforce a cumulative token budget across planning, compilation,
    # and verification.
    turn_id = uuid.uuid4().hex
    _llm.set_turn_id(turn_id)
    try:
        return _apply_spec_impl(prompt, scene_tree, temperature, planner, skip_cache)
    finally:
        _llm.clear_turn_id()


def _apply_spec_impl(
    prompt: str,
    scene_tree: Dict[str, Any] | None = None,
    temperature: float | None = None,
    planner: str | None = None,
    skip_cache: bool = False,
) -> Dict[str, Any]:
    """Internal implementation — called with turn_id already set.

    Serialised by ``_pipeline_lock`` so concurrent ``apply_spec`` calls
    don't corrupt the shared engine, system_graph, or assembler history.
    """
    with _acquire_pipeline_lock_ctx():
        # Warn if using plugin executor via MCP (it won't actually execute)
        if isinstance(_executor, DevForgePluginExecutor):
            full_payload = {
                "files": [],
                "operations": [],
                "errors": [
                    "DevForgePluginExecutor is not supported via MCP — "
                    "operations cannot be applied. Set DEVFORGE_EXECUTOR_BACKEND="
                    "godot_ai_mcp to use the godot-ai MCP backend for execution."
                ],
                "arch_delta": {},
                "scene_version": 0,
                "execution": None,
            }
            artifact_id = _artifact_store.store(full_payload)
            return _artifact_store.build_summary(artifact_id, full_payload)

        # ── SceneStore flow: fetch → plan → recheck → execute ──
        # The scene may change between when we read it and when we apply
        # operations.  The SceneStore tracks a version counter that bumps
        # on every content change; we stamp plans with their source version
        # and recheck before execution.

        MAX_REPLANS = 2  # cap replanning to avoid infinite loops

        # Use caller-supplied scene_tree only on first iteration; replans
        # always fetch fresh from Godot.
        current_scene: Dict[str, Any] | None = scene_tree

        for replan in range(MAX_REPLANS + 1):
            # Fetch fresh scene + version
            live_scene, live_version = _scene_store.get_or_fetch(_executor)

            # If the caller passed a scene_tree and it differs from what
            # we just fetched (or we have no live snapshot), use the live one.
            if current_scene is None:
                current_scene = live_scene
            elif replan > 0:
                # Replan iteration: always use the fresh live scene.
                current_scene = live_scene

            logger.info(
                "mcp_server",
                f"apply_spec: planning against v{live_version} (replan={replan}/{MAX_REPLANS})",
            )

            # Run pipeline
            result = _engine.run_pipeline(
                prompt,
                current_scene,
                scene_version=live_version,
                temperature=temperature,
                planner=planner,
                skip_cache=skip_cache,
            )
            _engine.update_history(prompt)

            # Recheck staleness before execution
            if replan < MAX_REPLANS:
                # Re-fetch to see if the scene moved during planning
                _recheck_scene, _recheck_version = _scene_store.get_or_fetch(_executor)
                if _recheck_version != live_version:
                    logger.info(
                        "mcp_server",
                        f"Scene moved during planning (v{live_version} → v{_recheck_version}) — replanning",
                    )
                    current_scene = _recheck_scene
                    continue

            # Execute whenever there are valid operations. Pipeline errors
            # (validator drops, compiler semantic warnings) are informational —
            # the bad ops were already filtered; only valid ops remain.
            # Skipping execution on any error defeated the validator's purpose
            # (Slice 4, 2026-06-15: semantic errors blocked G8 filler creation).
            if result.operations:
                exec_result = _executor.execute(
                    result.operations,
                    result.files,
                    current_scene,
                )
                # Only bump the version if execution actually succeeded.
                # Bumping on failure would force an unnecessary refetch
                # when the scene hasn't actually changed.
                if exec_result and exec_result.success:
                    _scene_store.note_writes()
            else:
                exec_result = None

            # Store full payload and return compact summary
            full_payload = {
                "files": result.files,
                "operations": result.operations,
                "errors": result.errors,
                "scene_version": result.scene_version,
                "arch_delta": result.arch_delta,
                "execution": exec_result.to_dict() if exec_result else None,
                "quality_warnings": result.quality_warnings,
            }
            artifact_id = _artifact_store.store(full_payload)
            return _artifact_store.build_summary(artifact_id, full_payload)


@mcp.tool()
def validate_spec(
    operations: List[Dict[str, Any]],
    scene_tree: Dict[str, Any],
    files: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Validate a batch of Godot operations against a scene tree without executing them.

    Call this when you have a candidate plan and want to check it for
    ordering errors, invalid node types, or missing parents before you
    call apply_spec. The tool returns the list of errors it found; it
    does not modify the scene.

    Arguments (literal JSON you can pass):
        {
          "operations": [
            {"type": "add_node", "parent": "/root/Main", "node_type": "Camera3D", "name": "MainCamera"}
          ],
          "scene_tree": {"name": "Main", "type": "Node3D", "children": []},
          "files": []
        }

    Returns a dict with these keys:
        {
          "valid": true,
          "errors": [],
          "valid_count": 1,
          "error_count": 0
        }
    """
    _init()

    # Generate turn_id for per-turn token budget tracking.
    # validate_spec may trigger LLM verifications via the pipeline
    # engine — those calls should carry a budget context and are
    # serialised under the pipeline lock.
    turn_id = uuid.uuid4().hex
    _llm.set_turn_id(turn_id)
    try:
        with _acquire_pipeline_lock_ctx():
            valid_ops, errors = _engine.validate_pipeline(
                operations,
                scene_tree,
                files or [],
            )
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "valid_count": len(valid_ops),
            "error_count": len(errors),
        }
    finally:
        _llm.clear_turn_id()


@mcp.tool()
def get_scene() -> Dict[str, Any]:
    """Read and inspect the current Godot scene tree from the live editor.

    Returns the full scene hierarchy: root node, all children with types
    and names, nested subtrees. Call this before building or modifying
    anything to see what nodes already exist (ground planes, cameras,
    lights, player objects, etc.).

    Returns a dict with the scene tree and its version:
        {
          "scene": {"name": "Main", "type": "Node3D", "children": [...]},
          "version": 12
        }

    Returns an empty scene dict if the editor has no scene open.
    """
    _init()
    scene, version = _scene_store.get_or_fetch(_executor)
    return {"scene": scene or {}, "version": version}


@mcp.tool()
def audit_scene() -> Dict[str, Any]:
    """Audit the current Godot scene for common problems.

    Walks the scene tree checking for missing collision shapes,
    unassigned meshes on MeshInstance3D nodes, duplicate sibling
    names, and other common issues.  Read-only — never mutates
    the scene.  No LLM calls.

    Call this before ``apply_spec`` to check scene health, or after
    making changes to verify nothing is broken.

    Arguments: none (reads the live scene from Godot).

    Returns violation counts by severity and an ordered list of
    findings with node paths, messages, and fix suggestions.
    """
    _init()

    scene, version = _scene_store.get_or_fetch(_executor)

    # Live property access (WO-004) — enables R3 (Camera3D.current)
    # and R4 (MeshInstance3D.mesh).  resolve_node_properties() returns
    # None when the editor is unreachable or the call fails; rules
    # R3/R4 already handle None by falling back to empty props.
    doctor = SceneDoctor(props_lookup=_executor.resolve_node_properties)
    violations = doctor.audit(scene)

    counts: dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    for v in violations:
        key = v.severity.lower()
        if key in counts:
            counts[key] += 1

    logger.info(
        "mcp_server",
        f"Audit complete: {len(violations)} violations "
        f"(critical={counts['critical']}, warning={counts['warning']}, "
        f"info={counts['info']}) scene_version={version}",
    )

    _journal.append(
        "audit_scene",
        f"Audit: {counts['critical']} crit, {counts['warning']} warn, {counts['info']} info",
        {"scene_version": version, **counts},
    )

    return {
        "scene_version": version,
        "counts": counts,
        "violations": [v.to_dict() for v in violations],
    }


@mcp.tool()
def batch_preview(
    query: str,
    property: str,
    value: Any,
) -> Dict[str, Any]:
    """Preview a batch property change before applying it.

    Filters nodes by type, name pattern, and/or subtree path, then
    shows which nodes would be affected by a ``set_property`` call.
    Read-only — does not mutate the scene.  Call ``batch_apply``
    with the returned ``plan_id`` to execute.

    Query syntax (space-separated tokens):
        type:OmniLight3D        — exact Godot node type
        name~lamp                — case-insensitive name substring
        under:/root/Main/Enemies — subtree

    Also accepts a few convenience phrasings:
        "all OmniLight3Ds"  "every Timer under /root/X"  "nodes named foo"

    Arguments:
        {
          "query": "type:OmniLight3D name~warm",
          "property": "light_energy",
          "value": 0.8
        }

    Returns:
        {
          "plan_id": "ab12cd34ef56",
          "matched": ["/root/Main/Lamp1", "/root/Main/Lamp2"],
          "match_count": 2,
          "property": "light_energy",
          "value": 0.8,
          "scene_version": 12,
          "hint": "Review the matched paths, then call batch_apply with this plan_id to execute."
        }

    Zero matches is a valid result (``match_count: 0``, ``plan_id: null``).
    """
    _init()

    scene, version = _scene_store.get_or_fetch(_executor)

    f = parse_query(query)
    matched = match_nodes(scene, f)

    if not matched:
        return {
            "plan_id": None,
            "matched": [],
            "match_count": 0,
            "property": property,
            "value": value,
            "scene_version": version,
            "hint": ("No nodes matched the query. Try a broader query, or check the scene tree with get_scene."),
        }

    ops = build_batch_ops(matched, property, value)
    plan_payload = {
        "operations": ops,
        "query": query,
        "scene_version": version,
    }
    plan_id = _artifact_store.store(plan_payload)

    logger.info(
        "mcp_server",
        f"batch_preview: {len(matched)} node(s) matched for {property}={value!r}",
    )

    return {
        "plan_id": plan_id,
        "matched": matched,
        "match_count": len(matched),
        "property": property,
        "value": value,
        "scene_version": version,
        "hint": ("Review the matched paths, then call batch_apply with this plan_id to execute."),
    }


@mcp.tool()
def batch_apply(plan_id: str) -> Dict[str, Any]:
    """Execute a batch property change previously previewed.

    Call this after ``batch_preview`` to apply the planned operations.
    Re-fetches the scene and refuses to execute if the scene changed
    since the preview (version drift protection).  Operations are
    validated before execution — invalid plans are rejected.

    Arguments:
        {
          "plan_id": "ab12cd34ef56"
        }

    Returns:
        {
          "success": true,
          "applied_count": 2,
          "results": [...],
          "errors": [],
          "success_count": 2,
          "failure_count": 0
        }

    Returns ``{"error": "..."}`` on unknown/expired plan_id or
    scene-version drift.
    """
    _init()

    plan = _artifact_store.get(plan_id)
    if plan is None:
        return {
            "error": (
                f"Unknown or expired plan_id: {plan_id}. "
                f"Plans are cached per-session. Re-run batch_preview "
                f"to create a fresh plan."
            )
        }

    ops = plan.get("operations", [])
    preview_version = plan.get("scene_version")

    # ── Version drift check ──────────────────────────────────
    live_scene, live_version = _scene_store.get_or_fetch(_executor)
    if preview_version is not None and live_version != preview_version:
        return {
            "error": (
                f"Scene changed since preview "
                f"(version {preview_version} → {live_version}). "
                f"Re-run batch_preview to see the current matches."
            )
        }

    # ── Validate + execute ───────────────────────────────────
    turn_id = uuid.uuid4().hex
    _llm.set_turn_id(turn_id)
    try:
        with _acquire_pipeline_lock_ctx():
            valid_ops, errors = _engine.validate_pipeline(
                ops,
                live_scene,
                [],
            )
            if errors:
                return {
                    "success": False,
                    "applied_count": 0,
                    "results": [],
                    "errors": errors,
                    "success_count": 0,
                    "failure_count": len(ops),
                }

            exec_result = _executor.execute(
                valid_ops,
                [],
                live_scene,
            )
            if exec_result and exec_result.success:
                _scene_store.note_writes()

        result_dict = exec_result.to_dict() if exec_result else {}
        result_dict["applied_count"] = result_dict.get("success_count", 0)

        logger.info(
            "mcp_server",
            f"batch_apply: {result_dict.get('applied_count', 0)} applied, {result_dict.get('failure_count', 0)} failed",
        )

        _journal.append(
            "batch_apply",
            f"Batch: {result_dict.get('applied_count', 0)} nodes",
            {"applied": result_dict.get("applied_count", 0), "failed": result_dict.get("failure_count", 0)},
        )

        return result_dict
    finally:
        _llm.clear_turn_id()


@mcp.tool()
def triage_errors(
    log_text: str | None = None,
) -> Dict[str, Any]:
    """Triage Godot runtime errors from the editor log.

    Parses raw Godot output, classifies each error against a knowledge
    table of 20 common errors, and returns explained findings with
    file/line and fix hints.  Read-only — no LLM calls.

    Call this after running the game or after ``apply_spec`` to check
    for runtime errors.  The returned findings include categories,
    explanations, and concrete fix suggestions.

    Arguments:
        {
          "log_text": "player.gd:42 - Invalid call..."
        }

    Omit ``log_text`` to pull logs from the live Godot editor.

    Returns:
        {
          "source": "live",
          "total_raw": 3,
          "findings": [
            {
              "file": "player.gd",
              "line": 42,
              "raw_message": "Invalid call. Nonexistent function...",
              "category": "missing_member",
              "known_id": "E01",
              "explanation": "A function is being called on an object...",
              "fix_hint": "Check the variable type at the call site...",
              "occurrence_count": 1
            }
          ],
          "by_category": {"missing_member": 1}
        }

    Returns ``{"error": "..."}`` if no live log is available and
    ``log_text`` was not provided.
    """
    _init()

    source = "provided"
    if log_text is None:
        log_text = _executor.read_logs()
        source = "live"
        if log_text is None:
            return {
                "error": (
                    "No live editor log available and no log_text "
                    "provided. Pass log_text to triage an offline log, "
                    "or ensure the Godot editor is running."
                )
            }

    result = triage_text(log_text)
    result["source"] = source

    logger.info(
        "mcp_server",
        f"Error triage complete: {result['total_raw']} raw errors, "
        f"{len(result['findings'])} unique findings "
        f"(source={source})",
    )

    _journal.append(
        "triage_errors",
        f"Triage: {len(result['findings'])} unique, {result['total_raw']} raw",
        {
            "findings": len(result["findings"]),
            "total_raw": result["total_raw"],
            "source": source,
            "by_category": result.get("by_category", {}),
        },
    )

    return result


@mcp.tool()
def journal_entries(
    n: int = 20,
    tool: str | None = None,
) -> Dict[str, Any]:
    """Read recent entries from the Progress Journal.

    Returns the most recent *n* entries (newest first), optionally
    filtered by tool name (e.g. "audit_scene", "batch_apply").
    Read-only — no LLM calls, no scene mutation.

    Arguments:
        {
          "n": 20,
          "tool": "audit_scene"
        }

    Returns:
        {
          "entries": [
            {
              "timestamp": 1718100000.0,
              "tool": "audit_scene",
              "event": "Audit: 2 crit, 3 warn, 0 info",
              "data": {"scene_version": 12, "critical": 2, ...}
            }
          ]
        }
    """
    _init()
    entries = _journal.get_entries(n=n, tool=tool)
    return {"entries": entries}


@mcp.tool()
def lore_schema_list() -> Dict[str, Any]:
    """List defined content schemas (items, NPCs, quests, etc.).

    Scans the schema directory for ``*.schema.json`` files.
    Read-only — no LLM calls, no scene mutation.

    Arguments: none.

    Returns:
        {
          "schemas": [
            {
              "name": "item",
              "version": 1,
              "description": "Game items and equipment",
              "field_count": 8,
              "required_fields": ["id", "name", "type"]
            }
          ]
        }
    """
    _init()
    schemas = lore_list_schemas()
    return {"schemas": schemas}


@mcp.tool()
def lore_data_validate(
    schema_name: str,
    data_path: str,
) -> Dict[str, Any]:
    """Validate a JSON data file against a content schema.

    Loads the schema by name, loads the data file at *data_path*
    (JSON array), validates every entry against the schema, and
    checks referential integrity against other loaded data.
    Read-only — no LLM calls, no scene mutation.

    Arguments:
        {
          "schema_name": "item",
          "data_path": "data/items.json"
        }

    Returns:
        {
          "schema": "item",
          "total_entries": 50,
          "valid": 48,
          "error_count": 2,
          "errors": [
            "[sword01] Missing required field 'damage'",
            "[shield02] Field 'weight': expected int, got str"
          ]
        }

    Returns ``{"error": "..."}`` if the schema or data file is missing.
    """
    _init()

    schema = load_schema(schema_name)
    if schema is None:
        return {"error": f"Unknown schema: '{schema_name}'. Use lore_schema_list to see available schemas."}

    entries = load_data_file(data_path)
    if entries is None:
        return {"error": f"Could not load data file: '{data_path}'. Ensure the file exists and is a valid JSON array."}

    result = validate_data(schema, entries)

    _journal.append(
        "lore_data_validate",
        f"Lore: {schema_name} — {result['valid']}/{result['total_entries']} valid",
        {
            "schema": schema_name,
            "valid": result["valid"],
            "total": result["total_entries"],
            "error_count": result["error_count"],
        },
    )

    logger.info(
        "mcp_server",
        f"Lore validate: {schema_name} — {result['valid']}/{result['total_entries']} valid, "
        f"{result['error_count']} errors",
    )
    return result


@mcp.tool()
def lore_integrity_check(
    data_files: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Check referential integrity across content data files.

    Loads multiple data files (each with a schema name and file path),
    then checks that every foreign-key reference points to an existing
    entry in the target data.  Read-only — no LLM calls, no scene
    mutation.

    Call this after adding or editing content data to verify that
    all cross-references are valid (e.g. every quest reward references
    a real item, every dialogue speaker references a real NPC).

    Arguments:
        {
          "data_files": [
            {"schema_name": "item", "data_path": "data/items.json"},
            {"schema_name": "npc", "data_path": "data/npcs.json"}
          ]
        }

    Returns:
        {
          "error_count": 2,
          "errors": [
            "npc 'bob': favorite_item='nonexistent' does not exist in item",
            "item 'sword01': npc_id='Unknown' does not exist in npc"
          ]
        }

    Returns ``{"error": "..."}`` if any schema or data file can't be loaded.
    """
    _init()

    # Load schemas
    schemas: dict[str, Any] = {}
    loaded_data: dict[str, list] = {}

    for df in data_files:
        schema_name = df.get("schema_name", "")
        data_path = df.get("data_path", "")

        if not schema_name or not data_path:
            return {"error": "Each entry must have 'schema_name' and 'data_path'"}

        # Load schema (cached)
        if schema_name not in schemas:
            schema = load_schema(schema_name)
            if schema is None:
                return {"error": f"Unknown schema: '{schema_name}'. Use lore_schema_list to see available schemas."}
            schemas[schema_name] = schema

        # Load data
        entries = load_data_file(data_path)
        if entries is None:
            return {"error": f"Could not load data file: '{data_path}'."}
        loaded_data[schema_name] = entries

    result = validate_integrity(loaded_data, schemas)

    logger.info(
        "mcp_server",
        f"Lore integrity: {len(loaded_data)} schemas, {result['error_count']} ref errors",
    )

    _journal.append(
        "lore_integrity_check",
        f"Lore integrity: {result['error_count']} ref errors across {len(loaded_data)} schemas",
        {"error_count": result["error_count"], "schemas": list(loaded_data.keys())},
    )

    return result


@mcp.tool()
def journal_summary() -> Dict[str, Any]:
    """Get an aggregated summary of the Progress Journal.

    Returns total entry count, date range, per-tool breakdown,
    and recently used tools.  Read-only — no LLM calls.

    Arguments: none.

    Returns:
        {
          "total_entries": 142,
          "first_ts": 1718100000.0,
          "last_ts": 1718180000.0,
          "by_tool": {"audit_scene": 80, "batch_apply": 12},
          "recent_tools": ["audit_scene", "batch_apply", "triage_errors"]
        }
    """
    _init()
    return _journal.summary()


@mcp.tool()
def quest_validate(
    filepath: str,
) -> Dict[str, Any]:
    """Validate a quest JSON data file for design problems.

    Loads a quest data file (JSON array of quest objects), builds a
    dependency graph, and runs four validation checks:

    1. **Unreachable quests** — quests that can't be reached from any
       starting quest (no prerequisites).
    2. **Prerequisite cycles** — A requires B, B requires A.
    3. **Item deadlocks** — quest requires an item no other quest grants.
    4. **Flag deadlocks** — quest requires a flag no quest sets.

    Each quest object must have: id, name, prerequisites, required_items,
    grants_items, required_flags, sets_flags.

    Arguments:
        {
          "filepath": "data/quests.json"
        }

    Returns:
        {
          "total_quests": 12,
          "start_nodes": 2,
          "issue_count": 3,
          "critical": 2,
          "warning": 1,
          "issues": [
            {"issue_type": "cycle", "severity": "CRITICAL",
             "quests": ["q5", "q6"],
             "message": "Prerequisite cycle: q5 → q6 → q5..."}
          ]
        }

    Returns ``{"error": "..."}`` if the file can't be loaded or parsed.
    """
    _init()

    result = validate_quest_file(filepath)

    if "error" in result:
        return result

    logger.info(
        "mcp_server",
        f"Quest validate: {result['total_quests']} quests, "
        f"{result['issue_count']} issues "
        f"(critical={result['critical']}, warning={result['warning']})",
    )

    _journal.append(
        "quest_validate",
        f"Quest validate: {result['total_quests']} quests, {result['issue_count']} issues",
        {
            "total_quests": result["total_quests"],
            "issue_count": result["issue_count"],
            "critical": result["critical"],
            "warning": result["warning"],
        },
    )

    return result


@mcp.tool()
def perf_sample(
    monitors: list[str] | None = None,
) -> Dict[str, Any]:
    """Sample live Godot performance metrics.

    Calls the Godot editor's performance monitor system and records
    a timestamped snapshot in an in-memory ring buffer (max 100 samples).
    Read-only — no LLM calls, no scene mutation.

    Omit *monitors* to fetch all available metrics (FPS, draw calls,
    memory usage, etc.).  Pass a list of specific metric names to
    get only those.

    Arguments:
        {
          "monitors": ["time/fps", "rendering/total_draw_calls"]
        }

    Returns:
        {
          "timestamp": 1718180000.0,
          "metrics": {"time/fps": 60.0, "rendering/total_draw_calls": 120},
          "sample_id": 0
        }

    Returns ``{"error": "..."}`` if the editor is unreachable.
    """
    _init()

    metrics = _executor.get_performance_monitors(monitors)
    if metrics is None:
        return {
            "error": (
                "Could not fetch performance monitors from the Godot editor. "
                "Ensure the editor is running with the godot-ai plugin enabled."
            )
        }

    sample = _sentinel.sample(metrics)

    return {
        "timestamp": sample.timestamp,
        "metrics": sample.metrics,
        "sample_id": _sentinel.count - 1,
    }


@mcp.tool()
def perf_history(
    n: int = 20,
) -> Dict[str, Any]:
    """Get recent performance samples with summary statistics.

    Returns the *n* most recent samples (newest first), plus per-metric
    summary stats (min, max, avg) aggregated across all stored samples.
    Read-only — no LLM calls, no scene mutation.

    Arguments:
        {
          "n": 20
        }

    Returns:
        {
          "samples": [{"timestamp": 1718180000.0, "metrics": {...}}],
          "summary": {
            "time/fps": {"min": 45.0, "max": 60.0, "avg": 57.3, "sample_count": 50}
          },
          "total_samples": 50
        }
    """
    _init()

    return _sentinel.history(n=n)


@mcp.tool()
def lint_content(
    filepath: str,
    schema_name: str | None = None,
    cross_file_paths: list[dict[str, str]] | None = None,
) -> Dict[str, Any]:
    """Lint a content data file for quality and correctness issues.

    Loads a JSON data file and runs a battery of deterministic checks:

    - **L01 (ERROR):** Duplicate IDs — same id value used twice in one file.
    - **L02 (WARNING):** Naming convention — ID doesn't match snake_case.
    - **L03 (ERROR):** Empty name — the ``name`` field is blank.
    - **L04 (ERROR):** Empty required field — a required field is null/empty.
    - **L05 (WARNING):** Mismatched key — a field in the data isn't in the schema (only when *schema_name* is given).
    - **L06 (ERROR):** Cross-file duplicate — an ID also appears in another data file (only when *cross_file_paths* are given).

    Pass *schema_name* to enable schema-aware checks (L04 strict mode,
    L05).  Schemas are loaded from the Lorekeeper schema directory.

    Pass *cross_file_paths* to check for duplicate IDs across files:
    each item is {"schema_name": "item", "data_path": "data/items.json"}.

    Arguments:
        {
          "filepath": "data/items.json",
          "schema_name": "item",
          "cross_file_paths": [
            {"schema_name": "item", "data_path": "data/more_items.json"}
          ]
        }

    Returns:
        {
          "total_entries": 50,
          "finding_count": 5,
          "errors": 3,
          "warnings": 2,
          "info": 0,
          "findings": [
            {
              "rule_id": "L01",
              "severity": "ERROR",
              "entry_index": 3,
              "entry_id": "sword01",
              "field": "id",
              "message": "Duplicate id 'sword01' — first seen at entry 0",
              "suggestion": "Ensure every id value is unique within the file."
            }
          ]
        }

    Returns ``{"error": "..."}`` if the file can't be loaded.
    """
    _init()

    # Load cross-file entries if specified
    cross: dict[str, list[dict]] | None = None
    if cross_file_paths:
        from devforge.lore.lorekeeper import load_data_file

        cross = {}
        for cf in cross_file_paths:
            sn = cf.get("schema_name", "")
            dp = cf.get("data_path", "")
            if not sn or not dp:
                continue
            entries = load_data_file(dp)
            if entries is not None:
                cross[sn] = entries

    result = run_lint_file(filepath, schema_name=schema_name, other_files=cross)

    if "error" in result:
        return result

    logger.info(
        "mcp_server",
        f"Lint: {filepath} — {result['finding_count']} findings "
        f"(errors={result['errors']}, warnings={result['warnings']})",
    )

    _journal.append(
        "lint_content",
        f"Lint: {filepath} — {result['finding_count']} findings",
        {
            "file": filepath,
            "findings": result["finding_count"],
            "errors": result["errors"],
            "warnings": result["warnings"],
        },
    )

    return result


@mcp.tool()
def polish_pass(
    apply_fixes: bool = False,
) -> Dict[str, Any]:
    """Audit the scene for game-feel deficiencies and optionally apply fixes.

    Walks the scene tree with deterministic polish rules and reports
    missing game-feel elements:

    - **P1 (WARNING):** Camera3D without position smoothing.
    - **P2 (WARNING):** Camera3D without screen-shake setup.
    - **P3 (WARNING):** Light nodes with zero energy.
    - **P4 (ERROR):** MeshInstance3D with no mesh assigned.
    - **P5 (WARNING):** UI elements using the default system font.

    Set *apply_fixes* to ``true`` to auto-apply fix operations.  Fixed
    operations are returned separately for preview or optional execution
    via ``batch_apply``.

    Arguments:
        {
          "apply_fixes": false
        }

    Returns:
        {
          "finding_count": 5,
          "errors": 1,
          "warnings": 4,
          "info": 0,
          "fixes_applied": 0,
          "fix_operations": [],
          "findings": [
            {
              "rule_id": "P1",
              "severity": "WARNING",
              "node_path": "/root/Main/Camera3D",
              "message": "Camera3D 'Camera3D' has no position smoothing...",
              "fix_applied": false,
              "fix_message": ""
            }
          ]
        }

    Returns an empty findings list when the scene is polished.
    """
    _init()

    scene, version = _scene_store.get_or_fetch(_executor)

    result = run_polish_pass(
        scene,
        apply_fixes=apply_fixes,
        props_lookup=_executor.resolve_node_properties,
    )

    logger.info(
        "mcp_server",
        f"Polish pass: {result['finding_count']} findings "
        f"(errors={result['errors']}, warnings={result['warnings']}), "
        f"fixes={result['fixes_applied']}",
    )

    _journal.append(
        "polish_pass",
        f"Polish: {result['finding_count']} findings, {result['fixes_applied']} fixes",
        {
            "findings": result["finding_count"],
            "errors": result["errors"],
            "warnings": result["warnings"],
            "fixes": result["fixes_applied"],
        },
    )

    result["scene_version"] = version
    return result


@mcp.tool()
def project_search(
    query: str,
) -> Dict[str, Any]:
    """Search the Godot project for files, symbols, and signals.

    Searches across three layers:
    1. **Filesystem content** — full-text search via godot-ai's ``search_filesystem``.
    2. **Filenames** — fallback name-only search if no content hits.
    3. **Symbols** — scans ``find_symbols`` on matching .gd files for
       function names, signal names, and class names matching the query.

    Call this when you need to find where a feature, function, or signal
    is implemented (e.g. "where is falling damage?", "who emits died?").

    Arguments:
        {
          "query": "falling damage"
        }

    Returns:
        {
          "query": "falling damage",
          "hit_count": 3,
          "hits": [
            {"source": "filesystem", "path": "res://scripts/player.gd",
             "line": 142, "snippet": "apply_falling_damage()"},
            {"source": "symbol", "path": "res://scripts/player.gd",
             "snippet": "apply_falling_damage", "symbol_type": "function"}
          ],
          "by_source": {"filesystem": 2, "symbol": 1}
        }

    Returns ``{"error": "..."}`` if the editor is unreachable.
    """
    _init()

    result = search_project(
        query,
        find_symbols_fn=_executor.find_symbols,
        search_filesystem_fn=_executor.search_filesystem,
    )

    logger.info(
        "mcp_server",
        f"Project search '{query}': {result['hit_count']} hits (by_source={result['by_source']})",
    )
    return result


@mcp.tool()
def test_scaffold(
    script_path: str,
    source: str | None = None,
) -> Dict[str, Any]:
    """Generate a deterministic test scaffold from GDScript function signatures.

    Parses function signatures from the GDScript source and generates a
    skeleton test file (WAT-compatible) with one test function per public
    method.  The user fills in actual assertions — no logic is invented.

    Provide *source* to paste the script content directly.  Omit *source*
    to fetch the script from the live editor via ``script_read``.

    Arguments:
        {
          "script_path": "scripts/player.gd",
          "source": "extends Node\nfunc add(a: int, b: int) -> int:\n    return a + b"
        }

    Returns:
        {
          "script_path": "scripts/player.gd",
          "function_count": 5,
          "public_count": 2,
          "test_scaffold": "extends WAT\n\nfunc test_add():...",
          "functions": [
            {"name": "add", "params": [{"name": "a", "type": "int"}],
             "return_type": "int"}
          ]
        }

    Returns ``{"error": "..."}`` if source can't be obtained.
    """
    _init()

    if source is None:
        return {
            "error": (
                f"No source provided for '{script_path}'. "
                f"Paste the script content as the 'source' argument "
                f"to generate a test scaffold."
            )
        }

    if not source.strip():
        return {"error": f"Source for '{script_path}' is empty."}

    result = scaffold_file(script_path, source)

    logger.info(
        "mcp_server",
        f"Test scaffold: {script_path} — {result['public_count']} public functions",
    )

    _journal.append(
        "test_scaffold",
        f"Scaffold: {script_path} — {result['public_count']} test functions",
        {"script": script_path, "functions": result["function_count"], "public": result["public_count"]},
    )

    return result


@mcp.tool()
def balance_sim(
    player: dict,
    enemies: list[dict],
    encounter_enemies: list[str],
    encounter_counts: dict[str, int] | None = None,
    simulations: int = 1000,
    hp_field: str = "hp",
    attack_field: str = "attack",
    defense_field: str = "defense",
    speed_field: str = "speed",
    level_field: str = "level",
) -> Dict[str, Any]:
    """Run Monte Carlo combat simulations against a player build.

    Evaluates one encounter: feeds *player* stats and *enemies* data
    into a deterministic round-by-round combat engine, runs *simulations*
    Monte Carlo iterations, and reports win probability, average rounds,
    damage stats, and more.

    For level progression sweeps, call with different player stats
    across multiple tool calls (e.g. level 1→5→10→20).

    Arguments:
        {
          "player": {"id": "hero", "name": "Hero", "hp": 100, "attack": 15, "defense": 8, "speed": 12, "level": 5},
          "enemies": [
            {"id": "goblin", "name": "Goblin", "hp": 30, "attack": 8, "defense": 3, "speed": 10, "level": 3}
          ],
          "encounter_enemies": ["goblin"],
          "encounter_counts": {"goblin": 3},
          "simulations": 1000
        }

    Returns:
        {
          "encounter_id": "custom",
          "encounter_name": "Custom Encounter",
          "total_simulations": 1000,
          "player_wins": 743,
          "player_losses": 257,
          "win_probability": 0.743,
          "avg_rounds": 5.2,
          "avg_player_hp_remaining": 34.1,
          "avg_damage_dealt": 87.3,
          "avg_damage_taken": 65.9,
          "avg_crits_landed": 1.2,
          "player_first_turn_pct": 0.62,
          "one_shot_probability": 0.003,
          "flawless_victory_probability": 0.02
        }

    Returns ``{"error": "..."}`` if player or enemy data is invalid.
    """
    _init()

    if not player or not enemies or not encounter_enemies:
        return {"error": "player, enemies, and encounter_enemies are required."}

    result = evaluate_encounter(
        player_data=player,
        enemy_data=enemies,
        encounter_enemies=encounter_enemies,
        encounter_counts=encounter_counts,
        encounter_id="custom",
        encounter_name="Custom Encounter",
        simulations=simulations,
        hp_field=hp_field,
        attack_field=attack_field,
        defense_field=defense_field,
        speed_field=speed_field,
        level_field=level_field,
    )

    logger.info(
        "mcp_server",
        f"balance_sim: {result['total_simulations']} sims, "
        f"win={result['win_probability']}, "
        f"avg_hp_left={result['avg_player_hp_remaining']}",
    )

    _journal.append(
        "balance_sim",
        f"Balance sim: {result['win_probability'] * 100:.1f}% win rate ({result['total_simulations']} sims)",
        {
            "win_probability": result["win_probability"],
            "simulations": result["total_simulations"],
            "avg_hp_remaining": result["avg_player_hp_remaining"],
        },
    )

    return result


@mcp.tool()
def signal_map(
    source: dict[str, str] | None = None,
    query: str | None = None,
) -> Dict[str, Any]:
    """Scan GDScript files for signals, connections, and emissions.

    Two modes:
    1. **Inline mode** — pass ``source`` as {filepath: code, ...} to scan
       specific files directly.
    2. **Search mode** — pass ``query`` to search the project via
       godot-ai's search_filesystem, then scan found .gd files.

    Returns a dependency graph showing who declares, emits, and listens
    to every signal.  Includes impact analysis: "what breaks if I rename
    signal X?" and orphan detection (signals with no emitters or listeners).

    Arguments:
        {
          "source": {
            "res://scripts/player.gd": "extends Node\\nsignal died\\n...",
            "res://scripts/ui.gd": "extends Node\\nfunc _ready(): player.died.connect(...)"
          }
        }

    Returns:
        {
          "signal_count": 3,
          "connection_count": 5,
          "emit_count": 4,
          "signals": [...SignalDecl dicts...],
          "connections": [...SignalConnection dicts...],
          "emits": [...SignalEmit dicts...],
          "orphaned": [...orphaned signal dicts...],
          "impact": {...optional, for query mode...}
        }

    Returns ``{"error": "..."}`` if no source and no query are provided.
    """
    _init()

    mapper = SignalMapper()

    if source:
        for file_path, code in source.items():
            mapper.scan_file(file_path, code)
        graph = mapper.build_graph()
        result = graph.to_dict()

        if query and query in graph.signals:
            result["impact"] = graph.impact_of_rename(query)

        logger.info(
            "mcp_server",
            f"signal_map (inline): {result['signal_count']} signals, "
            f"{result['connection_count']} connections, "
            f"{result['emit_count']} emits",
        )

        _journal.append(
            "signal_map",
            f"Signals: {result['signal_count']} decls, {result['connection_count']} conns, {len(result.get('orphaned', []))} orphaned",
            {
                "signals": result["signal_count"],
                "connections": result["connection_count"],
                "emits": result["emit_count"],
                "orphaned": len(result.get("orphaned", [])),
            },
        )

        return result

    if query:
        # Search mode: use godot-ai search_filesystem + script_read
        # (inline mode covers the core use case; search mode requires
        # the godot-ai executor which may not be available)
        return {
            "error": (
                "Search mode via godot-ai requires a live editor connection. "
                f"Use inline mode: pass 'source' as a dict of filepath→code. "
                f"Query: '{query}'"
            ),
        }

    return {"error": "Provide 'source' (dict of filepath→code) or 'query' for project search."}


@mcp.tool()
def smoke_run(
    pois: list[dict],
    output_dir: str = "/tmp/smoke",
) -> Dict[str, Any]:
    """Run a scripted smoke test through a list of POIs.

    Launches the game, teleports through each point of interest,
    captures screenshots + logs + perf samples, and stops the game.
    Returns a structured morning report with per-stop data and
    aggregate stats (FPS, error counts, screenshots).

    Each POI dict must have:
      - name: display name
      - position: {x, y, z} world coordinates
      - wait_seconds (optional, default 2.0)
      - description (optional)

    Requires a live godot-ai editor connection (run_project, game_eval,
    take_screenshot, get_logs, get_performance_monitors primitives).

    Arguments:
        {
          "pois": [
            {"name": "Town Square", "position": {"x": 0, "y": 0, "z": 0}, "wait_seconds": 2},
            {"name": "Dark Forest", "position": {"x": 500, "y": 0, "z": 300}, "wait_seconds": 3}
          ]
        }

    Returns:
        {
          "timestamp": 1718000000.0,
          "total_pois": 2,
          "pois_visited": 2,
          "total_errors_logged": 3,
          "total_screenshots": 2,
          "avg_fps": 58.5,
          "min_fps": 55.0,
          "stops": [...StopResult dicts...],
          "errors": [],
          "summary": "Smoke Run — ..."
        }

    Returns ``{"error": "..."}`` if the project can't be launched.
    """
    _init()

    if not pois:
        return {"error": "Provide at least one POI to visit."}

    # Build POIs from dicts
    poi_objects = []
    for p in pois:
        pos = p.get("position", {})
        poi_objects.append(
            build_poi(
                name=p.get("name", "Unnamed"),
                position=pos,
                wait=p.get("wait_seconds", 2.0),
                description=p.get("description", ""),
            )
        )

    runner = SmokeRunner(
        run_project_fn=_executor.run_project,
        stop_project_fn=_executor.stop_project,
        game_eval_fn=_executor.game_eval,
        take_screenshot_fn=_executor.take_screenshot,
        get_logs_fn=_executor.read_logs,
        get_perf_fn=_executor.get_performance_monitors,
    )
    report = runner.run(poi_objects, output_dir)
    result = report.to_dict()

    logger.info(
        "mcp_server",
        f"smoke_run: {result['pois_visited']}/{result['total_pois']} POIs, "
        f"avg_fps={result['avg_fps']}, {result['total_errors_logged']} errors",
    )

    _journal.append(
        "smoke_run",
        f"Smoke run: {result['pois_visited']}/{result['total_pois']} POIs, avg FPS {result['avg_fps']}",
        {
            "pois_visited": result["pois_visited"],
            "total_pois": result["total_pois"],
            "avg_fps": result["avg_fps"],
            "errors": result["total_errors_logged"],
        },
    )

    return result


@mcp.tool()
def design_companion(
    features: list[str],
) -> Dict[str, Any]:
    """Match your game's features against a genre pattern database.

    Takes a list of mechanic/feature names your game has (e.g. ["stamina",
    "inventory", "day_night"]) and matches them against a curated database
    of 17 open-world FP RPG patterns. Returns what you have, what you're
    missing (by priority: essential/important/nice-to-have), and a category
    breakdown with coverage percentages.

    Pure Python — no LLM calls, no scene mutation.

    Arguments:
        {
          "features": ["stamina", "sprint", "inventory", "quest_log", "loot", "day_night"]
        }

    Returns:
        {
          "features_provided": 6,
          "patterns_total": 17,
          "patterns_present": 5,
          "patterns_missing": 12,
          "present": [...],
          "missing_essential": [...pattern suggestions...],
          "by_category": {"player_mechanics": {"total": 3, "present": 2, "coverage": 0.67}, ...},
          "hint": "Focus on the 3 essential patterns first."
        }
    """
    _init()
    companion = DesignCompanion()
    result = companion.analyze(features)

    logger.info("mcp_server", f"Design companion: {result['patterns_present']}/{result['patterns_total']} patterns")
    _journal.append("design_companion", result["hint"], result)
    return result


@mcp.tool()
def dialogue_validate(
    filepath: str,
    npc_ids: list[str] | None = None,
) -> Dict[str, Any]:
    """Validate a dialogue tree JSON file for structural integrity.

    Checks: duplicate node IDs, missing start node, dead-end choices
    (point to nonexistent nodes), orphaned terminal nodes, and speaker
    validation against a known NPC list.

    Dialogue files are JSON with: id, name, start_node_id, nodes: [{id, speaker_id, text, choices: [{text, next_id}]}].

    Arguments:
        {
          "filepath": "data/dialogue/eldrin.json",
          "npc_ids": ["eldrin", "guard_captain", "innkeeper"]
        }

    Returns:
        {
          "filepath": "data/dialogue/eldrin.json",
          "node_count": 12,
          "issue_count": 2,
          "issues": [...],
          "valid": false
        }
    """
    _init()
    result = validate_dialogue_file(filepath, npc_ids)

    logger.info(
        "mcp_server", f"Dialogue validate: {result.get('node_count', 0)} nodes, {result.get('issue_count', 0)} issues"
    )
    _journal.append(
        "dialogue_validate",
        f"Dialogue: {result.get('node_count', 0)} nodes, {result.get('issue_count', 0)} issues",
        result,
    )
    return result


@mcp.tool()
def scene_extract(
    node_path: str,
    output_path: str,
    collision_strategy: str = "rename",
) -> Dict[str, Any]:
    """Extract a subtree from the live scene into its own .tscn file.

    Takes a node path (e.g. "/root/Main/Enemies"), extracts that subtree,
    and generates operations to replace it with an instance reference.
    Read-only preview — use batch_apply to execute the returned operations.

    collision_strategy: "rename" (append _001), "error" (fail), "skip" (no-op).

    Arguments:
        {
          "node_path": "/root/Main/Enemies",
          "output_path": "res://scenes/extracted_enemies.tscn",
          "collision_strategy": "rename"
        }

    Returns:
        {
          "success": true,
          "extracted_node_path": "/root/Main/Enemies",
          "new_instance_name": "Enemies",
          "extracted_scene_path": "res://scenes/extracted_enemies.tscn",
          "operation_count": 2,
          "operations": [...],
          "warnings": []
        }
    """
    _init()
    scene, version = _scene_store.get_or_fetch(_executor)
    refactorer = SceneRefactorer()
    result = refactorer.extract_subtree(scene, node_path, output_path, collision_strategy=collision_strategy)
    result_dict = result.to_dict()
    result_dict["scene_version"] = version

    logger.info("mcp_server", f"Scene extract: {node_path} -> {output_path}")
    _journal.append("scene_extract", f"Extracted {node_path} -> {output_path}", result_dict)
    return result_dict


@mcp.tool()
def scene_list_extractable(
    min_children: int = 3,
) -> Dict[str, Any]:
    """List candidate subtrees suitable for extraction.

    Scans the live scene and reports nodes with >= *min_children* children
    that could be extracted into separate .tscn files.

    Arguments:
        {
          "min_children": 3
        }

    Returns:
        {
          "candidate_count": 4,
          "candidates": [{path, name, type, child_count, suggested_output}, ...]
        }
    """
    _init()
    scene, _ = _scene_store.get_or_fetch(_executor)
    return list_extractable(scene, min_children)


@mcp.tool()
def template_list() -> Dict[str, Any]:
    """List available system templates.

    Scans the template directory for ready-to-instantiate game systems
    (FPS controller, save system, inventory, etc.).  Read-only — no
    LLM calls, no scene mutation.

    Arguments: none.

    Returns:
        {
          "templates": [
            {
              "slug": "fps_controller",
              "name": "FPS Controller",
              "description": "First-person controller with sprint, crouch...",
              "slot_count": 5,
              "script_count": 3
            }
          ]
        }
    """
    _init()

    templates = list_templates()
    logger.info(
        "mcp_server",
        f"template_list: {len(templates)} template(s) found",
    )
    return {"templates": templates}


@mcp.tool()
def template_preview(
    template_slug: str,
    slot_values: Dict[str, Any] | None = None,
    parent_path: str = "/root/Main",
) -> Dict[str, Any]:
    """Preview a template instantiation before applying it.

    Resolves a template by slug, fills in slot values (parameters),
    and returns the operations that would be executed — without
    modifying the scene.  Read-only.

    Call ``template_list`` first to discover available templates.
    Call ``template_apply`` with the same arguments to execute.

    Arguments:
        {
          "template_slug": "fps_controller",
          "slot_values": {"camera_height": 1.8, "walk_speed": 5.0},
          "parent_path": "/root/Main"
        }

    Returns the preview dict with slug, name, operations,
    script_previews, and collision_check paths.

    Returns ``{"error": "..."}`` if the template slug is unknown.
    """
    _init()

    template = load_template(template_slug)
    if template is None:
        return {"error": f"Unknown template: '{template_slug}'. Use template_list to see available templates."}

    try:
        preview = preview_template(template, slot_values, parent_path)
        logger.info(
            "mcp_server",
            f"template_preview: {template_slug} -> {preview['operation_count']} ops, {preview['script_count']} scripts",
        )
        return preview
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def template_apply(
    template_slug: str,
    slot_values: Dict[str, Any] | None = None,
    parent_path: str = "/root/Main",
    overwrite_files: bool = False,
) -> Dict[str, Any]:
    """Instantiate a system template into the live scene.

    Loads a template, resolves slot values, creates script files,
    and executes scene operations via the existing executor pipeline.
    Collision-safe: refuses to create nodes at paths that already
    exist in the scene, and refuses to overwrite existing script
    files unless ``overwrite_files`` is true (godot-ai's script_create
    replaces files silently — your customizations would be lost).

    Call ``template_preview`` first to see what would be created.
    Call this only after confirming the preview.

    Arguments:
        {
          "template_slug": "fps_controller",
          "slot_values": {"camera_height": 1.8, "walk_speed": 5.0},
          "parent_path": "/root/Main",
          "overwrite_files": false
        }

    Returns an ExecutionResult-like dict with ``applied_count``,
    ``success``, ``errors``, ``success_count``, ``failure_count``.

    Returns ``{"error": "..."}`` on unknown template or slot errors.
    """
    _init()

    template = load_template(template_slug)
    if template is None:
        return {"error": f"Unknown template: '{template_slug}'. Use template_list to see available templates."}

    def _file_exists(rel_path: str) -> bool | None:
        """Check the Godot project for an existing script file.

        Uses godot-ai's filesystem search; returns None (undeterminable)
        when the live editor doesn't answer.
        """
        res_path = "res://" + rel_path.lstrip("/")
        found = _executor.search_filesystem(rel_path.rsplit("/", 1)[-1])
        if found is None:
            return None
        import json as _json

        return res_path in _json.dumps(found)

    try:
        # Get current scene paths for collision checking
        scene, version = _scene_store.get_or_fetch(_executor)
        from devforge.knowledge.scene.scene_graph import SceneGraph

        graph = SceneGraph(scene)
        existing_paths = set(graph.all_paths())

        with _acquire_pipeline_lock_ctx():
            result = instantiate_template(
                template,
                slot_values,
                parent_path,
                _executor,
                existing_paths,
                file_exists=_file_exists,
                overwrite_files=overwrite_files,
            )

        if result.get("success"):
            _scene_store.note_writes()

        logger.info(
            "mcp_server",
            f"template_apply: {template_slug} -> "
            f"{result.get('applied_count', 0)} applied, "
            f"{result.get('failure_count', 0)} failed",
        )

        _journal.append(
            "template_apply",
            f"Template '{template_slug}': {result.get('applied_count', 0)} ops",
            {
                "slug": template_slug,
                "applied": result.get("applied_count", 0),
                "failed": result.get("failure_count", 0),
            },
        )

        return result

    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def read_artifact(
    artifact_id: str,
    section: str | None = None,
) -> Dict[str, Any]:
    """Fetch full details of a previous apply_spec or batch_preview result.

    ``apply_spec`` returns a compact summary with an ``artifact_id``.
    Call this with that ID to see the complete file contents, operation
    details (created/modified nodes, set properties, attached scripts),
    and execution diagnostics — node paths, property changes, script
    content, and any errors encountered.

    Arguments:
        {
          "artifact_id": "a1b2c3d4e5f6",
          "section": "operations"   // optional: "files", "operations",
                                     // "execution", "errors", "arch_delta",
                                     // or omit for everything
        }

    Returns the full payload stored under that ID.
    Returns {"error": "..."} if the artifact_id is unknown.
    """
    _init()

    payload = _artifact_store.get(artifact_id)
    if payload is None:
        return {
            "error": f"Unknown artifact_id: {artifact_id}. "
            f"Artifacts are per-session and were not found "
            f"(server may have restarted). "
            f"Re-run apply_spec to get a fresh artifact_id."
        }

    if section:
        if section in payload:
            return {section: payload[section]}
        return {"error": f"Unknown section '{section}'. Available: {', '.join(sorted(payload.keys()))}"}

    return payload


# ── Direct run ──────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="sse")
