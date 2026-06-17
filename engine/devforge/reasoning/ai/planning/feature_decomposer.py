"""
Breaks a user prompt into high-level architecture features.

Phase 3: Grammar-constrained JSON output via decomposer.gbnf.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Optional

from devforge.infrastructure.logger import logger


class FeatureDecomposer:
    """
    Breaks a user prompt into high-level architecture features.
    """

    GRAMMAR_PATH = Path(__file__).resolve().parents[2] / "prompts" / "decomposer.gbnf"

    def __init__(self):
        self._grammar: Optional[str] = None
        self._load_grammar()

    def _load_grammar(self) -> None:
        try:
            if self.GRAMMAR_PATH.exists():
                raw = self.GRAMMAR_PATH.read_text(encoding="utf-8")
                self._grammar = raw.replace("\r\n", "\n").strip()
                logger.info("feature_decomposer", f"Loaded grammar from {self.GRAMMAR_PATH}")
            else:
                logger.warn("feature_decomposer", f"Grammar not found: {self.GRAMMAR_PATH}")
        except Exception as exc:
            logger.error("feature_decomposer", f"Failed to load grammar: {exc}")

    @property
    def grammar(self) -> Optional[str]:
        """The loaded GBNF grammar for constraining decomposition output."""
        return self._grammar

    # ---------------------------------------------------------

    def decompose(
        self,
        prompt: str,
        llm: Callable[..., str],
    ) -> List[str]:

        llm_prompt = self._build_prompt(prompt)

        # Pass grammar if available — constrains output to parseable JSON
        if self._grammar:
            response = llm(llm_prompt, grammar=self._grammar)
        else:
            response = llm(llm_prompt)

        try:

            data = json.loads(response)

            if isinstance(data, list):

                features = []

                for f in data:

                    if isinstance(f, str):
                        features.append(f)

                if features:
                    return features

        except Exception:
            pass

        logger.warn("feature_decomposer", "Decomposition failed — falling back to [prompt]")
        return [prompt]

    # ---------------------------------------------------------

    def _build_prompt(self, prompt: str) -> str:

        return f"""
You are a system planner.

Break the user request into a list of architecture features.

Return ONLY JSON.

Example:

[
  "Create Player entity",
  "Add movement system",
  "Add health system"
]

User request:

{prompt}

Return JSON list now.
"""