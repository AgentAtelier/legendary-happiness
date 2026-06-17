"""
DevForge Gate 1 — Structural Contract Validator
=================================================
Enforces architectural boundaries from architectural_contracts.yaml.

Ported from WorldForge with import prefix updates.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from devforge.governance.analyzer import GDFileAnalysis, analyze_directory, analyze_file
from devforge.governance.contracts import ContractsParser
from devforge.infrastructure.logger import logger

# Exit code for CI integration
EXIT_CODE_GATE1_FAIL = 10


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------
@dataclass
class Violation:
    """A single contract violation."""

    rule_id: str
    severity: str  # "critical", "high", "warning"
    file_path: str
    line_number: Optional[int]
    description: str
    action: str  # "block_merge", "flag_for_review"

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "description": self.description,
            "action": self.action,
        }


@dataclass
class SignatureChange:
    """Detected change in a public method signature."""

    file_path: str
    function_name: str
    change_type: str  # "return_type_changed", "params_changed", "removed", "added"
    before: Optional[str]
    after: Optional[str]
    line_number: Optional[int]


@dataclass
class Gate1Result:
    """Complete Gate 1 validation result."""

    passed: bool
    violations: List[Violation] = field(default_factory=list)
    warnings: List[Violation] = field(default_factory=list)
    protected_files_touched: List[str] = field(default_factory=list)
    signature_changes: List[SignatureChange] = field(default_factory=list)
    unparsed_constructs: int = 0
    files_analyzed: int = 0
    cross_boundary_detected: bool = False
    exception_count: int = 0
    exception_ceiling: int = 5

    @property
    def blocking_violations(self) -> List[Violation]:
        return [v for v in self.violations if v.action == "block_merge"]

    @property
    def review_flags(self) -> List[Violation]:
        return [v for v in self.violations if v.action == "flag_for_review"]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "files_analyzed": self.files_analyzed,
            "violation_count": len(self.violations),
            "blocking_count": len(self.blocking_violations),
            "review_flag_count": len(self.review_flags),
            "warning_count": len(self.warnings),
            "unparsed_constructs": self.unparsed_constructs,
            "protected_files_touched": self.protected_files_touched,
            "cross_boundary_detected": self.cross_boundary_detected,
            "exception_count": self.exception_count,
            "exception_ceiling": self.exception_ceiling,
            "signature_changes": [
                {
                    "file": s.file_path,
                    "function": s.function_name,
                    "change": s.change_type,
                    "before": s.before,
                    "after": s.after,
                }
                for s in self.signature_changes
            ],
            "violations": [v.to_dict() for v in self.violations],
            "warnings": [v.to_dict() for v in self.warnings],
        }

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"Gate 1 — Structural Contract Validation: {status}",
            f"  Files analyzed: {self.files_analyzed}",
            f"  Blocking violations: {len(self.blocking_violations)}",
            f"  Review flags: {len(self.review_flags)}",
            f"  Warnings: {len(self.warnings)}",
        ]
        if self.unparsed_constructs > 0:
            lines.append(f"  ⚠ Unparsed constructs: {self.unparsed_constructs} (manual review recommended)")
        if self.protected_files_touched:
            lines.append(f"  ⚠ Protected files in diff: {self.protected_files_touched}")
        if self.cross_boundary_detected:
            lines.append("  ⚠ Cross-boundary change detected (sim/ + render/)")
        if self.signature_changes:
            lines.append(f"  ⚠ Public interface changes: {len(self.signature_changes)}")
            for sc in self.signature_changes:
                lines.append(f"    {sc.file_path}::{sc.function_name} — {sc.change_type}")
                if sc.before:
                    lines.append(f"      before: {sc.before}")
                if sc.after:
                    lines.append(f"      after:  {sc.after}")
        if self.violations:
            lines.append("  Violations:")
            for v in self.violations:
                loc = f":{v.line_number}" if v.line_number else ""
                lines.append(f"    [{v.severity.upper()}] {v.rule_id} — {v.file_path}{loc}")
                lines.append(f"      {v.description}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Path resolution
# --------------------------------------------------------------------------
def _resolve_import_path(import_path: str) -> str:
    """res://sim/core/sim_clock.gd → sim/core/sim_clock.gd"""
    if import_path.startswith("res://"):
        return import_path[6:]
    return import_path


def _get_file_layer(file_path: str, contracts: ContractsParser) -> Optional[str]:
    """Determine which architectural layer a file belongs to."""
    rel = _resolve_import_path(file_path)
    for layer_name, layer_def in contracts.get_layers().items():
        for layer_path in layer_def.get("paths", []):
            if rel.startswith(layer_path):
                return layer_name
    return None


