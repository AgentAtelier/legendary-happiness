"""
DevForge Scope Lock System
===========================
Before a coder model touches code (Phase 1+ autonomy), a scope lock
specifies exactly which files and interfaces it may modify.
Gate 1 validates compliance — files outside the scope lock trigger
unplanned pattern flags.

Usage:
    # Create a scope lock
    python -m devforge.governance.scope_lock create --files sim/ecology/eco_region.gd \\
        --subsystems ecology --depth new_behaviour --description "Add resource depletion states"

    # Validate a diff against a scope lock
    python -m devforge.governance.scope_lock validate --lock scope_lock.json \\
        --actual-files sim/ecology/eco_region.gd
"""

import argparse
import datetime
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ScopeLock:
    """Defines the boundary of allowed modifications for a coder model run."""

    lock_id: str
    created: str
    description: str
    allowed_files: List[str]  # Exact files the coder may modify
    allowed_directories: List[str]  # Directories where new files may be created
    forbidden_files: List[str]  # Explicitly blocked (e.g., protected files)
    subsystems: List[str]  # Subsystems in scope (for risk scoring)
    depth: str  # Depth classification
    interface_signatures: Dict[str, str]  # Expected function signatures (name → signature)
    max_new_files: int  # Maximum new files allowed
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "lock_id": self.lock_id,
            "created": self.created,
            "description": self.description,
            "allowed_files": self.allowed_files,
            "allowed_directories": self.allowed_directories,
            "forbidden_files": self.forbidden_files,
            "subsystems": self.subsystems,
            "depth": self.depth,
            "interface_signatures": self.interface_signatures,
            "max_new_files": self.max_new_files,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScopeLock":
        return cls(
            lock_id=data["lock_id"],
            created=data["created"],
            description=data["description"],
            allowed_files=data.get("allowed_files", []),
            allowed_directories=data.get("allowed_directories", []),
            forbidden_files=data.get("forbidden_files", []),
            subsystems=data.get("subsystems", []),
            depth=data.get("depth", "new_behaviour"),
            interface_signatures=data.get("interface_signatures", {}),
            max_new_files=data.get("max_new_files", 3),
            notes=data.get("notes", ""),
        )


