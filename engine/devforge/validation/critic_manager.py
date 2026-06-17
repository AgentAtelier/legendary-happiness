"""
CriticManager — orchestrates all validation critics in a unified gate.

The CriticManager runs the full governance suite against generated code:
  1. Deterministic Validator (R1-R6) — syntax/style rules
  2. Gate 1 (structural contracts) — architectural boundary enforcement
  3. Risk Scoring — formula-based risk assessment

All critics run in collect-all mode (never stop at first error).
Results feed into the repair loop and change report.

Usage:
    from devforge.validation.critic_manager import CriticManager

    critic = CriticManager(project_root="/path/to/project")
    result = critic.review(files=[("scripts/player.gd", content)], subsystems=["player_survival"])

    if not result.passed:
        for v in result.blocking_violations:
            print(f"{v.rule_id}: {v.message}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from devforge.infrastructure.logger import logger
from devforge.validation.deterministic_validator import (
    DeterministicValidator,
)

# Governance modules — imported lazily to avoid circular deps
# when the governance modules aren't needed.
_HAS_GOVERNANCE = False
try:
    from devforge.governance.gate1 import run_gate1
    from devforge.governance.risk_scoring import compute_risk

    _HAS_GOVERNANCE = True
except ImportError:
    pass


# --------------------------------------------------------------------------
# Unified violation type
# --------------------------------------------------------------------------
@dataclass
class CriticViolation:
    """A violation from any critic (deterministic or governance)."""
    source: str  # "det_validator", "gate1", "risk"
    rule_id: str
    severity: str  # "critical", "high", "warning"
    file_path: Optional[str]
    line_number: Optional[int]
    message: str
    action: str  # "block_merge", "flag_for_review"

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "message": self.message,
            "action": self.action,
        }


@dataclass
class CriticResult:
    """Complete result of a critic review pass.

    Attributes:
        passed: True if no blocking violations.
        blocking_violations: CriticViolations that block the change.
        review_flags: Non-blocking issues for manual review.
        risk_result: Risk scoring result (None if not computed).
        files_checked: Number of files validated.
        cross_boundary: Whether change touches sim/ + render/ layers.
    """

    passed: bool = True
    blocking_violations: List[CriticViolation] = field(default_factory=list)
    review_flags: List[CriticViolation] = field(default_factory=list)
    risk_result: Optional[Any] = None  # RiskResult when governance available
    files_checked: int = 0
    cross_boundary: bool = False

    @property
    def violation_count(self) -> int:
        return len(self.blocking_violations)

    def to_dict(self) -> dict:
        base: Dict[str, Any] = {
            "passed": self.passed,
            "violation_count": self.violation_count,
            "review_flag_count": len(self.review_flags),
            "files_checked": self.files_checked,
            "cross_boundary": self.cross_boundary,
            "blocking_violations": [v.to_dict() for v in self.blocking_violations],
            "review_flags": [v.to_dict() for v in self.review_flags],
        }
        if self.risk_result is not None:
            base["risk_score"] = getattr(self.risk_result, "final_score", 0)
            base["risk_tier"] = getattr(
                getattr(self.risk_result, "tier", None), "value", "unknown"
            )
        return base

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"CriticManager Review: {status}",
            f"  Files checked: {self.files_checked}",
            f"  Blocking violations: {self.violation_count}",
            f"  Review flags: {len(self.review_flags)}",
        ]
        if self.risk_result is not None:
            score = getattr(self.risk_result, "final_score", "?")
            tier = getattr(getattr(self.risk_result, "tier", None), "value", "?")
            lines.append(f"  Risk score: {score} ({tier})")
        if self.cross_boundary:
            lines.append("  ⚠ Cross-boundary change detected (sim/ + render/)")
        if self.blocking_violations:
            lines.append("  Violations:")
            for v in self.blocking_violations:
                loc = f":{v.line_number}" if v.line_number else ""
                path = f" — {v.file_path}" if v.file_path else ""
                lines.append(
                    f"    [{v.severity.upper()}] [{v.source}] {v.rule_id}"
                    f"{path}{loc}: {v.message}"
                )
        return "\n".join(lines)


# --------------------------------------------------------------------------
# CriticManager
# --------------------------------------------------------------------------
class CriticManager:
    """Orchestrates all validation critics against generated code.

    Runs:
      1. DeterministicValidator (R1-R6) — per-file syntax/style
      2. Gate 1 (structural contracts) — architectural boundaries
      3. Risk scoring — formula-based risk assessment

    All critics run regardless of prior failures (collect-all strategy).
    """

    def __init__(
        self,
        project_root: str = ".",
        contracts_path: Optional[str] = None,
    ):
        """Args:
            project_root: Root of the project for Gate 1 path resolution.
            contracts_path: Override path to architectural_contracts.yaml.
        """
        self._project_root = project_root
        self._contracts_path = contracts_path
        self._det_validator = DeterministicValidator()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def review(
        self,
        files: List[Tuple[str, str]],
        subsystems: Optional[List[str]] = None,
        depth: str = "new_behaviour",
        scope_lock: Optional[Any] = None,
    ) -> CriticResult:
        """Run all critics against a set of generated files.

        Args:
            files: List of (file_path, file_content) tuples.
            subsystems: Subsystems touched (for risk scoring).
            depth: Modification depth for risk scoring.
            scope_lock: Optional ScopeLock for conformance check.

        Returns:
            CriticResult with pass/fail and all violations.
        """
        result = CriticResult(files_checked=len(files))
        file_paths = [fp for fp, _ in files]

        # ── 1. Deterministic Validator (R1-R6) ──
        logger.info("critic", f"Running deterministic validator on {len(files)} files")
        for fp, content in files:
            vr = self._det_validator.validate_patch(fp, content)
            for v in vr.blocking_violations:
                result.blocking_violations.append(
                    CriticViolation(
                        source="det_validator",
                        rule_id=v.rule_id,
                        severity=v.severity,
                        file_path=fp,
                        line_number=v.line_number,
                        message=v.message,
                        action=v.action,
                    )
                )
            for v in vr.review_flags:
                result.review_flags.append(
                    CriticViolation(
                        source="det_validator",
                        rule_id=v.rule_id,
                        severity=v.severity,
                        file_path=fp,
                        line_number=v.line_number,
                        message=v.message,
                        action=v.action,
                    )
                )

        # ── 2. Gate 1 (structural contracts) ──
        if _HAS_GOVERNANCE:
            logger.info("critic", f"Running Gate 1 on {len(file_paths)} files")
            try:
                gate1 = run_gate1(
                    project_root=self._project_root,
                    changed_files=file_paths,
                    contracts_path=self._contracts_path,
                )
                for v in gate1.violations:
                    result.blocking_violations.append(
                        CriticViolation(
                            source="gate1",
                            rule_id=v.rule_id,
                            severity=v.severity,
                            file_path=v.file_path,
                            line_number=v.line_number,
                            message=v.description,
                            action=v.action,
                        )
                    )
                for v in gate1.warnings:
                    result.review_flags.append(
                        CriticViolation(
                            source="gate1",
                            rule_id=v.rule_id,
                            severity=v.severity,
                            file_path=v.file_path,
                            line_number=v.line_number,
                            message=v.description,
                            action=v.action,
                        )
                    )
                result.cross_boundary = gate1.cross_boundary_detected
            except Exception as exc:
                logger.error("critic", f"Gate 1 failed: {exc}")
        else:
            logger.info("critic", "Governance modules not available — skipping Gate 1")

        # ── 3. Risk Scoring ──
        if _HAS_GOVERNANCE and subsystems:
            logger.info("critic", "Computing risk score")
            try:
                risk = compute_risk(
                    subsystems=subsystems,
                    depth=depth,
                    files_modified=len(files),
                    crosses_sim_render=result.cross_boundary,
                )
                result.risk_result = risk
                if risk.halt_architectural_change:
                    result.blocking_violations.append(
                        CriticViolation(
                            source="risk",
                            rule_id="HALT_ARCHITECTURAL_CHANGE",
                            severity="critical",
                            file_path=None,
                            line_number=None,
                            message=(
                                f"Change touches a weight-5 subsystem with risk score "
                                f"{risk.final_score} ({risk.tier.value}). "
                                f"Architectural Change Proposal required."
                            ),
                            action="block_merge",
                        )
                    )
            except Exception as exc:
                logger.error("critic", f"Risk scoring failed: {exc}")

        # ── Determine pass/fail ──
        result.passed = len(result.blocking_violations) == 0

        status = "PASSED" if result.passed else "FAILED"
        logger.info(
            "critic",
            f"CriticManager review {status}: {result.violation_count} blocking, "
            f"{len(result.review_flags)} flags",
        )

        return result
