"""Scene Doctor — deterministic scene auditor.

Walks the scene tree and runs all registered audit rules.  Returns
violations with severity, message, and fix suggestions.  No LLM
anywhere in this module (tier 0 — works with the LLM off).
"""

from __future__ import annotations

from typing import Callable

from devforge.auditing.rules import ALL_RULES, Violation
from devforge.infrastructure.logger import logger
from devforge.knowledge.scene.scene_graph import SceneGraph


class SceneDoctor:
    """Deterministic scene auditor — runs rules, collects violations."""

    def __init__(
        self,
        props_lookup: Callable[[str], dict | None] | None = None,
    ):
        """*props_lookup* is ``(node_path) -> property dict | None``.

        When None (v1 default), rules that need properties return an
        INFO ``'R<N> skipped (no property access)'`` violation instead
        of crashing or silently skipping.
        """
        self._props_lookup = props_lookup

    def audit(self, scene_tree: dict) -> list[Violation]:
        """Run all registered rules against *scene_tree*.

        Deterministic: same tree in, same violations out, stable
        ordering (by rule_id, then node_path).  Rules that raise
        are caught and logged — a buggy rule never kills the audit.
        """
        graph = SceneGraph(scene_tree)
        violations: list[Violation] = []

        for rule_fn in ALL_RULES:
            try:
                violations.extend(rule_fn(graph, self._props_lookup))
            except Exception as exc:
                logger.warn(
                    "scene_doctor",
                    f"Rule {rule_fn.__name__} raised {type(exc).__name__}: {exc} — skipping",
                )

        # Stable ordering: by rule_id, then node_path
        violations.sort(key=lambda v: (v.rule_id, v.node_path))
        return violations
