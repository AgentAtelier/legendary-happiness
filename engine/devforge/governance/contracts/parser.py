"""
DevForge Contracts Parser
==========================
Reads architectural_contracts.yaml and provides typed accessor functions.
Gate 1 consumes this to enforce boundary rules.

Usage as module:
    from devforge.governance.contracts.parser import ContractsParser
    cp = ContractsParser("contracts/architectural_contracts.yaml")
    rules = cp.get_boundary_rules()

Usage as CLI:
    python -m devforge.governance.contracts.parser contracts/architectural_contracts.yaml --summary
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from devforge.infrastructure.logger import logger


class ContractsParser:
    """Read-only parser for architectural_contracts.yaml."""

    REQUIRED_KEYS = [
        "schema_version",
        "layers",
        "boundary_rules",
        "return_type_rules",
        "protected_files",
        "permitted_singletons",
        "exception_ceiling",
        "exceptions",
        "hard_constraints",
    ]

    def __init__(self, path: str):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(f"Contracts file not found: {self.path}")
        try:
            with open(self.path, "r") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise RuntimeError(f"Malformed YAML in {self.path}: {e}")

        if data is None:
            raise ValueError(f"Empty YAML file: {self.path}")
        if "schema_version" not in data:
            raise ValueError("Missing 'schema_version' in contracts YAML.")

        missing = [k for k in self.REQUIRED_KEYS if k not in data]
        if missing:
            raise ValueError(f"Missing required keys in contracts YAML: {missing}")

        return data

    @property
    def schema_version(self) -> str:
        return self._data["schema_version"]

    def get_layers(self) -> Dict[str, Dict]:
        """Return layer definitions keyed by layer name."""
        return self._data.get("layers", {})

    def get_layer_paths(self, layer_name: str) -> List[str]:
        """Return filesystem paths for a given layer."""
        layers = self.get_layers()
        if layer_name not in layers:
            raise KeyError(f"Unknown layer: {layer_name}. Valid: {list(layers.keys())}")
        return layers[layer_name].get("paths", [])

    def get_boundary_rules(self) -> List[Dict]:
        """Return all boundary rules as dicts."""
        return self._data.get("boundary_rules", [])

    def get_protected_files(self) -> List[str]:
        """Return protected file paths as plain strings."""
        return [pf["path"] for pf in self._data.get("protected_files", [])]

    def get_protected_file_details(self) -> List[Dict]:
        """Return full protected file records (path, description, guards)."""
        return self._data.get("protected_files", [])

    def get_return_type_rules(self) -> List[Dict]:
        """Return return type restriction rules."""
        return self._data.get("return_type_rules", [])

    def get_permitted_singletons(self) -> List[Dict]:
        """Return list of permitted singleton definitions (name + autoload_path)."""
        return self._data.get("permitted_singletons", [])

    def get_permitted_singleton_names(self) -> List[str]:
        """Return just the permitted singleton names."""
        return [s["name"] for s in self.get_permitted_singletons()]

    def get_exception_count(self) -> int:
        """Return current number of contract exceptions."""
        return len(self._data.get("exceptions", []))

    def get_exception_ceiling(self) -> int:
        """Return the hard ceiling for exceptions (C-12)."""
        return self._data.get("exception_ceiling", 0)

    def is_ceiling_exceeded(self) -> bool:
        """Check if exception count exceeds ceiling."""
        return self.get_exception_count() > self.get_exception_ceiling()

    def get_exceptions(self) -> List[Dict]:
        """Return all active exceptions."""
        return self._data.get("exceptions", [])

    def get_hard_constraints(self) -> List[Dict]:
        """Return all constitutional hard constraints."""
        return self._data.get("hard_constraints", [])

    def get_constraint_by_id(self, constraint_id: str) -> Optional[Dict]:
        """Look up a specific hard constraint by ID."""
        for c in self.get_hard_constraints():
            if c.get("id") == constraint_id:
                return c
        return None

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for quick inspection."""
        return {
            "schema_version": self.schema_version,
            "layer_count": len(self.get_layers()),
            "boundary_rule_count": len(self.get_boundary_rules()),
            "return_type_rule_count": len(self.get_return_type_rules()),
            "protected_file_count": len(self.get_protected_files()),
            "singleton_count": len(self.get_permitted_singletons()),
            "exception_count": self.get_exception_count(),
            "exception_ceiling": self.get_exception_ceiling(),
            "ceiling_exceeded": self.is_ceiling_exceeded(),
            "hard_constraint_count": len(self.get_hard_constraints()),
        }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DevForge Architectural Contracts Parser")
    parser.add_argument("path", help="Path to architectural_contracts.yaml")
    parser.add_argument("--summary", action="store_true", help="Print a summary of the contracts file.")
    parser.add_argument(
        "--section",
        choices=[
            "boundary_rules",
            "return_type_rules",
            "protected_files",
            "singletons",
            "exceptions",
            "hard_constraints",
            "layers",
        ],
        help="Print a specific section as JSON.",
    )

    args = parser.parse_args()

    try:
        cp = ContractsParser(args.path)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        logger.error("contracts", str(e))
        exit(1)

    if args.summary:
        print(json.dumps(cp.summary(), indent=2))
    elif args.section:
        section_map = {
            "boundary_rules": cp.get_boundary_rules,
            "return_type_rules": cp.get_return_type_rules,
            "protected_files": cp.get_protected_file_details,
            "singletons": cp.get_permitted_singletons,
            "exceptions": cp.get_exceptions,
            "hard_constraints": cp.get_hard_constraints,
            "layers": cp.get_layers,
        }
        print(json.dumps(section_map[args.section](), indent=2))
    else:
        print(json.dumps(cp.summary(), indent=2))
