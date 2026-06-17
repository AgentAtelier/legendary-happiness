"""
DevForge Change Report Generator
=================================
Consumes Gate 1-3 outputs and risk scoring to produce a structured
change report with a mandatory explicit question.

The approve action is not available until the explicit question is answered.
Questions are generated based on risk tier — higher risk = harder questions.

Usage:
    from devforge.governance.change_report import generate_report
    report = generate_report(gate1_result, gate2_result, gate3_result, risk_result, changed_files)
"""

import datetime
import hashlib
import json
from dataclasses import dataclass, field
from typing import List, Optional

# --------------------------------------------------------------------------
# Question templates by risk tier
# --------------------------------------------------------------------------
TIER_QUESTIONS = {
    "low": [
        "Does this change stay within the existing subsystem interface?",
        "Are there any implicit coupling risks through shared data structures?",
        "Does this change maintain the current simulation/render boundary?",
    ],
    "medium": [
        "How does this change affect the determinism guarantee of the simulation?",
        "What happens to existing save files if this change is merged?",
        "Does this change introduce any new inter-layer dependencies?",
        "Could this change affect tick performance under load?",
    ],
    "high": [
        "What is the migration path if this change causes a regression?",
        "How would you verify this change doesn't break determinism across 1000 ticks?",
        "Does this change require an update to the architectural contracts?",
        "What subsystems could be indirectly affected by this interface change?",
        "If this change fails in production, what is the rollback procedure?",
    ],
    "critical": [
        "Why does this change require modifying a weight-5 subsystem, and what alternatives were considered?",
        "Provide the full before/after interface diagram for all affected subsystems.",
        "What is the complete blast radius if this change introduces a subtle determinism failure?",
        "Does this change require an Architectural Change Proposal? If not, explain why.",
        "How will you verify that this change has not introduced implicit coupling through shared data?",
    ],
}

# Cross-boundary addendum questions
CROSS_BOUNDARY_QUESTIONS = [
    "This change touches both sim/ and render/ layers. Explain why both need modification.",
    "How does the simulation/render boundary remain intact after this change?",
]

