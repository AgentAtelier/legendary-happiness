"""Test plug-in interface. A test is a self-contained unit that owns both
how it runs and how it scores, so scoring logic is never centralized and
can't drift.

To add a new test: subclass Test, fill in the class-level fields, implement
run() and score(), and register it in the Catalog. Nothing else changes.
"""

from __future__ import annotations

from typing import Any

from .context import Context
from .result import ScoredResult


class Test:
    """Atomic test plug-in. Owns run + score.

    Class-level attributes (no __init__ — these are declarations):
        id: Unique identifier (e.g. "probe.llama.throughput").
        category: "probe" | "scenario" | "capability" | "variety" | "intent" | "ceiling".
        title: Short UI label.
        description: Plain-language explainer (feeds the Testing tab).
        suites: Which suites include this test (e.g. ["everything", "llama-layer"]).
        repeatable: Whether repeat > 1 makes sense for this test.
        needs_reset: Whether the runner should reset the probe scene before this test.
        skip_cache: Whether apply_spec calls should skip the plan cache.
        expect_break: If True, "broke" status is expected success (stress tests).
        timeout_s: Per-test timeout in seconds (default 300).
    """

    # ── Declarations (override in subclass) ──────────────────────

    id: str = ""
    category: str = "probe"
    title: str = ""
    description: str = ""
    suites: list[str] = ["everything"]
    repeatable: bool = False
    needs_reset: bool = False
    skip_cache: bool = False
    expect_break: bool = False
    timeout_s: int = 300

    # ── Interface ────────────────────────────────────────────────

    async def run(self, ctx: Context) -> dict[str, Any]:
        """Execute the test against the live stack via ctx. Returns RAW observations.

        This should capture everything needed for scoring (API responses,
        scene snapshots, timings) so that score() can be a pure function.
        """
        raise NotImplementedError("Test.run()")

    def score(self, raw: dict[str, Any]) -> ScoredResult:
        """Pure function: raw observations → structured verdict.

        Never reaches into global state or makes live API calls.
        This is where interpretation lives, and it's unit-testable.
        """
        raise NotImplementedError("Test.score()")

    # ── Helpers ──────────────────────────────────────────────────

    @classmethod
    def to_catalog_entry(cls) -> dict[str, Any]:
        """Return a lightweight catalog entry (for UI pickers)."""
        return {
            "id": cls.id,
            "category": cls.category,
            "title": cls.title,
            "description": cls.description,
            "suites": cls.suites,
            "repeatable": cls.repeatable,
            "skip_cache": cls.skip_cache,
            "expect_break": cls.expect_break,
        }
