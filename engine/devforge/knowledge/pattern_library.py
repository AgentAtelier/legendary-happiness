from __future__ import annotations

from typing import Dict, Any


class PatternLibrary:
    def __init__(self):

        self.patterns: Dict[str, Dict[str, Any]] = {}

    # ─────────────────────────────────────

    def register(self, name: str, pattern: Dict[str, Any]):

        self.patterns[name] = pattern

    # ─────────────────────────────────────

    def get(self, name: str):

        return self.patterns.get(name)

    # ─────────────────────────────────────

    def list_patterns(self):

        return list(self.patterns.keys())

    # ─────────────────────────────────────

    def match(self, prompt: str):

        results = []

        prompt_lower = prompt.lower()

        for name in self.patterns:
            if name.lower() in prompt_lower:
                results.append(self.patterns[name])

        return results