# Protected file addendum questions
PROTECTED_FILE_QUESTIONS = [
    "This change modifies a protected file. Where is the Architectural Change Proposal?",
    "What is the justification for modifying {file}? This is permanently human-controlled.",
]


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------
@dataclass
class ChangeReport:
    """Structured change report for human review."""

    run_id: str
    timestamp: str
    risk_score: int
    risk_tier: str

    # Gate results
    gate1_passed: Optional[bool] = None
    gate2_passed: Optional[bool] = None
    gate3_passed: Optional[bool] = None
    pipeline_passed: bool = False

    # Details
    files_modified: List[str] = field(default_factory=list)
    subsystems_touched: List[str] = field(default_factory=list)
    violations: List[dict] = field(default_factory=list)
    warnings: List[dict] = field(default_factory=list)
    protected_files_touched: List[str] = field(default_factory=list)
    cross_boundary: bool = False
    performance_delta_percent: Optional[float] = None

    # The mandatory question
    explicit_question: str = ""

    # Plan conformance
    unplanned_patterns: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "risk_score": self.risk_score,
            "risk_tier": self.risk_tier,
            "gate1_passed": self.gate1_passed,
            "gate2_passed": self.gate2_passed,
            "gate3_passed": self.gate3_passed,
            "pipeline_passed": self.pipeline_passed,
            "files_modified": self.files_modified,
            "subsystems_touched": self.subsystems_touched,
            "violation_count": len(self.violations),
            "violations": self.violations,
            "warnings": self.warnings,
            "protected_files_touched": self.protected_files_touched,
            "cross_boundary": self.cross_boundary,
            "performance_delta_percent": self.performance_delta_percent,
            "explicit_question": self.explicit_question,
            "unplanned_patterns": self.unplanned_patterns,
        }

    def to_text(self) -> str:
        """Human-readable report."""
        status = "PASSED" if self.pipeline_passed else "FAILED"
        lines = [
            "=" * 64,
            f"DEVFORGE CHANGE REPORT — {self.run_id}",
            "=" * 64,
            f"Timestamp: {self.timestamp}",
            f"Risk Score: {self.risk_score} ({self.risk_tier.upper()})",
            f"Pipeline: {status}",
            "",
            "— Gate Results —",
        ]

        for gate_name, gate_val in [
            ("Gate 1 (Structural)", self.gate1_passed),
            ("Gate 2 (Determinism)", self.gate2_passed),
            ("Gate 3 (Performance)", self.gate3_passed),
        ]:
            if gate_val is None:
                lines.append(f"  {gate_name}: NOT RUN")
            else:
                lines.append(f"  {gate_name}: {'PASS' if gate_val else 'FAIL'}")

        if self.performance_delta_percent is not None:
            sign = "+" if self.performance_delta_percent > 0 else ""
            lines.append(f"  Performance delta: {sign}{self.performance_delta_percent:.1f}%")

        lines.append("")
        lines.append("— Scope —")
        lines.append(f"  Files modified: {len(self.files_modified)}")
        for f in self.files_modified:
            lines.append(f"    {f}")
        lines.append(f"  Subsystems: {', '.join(self.subsystems_touched) if self.subsystems_touched else 'none'}")

        if self.cross_boundary:
            lines.append("  ⚠ CROSS-BOUNDARY: sim/ + render/ both modified")

        if self.protected_files_touched:
            lines.append(f"  ⚠ PROTECTED FILES: {self.protected_files_touched}")

        if self.violations:
            lines.append("")
            lines.append(f"— Violations ({len(self.violations)}) —")
            for v in self.violations:
                loc = f":{v.get('line_number', '')}" if v.get("line_number") else ""
                lines.append(f"  [{v['severity'].upper()}] {v['rule_id']} — {v['file_path']}{loc}")
                lines.append(f"    {v['description']}")

        if self.unplanned_patterns:
            lines.append("")
            lines.append("— Unplanned Patterns —")
            for p in self.unplanned_patterns:
                lines.append(f"  ⚠ {p}")

        lines.append("")
        lines.append("=" * 64)
        lines.append("MANDATORY QUESTION (must answer before approval):")
        lines.append("")
        lines.append(f"  {self.explicit_question}")
        lines.append("")
        lines.append("Your answer: _______________________________________________")
        lines.append("=" * 64)

        return "\n".join(lines)


# --------------------------------------------------------------------------
# Question generation
# --------------------------------------------------------------------------
def _generate_question(
    risk_tier: str,
    cross_boundary: bool,
    protected_files: List[str],
    violations: List[dict],
    performance_delta: Optional[float],
) -> str:
    """
    Generate the mandatory explicit question based on risk tier and context.
    Returns the most relevant question for the situation.
    """
    # If there are violations, ask about those first
    if violations:
        blocking = [v for v in violations if v.get("action") == "block_merge"]
        if blocking:
            v = blocking[0]
            return (
                f"Gate 1 found a blocking violation ({v['rule_id']}): {v['description']} "
                f"How will you resolve this before proceeding?"
            )

    # If protected files are touched
    if protected_files:
        return PROTECTED_FILE_QUESTIONS[0]

    # If cross-boundary
    if cross_boundary:
        return CROSS_BOUNDARY_QUESTIONS[0]

    # If performance regression
    if performance_delta is not None and performance_delta > 0:
        return (
            f"Performance increased by {performance_delta:.1f}%. "
            f"Which feature caused this and is the regression acceptable?"
        )

    # Default to tier-based question
    seed = hashlib.md5(datetime.datetime.now(datetime.timezone.utc).isoformat().encode()).hexdigest()
    questions = TIER_QUESTIONS.get(risk_tier, TIER_QUESTIONS["medium"])
    idx = int(seed[:8], 16) % len(questions)
    return questions[idx]


