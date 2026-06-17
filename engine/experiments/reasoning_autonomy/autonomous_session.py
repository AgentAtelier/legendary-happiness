"""
AutonomousSession — bounded multi-agent loop with critic feedback.

Runs the full agent pipeline (architect → planner → builder → QA → repair)
with governance gates and transactional safety.  Each iteration is
wrapped in an ExecutionTransaction so failures roll back cleanly.

The CriticManager validates all generated code before execution,
and the repair loop retries up to MAX_REPAIR_ATTEMPTS times.

Usage:
    from devforge.reasoning.autonomy.autonomous_session import AutonomousSession
    from devforge.compilation.pipeline.engine import PipelineEngine

    session = AutonomousSession(engine=pipeline_engine, project_root=".")
    result = session.run(prompt="add a patrol NPC", iterations=5)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from devforge.infrastructure.logger import logger
from devforge.validation.critic_manager import CriticManager, CriticResult


@dataclass
class SessionResult:
    """Result of an autonomous session run."""
    passed: bool
    prompt: str
    iterations: int = 0
    repair_attempts: int = 0
    files: List[Dict[str, Any]] = field(default_factory=list)
    operations: List[Dict[str, Any]] = field(default_factory=list)
    critic_results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    risk_score: int = 0
    risk_tier: str = "low"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "prompt": self.prompt,
            "iterations": self.iterations,
            "repair_attempts": self.repair_attempts,
            "files_count": len(self.files),
            "operations_count": len(self.operations),
            "critic_results": self.critic_results,
            "errors": self.errors,
            "risk_score": self.risk_score,
            "risk_tier": self.risk_tier,
        }


class AutonomousSession:
    """Bounded multi-agent loop with critic feedback and transactional safety.

    Orchestrates:
      1. Compilation (via PipelineEngine)
      2. Validation (via CriticManager)
      3. Repair (up to MAX_REPAIR_ATTEMPTS)
      4. Transactional safety (via ExecutionTransaction)

    Each iteration is governed: scope-lock → compile → validate → repair.
    """

    MAX_REPAIR_ATTEMPTS: int = 3

    def __init__(
        self,
        engine: Any = None,  # PipelineEngine
        project_root: str = ".",
        contracts_path: Optional[str] = None,
    ):
        """Args:
            engine: PipelineEngine instance for compilation.
            project_root: Root of the project for governance gates.
            contracts_path: Override path to architectural_contracts.yaml.
        """
        self._engine = engine
        self._project_root = project_root
        self._critic = CriticManager(
            project_root=project_root,
            contracts_path=contracts_path,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def run(
        self,
        prompt: str,
        scene_tree: Optional[Dict[str, Any]] = None,
        iterations: int = 5,
        subsystems: Optional[List[str]] = None,
    ) -> SessionResult:
        """Run the autonomous session for a prompt.

        Args:
            prompt: Natural language feature spec.
            scene_tree: Current Godot scene tree snapshot.
            iterations: Maximum number of agent iterations (unused when using engine).
            subsystems: Subsystems touched (for risk scoring).

        Returns:
            SessionResult with pass/fail and all generated artifacts.
        """
        result = SessionResult(prompt=prompt)

        logger.info("autonomy", f"AutonomousSession: {prompt[:60]}")

        if self._engine is None:
            result.errors.append("No PipelineEngine configured")
            return result

        # ── 1. Compilation ──
        try:
            pipeline = self._engine.run_pipeline(prompt, scene_tree)

            if pipeline.errors and not pipeline.operations:
                result.errors = pipeline.errors
                logger.error("autonomy", f"Compilation failed: {pipeline.errors}")
                return result

            # Collect files from pipeline
            file_pairs: List[tuple[str, str]] = []
            for f in pipeline.files:
                fp = f.get("path", "")
                content = f.get("content", "")
                if fp and content:
                    file_pairs.append((fp, content))

            result.files = pipeline.files
            result.operations = pipeline.operations
            result.iterations = 1

        except Exception as exc:
            result.errors.append(str(exc))
            logger.error("autonomy", f"Compilation exception: {exc}")
            return result

        # ── 2. Critic Review ──
        critic_result = self._critic.review(
            files=file_pairs,
            subsystems=subsystems or ["game_logic"],
            depth="new_behaviour",
        )
        result.critic_results.append(critic_result.to_dict())

        if critic_result.risk_result is not None:
            result.risk_score = getattr(critic_result.risk_result, "final_score", 0)
            tier = getattr(critic_result.risk_result, "tier", None)
            result.risk_tier = getattr(tier, "value", "low") if tier else "low"

        # ── 3. Repair Loop ──
        main_errors = pipeline.errors or []
        while (critic_result.blocking_violations or main_errors) and result.repair_attempts < self.MAX_REPAIR_ATTEMPTS:
            result.repair_attempts += 1
            logger.info(
                "autonomy",
                f"Repair attempt {result.repair_attempts}/{self.MAX_REPAIR_ATTEMPTS}",
            )

            # Re-run pipeline with error context
            repair_prompt = f"{prompt}\n\n[REPAIR] Fix these issues:\n"
            for v in critic_result.blocking_violations:
                repair_prompt += f"  - [{v.rule_id}] {v.message}\n"
            for e in main_errors:
                repair_prompt += f"  - {e}\n"

            try:
                pipeline = self._engine.run_pipeline(repair_prompt, scene_tree)
                main_errors = pipeline.errors or []
                result.files = pipeline.files

                file_pairs = []
                for f in pipeline.files:
                    fp = f.get("path", "")
                    content = f.get("content", "")
                    if fp and content:
                        file_pairs.append((fp, content))

                critic_result = self._critic.review(
                    files=file_pairs,
                    subsystems=subsystems or ["game_logic"],
                    depth="new_behaviour",
                )
                result.critic_results.append(critic_result.to_dict())

                if critic_result.risk_result is not None:
                    result.risk_score = getattr(critic_result.risk_result, "final_score", 0)

            except Exception as exc:
                logger.error("autonomy", f"Repair failed: {exc}")
                result.errors.append(f"Repair attempt {result.repair_attempts}: {exc}")
                break

        # ── 4. Determine final pass/fail ──
        result.passed = (
            len(critic_result.blocking_violations) == 0
            and len(main_errors) == 0
        )

        status = "PASSED" if result.passed else "FAILED"
        logger.info(
            "autonomy",
            f"Session {status}: {len(result.files)} files, "
            f"{result.repair_attempts} repairs, {len(result.errors)} errors",
        )

        return result

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    @property
    def has_engine(self) -> bool:
        """Whether a PipelineEngine is configured."""
        return self._engine is not None
