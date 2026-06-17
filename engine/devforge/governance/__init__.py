"""
DevForge Governance — Architectural Validation Pipeline
=========================================================
Enforces constitutional boundaries defined in architectural_contracts.yaml.

Components:
    gate1.py            — Gate 1 (structural contract validation)
    analyzer.py         — GDScript static analyzer
    scope_lock.py       — Scope lock system for coder model boundaries
    risk_scoring.py     — Risk scoring calculator (formula-only)
    change_report.py    — Structured change report with mandatory question
    contracts/          — Contracts parser
    decision_log.py     — Append-only decision log (DF-MMDD-NNNN)
    metrics_append.py   — CSV metrics appender
    sidecar_validator.py— Asset sidecar validator (C-07)
    schemas/            — JSON schemas and architectural contracts YAML
"""

from devforge.governance.analyzer import GDFileAnalysis, analyze_directory, analyze_file
from devforge.governance.change_report import ChangeReport, generate_report
from devforge.governance.contracts.parser import ContractsParser
from devforge.governance.decision_log import append_entry, compute_stats, generate_run_id, list_entries
from devforge.governance.gate1 import Gate1Result, SignatureChange, Violation, run_gate1
from devforge.governance.metrics_append import append_row, print_summary, validate_row
from devforge.governance.risk_scoring import (
    SUBSYSTEM_WEIGHTS,
    Depth,
    RiskResult,
    RiskTier,
    compute_risk,
)
from devforge.governance.scope_lock import (
    ScopeLock,
    ScopeValidation,
    create_scope_lock,
    validate_against_lock,
)
from devforge.governance.sidecar_validator import (
    generate_template,
    scan_directory,
    validate_sidecar,
)

__all__ = [
    # Gate 1
    "run_gate1",
    "Gate1Result",
    "Violation",
    "SignatureChange",
    # Analyzer
    "analyze_file",
    "analyze_directory",
    "GDFileAnalysis",
    # Contracts
    "ContractsParser",
    # Scope Lock
    "ScopeLock",
    "ScopeValidation",
    "create_scope_lock",
    "validate_against_lock",
    # Risk Scoring
    "compute_risk",
    "RiskResult",
    "RiskTier",
    "Depth",
    "SUBSYSTEM_WEIGHTS",
    # Change Report
    "ChangeReport",
    "generate_report",
    # Decision Log
    "append_entry",
    "generate_run_id",
    "list_entries",
    "compute_stats",
    # Metrics
    "append_row",
    "validate_row",
    "print_summary",
    # Sidecar Validator
    "validate_sidecar",
    "scan_directory",
    "generate_template",
]
