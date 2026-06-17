"""
Coordinator — bounded blackboard loop with governance gates.

Orchestrates the full multi-agent pipeline:
    architect → planner → builder → QA → repair

Each agent reads/writes to a shared context dict (the blackboard).
Governance gates (scope lock, risk scoring, Gate 1) run automatically
at the appropriate checkpoints.

Phase 9: Fully wired with real pipeline components and governance.

Usage:
    coordinator = Coordinator(llm=llm_router, config=runtime_config)
    result = coordinator.run("add a patrol NPC", scene_tree)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from devforge.infrastructure.logger import logger
from devforge.infrastructure.runtime_config import RuntimeConfig
from devforge.infrastructure.llm.router import LLMRouter
from devforge.knowledge.system_graph.system_graph import SystemGraph, NodeType

from devforge.reasoning.agents.architect_agent import ArchitectAgent
from devforge.reasoning.agents.planner_agent import PlannerAgent
from devforge.reasoning.agents.builder_agent import BuilderAgent
from devforge.reasoning.agents.qa_agent import QAAgent
from devforge.reasoning.agents.repair_agent import RepairAgent


class Coordinator:
    """Bounded blackboard loop that orchestrates multi-step features.

    Each sub-task flows through: scope-lock → plan → compile →
    validate → govern → checkpoint → apply → repair.

    The SystemGraph (blackboard) is updated after each sub-task.
    """

    MAX_REPAIR_ATTEMPTS: int = 3

    def __init__(
        self,
        llm: LLMRouter,
        config: RuntimeConfig,
        system_graph: Optional[SystemGraph] = None,
    ):
        """Args:
        llm: LLM router for agent inference.
        config: Runtime configuration.
        system_graph: Shared SystemGraph (blackboard). Created if None.
        """
        self._llm = llm
        self._config = config
        self.graph = system_graph or SystemGraph()

        # Create agents
        self.architect = ArchitectAgent(llm)
        self.planner = PlannerAgent(llm)
        self.builder = BuilderAgent()
        self.qa = QAAgent()
        self.repair = RepairAgent()

        # Governance (lazy-loaded)
        self._scope_lock_fn = None
        self._risk_fn = None

        # Transaction class
        from devforge.transaction.transaction import ExecutionTransaction

        self.transaction_cls = ExecutionTransaction

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def run(
        self,
        prompt: str,
        scene_tree: Dict[str, Any],
        subsystems: Optional[List[str]] = None,
        depth: str = "new_behaviour",
    ) -> Dict[str, Any]:
        """Run the full multi-agent pipeline for a prompt.

        Args:
            prompt: Natural language feature spec.
            scene_tree: Current Godot scene tree snapshot.
            subsystems: Subsystems touched (for risk scoring).
            depth: Modification depth classification.

        Returns:
            Context dict with all generated artifacts and governance results.
        """
        context: Dict[str, Any] = {
            "prompt": prompt,
            "scene_tree": scene_tree,
            "system_graph": self.graph,
            "subsystems": subsystems or ["game_logic"],
            "depth": depth,
        }

        # ── 0. Pre-flight governance (scope lock + risk scoring) ──
        self._run_preflight(context)

        # Check if blocked
        if context.get("blocked"):
            return context

        # ── 1. Architecture ──
        logger.info("coordinator", "Step 1: Architecture")
        arch_result = self.architect.run(context)
        context.update(arch_result)

        # Update blackboard with architecture entities
        for sys_name in context.get("systems", []):
            self.graph.add_node(sys_name, sys_name, NodeType.SYSTEM)
        for ent in context.get("entities", []):
            name = ent.get("name") if isinstance(ent, dict) else ent
            self.graph.add_node(name, name, NodeType.ENTITY)

        # ── 2. Planning ──
        logger.info("coordinator", "Step 2: Planning")
        plan_result = self.planner.run(context)
        context.update(plan_result)

        # ── 3. Build ──
        logger.info("coordinator", "Step 3: Build")
        build_result = self.builder.run(context)
        context.update(build_result)

        # ── 4. QA ──
        logger.info("coordinator", "Step 4: QA")
        qa_result = self.qa.run(context)
        context.update(qa_result)

        # ── 5. Repair loop ──
        if qa_result.get("status") != "ok":
            for attempt in range(self.MAX_REPAIR_ATTEMPTS):
                logger.info("coordinator", f"Step 5: Repair attempt {attempt + 1}")
                context.update(self.repair.run(context))
                qa_result = self.qa.run(context)
                context.update(qa_result)
                if qa_result.get("status") == "ok":
                    break

        # ── 6. Post-flight governance ──
        self._run_postflight(context)

        # Determine final status
        context["status"] = (
            "ok" if qa_result.get("status") == "ok" and not context.get("governance_blocked", False) else "fail"
        )

        logger.info(
            "coordinator",
            f"Coordinator complete: status={context['status']}, "
            f"ops={len(context.get('operations', []))}, "
            f"files={len(context.get('files', []))}",
        )

        return context

    # ------------------------------------------------------------------
    # Governance hooks
    # ------------------------------------------------------------------
    def _run_preflight(self, context: Dict[str, Any]) -> None:
        """Pre-flight: scope lock + risk scoring check."""
        try:
            from devforge.governance.scope_lock import create_scope_lock
            from devforge.governance.risk_scoring import compute_risk

            # Create scope lock
            scope = create_scope_lock(
                description=context["prompt"],
                allowed_files=context.get("allowed_files", ["scripts/*.gd"]),
                subsystems=context.get("subsystems", ["game_logic"]),
                depth=context.get("depth", "new_behaviour"),
            )
            context["scope"] = scope

            # Risk scoring
            risk = compute_risk(
                subsystems=context.get("subsystems", ["game_logic"]),
                depth=context.get("depth", "new_behaviour"),
                files_modified=len(scope.allowed_files),
            )
            context["risk"] = risk

            if risk.halt_architectural_change:
                context["blocked"] = True
                context["block_reason"] = (
                    f"Halting: architectural change required for weight-5 subsystem. "
                    f"Risk score: {risk.final_score} ({risk.tier.value})"
                )
                logger.warn("coordinator", context["block_reason"])
        except ImportError:
            logger.info("coordinator", "Governance modules not available — skipping preflight")
        except Exception as exc:
            logger.error("coordinator", f"Preflight governance failed: {exc}")

    def _run_postflight(self, context: Dict[str, Any]) -> None:
        """Post-flight: run Gate 1 validation on generated files."""
        try:
            from devforge.governance.gate1 import run_gate1
            from devforge.governance.risk_scoring import compute_risk

            files = context.get("files", [])
            file_paths = [f.get("path", "") for f in files if f.get("path")]
            project_root = str(self._config.game_root) if self._config.game_root else "."

            if file_paths:
                gate1 = run_gate1(
                    project_root=project_root,
                    changed_files=file_paths,
                )
                context["gate1"] = gate1

                # Recompute risk with actual file count
                risk = compute_risk(
                    subsystems=context.get("subsystems", ["game_logic"]),
                    depth=context.get("depth", "new_behaviour"),
                    files_modified=len(file_paths),
                    crosses_sim_render=gate1.cross_boundary_detected,
                )
                context["risk"] = risk

                if not gate1.passed:
                    context["governance_blocked"] = True
                    context.setdefault("violations", []).extend([v.to_dict() for v in gate1.blocking_violations])
                    logger.warn(
                        "coordinator",
                        f"Gate 1 failed: {len(gate1.blocking_violations)} blocking violations",
                    )
        except ImportError:
            logger.info("coordinator", "Governance modules not available — skipping postflight")
        except Exception as exc:
            logger.error("coordinator", f"Postflight governance failed: {exc}")