# --------------------------------------------------------------------------
# Main report generator
# --------------------------------------------------------------------------
def generate_report(
    run_id: str,
    changed_files: List[str],
    subsystems: List[str],
    risk_result: dict,
    gate1_result: Optional[dict] = None,
    gate2_result: Optional[dict] = None,
    gate3_result: Optional[dict] = None,
    scope_lock: Optional[dict] = None,
) -> ChangeReport:
    """
    Generate a structured change report from gate outputs and risk scoring.

    Args:
        run_id: DF-MMDD-NNNN format run identifier.
        changed_files: List of project-relative file paths.
        subsystems: List of subsystem names touched.
        risk_result: Output from risk_scoring.compute_risk().to_dict() or similar.
        gate1_result: Output from gate1.run_gate1().to_dict().
        gate2_result: Output from gate2.run_gate2().to_dict().
        gate3_result: Output from gate3.run_gate3().to_dict().
        scope_lock: Optional scope lock document for conformance check.
    """
    report = ChangeReport(
        run_id=run_id,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        risk_score=risk_result.get("final_score", 0),
        risk_tier=risk_result.get("tier", "medium"),
        files_modified=changed_files,
        subsystems_touched=subsystems,
    )

    # Gate 1
    if gate1_result:
        report.gate1_passed = gate1_result.get("passed")
        report.violations = gate1_result.get("violations", [])
        report.warnings = gate1_result.get("warnings", [])
        report.protected_files_touched = gate1_result.get("protected_files_touched", [])
        report.cross_boundary = gate1_result.get("cross_boundary_detected", False)

    # Gate 2
    if gate2_result:
        report.gate2_passed = gate2_result.get("passed")

    # Gate 3
    if gate3_result:
        report.gate3_passed = gate3_result.get("passed")
        report.performance_delta_percent = gate3_result.get("delta_percent")

    # Pipeline passes only if all run gates passed
    gate_results = [r for r in [report.gate1_passed, report.gate2_passed, report.gate3_passed] if r is not None]
    report.pipeline_passed = all(gate_results) if gate_results else False

    # Scope conformance check
    if scope_lock:
        locked_files = set(scope_lock.get("allowed_files", []))
        actual_files = set(changed_files)
        unexpected = actual_files - locked_files
        if unexpected:
            report.unplanned_patterns.extend([f"File outside scope lock: {f}" for f in sorted(unexpected)])

    # Generate mandatory question
    report.explicit_question = _generate_question(
        risk_tier=report.risk_tier,
        cross_boundary=report.cross_boundary,
        protected_files=report.protected_files_touched,
        violations=report.violations,
        performance_delta=report.performance_delta_percent,
    )

    return report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="DevForge Change Report Generator")
    parser.add_argument("--gate1", help="Path to Gate 1 result JSON.")
    parser.add_argument("--gate2", help="Path to Gate 2 result JSON.")
    parser.add_argument("--gate3", help="Path to Gate 3 result JSON.")
    parser.add_argument("--risk-json", help="Path to risk scoring result JSON.")
    parser.add_argument("--run-id", default="DF-0000-0000")
    parser.add_argument("--files", nargs="+", default=[])
    parser.add_argument("--subsystems", nargs="+", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", help="Write report to file instead of stdout.")

    args = parser.parse_args()

    def _load_json(path):
        if path and Path(path).exists():
            with open(path) as f:
                return json.load(f)
        return None

    report = generate_report(
        run_id=args.run_id,
        changed_files=args.files,
        subsystems=args.subsystems,
        risk_result=_load_json(args.risk_json) or {"final_score": 0, "tier": "low"},
        gate1_result=_load_json(args.gate1),
        gate2_result=_load_json(args.gate2),
        gate3_result=_load_json(args.gate3),
    )

    output = json.dumps(report.to_dict(), indent=2) if args.json else report.to_text()

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Report written to {args.output}")
    else:
        print(output)