# --------------------------------------------------------------------------
# Validation checks
# --------------------------------------------------------------------------
def _check_boundary_rules(
    analysis: GDFileAnalysis,
    contracts: ContractsParser,
) -> List[Violation]:
    """Check boundary rules (BR-01 through BR-05)."""
    violations = []
    file_layer = _get_file_layer(analysis.file_path, contracts)

    if file_layer is None:
        return violations

    for rule in contracts.get_boundary_rules():
        if rule["source_layer"] != file_layer:
            continue

        # Check forbidden_imports (layer-level)
        for imp in analysis.imports:
            imp_rel = _resolve_import_path(imp.path)
            imp_layer = _get_file_layer(imp_rel, contracts)

            if imp_layer in rule.get("forbidden_imports", []):
                violations.append(
                    Violation(
                        rule_id=rule["id"],
                        severity=rule.get("severity", "critical"),
                        file_path=analysis.file_path,
                        line_number=imp.line_number,
                        description=(
                            f"Layer '{file_layer}' imports from forbidden layer '{imp_layer}': "
                            f'{imp.kind}("{imp.path}") — {rule["description"]}'
                        ),
                        action=rule.get("action", "block_merge"),
                    )
                )

        # Check forbidden_patterns (path substring)
        for imp in analysis.imports:
            imp_rel = _resolve_import_path(imp.path)
            for pattern in rule.get("forbidden_patterns", []):
                if pattern in imp_rel:
                    violations.append(
                        Violation(
                            rule_id=rule["id"],
                            severity=rule.get("severity", "critical"),
                            file_path=analysis.file_path,
                            line_number=imp.line_number,
                            description=(
                                f"Import matches forbidden pattern '{pattern}': "
                                f'{imp.kind}("{imp.path}") — {rule["description"]}'
                            ),
                            action=rule.get("action", "block_merge"),
                        )
                    )

    return violations


def _check_return_types(
    analysis: GDFileAnalysis,
    contracts: ContractsParser,
) -> List[Violation]:
    """Check return type restrictions (RT-01, RT-02)."""
    violations = []
    file_layer = _get_file_layer(analysis.file_path, contracts)
    if file_layer is None:
        return violations

    for rule in contracts.get_return_type_rules():
        if rule["scope"] != file_layer:
            continue

        forbidden = set(rule.get("forbidden_return_types", []))
        for func in analysis.public_functions:
            if func.return_type and func.return_type in forbidden:
                violations.append(
                    Violation(
                        rule_id=rule["id"],
                        severity="critical",
                        file_path=analysis.file_path,
                        line_number=func.line_number,
                        description=(
                            f"Public method '{func.name}()' returns forbidden type "
                            f"'{func.return_type}' — {rule['description']}"
                        ),
                        action="block_merge",
                    )
                )

    return violations


def _check_protected_files(
    changed_files: List[str],
    contracts: ContractsParser,
) -> Tuple[List[str], List[Violation]]:
    """Detect protected file modifications."""
    protected = set(contracts.get_protected_files())
    touched = []
    violations = []

    for f in changed_files:
        rel = _resolve_import_path(f)
        if rel in protected:
            touched.append(rel)
            violations.append(
                Violation(
                    rule_id="PROTECTED",
                    severity="critical",
                    file_path=rel,
                    line_number=None,
                    description=(
                        f"Protected file '{rel}' in diff. "
                        f"Requires Architectural Change Proposal. "
                        f"Must never appear in coder-model scope lock."
                    ),
                    action="block_merge",
                )
            )

    return touched, violations


def _check_cross_boundary(
    changed_files: List[str],
    contracts: ContractsParser,
) -> bool:
    """Detect sim/ + render/ cross-boundary changes."""
    layers = set()
    for f in changed_files:
        layer = _get_file_layer(f, contracts)
        if layer:
            layers.add(layer)
    return "simulation" in layers and "render" in layers


def _check_unparsed_constructs(
    analysis: GDFileAnalysis,
) -> List[Violation]:
    """Flag analyzer parse warnings as review items."""
    warnings = []
    for pw in analysis.warnings:
        warnings.append(
            Violation(
                rule_id="PARSE_WARNING",
                severity="warning",
                file_path=analysis.file_path,
                line_number=pw.line_number,
                description=f"[{pw.category}] {pw.message}",
                action="flag_for_review",
            )
        )
    return warnings


# --------------------------------------------------------------------------
# Signature comparison
# --------------------------------------------------------------------------
def compare_signatures(
    before: GDFileAnalysis,
    after: GDFileAnalysis,
) -> List[SignatureChange]:
    """
    Compare public function signatures between two versions of a file.
    Detects return type changes, parameter changes, additions, and removals.
    """
    changes = []

    before_funcs = {f.name: f for f in before.public_functions}
    after_funcs = {f.name: f for f in after.public_functions}

    # Removed functions
    for name in before_funcs:
        if name not in after_funcs:
            f = before_funcs[name]
            changes.append(
                SignatureChange(
                    file_path=after.file_path,
                    function_name=name,
                    change_type="removed",
                    before=f"-> {f.return_type}" if f.return_type else "(no return type)",
                    after=None,
                    line_number=f.line_number,
                )
            )

    # Added functions
    for name in after_funcs:
        if name not in before_funcs:
            f = after_funcs[name]
            changes.append(
                SignatureChange(
                    file_path=after.file_path,
                    function_name=name,
                    change_type="added",
                    before=None,
                    after=f"-> {f.return_type}" if f.return_type else "(no return type)",
                    line_number=f.line_number,
                )
            )

    # Changed signatures
    for name in before_funcs:
        if name not in after_funcs:
            continue
        bf = before_funcs[name]
        af = after_funcs[name]

        if bf.return_type != af.return_type:
            changes.append(
                SignatureChange(
                    file_path=after.file_path,
                    function_name=name,
                    change_type="return_type_changed",
                    before=f"-> {bf.return_type}" if bf.return_type else "(none)",
                    after=f"-> {af.return_type}" if af.return_type else "(none)",
                    line_number=af.line_number,
                )
            )

        if bf.param_types != af.param_types:
            changes.append(
                SignatureChange(
                    file_path=after.file_path,
                    function_name=name,
                    change_type="params_changed",
                    before=str(bf.param_types),
                    after=str(af.param_types),
                    line_number=af.line_number,
                )
            )

    return changes