@dataclass
class ScopeValidation:
    """Result of validating actual changes against a scope lock."""

    passed: bool
    lock_id: str
    files_in_scope: List[str] = field(default_factory=list)
    files_out_of_scope: List[str] = field(default_factory=list)
    forbidden_files_touched: List[str] = field(default_factory=list)
    new_files_count: int = 0
    new_files_over_limit: bool = False
    accuracy_percent: float = 0.0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "lock_id": self.lock_id,
            "files_in_scope": self.files_in_scope,
            "files_out_of_scope": self.files_out_of_scope,
            "forbidden_files_touched": self.forbidden_files_touched,
            "new_files_count": self.new_files_count,
            "new_files_over_limit": self.new_files_over_limit,
            "accuracy_percent": self.accuracy_percent,
        }

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"Scope Lock Validation: {status}  (lock: {self.lock_id})",
            f"  In scope: {len(self.files_in_scope)}",
            f"  Out of scope: {len(self.files_out_of_scope)}",
            f"  Accuracy: {self.accuracy_percent:.0f}%",
        ]
        if self.files_out_of_scope:
            lines.append("  ⚠ Files outside scope lock:")
            for f in self.files_out_of_scope:
                lines.append(f"    {f}")
        if self.forbidden_files_touched:
            lines.append("  ⚠ FORBIDDEN files touched:")
            for f in self.forbidden_files_touched:
                lines.append(f"    {f}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Core operations
# --------------------------------------------------------------------------
def create_scope_lock(
    description: str,
    allowed_files: List[str],
    subsystems: List[str],
    depth: str = "new_behaviour",
    allowed_directories: Optional[List[str]] = None,
    forbidden_files: Optional[List[str]] = None,
    interface_signatures: Optional[Dict[str, str]] = None,
    max_new_files: int = 3,
    contracts_parser=None,
    notes: str = "",
) -> ScopeLock:
    """
    Create a new scope lock document.

    Automatically populates forbidden_files from contracts if parser is provided.
    """
    # Auto-populate forbidden files from contracts
    if forbidden_files is None:
        forbidden_files = []
    if contracts_parser:
        protected = contracts_parser.get_protected_files()
        forbidden_files = list(set(forbidden_files + protected))

    # Validate no allowed file is also forbidden
    conflict = set(allowed_files) & set(forbidden_files)
    if conflict:
        raise ValueError(f"Scope lock conflict: files are both allowed and forbidden: {conflict}")

    now = datetime.datetime.now(datetime.timezone.utc)
    lock_id = f"SL-{now.strftime('%m%d')}-{now.strftime('%H%M%S')}"

    return ScopeLock(
        lock_id=lock_id,
        created=now.isoformat(),
        description=description,
        allowed_files=sorted(allowed_files),
        allowed_directories=sorted(allowed_directories or []),
        forbidden_files=sorted(forbidden_files),
        subsystems=sorted(subsystems),
        depth=depth,
        interface_signatures=interface_signatures or {},
        max_new_files=max_new_files,
        notes=notes,
    )


def validate_against_lock(
    lock: ScopeLock,
    actual_files: List[str],
    new_files: Optional[List[str]] = None,
) -> ScopeValidation:
    """
    Validate actual changed files against a scope lock.

    Args:
        lock: The scope lock to validate against.
        actual_files: Files that were actually modified.
        new_files: Files that were newly created (not modified).

    Returns:
        ScopeValidation with pass/fail and details.
    """
    allowed_set = set(lock.allowed_files)
    forbidden_set = set(lock.forbidden_files)
    allowed_dirs = lock.allowed_directories

    in_scope = []
    out_of_scope = []
    forbidden_touched = []

    for f in actual_files:
        if f in forbidden_set:
            forbidden_touched.append(f)
        elif f in allowed_set:
            in_scope.append(f)
        elif any(f.startswith(d) for d in allowed_dirs):
            in_scope.append(f)  # New file in allowed directory
        else:
            out_of_scope.append(f)

    new_count = len(new_files) if new_files else 0
    over_limit = new_count > lock.max_new_files

    # Accuracy
    total = max(len(actual_files), len(lock.allowed_files))
    accuracy = (len(in_scope) / total * 100) if total > 0 else 100.0

    passed = len(out_of_scope) == 0 and len(forbidden_touched) == 0 and not over_limit

    return ScopeValidation(
        passed=passed,
        lock_id=lock.lock_id,
        files_in_scope=in_scope,
        files_out_of_scope=out_of_scope,
        forbidden_files_touched=forbidden_touched,
        new_files_count=new_count,
        new_files_over_limit=over_limit,
        accuracy_percent=round(accuracy, 1),
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DevForge Scope Lock System")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # --- create ---
    p_create = sub.add_parser("create", help="Create a new scope lock")
    p_create.add_argument("--files", nargs="+", required=True)
    p_create.add_argument("--subsystems", nargs="+", required=True)
    p_create.add_argument(
        "--depth", default="new_behaviour", choices=["read_only", "new_behaviour", "modifies_interface", "restructures"]
    )
    p_create.add_argument("--description", required=True)
    p_create.add_argument("--dirs", nargs="*", default=[])
    p_create.add_argument("--max-new-files", type=int, default=3)
    p_create.add_argument("--contracts", help="Path to contracts YAML for auto-populating forbidden files.")
    p_create.add_argument("--output", help="Save to file instead of stdout.")

    # --- validate ---
    p_val = sub.add_parser("validate", help="Validate files against a scope lock")
    p_val.add_argument("--lock", required=True, help="Path to scope lock JSON.")
    p_val.add_argument("--actual-files", nargs="+", required=True)
    p_val.add_argument("--new-files", nargs="*", default=[])

    args = parser.parse_args()

    if args.cmd == "create":
        cp = None
        if args.contracts:
            from devforge.governance.contracts import ContractsParser

            cp = ContractsParser(args.contracts)

        lock = create_scope_lock(
            description=args.description,
            allowed_files=args.files,
            subsystems=args.subsystems,
            depth=args.depth,
            allowed_directories=args.dirs,
            max_new_files=args.max_new_files,
            contracts_parser=cp,
        )

        output = json.dumps(lock.to_dict(), indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Scope lock saved to {args.output}")
        else:
            print(output)

    elif args.cmd == "validate":
        with open(args.lock) as f:
            lock = ScopeLock.from_dict(json.load(f))

        result = validate_against_lock(lock, args.actual_files, args.new_files)
        print(result.summary())
        exit(0 if result.passed else 1)
