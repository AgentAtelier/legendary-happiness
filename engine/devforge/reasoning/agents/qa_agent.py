"""
QAAgent — validates generated code using CriticManager.

Phase 9: Wired to use the CriticManager for comprehensive validation
(deterministic rules + Gate 1 + risk scoring), not just a stub.

Usage:
    agent = QAAgent(project_root=".")
    result = agent.run(context)

The context must contain:
    - files: List of dicts with "path" and "content" keys
    - subsystems: (optional) List of subsystem names for risk scoring
"""

from __future__ import annotations

from devforge.reasoning.agents.agent import Agent
from devforge.validation.critic_manager import CriticManager


class QAAgent(Agent):
    """Validates generated code through the CriticManager pipeline."""

    def __init__(self, project_root: str = "."):
        super().__init__("qa")
        self._critic = CriticManager(project_root=project_root)

    def run(self, context: dict) -> dict:
        files = context.get("files", [])
        errors = context.get("errors", [])

        # If no files and no operations, fail
        operations = context.get("operations", [])
        if not files and not operations and not context.get("architecture_delta"):
            return {
                "status": "fail",
                "reason": "no files or operations generated",
            }

        # Collect file pairs for critic
        file_pairs = []
        for f in files:
            fp = f.get("path", "")
            fc = f.get("content", "")
            if fp and fc:
                file_pairs.append((fp, fc))

        if not file_pairs:
            # No files to validate — pass if no errors
            return {
                "status": "ok" if not errors else "fail",
                "violations": [],
                "critic_result": None,
            }

        # Run critic review
        critic_result = self._critic.review(
            files=file_pairs,
            subsystems=context.get("subsystems", ["game_logic"]),
            depth=context.get("depth", "new_behaviour"),
        )

        violations = [v.to_dict() for v in critic_result.blocking_violations]
        review_flags = [v.to_dict() for v in critic_result.review_flags]

        # Combine with pipeline errors
        all_errors = list(errors or [])
        for v in violations:
            all_errors.append(f"[{v['rule_id']}] {v['message']}")

        return {
            "status": "ok" if critic_result.passed and not errors else "fail",
            "violations": violations,
            "review_flags": review_flags,
            "critic_result": critic_result.to_dict(),
            "errors": all_errors,
        }