# --------------------------------------------------------------------------
# Main Gate 1 runner
# --------------------------------------------------------------------------
def run_gate1(
    project_root: str,
    changed_files: Optional[List[str]] = None,
    contracts_path: Optional[str] = None,
    scan_all: bool = False,
    baseline_analyses: Optional[Dict[str, GDFileAnalysis]] = None,
) -> Gate1Result:
    """
    Run Gate 1 structural contract validation.

    Args:
        project_root: Path to the project root.
        changed_files: Project-relative paths of changed files.
        contracts_path: Override path to architectural_contracts.yaml.
        scan_all: If True, analyze all .gd files.
        baseline_analyses: Previous file analyses for signature comparison.
                          Keys are project-relative file paths.
    """
    root = Path(project_root)

    # Load contracts
    if contracts_path:
        cp = ContractsParser(contracts_path)
    else:
        default = root / "contracts" / "architectural_contracts.yaml"
        cp = ContractsParser(str(default))

    result = Gate1Result(
        passed=True,
        exception_count=cp.get_exception_count(),
        exception_ceiling=cp.get_exception_ceiling(),
    )

    # Determine files to analyze
    if scan_all:
        analyses = analyze_directory(str(root))
        changed_files = [a.file_path for a in analyses]
    elif changed_files:
        analyses = []
        for f in changed_files:
            full = str(root / f) if not Path(f).is_absolute() else f
            if Path(full).exists() and full.endswith(".gd"):
                analyses.append(analyze_file(full))
    else:
        return result

    result.files_analyzed = len(analyses)
    logger.info("gate1", f"Analyzing {result.files_analyzed} files")

    # Normalize to project-relative paths
    rel_changed = []
    for f in changed_files or []:
        if Path(f).is_absolute():
            try:
                rel_changed.append(str(Path(f).relative_to(root)))
            except ValueError:
                rel_changed.append(f)
        else:
            rel_changed.append(f)

    # Protected files
    touched, pf_violations = _check_protected_files(rel_changed, cp)
    result.protected_files_touched = touched
    result.violations.extend(pf_violations)
    if touched:
        logger.warn("gate1", f"Protected files in diff: {touched}")

    # Cross-boundary
    result.cross_boundary_detected = _check_cross_boundary(rel_changed, cp)
    if result.cross_boundary_detected:
        logger.warn("gate1", "Cross-boundary change detected")

    # Analyze each file
    for analysis in analyses:
        # Normalize path
        try:
            rel_path = str(Path(analysis.file_path).relative_to(root))
        except ValueError:
            rel_path = analysis.file_path
        analysis.file_path = rel_path

        # Boundary rules
        result.violations.extend(_check_boundary_rules(analysis, cp))

        # Return types
        result.violations.extend(_check_return_types(analysis, cp))

        # Unparsed constructs
        unparsed = _check_unparsed_constructs(analysis)
        result.warnings.extend(unparsed)
        result.unparsed_constructs += len(analysis.warnings)

        # Signature comparison (if baseline available)
        if baseline_analyses and rel_path in baseline_analyses:
            sig_changes = compare_signatures(baseline_analyses[rel_path], analysis)
            result.signature_changes.extend(sig_changes)
            if sig_changes:
                logger.info("gate1", f"Signature changes in {rel_path}: {len(sig_changes)}")

    # Exception ceiling
    if cp.is_ceiling_exceeded():
        result.violations.append(
            Violation(
                rule_id="C-12",
                severity="critical",
                file_path="contracts/architectural_contracts.yaml",
                line_number=None,
                description=(
                    f"Exception ceiling exceeded: {cp.get_exception_count()} > "
                    f"{cp.get_exception_ceiling()}. Full contract rewrite required (C-12)."
                ),
                action="block_merge",
            )
        )

    # Final pass/fail
    result.passed = len(result.blocking_violations) == 0

    status = "PASSED" if result.passed else "FAILED"
    logger.info(
        "gate1",
        f"Gate 1 {status}: {len(result.violations)} violations, "
        f"{len(result.warnings)} warnings, {result.unparsed_constructs} unparsed",
    )

    return result
