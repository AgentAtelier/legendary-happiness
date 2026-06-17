"""
DevForge Decision Log CLI
==========================
Append-only structured log of architectural decisions.
Every merge appends a record. Approve action locked until explicit question answered.

Usage:
    python -m devforge.governance.decision_log append --json entry.json --schema schemas/decision_log_entry_schema.json
    python -m devforge.governance.decision_log append --json entry.json --schema schemas/decision_log_entry_schema.json --auto-id
    python -m devforge.governance.decision_log list --log decision_log.jsonl -n 5
    python -m devforge.governance.decision_log list --log decision_log.jsonl --tier critical
    python -m devforge.governance.decision_log stats --log decision_log.jsonl
"""

import argparse
import datetime
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

RUN_PATTERN = re.compile(r"^DF-[0-9]{4}-[0-9]{4}$")

DEFAULT_LOG_PATH = "decision_log.jsonl"


# --------------------------------------------------------------------------
# Schema validation
# --------------------------------------------------------------------------
def _validate_against_schema(entry: dict, schema_path: str) -> None:
    """Validate entry against JSON schema. Falls back to basic checks if jsonschema unavailable."""
    try:
        from jsonschema import ValidationError, validate

        with open(schema_path, "r") as f:
            schema = json.load(f)
        validate(instance=entry, schema=schema)
    except ImportError:
        # Fallback: basic structural validation without jsonschema
        _validate_basic(entry)
    except ValidationError as e:
        raise ValueError(f"Schema validation failed: {e.message}")


def _validate_basic(entry: dict) -> None:
    """Minimal validation when jsonschema is unavailable."""
    required = [
        "run_id",
        "timestamp",
        "decision",
        "explicit_question",
        "explicit_question_answer",
        "human_rationale",
        "unplanned_patterns_reviewed",
        "risk_score",
        "model_version",
    ]
    missing = [k for k in required if k not in entry]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    if entry["decision"] not in ("approved", "revision_requested", "rejected"):
        raise ValueError(f"Invalid decision: {entry['decision']}")

    if not RUN_PATTERN.match(entry["run_id"]):
        raise ValueError(f"Invalid run_id format: {entry['run_id']}. Expected DF-MMDD-NNNN.")


# --------------------------------------------------------------------------
# Run ID generation
# --------------------------------------------------------------------------
def generate_run_id(log_path: str = DEFAULT_LOG_PATH) -> str:
    """Generate next run_id for today: DF-MMDD-NNNN (auto-incrementing)."""
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%m%d")
    prefix = f"DF-{today}-"
    seq = 0

    path = Path(log_path)
    if path.exists():
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    rid = data.get("run_id", "")
                    if rid.startswith(prefix):
                        num = int(rid[len(prefix) :])
                        seq = max(seq, num)
                except (json.JSONDecodeError, ValueError):
                    continue

    return f"{prefix}{seq + 1:04d}"


