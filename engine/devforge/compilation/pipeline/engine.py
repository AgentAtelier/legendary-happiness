"""Pipeline Engine — shared pipeline orchestration.

Extracted from the FastAPI server so both it and the MCP server
can import the same pipeline logic with zero duplication.

Usage::

    engine = PipelineEngine(llm=_llm, system_graph=_system_graph, config=_config)
    result = engine.run_pipeline(prompt="add a player", scene_tree=scene)
    # result.files, result.operations, result.errors
"""

from __future__ import annotations

import functools
import json

# Bug 2 (2026-06-14): deterministic delete/rename intent pre-pass.
# Scans the prompt for "delete/remove <name>" and "rename <old> to <new>"
# patterns and injects _remove / _rename markers into the delta so the
# architecture compiler emits RemoveNodeStep / RenameNodeStep.
import re as _re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler
from devforge.compilation.pipeline.architecture_planner import ArchitecturePlanner, PlanningError
from devforge.compilation.pipeline.completeness import CompletenessChecker
from devforge.compilation.pipeline.context_assembler import ContextAssembler
from devforge.compilation.pipeline.operation_generator import OperationGenerator
from devforge.compilation.pipeline.ops_planner import OpsPlanner, OpsPlanningError
from devforge.compilation.pipeline.repair_engine import RepairEngine

# Lift GDScript pasted into the prompt *before* the planner sees it,
# so the planner does not invent duplicate systems for code we are
# about to emit verbatim.
from devforge.compilation.pipeline.script_extractor import extract as extract_scripts
from devforge.compilation.pipeline.validator import OperationValidator
from devforge.governance.quality_gate import assess_quality
from devforge.infrastructure.llm.llama_client import BudgetExceededError
from devforge.infrastructure.llm.router import LLMRouter
from devforge.infrastructure.logger import logger
from devforge.infrastructure.runtime_config import RuntimeConfig
from devforge.knowledge.scene.scene_graph import SceneGraph
from devforge.knowledge.system_graph.system_graph import SystemGraph
from devforge.reasoning.prompts.conditioning import prepend_conditioning


def _clean_rename_target(name: str) -> str:
    """Strip leading articles, trailing qualifiers, and punctuation from
    a rename from/to name — the LLM planner frequently emits names with
    articles ("the Origin"), trailing qualifiers ("Origin node"), and
    punctuation ("Renamed."). Returns a clean bare name."""
    if not name:
        return ""
    name = name.strip()
    # Leading articles
    name = _re.sub(r"^(?:the|a|an)\s+", "", name, flags=_re.IGNORECASE)
    # Trailing node/entity qualifiers
    name = _re.sub(r"\s+(?:node|entity|object)$", "", name, flags=_re.IGNORECASE)
    # Trailing punctuation (period, comma, semicolon, colon)
    name = _re.sub(r"[.,;:]+$", "", name)
    return name.strip()


_DELETE_INTENT_RE = _re.compile(
    r"(?:then|and)\s+(?:delete|remove)\s+(?:the\s+(?:node|entity)\s+)?(?:it|them)",
    _re.IGNORECASE,
)
_RENAME_TO_RE = _re.compile(
    r"(?:then|and)?\s*rename\s+(?:the\s+)?(.+?)(?:\s+(?:node|entity))?\s+to\s+(.+?)(?:$|[.,;])",
    _re.IGNORECASE,
)

# Bug 3 (2026-06-15): entity recovery regex. Extracts entity specs
# from prompts when the LLM drops them ("Create a <Type> named <Name>").
_ENTITY_FROM_PROMPT_RE = _re.compile(
    r"(?:create|add|place|spawn)\s+(?:a\s+|an\s+)?(\w+(?:3D|2D))\s+"
    r"(?:with\s+(?:a\s+)?(\w+)\s+)?(?:named|called)\s+(\w+)",
    _re.IGNORECASE,
)


def _recover_entities_from_prompt(prompt: str) -> list[dict]:
    """Extract entity specs from prompt text when the LLM drops them.

    Matches patterns like "Create a MeshInstance3D with BoxMesh named
    ScriptedCube" and returns [{"name": "ScriptedCube", "type":
    "MeshInstance3D", "props": {"mesh": "box"}}].
    """
    entities: list[dict] = []
    seen: set[str] = set()
    for m in _ENTITY_FROM_PROMPT_RE.finditer(prompt):
        node_type = m.group(1)
        mesh = m.group(2)  # optional
        name = m.group(3)
        # Skip pronouns (shouldn't match, but defense-in-depth)
        if name.lower() in ("it", "them", "this", "that", "the"):
            continue
        if name in seen:
            continue
        seen.add(name)
        entity: dict = {"name": name, "type": node_type}
        if mesh:
            entity.setdefault("props", {})["mesh"] = mesh.lower()
        entities.append(entity)
    return entities


# Governance gates — initialised in __init__, not hidden behind a module-level try/except.
# See PipelineEngine.__init__ for the explicit init.


@dataclass
class GateResult:
    """Result from a single governance gate."""

    gate_name: str
    passed: bool
    violations: List[Dict[str, Any]] = field(default_factory=list)
    risk_score: int = 0
    risk_tier: str = "unknown"
    cross_boundary: bool = False


@dataclass
class PipelineResult:
    """Result of running the full pipeline."""

    files: List[Dict[str, Any]] = field(default_factory=list)
    operations: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    arch_delta: Dict[str, Any] = field(default_factory=dict)
    scene_tree: Dict[str, Any] = field(default_factory=dict)
    scene_version: int = 0
    # Phase 9: governance gate results
    gate_results: List[GateResult] = field(default_factory=list)
    risk_score: int = 0
    risk_tier: str = "unknown"
    # Phase 10: performance metrics
    stage_latencies: Dict[str, float] = field(default_factory=dict)
    cache_stats: Dict[str, Any] = field(default_factory=dict)
    # Phase 6+: pipeline diagnostics (single source of truth for probes + shootout)
    plan_retries: int = 0  # how many retries before planner succeeded
    repair_count: int = 0  # operations fixed by repair engine
    completeness_added: int = 0  # nodes auto-injected by completeness checker
    token_used: int = 0  # tokens consumed (from LLM gateway, 0 if unavailable)
    # Workstream A2: planner instrumentation
    truncated: bool = False  # planner output hit n_predict limit

    # Slice B: deterministic quality/collapse warnings (advisory, never blocks)
    quality_warnings: List[str] = field(default_factory=list)


