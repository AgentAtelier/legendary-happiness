"""
DevForge Metrics CSV Appender
==============================
Appends one row to metrics.csv after every validation pipeline run.
No dashboards — spreadsheet is sufficient.

Usage:
    python -m devforge.governance.metrics_append --json row.json
    python -m devforge.governance.metrics_append --json row.json --file metrics.csv
    python -m devforge.governance.metrics_append --summary --file metrics.csv
"""

import csv
import json
import argparse
import re
from pathlib import Path
from typing import Any, Dict, List

RUN_PATTERN = re.compile(r"^DF-[0-9]{4}-[0-9]{4}$")

HEADER = [
    "run_id",
    "timestamp",
    "tick_budget_ms",
    "tick_baseline_ms",
    "tick_delta_ms",
    "boundary_violations_caught",
    "boundary_violations_30d",
    "repair_loop_depth",
    "max_repair_attempts",
    "plan_conformance_flagged",
    "scope_files_estimated",
    "scope_files_actual",
    "scope_accuracy_pct",
    "decision_log_word_count",
    "risk_score",
    "risk_tier",
    "gate1_pass",
    "gate2_pass",
    "gate3_pass",
]

REQUIRED_FIELDS = set(HEADER)

NUMERIC_FIELDS = {
    "tick_budget_ms",
    "tick_baseline_ms",
    "tick_delta_ms",
    "boundary_violations_caught",
    "boundary_violations_30d",
    "repair_loop_depth",
    "max_repair_attempts",
    "plan_conformance_flagged",
    "scope_files_estimated",
    "scope_files_actual",
    "scope_accuracy_pct",
    "decision_log_word_count",
    "risk_score",
}

GATE_FIELDS = {"gate1_pass", "gate2_pass", "gate3_pass"}
VALID_GATE_VALUES = {"0", "1", "null", ""}
VALID_TIERS = {"low", "medium", "high", "critical"}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def validate_row(row: Dict[str, Any]) -> List[str]:
    """
    Validate a row dict. Returns list of error messages (empty = valid).
    """
    errors = []

    # Check all required fields present
    missing = REQUIRED_FIELDS - set(row.keys())
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")

    # Validate run_id format
    run_id = str(row.get("run_id", ""))
    if not RUN_PATTERN.match(run_id):
        errors.append(f"Invalid run_id format: '{run_id}'. Expected DF-MMDD-NNNN.")

    # Validate numeric fields
    for field in NUMERIC_FIELDS:
        val = row.get(field)
        if val is None or str(val).strip() == "":
            continue  # Allow empty for optional context
        try:
            float(val)
        except (ValueError, TypeError):
            errors.append(f"Non-numeric value in {field}: '{val}'")

    # Validate gate pass fields (1, 0, or null)
    for field in GATE_FIELDS:
        val = str(row.get(field, "")).strip().lower()
        if val not in VALID_GATE_VALUES:
            errors.append(f"Invalid gate value in {field}: '{val}'. Expected 1, 0, or null.")

    # Validate risk_tier
    tier = str(row.get("risk_tier", "")).strip().lower()
    if tier and tier not in VALID_TIERS:
        errors.append(f"Invalid risk_tier: '{tier}'. Expected: {sorted(VALID_TIERS)}")

    return errors


# --------------------------------------------------------------------------
# Core operations
# --------------------------------------------------------------------------
def append_row(row: Dict[str, Any], path: str = "metrics.csv") -> None:
    """
    Validate and append a row to metrics CSV.
    Creates file with header if it doesn't exist.
    Raises ValueError on validation failure.
    """
    errors = validate_row(row)
    if errors:
        raise ValueError("Row validation failed:\n  " + "\n  ".join(errors))

    # Normalize all values to strings for CSV
    str_row = {k: str(row.get(k, "")) for k in HEADER}

    file_exists = Path(path).exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        if not file_exists:
            writer.writeheader()
        writer.writerow(str_row)


def read_last_n(path: str = "metrics.csv", n: int = 5) -> List[Dict[str, str]]:
    """Read last N rows from metrics CSV."""
    filepath = Path(path)
    if not filepath.exists():
        return []

    with open(filepath, "r", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    return rows[-n:]


def print_summary(path: str = "metrics.csv", n: int = 5) -> None:
    """Print a formatted table of the last N entries."""
    rows = read_last_n(path, n)
    if not rows:
        print("No metrics data found.")
        return

    # Column widths
    cols = [
        "run_id",
        "risk_tier",
        "tick_delta_ms",
        "boundary_violations_caught",
        "repair_loop_depth",
        "gate1_pass",
        "gate2_pass",
        "gate3_pass",
    ]
    headers = ["RunID", "Tier", "TickΔ(ms)", "Violations", "Repairs", "G1", "G2", "G3"]
    widths = [max(len(h), max(len(str(r.get(c, ""))) for r in rows)) for h, c in zip(headers, cols)]

    # Header
    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_line)
    print("-" * len(header_line))

    # Rows
    for row in rows:
        values = [str(row.get(c, "")).ljust(w) for c, w in zip(cols, widths)]
        print("  ".join(values))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DevForge Metrics CSV Appender")
    parser.add_argument("--json", help="Path to JSON file or JSON string containing row data.")
    parser.add_argument("--file", default="metrics.csv", help="Path to metrics CSV.")
    parser.add_argument("--summary", action="store_true", help="Print last 5 entries as a formatted table.")
    parser.add_argument("-n", type=int, default=5, help="Number of entries to show in summary (default 5).")

    args = parser.parse_args()

    if args.summary:
        print_summary(args.file, args.n)
    elif args.json:
        # Load from file or string
        json_input = args.json
        if Path(json_input).exists():
            with open(json_input, "r") as f:
                row = json.load(f)
        else:
            row = json.loads(json_input)

        try:
            append_row(row, args.file)
            print(f"Appended: {row.get('run_id', '?')}")
        except ValueError as e:
            print(f"REJECTED: {e}")
            exit(1)
    else:
        parser.print_help()
