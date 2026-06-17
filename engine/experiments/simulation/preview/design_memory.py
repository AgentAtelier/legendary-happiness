"""Persistent design memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List


class DesignMemory:
    def __init__(self, path: str = "memory/design_memory.json"):

        self.path = Path(path)

        self.records: List[Dict[str, Any]] = []

        self._load()

    # ---------------------------------------------------------

    def store(
        self,
        systems,
        metrics,
        critique,
    ):

        record = {
            "systems": systems,
            "metrics": {name: metric.value for name, metric in metrics.items()},
            "critique": critique,
        }

        self.records.append(record)

        self._save()

    # ---------------------------------------------------------

    def best_designs(self, metric_name: str, limit: int = 5):

        ranked = sorted(
            self.records,
            key=lambda r: abs(r["metrics"].get(metric_name, 0)),
        )

        return ranked[:limit]

    # ---------------------------------------------------------

    def all_records(self):

        return self.records

    # ---------------------------------------------------------

    def _load(self):

        if not self.path.exists():
            return

        with open(self.path, "r") as f:
            self.records = json.load(f)

    # ---------------------------------------------------------

    def _save(self):

        self.path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.path, "w") as f:
            json.dump(self.records, f, indent=2)