class PipelineEngine:
    """Orchestrates the full DevForge pipeline: prompt → operations.

    Creates and caches all pipeline components.  Designed to be shared
    between the FastAPI server and MCP server.
    """

    def __init__(
        self,
        llm: LLMRouter,
        system_graph: SystemGraph,
        config: RuntimeConfig,
        *,
        history: List[str] | None = None,
        plan_cache: Any | None = None,
        grammar_path: str | None = None,
    ):
        self._llm = llm
        self._system_graph = system_graph
        self._config = config

        # Pipeline components (stateless, safe to cache)
        self._planner = ArchitecturePlanner(
            cache=plan_cache,
            grammar_path=grammar_path,
        )
        self._ops_planner: OpsPlanner | None = None
        if config.planner_mode == "ops":
            self._ops_planner = OpsPlanner()
            logger.info("pipeline.engine", "Ops planner initialised — DEVFORGE_PLANNER=ops")

        # Spatial layout planner — always initialise when the spatial module
        # is importable, regardless of the global DEVFORGE_PLANNER setting.
        # Per-request planner="layout" / "building" relies on these being
        # ready (see run_pipeline's effective_mode routing).
        self._layout_planner: Any = None
        self._building_planner: Any = None
        self._bsp_partitioner: Any = None
        self._scatter_planner: Any = None
        self._scatter_engine: Any = None
        self._ssp_planner: Any = None
        self._ssp_engine: Any = None
        self._wfc_planner: Any = None
        self._wfc_engine: Any = None
        self._voronoi_planner: Any = None
        self._voronoi_engine: Any = None
        self._room_intent_planner: Any = None
        self._spatial_compiler: Any = None
        try:
            from devforge.spatial.bsp import BSPPartitioner
            from devforge.spatial.building_planner import BuildingPlanner
            from devforge.spatial.compiler import SpatialCompiler
            from devforge.spatial.layout_planner import LayoutPlanner
            from devforge.spatial.lexicon import AssetLexicon
            from devforge.spatial.room_intent_planner import RoomIntentPlanner
            from devforge.spatial.scatter import ScatterEngine
            from devforge.spatial.scatter_planner import ScatterPlanner
            from devforge.spatial.ssp import SSPEngine
            from devforge.spatial.ssp_planner import SSPPlanner
            from devforge.spatial.voronoi import VoronoiEngine
            from devforge.spatial.voronoi_planner import VoronoiPlanner
            from devforge.spatial.wfc import WFCEngine
            from devforge.spatial.wfc_planner import WFCPlanner

            lexicon = AssetLexicon()
            self._spatial_compiler = SpatialCompiler(lexicon)
            self._layout_planner = LayoutPlanner(lexicon, self._spatial_compiler)
            self._building_planner = BuildingPlanner(lexicon, self._spatial_compiler)
            self._bsp_partitioner = BSPPartitioner(self._spatial_compiler)
            self._scatter_planner = ScatterPlanner(lexicon)
            self._scatter_engine = ScatterEngine(lexicon)
            self._ssp_engine = SSPEngine(self._spatial_compiler)
            self._ssp_planner = SSPPlanner(lexicon, self._ssp_engine)
            self._wfc_planner = WFCPlanner()
            self._wfc_engine = WFCEngine()
            self._voronoi_planner = VoronoiPlanner()
            self._voronoi_engine = VoronoiEngine()
            self._room_intent_planner = RoomIntentPlanner(lexicon, self._ssp_engine)
            logger.info(
                "pipeline.engine",
                "Layout + building + scatter + SSP + WFC + Voronoi + RoomIntent planners initialised "
                "(per-request routing ready)",
            )
        except ImportError as exc:
            logger.warn(
                "pipeline.engine",
                f"Spatial module not importable ({exc}); layout/building/scatter/SSP planners unavailable",
            )

        self._compiler = ArchitectureCompiler()
        self._generator = OperationGenerator()
        self._completeness = CompletenessChecker()
        self._validator = OperationValidator()
        self._repair = RepairEngine()

        # Phase 9: risk scoring defaults (override per-run via run_pipeline kwargs)
        self.risk_subsystems: List[str] = ["npc_behaviour"]
        self.risk_depth: str = "new_behaviour"

        # Context assembler (needs game_root)
        self._assembler = ContextAssembler(
            game_root=Path(config.game_root),
            system_graph=system_graph,
            history=history or [],
        )

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def run_pipeline(
        self,
        prompt: str,
        scene_tree: Dict[str, Any] | None = None,
        scene_version: int = 0,
        temperature: float | None = None,
        planner: str | None = None,
        skip_cache: bool = False,
    ) -> PipelineResult:
        """Run the full pipeline: prompt → validated operations.

        Args:
            prompt: Natural language spec (e.g. "add a patrol NPC").
            scene_tree: Current Godot scene tree snapshot.
            scene_version: Version of the scene snapshot from SceneStore.
                Stamped on the returned PipelineResult so callers can
                detect staleness before execution.
            temperature: Per-call sampler override (None = use config default).
            planner: Per-call planner override — "arch" | "layout"
                | "building" | "scatter" | "ssp" | "room" | "wfc"
                | "voronoi" | "ops".
                None = use the global DEVFORGE_PLANNER config.  Set to
                "layout" for single-room spatial prompts; "building" for
                multi-room BSP buildings; "scatter" for outdoor
                garden/forest Poisson-disk placement; "ssp" for
                semantic room generation with archetype defaults; "room"
                for Intent Descriptor room generation (richer LLM brief);
                "wfc" for dungeon/cave generation via Wave Function
                Collapse; "voronoi" for town/district generation via
                Voronoi tessellation.
            skip_cache: If True, bypass the plan cache (used by harness
                diagnostics for repeat-diversity measurement).

        Returns:
            PipelineResult with files, operations, and any errors.
        """
        try:
            if not self._llm.is_configured:
                return PipelineResult(
                    errors=["LLM backend not configured"],
                    scene_tree=scene_tree or {},
                    scene_version=scene_version,
                )

            scene = self._normalize_scene(scene_tree)
            stages: Dict[str, float] = {}
            # Repair convergence state is per-run (engine instance is shared
            # across apply_spec calls — see RepairEngine.reset docstring)
            self._repair.reset()

            # Phase 0: Script extraction (deterministic, no LLM).
            # If the user pasted GDScript, lift it into create_file ops and
            # scrub it from the prompt the planner will see. Pre-planner files
            # are merged into the final result after the planner + compiler run.
            t0 = time.perf_counter()
            extracted_files, planner_prompt = extract_scripts(prompt)
            stages["script_extraction"] = (time.perf_counter() - t0) * 1000
            prompt_scrubbed = extracted_files and planner_prompt != prompt

            # If the entire prompt was GDScript, there is nothing left
            # to plan — return the extracted files without an LLM call.
            if extracted_files and not planner_prompt.strip():
                logger.info(
                    "pipeline.engine",
                    f"Prompt fully consumed by script extraction ({len(extracted_files)} file(s)) — skipping planner",
                )
                files: List[Dict[str, Any]] = []
                seen_paths: set[str] = set()
                for ef in extracted_files:
                    if ef.path not in seen_paths:
                        files.append({"path": ef.path, "content": ef.content})
                        seen_paths.add(ef.path)
                return PipelineResult(
                    files=files,
                    operations=[],
                    scene_tree=scene,
                    scene_version=scene_version,
                    stage_latencies=stages,
                )

            # Phase 0.5: System-owned conditioning (additive). Prepend the quality
            # directive so a plain user prompt gets the best output — the owner
            # never needs "magic words". Toggle: DEVFORGE_PLANNER_CONDITIONING=0.
            # (NEXT-PHASE-RECONCILED-DIRECTION.md, slice A.)
            planner_prompt = prepend_conditioning(planner_prompt)

            # Phase 1: Context Assembly
            # The architecture planner's output schema cannot use code — it
            # emits names/types/connections. Full script bodies in its context
            # are pure cost. The planner path uses signatures_only=True which
            # forces the signature-only branch of _code_context.
            t0 = time.perf_counter()
            context = self._assembler.assemble(
                scene,
                planner_prompt,
                signatures_only=True,
            )
            stages["context_assembly"] = (time.perf_counter() - t0) * 1000

            # Phase 2: Architecture Planning (LLM)
            #
            # Phase 6: When planner_mode == "ops", use direct operation
            # generation via OpsPlanner. When planner_mode == "layout",
            # use the spatial layout pipeline (Patterns+Slots+ARCS).
            # Otherwise use the default ArchitecturePlanner →
            # ArchitectureCompiler path.
            # Per-request `planner` param overrides the global config.
            # NOTE: Ops planner shelved June 14, 2026 — scored 14/100 vs
            # arch 61/100 on shootout (LLM can't emit 45+ JSON ops in one
            # constrained call). Kept behind the flag for future revisit.
            effective_mode = planner or self._config.planner_mode
            compilation_errors: List[str] = []
            if effective_mode == "layout" and self._layout_planner is not None and self._spatial_compiler is not None:
                result = self._run_layout_path(
                    context,
                    planner_prompt,
                    scene,
                    scene_version,
                    stages,
                    temperature=temperature,
                    skip_cache=skip_cache,
                )
                if isinstance(result, PipelineResult):
                    return result  # error early-return
                files, operations, arch_delta, plan_retries = result
            elif (
                effective_mode == "building"
                and self._building_planner is not None
                and self._bsp_partitioner is not None
            ):
                result = self._run_building_path(
                    context,
                    planner_prompt,
                    scene,
                    scene_version,
                    stages,
                    temperature=temperature,
                    skip_cache=skip_cache,
                )
                if isinstance(result, PipelineResult):
                    return result  # error early-return
                files, operations, arch_delta, plan_retries = result
            elif effective_mode == "scatter" and self._scatter_planner is not None and self._scatter_engine is not None:
                result = self._run_scatter_path(
                    context,
                    planner_prompt,
                    scene,
                    scene_version,
                    stages,
                    temperature=temperature,
                    skip_cache=skip_cache,
                )
                if isinstance(result, PipelineResult):
                    return result  # error early-return
                files, operations, arch_delta, plan_retries = result
            elif (
                effective_mode == "ssp"
                and self._ssp_planner is not None
                and self._ssp_engine is not None
                and self._spatial_compiler is not None
            ):
                result = self._run_ssp_path(
                    context,
                    planner_prompt,
                    scene,
                    scene_version,
                    stages,
                    temperature=temperature,
                    skip_cache=skip_cache,
                )
                if isinstance(result, PipelineResult):
                    return result  # error early-return
                files, operations, arch_delta, plan_retries = result
            elif (
                effective_mode == "room"
                and self._room_intent_planner is not None
                and self._ssp_engine is not None
                and self._spatial_compiler is not None
            ):
                result = self._run_room_path(
                    context,
                    planner_prompt,
                    scene,
                    scene_version,
                    stages,
                    temperature=temperature,
                    skip_cache=skip_cache,
                )
                if isinstance(result, PipelineResult):
                    return result  # error early-return
                files, operations, arch_delta, plan_retries = result
            elif effective_mode == "wfc" and self._wfc_planner is not None and self._wfc_engine is not None:
                result = self._run_wfc_path(
                    context,
                    planner_prompt,
                    scene,
                    scene_version,
                    stages,
                    temperature=temperature,
                    skip_cache=skip_cache,
                )
                if isinstance(result, PipelineResult):
                    return result  # error early-return
                files, operations, arch_delta, plan_retries = result
            elif effective_mode == "voronoi" and self._voronoi_planner is not None and self._voronoi_engine is not None:
                result = self._run_voronoi_path(
                    context,
                    planner_prompt,
                    scene,
                    scene_version,
                    stages,
                    temperature=temperature,
                    skip_cache=skip_cache,
                )
                if isinstance(result, PipelineResult):
                    return result  # error early-return
                files, operations, arch_delta, plan_retries = result
            elif effective_mode == "ops" and self._ops_planner is not None:
                result = self._run_ops_path(
                    context,
                    planner_prompt,
                    scene,
                    scene_version,
                    stages,
                    temperature=temperature,
                )
                if isinstance(result, PipelineResult):
                    return result  # error early-return
                files, operations, arch_delta, plan_retries = result
            else:
                result = self._run_arch_path(
                    context,
                    planner_prompt,
                    scene,
                    scene_version,
                    stages,
                    temperature=temperature,
                    skip_cache=skip_cache,
                )
                if isinstance(result, PipelineResult):
                    return result  # error early-return
                files, operations, arch_delta, plan_retries, compilation_errors = result

            # Phase 5: Completeness
            t0 = time.perf_counter()
            op_count_before = len(operations)
            operations = self._completeness.enforce(files, operations, scene)
            completeness_added = len(operations) - op_count_before
            stages["completeness"] = (time.perf_counter() - t0) * 1000

            # Phase 6: Validation
            t0 = time.perf_counter()
            operations, errors = self._validator.validate(operations, scene, files)
            stages["validation"] = (time.perf_counter() - t0) * 1000

            # Merge compiler-detected semantic errors (Slice 4, 2026-06-15).
            # These are errors the architecture_compiler found that don't go
            # through the validator (e.g. Camera3D with MeshInstance3D child).
            if compilation_errors:
                errors = compilation_errors + errors
                logger.info(
                    "pipeline.engine",
                    f"Merged {len(compilation_errors)} compiler semantic error(s)",
                )

            # Phase 7: Repair
            t0 = time.perf_counter()
            repair_count = 0
            if errors:
                op_count_before_repair = len(operations)
                operations = self._repair.repair(operations, errors, scene, files)
                repair_count = len(operations) - op_count_before_repair
            stages["repair"] = (time.perf_counter() - t0) * 1000

            # Slice B: deterministic quality gate (advisory — signals, never blocks).
            quality_warnings = assess_quality(operations, arch_delta, planner_prompt)
            if quality_warnings:
                logger.warn(
                    "pipeline.engine",
                    f"quality gate: {'; '.join(quality_warnings)}",
                )

            # Phase 9: Run governance gates on generated files
            t0 = time.perf_counter()
            gate_results = self._run_governance_gates(
                files=files,
                file_paths=[f.get("path", "") for f in files],
                subsystems=getattr(self, "risk_subsystems", ["game_logic"]),
                depth=getattr(self, "risk_depth", "new_behaviour"),
            )
            stages["governance"] = (time.perf_counter() - t0) * 1000
            risk_score = sum(gr.risk_score for gr in gate_results)
            risk_tier = "unknown"
            if gate_results:
                tiers = [gr.risk_tier for gr in gate_results if gr.risk_tier != "unknown"]
                if tiers:
                    order = {"low": 0, "medium": 1, "high": 2, "critical": 3, "unknown": -1}
                    risk_tier = max(tiers, key=lambda t: order.get(t, -1))

            # If any gate blocks, add errors
            for gr in gate_results:
                if not gr.passed:
                    for v in gr.violations:
                        errors.append(
                            f"[{gr.gate_name}] {v.get('rule_id', '?')}: {v.get('message', v.get('description', ''))}"
                        )

            # Cache stats from planner
            cache_stats = self._planner.cache_stats or {}

            # Merge pre-planner extracted scripts into the final result
            # so the executor actually creates them. Extracted files
            # always win on path collision (they reflect user intent).
            if extracted_files:
                seen_paths = {f.get("path") for f in files}
                for ef in extracted_files:
                    if ef.path not in seen_paths:
                        files.append({"path": ef.path, "content": ef.content})
                        seen_paths.add(ef.path)
                if prompt_scrubbed:
                    logger.info(
                        "pipeline.engine",
                        f"Merged {len(extracted_files)} pre-planner script(s) into result",
                    )

            return PipelineResult(
                files=files,
                operations=operations,
                errors=errors,
                arch_delta=arch_delta,
                scene_tree=scene,
                scene_version=scene_version,
                gate_results=gate_results,
                quality_warnings=quality_warnings,
                risk_score=risk_score,
                risk_tier=risk_tier,
                stage_latencies=stages,
                cache_stats=cache_stats,
                plan_retries=plan_retries,
                repair_count=repair_count,
                completeness_added=completeness_added,
                token_used=0,  # TODO: capture from LLM gateway when available
                truncated=False,
            )

        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("pipeline.engine", f"Pipeline failed: {exc}\n{tb}")
            return PipelineResult(
                errors=[str(exc)],
                scene_tree=scene_tree or {},
                scene_version=scene_version,
            )

    # ------------------------------------------------------------------
    # Governance gates (Phase 9)
    # ------------------------------------------------------------------

    def _run_governance_gates(
        self,
        files: List[Dict[str, Any]],
        file_paths: List[str],
        subsystems: Optional[List[str]] = None,
        depth: str = "new_behaviour",
    ) -> List[GateResult]:
        """Run all governance gates against generated files.

        Returns a GateResult per gate that was run.  When governance
        modules are unavailable, returns an empty list.
        """
        results: List[GateResult] = []

        try:
            from devforge.governance.gate1 import run_gate1
            from devforge.governance.risk_scoring import compute_risk
        except ImportError:
            logger.warn("pipeline.engine", "Governance modules not importable; gates skipped")
            return results

        # ── Gate 1: Structural Contracts ──
        try:
            projects_dir = str(self._config.game_root) if self._config.game_root else "."
            gate1 = run_gate1(
                project_root=projects_dir,
                changed_files=[fp for fp in file_paths if fp.endswith(".gd")],
            )
            gr = GateResult(
                gate_name="gate1_structural",
                passed=gate1.passed,
                violations=[v.to_dict() for v in gate1.violations],
                cross_boundary=gate1.cross_boundary_detected,
            )
            results.append(gr)
            logger.info(
                "pipeline.engine",
                f"Gate 1: {'PASS' if gate1.passed else 'FAIL'} "
                f"({len(gate1.violations)} violations, {len(gate1.warnings)} warnings)",
            )
        except Exception as exc:
            logger.error("pipeline.engine", f"Gate 1 failed: {exc}")

        # ── Risk Scoring ──
        try:
            risk = compute_risk(
                subsystems=subsystems or ["game_logic"],
                depth=depth,
                files_modified=len(files),
                crosses_sim_render=any(hasattr(gr, "cross_boundary") and gr.cross_boundary for gr in results),
            )
            gr = GateResult(
                gate_name="risk_scoring",
                passed=risk.tier.value != "critical",
                risk_score=risk.final_score,
                risk_tier=risk.tier.value,
            )
            results.append(gr)
            logger.info(
                "pipeline.engine",
                f"Risk scoring: score={risk.final_score}, tier={risk.tier.value}",
            )
        except Exception as exc:
            logger.error("pipeline.engine", f"Risk scoring failed: {exc}")

        return results

    @property
    def cache_stats(self) -> Optional[Dict]:
        """Cache hit/miss stats from the planner (None if no cache configured)."""
        return self._planner.cache_stats

    @property
    def grammar(self) -> Optional[str]:
        """The GBNF grammar for JSON output constraint (if configured)."""
        return self._planner.grammar

    def update_history(self, prompt: str) -> None:
        """Record a prompt in the context assembler's history.

        Call after each ``run_pipeline()`` to keep history current
        for subsequent requests.
        """
        self._assembler.history.append(prompt)
        if len(self._assembler.history) > self._assembler.MAX_HISTORY:
            self._assembler.history.pop(0)

    # ------------------------------------------------------------------
    # Phase 6: Ops path (DEVFORGE_PLANNER=ops)
    # ------------------------------------------------------------------

    def _run_ops_path(
        self,
        context: str,
        planner_prompt: str,
        scene: Dict[str, Any],
        scene_version: int,
        stages: Dict[str, float],
        temperature: float | None = None,
    ) -> Tuple[List[Dict], List[Dict], Dict, int] | PipelineResult:
        """Run the ops path: LLM emits operations directly.

        Returns (files, operations, arch_delta, plan_retries) on success, or
        PipelineResult on error (caller should return it immediately).
        """
        t0 = time.perf_counter()
        ops_grammar = self._ops_planner.grammar
        ops_kwargs: dict[str, object] = {}
        if ops_grammar:
            ops_kwargs["grammar"] = ops_grammar
        if temperature is not None:
            ops_kwargs["temperature"] = temperature
        ops_llm_fn = functools.partial(self._llm.generate, **ops_kwargs) if ops_kwargs else self._llm.generate

        max_retries = self._config.max_plan_retries
        ops_result = None
        retry_prompt = planner_prompt
        retry_errors: List[str] = []

        for attempt in range(1, max_retries + 1):
            try:
                ops_result = self._ops_planner.plan(
                    context=context,
                    prompt=retry_prompt,
                    llm_fn=ops_llm_fn,
                    scene=scene,
                )
                break
            except BudgetExceededError:
                stages["architecture_planning"] = (time.perf_counter() - t0) * 1000
                return PipelineResult(
                    errors=[
                        "Token budget exceeded — the LLM Gateway rejected "
                        "this request because the per-turn token limit "
                        "was reached."
                    ],
                    scene_tree=scene,
                    scene_version=scene_version,
                    stage_latencies=stages,
                )
            except OpsPlanningError as ope:
                retry_errors.append(str(ope))
                if attempt == max_retries:
                    stages["architecture_planning"] = (time.perf_counter() - t0) * 1000
                    return PipelineResult(
                        errors=[f"Ops planning failed after {attempt} attempts: " + "; ".join(retry_errors)],
                        scene_tree=scene,
                        scene_version=scene_version,
                        stage_latencies=stages,
                    )
                retry_prompt = f"{planner_prompt}\n\nThe previous output failed: {ope}. Fix only those issues."
                logger.info(
                    "pipeline.engine",
                    f"Ops planning retry {attempt}/{max_retries}",
                )

        stages["architecture_planning"] = (time.perf_counter() - t0) * 1000

        if ops_result is None:
            return PipelineResult(
                errors=["Ops planner returned no result — max_retries may be 0."],
                scene_tree=scene,
                scene_version=scene_version,
                stage_latencies=stages,
            )

        if self._llm.last_truncated:
            logger.warn("pipeline.engine", "Ops plan was truncated by n_predict")
            return PipelineResult(
                errors=["Operations plan truncated — response hit n_predict limit."],
                scene_tree=scene,
                scene_version=scene_version,
                stage_latencies=stages,
                truncated=True,
            )

        files = self._dedupe_files(ops_result.get("files", []))
        operations = self._dedupe_operations(ops_result.get("operations", []))
        stages["compilation"] = 0.0
        stages["operation_generation"] = 0.0

        plan_retries = attempt - 1  # 0 if first attempt succeeded
        return files, operations, {}, plan_retries  # no arch_delta in ops mode

    # ------------------------------------------------------------------
    # Arch path (default: DEVFORGE_PLANNER=arch)
    # ------------------------------------------------------------------

    def _run_arch_path(
        self,
        context: str,
        planner_prompt: str,
        scene: Dict[str, Any],
        scene_version: int,
        stages: Dict[str, float],
        temperature: float | None = None,
        skip_cache: bool = False,
    ) -> Tuple[List[Dict], List[Dict], Dict, int, List[str]] | PipelineResult:
        """Run the arch path: planner → compiler → operation generator.

        Returns (files, operations, arch_delta, plan_retries, compilation_errors) on success, or
        PipelineResult on error (caller should return it immediately).
        """
        t0 = time.perf_counter()
        planner_grammar = self._planner.grammar
        arch_profile = self._config.sampler_profiles.get("arch", {})
        if temperature is not None:
            arch_profile = {**arch_profile, "temperature": temperature}
        llm_fn = (
            functools.partial(self._llm.generate, grammar=planner_grammar, **arch_profile)
            if planner_grammar
            else functools.partial(self._llm.generate, **arch_profile)
        )

        arch_delta = None
        retry_errors: List[str] = []
        retry_prompt = planner_prompt

        max_retries = self._config.max_plan_retries
        for attempt in range(1, max_retries + 1):
            try:
                arch_delta = self._planner.plan(
                    context=context,
                    prompt=retry_prompt,
                    llm_fn=llm_fn,
                    scene=scene,
                    graph=self._system_graph,
                    skip_cache=skip_cache,
                )
                break
            except BudgetExceededError:
                stages["architecture_planning"] = (time.perf_counter() - t0) * 1000
                return PipelineResult(
                    errors=[
                        "Token budget exceeded — the LLM Gateway rejected "
                        "this request because the per-turn token limit was "
                        "reached. Simplify the prompt or raise "
                        "GATEWAY_BUDGET_TOKENS."
                    ],
                    scene_tree=scene,
                    scene_version=scene_version,
                    stage_latencies=stages,
                )
            except PlanningError as pe:
                retry_errors.append(str(pe))
                if attempt == max_retries:
                    stages["architecture_planning"] = (time.perf_counter() - t0) * 1000
                    return PipelineResult(
                        errors=[f"Architecture planning failed after {attempt} attempts: " + "; ".join(retry_errors)],
                        scene_tree=scene,
                        scene_version=scene_version,
                        stage_latencies=stages,
                    )
                is_budget_error = "budget" in str(pe).lower() or "token" in str(pe).lower()
                retry_prompt = f"{planner_prompt}\n\nThe previous plan failed: {pe}. Fix only those issues."
                context = self._assembler.assemble(
                    scene,
                    retry_prompt,
                    minimal=(attempt >= 2 and is_budget_error),
                    signatures_only=True,
                )
                ctx_label = "trimmed" if (attempt >= 2 and is_budget_error) else "full"
                logger.info(
                    "pipeline.engine",
                    f"Planning retry {attempt}/{max_retries} — "
                    f"{ctx_label} context ({len(context)} chars, "
                    f"budget_error={is_budget_error})",
                )

        stages["architecture_planning"] = (time.perf_counter() - t0) * 1000

        # Telemetry: planned entity count (visibility + conditioning A/B).
        # Grep-able: "Arch plan parsed: N entities".
        logger.info(
            "pipeline.engine",
            f"Arch plan parsed: {len(arch_delta.get('entities', []))} entities",
        )

        # Deterministic dedup — check the LIVE scene tree (source of truth).
        # The old dedup checked only the in-memory system_graph which is
        # shared across ALL apply_spec calls and never pruned; entities
        # deleted by probe-scene reset (gauntlet, scenarios) remained in
        # the graph and were silently dropped, causing apply_spec to report
        # success while building nothing (P2 root cause, 6/14).
        #
        # The fix: check the live scene.  If an entity exists in the live
        # scene, skip it — whoever put it there (previous apply_spec,
        # manual edit) already created it.  If it does NOT exist in the
        # live scene, allow it through — even if the system_graph still
        # remembers a now-deleted node from a prior run.
        def _live_scene_names(node: dict) -> set[str]:
            names: set[str] = set()
            n = node.get("name", "")
            if n:
                names.add(n)
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    names |= _live_scene_names(child)
            return names

        scene_names = _live_scene_names(scene)

        new_entities = [e for e in arch_delta.get("entities", []) if e.get("name") not in scene_names]
        dropped = len(arch_delta.get("entities", [])) - len(new_entities)
        if dropped > 0:
            logger.info(
                "pipeline.engine",
                f"Deterministic dedup: dropped {dropped} entities already "
                f"in live scene ({len(scene_names)} names in tree)",
            )
        arch_delta["entities"] = new_entities

        if self._llm.last_truncated:
            logger.warn("pipeline.engine", "Architecture plan was truncated by n_predict")
            return PipelineResult(
                errors=[
                    "Architecture plan truncated — response hit n_predict limit. "
                    "Try a simpler prompt or raise max_tokens."
                ],
                scene_tree=scene,
                scene_version=scene_version,
                stage_latencies=stages,
                truncated=True,
            )

        # Bug 2 (2026-06-14): deterministic delete/rename intent pre-pass.
        # The LLM planner emits a duplicate add_node instead of _remove/_rename
        # markers for "create then delete/rename" prompts. Scan the prompt and
        # inject the correct markers so the architecture compiler generates
        # RemoveNodeStep / RenameNodeStep instead of a duplicate CreateEntityStep.
        #
        # Bug 2.3 (2026-06-15): the LLM planner can also emit _rename directly
        # with dirty names ("the Origin node" → "Renamed."). Clean the planner's
        # _rename in-place even when we don't inject a new one.
        #
        # Also strip spurious systems the LLM invents for pure edit prompts —
        # a "create then delete" prompt should not produce an attach_script.
        _delete_match = _DELETE_INTENT_RE.search(planner_prompt)
        _rename_match = _RENAME_TO_RE.search(planner_prompt)
        _has_edit_intent = bool(_delete_match or _rename_match)

        if _has_edit_intent:
            entities = arch_delta.get("entities", [])
            if _delete_match and entities:
                # The LLM created the node then didn't emit _remove.
                # Find the first entity the LLM planned (the one to delete)
                # and inject _remove for it.
                target_name = entities[0].get("name", "") if entities else ""
                if target_name and not arch_delta.get("_remove"):
                    arch_delta["_remove"] = target_name
                    logger.info(
                        "pipeline.engine",
                        f"Deterministic delete: injected _remove for '{target_name}'",
                    )
            if _rename_match and not arch_delta.get("_rename"):
                old = _rename_match.group(1).strip()
                new = _rename_match.group(2).strip()
                # Bug 2.2 (2026-06-15): the non-greedy (.+?) in
                # _RENAME_TO_RE captures literal pronouns ("it", "them",
                # "this", "that") instead of the entity name. Resolve
                # pronouns to the first entity created in this delta so
                # the compiler renames the correct node.
                if old.lower() in ("it", "them", "this", "that"):
                    entities = arch_delta.get("entities", [])
                    if entities:
                        old = entities[0].get("name", old)
                    else:
                        old = ""  # can't resolve pronoun→skip rename
                old = _clean_rename_target(old)
                new = _clean_rename_target(new)
                if old and new:
                    arch_delta["_rename"] = {"from": old, "to": new}
                    logger.info(
                        "pipeline.engine",
                        f"Deterministic rename: injected _rename {old}→{new}",
                    )
            # Bug 2.3: clean the planner's _rename in-place when it emitted
            # its own (dirty) _rename — the guard above skips injection, but
            # the names may still need article/qualifier/punctuation stripping.
            if arch_delta.get("_rename") and isinstance(arch_delta["_rename"], dict):
                rn = arch_delta["_rename"]
                old_raw = rn.get("from", "")
                new_raw = rn.get("to", "")
                old_clean = _clean_rename_target(old_raw)
                new_clean = _clean_rename_target(new_raw)
                if old_clean != old_raw or new_clean != new_raw:
                    rn["from"] = old_clean
                    rn["to"] = new_clean
                    logger.info(
                        "pipeline.engine",
                        f"Cleaned planner _rename: '{old_raw}'→'{old_clean}', '{new_raw}'→'{new_clean}'",
                    )
            # Strip spurious systems for pure edit prompts — the LLM shouldn't
            # invent scripts for "create then delete" or "create then rename".
            if arch_delta.get("systems"):
                sys_names = [s.get("name", "?") for s in arch_delta["systems"] if isinstance(s, dict)]
                logger.info(
                    "pipeline.engine",
                    f"Stripping {len(sys_names)} spurious system(s) from edit prompt: {sys_names}",
                )
                arch_delta["systems"] = []

        # T2: recover behavior systems the planner shed under load. On big
        # prompts the LLM emits entities but 0 systems → 0 scripts; infer the
        # missing systems deterministically from the prompt + entity types.
        # Gate: skip infer_systems for pure edit prompts (delete/rename) —
        # those should not get behavior scripts.
        #
        # IMPORTANT: entity recovery (Bug 3) runs BEFORE infer_systems so
        # that recovered entities are visible to the intent detector — if
        # the LLM dropped both entity AND system, we recover the entity
        # first, then infer_systems can match the recovered entity's type
        # against keyword intents.
        #
        # Bug 3 (2026-06-15): entity recovery — when the LLM drops entities
        # for prompts that clearly describe creating named nodes (e.g.
        # "Create a MeshInstance3D ... named ScriptedCube ..."), extract
        # entity specs from the prompt and inject them so the compiler has
        # something to build. This is the complement of infer_systems:
        # recover entities the LLM dropped alongside systems.
        if not arch_delta.get("entities") and not _has_edit_intent:
            recovered = _recover_entities_from_prompt(planner_prompt)
            if recovered:
                # Don't inject entities that already exist in the live scene
                fresh = [e for e in recovered if e.get("name") not in scene_names]
                if fresh:
                    arch_delta["entities"] = fresh
                    logger.info(
                        "pipeline.engine",
                        f"Recovered {len(fresh)} entity(s) the LLM dropped: {[e.get('name') for e in fresh]}",
                    )

        inferred: list[dict] = []
        if not _has_edit_intent:
            inferred = self._compiler.infer_systems(
                planner_prompt, arch_delta.get("entities", []), arch_delta.get("systems", [])
            )
        if inferred:
            arch_delta.setdefault("systems", []).extend(inferred)
            logger.info(
                "pipeline.engine",
                f"Inferred {len(inferred)} behavior system(s) the planner omitted: {[s['name'] for s in inferred]}",
            )

        # Phase 3: Compilation
        t0 = time.perf_counter()
        scene_graph = SceneGraph(scene)
        plan = self._compiler.compile(arch_delta, scene=scene_graph)
        stages["compilation"] = (time.perf_counter() - t0) * 1000

        # Collect compiler-detected semantic errors (Slice 4, 2026-06-15).
        # The architecture_compiler may detect semantically invalid
        # constructs (e.g. Camera3D with MeshInstance3D child) that are
        # structurally valid but wrong. These errors are surfaced in
        # the pipeline result so callers (gauntlet, scenarios) can count
        # them as validation failures.
        compilation_errors: List[str] = list(getattr(self._compiler, "_semantic_errors", []))

        # Phase 4: Operation Generation
        t0 = time.perf_counter()
        result = self._generator.generate_from_plan(plan)
        files = self._dedupe_files(result.get("files", []))
        operations = self._dedupe_operations(result.get("operations", []))
        stages["operation_generation"] = (time.perf_counter() - t0) * 1000

        plan_retries = attempt - 1  # 0 if first attempt succeeded
        return files, operations, arch_delta, plan_retries, compilation_errors

    # ------------------------------------------------------------------
    # Shared spatial path factory — used by all planner="*" routes
    # ------------------------------------------------------------------

    def _run_spatial_path(
        self,
        context: str,
        planner_prompt: str,
        scene: Dict[str, Any],
        scene_version: int,
        stages: Dict[str, float],
        *,
        planner_instance: Any,
        compile_fn: Any,
        arch_key: str,
        planner_label: str,
        temperature: float | None = None,
        skip_cache: bool = False,
    ) -> Tuple[List[Dict], List[Dict], Dict, int] | PipelineResult:
        """Run a spatial planner path: planner → engine → op generator.

        All five spatial paths (layout, building, scatter, ssp, wfc) share
        this exact structure.  Only the planner instance, compile function,
        arch_delta key, and log label vary.

        Args:
            planner_instance: Any planner with ``.plan()`` and ``.grammar``.
            compile_fn: ``(json_result, root_path=...) -> DevForgePlan``.
            arch_key: Key for arch_delta dict (``"_layout"``, ``"_wfc"``, …).
            planner_label: Human label for log messages (``"Layout"``, …).

        Returns:
            (files, operations, arch_delta, plan_retries) on success, or
            PipelineResult on error (caller should return it immediately).
        """
        t0 = time.perf_counter()
        grammar = planner_instance.grammar
        arch_profile = self._config.sampler_profiles.get("arch", {})
        if temperature is not None:
            arch_profile = {**arch_profile, "temperature": temperature}
        llm_fn = (
            functools.partial(self._llm.generate, grammar=grammar, **arch_profile)
            if grammar
            else functools.partial(self._llm.generate, **arch_profile)
        )

        json_result: Dict = {}
        max_retries = self._config.max_plan_retries
        retry_errors: List[str] = []
        retry_prompt = planner_prompt

        for attempt in range(1, max_retries + 1):
            try:
                json_result = planner_instance.plan(
                    context=context,
                    prompt=retry_prompt,
                    llm_fn=llm_fn,
                    scene=scene,
                    skip_cache=skip_cache,
                )
                break
            except BudgetExceededError:
                stages["architecture_planning"] = (time.perf_counter() - t0) * 1000
                return PipelineResult(
                    errors=[f"Token budget exceeded during {planner_label} planning."],
                    scene_tree=scene,
                    scene_version=scene_version,
                    stage_latencies=stages,
                )
            except Exception as exc:
                retry_errors.append(str(exc))
                if attempt == max_retries:
                    stages["architecture_planning"] = (time.perf_counter() - t0) * 1000
                    return PipelineResult(
                        errors=[
                            f"{planner_label} planning failed after {attempt} attempts: " + "; ".join(retry_errors)
                        ],
                        scene_tree=scene,
                        scene_version=scene_version,
                        stage_latencies=stages,
                    )
                retry_prompt = f"{planner_prompt}\n\nThe previous plan failed: {exc}. Fix only those issues."
                logger.info(
                    "pipeline.engine",
                    f"{planner_label} planning retry {attempt}/{max_retries}",
                )

        stages["architecture_planning"] = (time.perf_counter() - t0) * 1000

        if self._llm.last_truncated:
            logger.warn("pipeline.engine", f"{planner_label} plan was truncated by n_predict")
            return PipelineResult(
                errors=[f"{planner_label} plan truncated — response hit n_predict limit."],
                scene_tree=scene,
                scene_version=scene_version,
                stage_latencies=stages,
                truncated=True,
            )

        # Phase 3: Compilation (JSON → DevForgePlan)
        t0 = time.perf_counter()
        try:
            root_name = scene.get("name", "Main")
            root_path = f"/root/{root_name}"
            plan = compile_fn(json_result, root_path=root_path)
        except Exception as exc:
            logger.error("pipeline.engine", f"{planner_label} compilation failed: {exc}")
            return PipelineResult(
                errors=[f"{planner_label} compilation failed: {exc}"],
                scene_tree=scene,
                scene_version=scene_version,
                stage_latencies=stages,
            )
        stages["compilation"] = (time.perf_counter() - t0) * 1000

        # Phase 4: Operation Generation
        t0 = time.perf_counter()
        result = self._generator.generate_from_plan(plan)
        files = self._dedupe_files(result.get("files", []))
        operations = self._dedupe_operations(result.get("operations", []))
        stages["operation_generation"] = (time.perf_counter() - t0) * 1000

        plan_retries = attempt - 1
        # Pass the JSON as arch_delta so probes can inspect it
        arch_delta = {
            arch_key: json_result,
            "systems": [],
            "entities": [],
            "connections": [],
        }
        return files, operations, arch_delta, plan_retries

    # ------------------------------------------------------------------
    # Layout path (DEVFORGE_PLANNER=layout) — spatial room generation
    # ------------------------------------------------------------------

    def _run_layout_path(
        self,
        context: str,
        planner_prompt: str,
        scene: Dict[str, Any],
        scene_version: int,
        stages: Dict[str, float],
        temperature: float | None = None,
        skip_cache: bool = False,
    ) -> Tuple[List[Dict], List[Dict], Dict, int] | PipelineResult:
        """Run the layout path: layout planner → spatial compiler → op generator."""
        return self._run_spatial_path(
            context,
            planner_prompt,
            scene,
            scene_version,
            stages,
            planner_instance=self._layout_planner,
            compile_fn=self._spatial_compiler.compile_layout,
            arch_key="_layout",
            planner_label="Layout",
            temperature=temperature,
            skip_cache=skip_cache,
        )

    # ------------------------------------------------------------------
    # Building path (planner="building") — BSP multi-room generation
    # ------------------------------------------------------------------

    def _run_building_path(
        self,
        context: str,
        planner_prompt: str,
        scene: Dict[str, Any],
        scene_version: int,
        stages: Dict[str, float],
        temperature: float | None = None,
        skip_cache: bool = False,
    ) -> Tuple[List[Dict], List[Dict], Dict, int] | PipelineResult:
        """Run the building path: building planner → BSP partitioner → op generator."""
        return self._run_spatial_path(
            context,
            planner_prompt,
            scene,
            scene_version,
            stages,
            planner_instance=self._building_planner,
            compile_fn=self._bsp_partitioner.compile_building,
            arch_key="_building",
            planner_label="Building",
            temperature=temperature,
            skip_cache=skip_cache,
        )

    # ------------------------------------------------------------------
    # Scatter path (planner="scatter") — outdoor Poisson-disk placement
    # ------------------------------------------------------------------

    def _run_scatter_path(
        self,
        context: str,
        planner_prompt: str,
        scene: Dict[str, Any],
        scene_version: int,
        stages: Dict[str, float],
        temperature: float | None = None,
        skip_cache: bool = False,
    ) -> Tuple[List[Dict], List[Dict], Dict, int] | PipelineResult:
        """Run the scatter path: scatter planner → scatter engine → op generator."""
        return self._run_spatial_path(
            context,
            planner_prompt,
            scene,
            scene_version,
            stages,
            planner_instance=self._scatter_planner,
            compile_fn=self._scatter_engine.compile_garden,
            arch_key="_scatter",
            planner_label="Scatter",
            temperature=temperature,
            skip_cache=skip_cache,
        )

    # ------------------------------------------------------------------
    # SSP path (planner="ssp") — Semantic Spatial Primitives
    # ------------------------------------------------------------------

    def _run_ssp_path(
        self,
        context: str,
        planner_prompt: str,
        scene: Dict[str, Any],
        scene_version: int,
        stages: Dict[str, float],
        temperature: float | None = None,
        skip_cache: bool = False,
    ) -> Tuple[List[Dict], List[Dict], Dict, int] | PipelineResult:
        """Run the SSP path: SSP planner → SSP engine → op generator."""
        return self._run_spatial_path(
            context,
            planner_prompt,
            scene,
            scene_version,
            stages,
            planner_instance=self._ssp_planner,
            compile_fn=self._ssp_engine.compile_room,
            arch_key="_ssp",
            planner_label="SSP",
            temperature=temperature,
            skip_cache=skip_cache,
        )

    # ------------------------------------------------------------------
    # Voronoi path (planner="voronoi") — district/town generation
    # ------------------------------------------------------------------

    def _run_voronoi_path(
        self,
        context: str,
        planner_prompt: str,
        scene: Dict[str, Any],
        scene_version: int,
        stages: Dict[str, float],
        temperature: float | None = None,
        skip_cache: bool = False,
    ) -> Tuple[List[Dict], List[Dict], Dict, int] | PipelineResult:
        """Run the Voronoi path: Voronoi planner → Voronoi engine → op generator."""
        return self._run_spatial_path(
            context,
            planner_prompt,
            scene,
            scene_version,
            stages,
            planner_instance=self._voronoi_planner,
            compile_fn=self._voronoi_engine.compile_town,
            arch_key="_voronoi",
            planner_label="Voronoi",
            temperature=temperature,
            skip_cache=skip_cache,
        )

    # ------------------------------------------------------------------
    # WFC path (planner="wfc") — Wave Function Collapse dungeon gen
    # ------------------------------------------------------------------

    def _run_wfc_path(
        self,
        context: str,
        planner_prompt: str,
        scene: Dict[str, Any],
        scene_version: int,
        stages: Dict[str, float],
        temperature: float | None = None,
        skip_cache: bool = False,
    ) -> Tuple[List[Dict], List[Dict], Dict, int] | PipelineResult:
        """Run the WFC path: WFC planner → WFC engine → op generator."""
        return self._run_spatial_path(
            context,
            planner_prompt,
            scene,
            scene_version,
            stages,
            planner_instance=self._wfc_planner,
            compile_fn=self._wfc_engine.compile_dungeon,
            arch_key="_wfc",
            planner_label="WFC",
            temperature=temperature,
            skip_cache=skip_cache,
        )

    # ------------------------------------------------------------------
    # Room Intent path (planner="room") — Intent Descriptor room gen
    # ------------------------------------------------------------------

    def _run_room_path(
        self,
        context: str,
        planner_prompt: str,
        scene: Dict[str, Any],
        scene_version: int,
        stages: Dict[str, float],
        temperature: float | None = None,
        skip_cache: bool = False,
    ) -> Tuple[List[Dict], List[Dict], Dict, int] | PipelineResult:
        """Run the room path: RoomIntent planner → SSP engine → op generator."""
        return self._run_spatial_path(
            context,
            planner_prompt,
            scene,
            scene_version,
            stages,
            planner_instance=self._room_intent_planner,
            compile_fn=self._ssp_engine.compile_room,
            arch_key="_room",
            planner_label="RoomIntent",
            temperature=temperature,
            skip_cache=skip_cache,
        )

    # ------------------------------------------------------------------
    # Validation-only
    # ------------------------------------------------------------------

    def validate_pipeline(
        self,
        operations: List[Dict[str, Any]],
        scene_tree: Dict[str, Any],
        files: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Validate operations against a scene tree.

        Returns (valid_ops, error_messages).
        """
        scene = self._normalize_scene(scene_tree)
        return self._validator.validate(operations, scene, files)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_scene(scene_tree: Dict[str, Any] | None) -> Dict[str, Any]:
        """Ensure scene_tree has a proper root wrapper."""
        if not scene_tree:
            return {"name": "Main", "type": "Node3D", "children": []}

        name = scene_tree.get("name", "")
        if name == "root":
            children = scene_tree.get("children", [])
            if children:
                return children[0]
            return {"name": "Main", "type": "Node3D", "children": []}

        return scene_tree

    @staticmethod
    def _dedupe_files(files: List[dict]) -> List[dict]:
        seen: set = set()
        result: list = []
        for f in files:
            path = f.get("path")
            if path and path not in seen:
                seen.add(path)
                result.append(f)
        return result

    @staticmethod
    def _dedupe_operations(ops: List[dict]) -> List[dict]:
        seen: set = set()
        result: list = []
        for op in ops:
            try:
                key = json.dumps(op, sort_keys=True, default=str)
            except Exception:
                key = id(op)
            if key not in seen:
                seen.add(key)
                result.append(op)
        return result
