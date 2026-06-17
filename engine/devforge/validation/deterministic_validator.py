"""Deterministic Validator — orchestrates Tier 1 regex-based rules.

Runs BEFORE any LLM review to save inference time.  All rules are
pure Python (regex, string analysis) and stateless.

Entry point::

    validator = DeterministicValidator()
    result = validator.validate_patch("scripts/player.gd", content)

    if not result.passed:
        for v in result.blocking_violations:
            print(f"{v.rule_id}: {v.message}")

Borrows from WorldForge Gate1:
  - severity field on Violations
  - review_flags list (non-blocking semantic issues)
  - unparsed_constructs flag
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from devforge.infrastructure.logger import logger
from devforge.validation.rules import ALL_RULES
from devforge.validation.rules.base import Rule, Violation


@dataclass
class ValidationResult:
    """Complete result of a deterministic validation run.

    Attributes:
        passed: True if no blocking violations.
        blocking_violations: Violations that block the change.
        warnings: Non-blocking issues (review_flags).
        review_flags: Semantic issues for manual review.
        unparsed_constructs: Number of constructs the analyzer couldn't parse.
    """

    passed: bool = True
    blocking_violations: List[Violation] = field(default_factory=list)
    warnings: List[Violation] = field(default_factory=list)
    review_flags: List[Violation] = field(default_factory=list)
    unparsed_constructs: int = 0

    @property
    def violation_count(self) -> int:
        return len(self.blocking_violations)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violation_count": self.violation_count,
            "warning_count": len(self.warnings),
            "review_flag_count": len(self.review_flags),
            "unparsed_constructs": self.unparsed_constructs,
            "blocking_violations": [v.to_dict() for v in self.blocking_violations],
            "warnings": [v.to_dict() for v in self.warnings],
            "review_flags": [v.to_dict() for v in self.review_flags],
        }

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"Deterministic Validator: {status}",
            f"  Blocking violations: {self.violation_count}",
            f"  Warnings: {len(self.warnings)}",
            f"  Review flags: {len(self.review_flags)}",
        ]
        if self.unparsed_constructs > 0:
            lines.append(f"  ⚠ Unparsed constructs: {self.unparsed_constructs}")
        if self.blocking_violations:
            lines.append("  Violations:")
            for v in self.blocking_violations:
                loc = f":{v.line_number}" if v.line_number else ""
                lines.append(f"    [{v.severity.upper()}] {v.rule_id} — {v.message}{loc}")
        return "\n".join(lines)


class DeterministicValidator:
    """Runs all Tier 1 rules sequentially against a GDScript patch.

    Collects all violations rather than stopping at the first error.
    Never writes to disk — operates purely on the input string.
    """

    def __init__(self, rules: List[type[Rule]] | None = None):
        """
        Args:
            rules: Custom rule list. Defaults to ALL_RULES from the registry.
        """
        self._rules: List[Rule] = [rule_cls() for rule_cls in (rules or ALL_RULES)]

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def validate_patch(self, file_path: str, patched_content: str) -> ValidationResult:
        """Validate a GDScript patch against all Tier 1 rules.

        Args:
            file_path: Relative path to the file being modified.
            patched_content: Full proposed content of the file (in-memory).

        Returns:
            ValidationResult with pass/fail and structured violations.
        """
        result = ValidationResult()

        for rule in self._rules:
            try:
                violations = rule.check(file_path, patched_content)
            except Exception as exc:
                logger.error(
                    "validator",
                    f"Rule {rule.__class__.__name__} crashed: {exc}",
                )
                result.blocking_violations.append(
                    Violation(
                        rule_id="VALIDATOR_ERROR",
                        message=f"Internal error in {rule.__class__.__name__}: {exc}",
                        severity="critical",
                        action="block_merge",
                    )
                )
                continue

            for v in violations:
                if v.action == "block_merge":
                    result.blocking_violations.append(v)
                elif v.action == "flag_for_review":
                    result.review_flags.append(v)
                else:
                    result.warnings.append(v)

        # Determine pass/fail
        result.passed = len(result.blocking_violations) == 0

        if not result.passed:
            logger.info(
                "validator",
                f"Validation FAILED: {result.violation_count} blocking violations",
            )
        else:
            logger.info("validator", "Validation PASSED")

        return result

    # ------------------------------------------------------------------
    # Bulk validation
    # ------------------------------------------------------------------

    def validate_files(self, patches: List[tuple[str, str]]) -> List[ValidationResult]:
        """Validate multiple patches, returning per-file results.

        Args:
            patches: List of (file_path, patched_content) tuples.

        Returns:
            List of ValidationResult, one per patch.
        """
        return [self.validate_patch(fp, content) for fp, content in patches]

    @property
    def rule_count(self) -> int:
        return len(self._rules)