# --------------------------------------------------------------------------
# Core operations
# --------------------------------------------------------------------------
def append_entry(
    entry: dict,
    schema_path: str,
    log_path: str = DEFAULT_LOG_PATH,
    auto_id: bool = False,
) -> str:
    """
    Validate and append a decision log entry.

    Returns the run_id of the appended entry.
    Raises ValueError if validation fails or explicit_question_answer is insufficient.
    """
    # Auto-generate run_id if requested
    if auto_id:
        entry["run_id"] = generate_run_id(log_path)

    # Hard gate: explicit question must be answered (constitutional requirement)
    answer = entry.get("explicit_question_answer", "")
    if not answer or len(answer.strip()) < 10:
        raise ValueError(
            "Approve action blocked: explicit_question_answer must be >= 10 characters. "
            "This is a constitutional requirement — the approve action is unavailable "
            "until the explicit question is answered in writing."
        )

    # Validate
    _validate_against_schema(entry, schema_path)

    # Derive risk_tier if not set
    if "risk_tier" not in entry or not entry["risk_tier"]:
        score = entry.get("risk_score", 0)
        if score <= 3:
            entry["risk_tier"] = "low"
        elif score <= 7:
            entry["risk_tier"] = "medium"
        elif score <= 11:
            entry["risk_tier"] = "high"
        else:
            entry["risk_tier"] = "critical"

    # Append (never modify existing)
    with open(log_path, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    return entry["run_id"]


def list_entries(
    log_path: str = DEFAULT_LOG_PATH,
    n: int = 10,
    tier_filter: Optional[str] = None,
) -> List[Dict]:
    """Return last N entries, optionally filtered by risk tier."""
    path = Path(log_path)
    if not path.exists():
        return []

    entries = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if tier_filter and entry.get("risk_tier") != tier_filter:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    return entries[-n:]


def compute_stats(log_path: str = DEFAULT_LOG_PATH) -> Dict[str, Any]:
    """Compute summary statistics from the decision log."""
    path = Path(log_path)
    if not path.exists():
        return {"total": 0, "tiers": {}, "avg_rationale_words": 0}

    entries = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not entries:
        return {"total": 0, "tiers": {}, "avg_rationale_words": 0}

    tiers: Dict[str, int] = {}
    total_words = 0
    decisions: Dict[str, int] = {}

    for e in entries:
        tier = e.get("risk_tier", "unknown")
        tiers[tier] = tiers.get(tier, 0) + 1

        decision = e.get("decision", "unknown")
        decisions[decision] = decisions.get(decision, 0) + 1

        rationale = e.get("human_rationale", "")
        total_words += len(rationale.split())

    return {
        "total": len(entries),
        "tiers": tiers,
        "decisions": decisions,
        "avg_rationale_words": round(total_words / len(entries), 1),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _format_entry_short(entry: dict) -> str:
    """One-line summary of a decision log entry."""
    rid = entry.get("run_id", "?")
    decision = entry.get("decision", "?")
    tier = entry.get("risk_tier", "?")
    ts = entry.get("timestamp", "?")[:10]
    files = len(entry.get("files_modified", []))
    return f"  {rid}  {ts}  {decision:<20s}  {tier:<10s}  {files} files"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DevForge Decision Log — append-only architectural record")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # --- append ---
    p_append = sub.add_parser("append", help="Append a new decision log entry")
    p_append.add_argument("--json", required=True, help="Path to JSON file or JSON string for the entry.")
    p_append.add_argument("--schema", required=True, help="Path to decision_log_entry_schema.json.")
    p_append.add_argument("--log", default=DEFAULT_LOG_PATH)
    p_append.add_argument("--auto-id", action="store_true", help="Auto-generate run_id (DF-MMDD-NNNN).")

    # --- list ---
    p_list = sub.add_parser("list", help="List recent entries")
    p_list.add_argument("--log", default=DEFAULT_LOG_PATH)
    p_list.add_argument("-n", type=int, default=10, help="Number of entries (default 10)")
    p_list.add_argument("--tier", choices=["low", "medium", "high", "critical"])

    # --- stats ---
    p_stats = sub.add_parser("stats", help="Print log statistics")
    p_stats.add_argument("--log", default=DEFAULT_LOG_PATH)

    args = parser.parse_args()

    if args.cmd == "append":
        # Load entry from file or string
        json_input = args.json
        if Path(json_input).exists():
            with open(json_input, "r") as f:
                entry = json.load(f)
        else:
            entry = json.loads(json_input)

        try:
            rid = append_entry(entry, args.schema, args.log, auto_id=args.auto_id)
            print(f"Appended: {rid}")
        except ValueError as e:
            print(f"REJECTED: {e}")
            exit(1)

    elif args.cmd == "list":
        entries = list_entries(args.log, args.n, tier_filter=args.tier)
        if not entries:
            print("No entries found.")
        else:
            print(f"{'RunID':<16s}  {'Date':<10s}  {'Decision':<20s}  {'Tier':<10s}  Files")
            print("-" * 72)
            for e in entries:
                print(_format_entry_short(e))

    elif args.cmd == "stats":
        s = compute_stats(args.log)
        print(json.dumps(s, indent=2))
