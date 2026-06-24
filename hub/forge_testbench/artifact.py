"""Artifact — the persisted output of a test run.

One Artifact = one complete run (single model or sweep). Contains:
  - Metadata (kind, ts, model, models, suite)
  - A flat list of Results (every test, every repeat)
  - Optional aggregated comparison data for multi-model runs

Artifacts are pure data — renderers (reporting.py) consume them without
re-interpreting numbers.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .result import Result

ARTIFACT_DIR = Path(__file__).parent.parent / "data" / "testbench"


class Artifact:
    """Immutable record of a test run."""

    def __init__(
        self,
        kind: str,
        suite: str,
        models: list[str],
        *,
        results: list[Result] | None = None,
        meta: dict | None = None,
    ) -> None:
        self.kind = kind  # "single" | "sweep" | "repeat"
        self.suite = suite
        self.models = models
        self.ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.ts_slug = time.strftime("%Y%m%d-%H%M%S")
        self.results = results or []
        self.meta = meta or {}

    def add(self, result: Result) -> None:
        self.results.append(result)

    def extend(self, results: list[Result]) -> None:
        self.results.extend(results)

    def by_model(self, model: str) -> list[Result]:
        return [r for r in self.results if r.model == model]

    def by_test(self, test_id: str) -> list[Result]:
        return [r for r in self.results if r.test_id == test_id]

    def by_category(self, category: str) -> list[Result]:
        return [r for r in self.results if r.category == category]

    def model_summary(self) -> dict[str, dict]:
        """Return per-model pass/broke/partial/error counts and avg score."""
        out: dict[str, dict] = {}
        for model in self.models:
            model_results = self.by_model(model)
            counts = {"ok": 0, "partial": 0, "broke": 0, "error": 0, "total": 0}
            scores: list[int] = []
            for r in model_results:
                counts[r.status] = counts.get(r.status, 0) + 1
                counts["total"] += 1
                if r.score is not None:
                    scores.append(r.score)
            out[model] = {
                "counts": counts,
                "avg_score": round(sum(scores) / max(len(scores), 1)) if scores else None,
                "total_latency_ms": sum(r.latency_ms for r in model_results),
            }
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "suite": self.suite,
            "ts": self.ts,
            "models": self.models,
            "results": [r.to_dict() for r in self.results],
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Artifact:
        art = cls(
            kind=d["kind"],
            suite=d["suite"],
            models=d["models"],
            meta=d.get("meta", {}),
        )
        art.ts = d.get("ts", art.ts)
        art.ts_slug = d.get("ts_slug", art.ts_slug)
        art.results = [Result.from_dict(r) for r in d.get("results", [])]
        return art

    def save(self) -> Path:
        """Persist to data/testbench/<ts_slug>/artifact.json."""
        out_dir = ARTIFACT_DIR / self.ts_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "artifact.json"
        out_file.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        return out_dir

    @classmethod
    def load(cls, ts_slug: str) -> Artifact | None:
        """Load a previously-saved artifact by timestamp slug."""
        fp = ARTIFACT_DIR / ts_slug / "artifact.json"
        if not fp.exists():
            return None
        try:
            return cls.from_dict(json.loads(fp.read_text()))
        except Exception:
            return None

    @classmethod
    def list_runs(cls, limit: int = 30) -> list[dict]:
        """List saved artifact runs with metadata."""
        runs = []
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        for d in sorted(ARTIFACT_DIR.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            fp = d / "artifact.json"
            if not fp.exists():
                continue
            try:
                data = json.loads(fp.read_text())
                runs.append(
                    {
                        "ts_slug": d.name,
                        "ts": data.get("ts"),
                        "kind": data.get("kind"),
                        "suite": data.get("suite"),
                        "models": data.get("models"),
                        "result_count": len(data.get("results", [])),
                    }
                )
            except Exception:
                continue
            if len(runs) >= limit:
                break
        return runs
