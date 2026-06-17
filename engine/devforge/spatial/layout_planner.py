"""Layout Planner — LLM-powered spatial layout generation.

Mirrors ArchitecturePlanner: builds a prompt, calls the LLM with a
GBNF grammar, parses the response into a layout JSON.

The LLM outputs semantic intent only: which pattern, which dimensions,
which assets go in which slots. The SpatialCompiler resolves everything
into absolute transforms.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from devforge.infrastructure.logger import logger
from devforge.spatial.lexicon import AssetLexicon
from devforge.spatial.compiler import SpatialCompiler


class LayoutPlanningError(Exception):
    """LLM layout planning failed — retryable."""


class LayoutPlanner:
    """Generates layout JSON from natural language prompts."""

    DEFAULT_GRAMMAR_PATH = Path(__file__).resolve().parent / "prompts" / "layout_planner.gbnf"

    def __init__(
        self,
        lexicon: AssetLexicon | None = None,
        compiler: SpatialCompiler | None = None,
        grammar_path: str | Path | None = None,
    ):
        self._lexicon = lexicon or AssetLexicon()
        self._compiler = compiler or SpatialCompiler(self._lexicon)
        self._grammar_path = str(grammar_path or self.DEFAULT_GRAMMAR_PATH)
        self._grammar_text: Optional[str] = None
        self._load_grammar()

    # ── public API ──────────────────────────────────────────

    def plan(
        self,
        *,
        context: str,
        prompt: str,
        llm_fn: Callable[[str], str],
        scene: Optional[Dict] = None,
        skip_cache: bool = False,
    ) -> Dict:
        """Generate a layout JSON, using cache if available.

        Args:
            context: Existing scene/architecture context.
            prompt: User's natural language spec.
            llm_fn: Callable that takes a prompt and returns LLM output.
            scene: Current scene tree (unused currently, for API compat).

        Returns:
            Layout JSON dict with pattern, dimensions, slot_fills, arcs_overrides.
        """
        llm_prompt = self._build_prompt(context, prompt)

        logger.info(
            "layout_planner",
            "Calling LLM for layout",
            prompt_preview=prompt[:100],
            grammar=self._grammar_text is not None,
        )

        try:
            response = llm_fn(llm_prompt)
            result = self._parse_response(response)

            logger.info(
                "layout_planner",
                "Layout parsed",
                pattern=result.get("pattern"),
                slots=len(result.get("slot_fills", {})),
                arcs=len(result.get("arcs_overrides", [])),
            )

            return result

        except Exception as exc:
            logger.error("layout_planner", f"LLM planning failed: {exc}")
            raise LayoutPlanningError(str(exc)) from exc

    @property
    def grammar(self) -> Optional[str]:
        """The loaded GBNF grammar text."""
        return self._grammar_text

    # ── internals ───────────────────────────────────────────

    def _load_grammar(self) -> None:
        try:
            gf = Path(self._grammar_path)
            if gf.exists():
                raw = gf.read_text(encoding="utf-8")
                self._grammar_text = raw.replace("\r\n", "\n").strip()
                logger.info("layout_planner", f"Loaded grammar from {self._grammar_path}")
            else:
                logger.warn("layout_planner", f"Grammar not found: {self._grammar_path}")
        except Exception as exc:
            logger.error("layout_planner", f"Failed to load grammar: {exc}")

    def _build_prompt(self, context: str, prompt: str) -> str:
        """Build the layout planner prompt."""
        asset_summary = self._lexicon.summary_for_prompt()
        pattern_summary = self._compiler.pattern_summary_for_prompt()
        pattern_ids = ", ".join(self._compiler.pattern_ids)
        asset_ids = ", ".join(self._lexicon.asset_ids)

        return f"""You are a spatial layout planner for a Godot 4 game level editor.
Choose a room pattern, set its dimensions, and assign greybox assets to slots.

AVAILABLE PATTERNS (choose one):
{pattern_summary}

ASSET CATALOG (assign to slots by id):
{asset_summary}

SCHEMA — output ONLY this JSON:
{{
  "pattern": "<pattern_id>",
  "dimensions": {{"width": <number>, "height": <number>, "depth": <number>}},
  "slot_fills": {{"<slot_id>": "<asset_id>", ...}},
  "arcs_overrides": [
    {{"asset": "<asset_id>", "anchor": {{"chain": ["<object_name>", "<direction>", <distance>]}}, "offset": [x, y, z]}}
  ]
}}

RULES:
- "pattern" must be one of: {pattern_ids}
- "dimensions" are in metres. Use the pattern's defaults unless the user specifies otherwise.
- "slot_fills" maps slot IDs to asset IDs. Only fill slots mentioned in the user request.
  Omit slots the user doesn't reference — leave them empty.
- "arcs_overrides" is for custom placements: "put the stove next to the fridge".
  Use it sparingly — prefer slot_fills.
- Every asset_id must be from: {asset_ids}
- Think about SEMANTIC FIT: fridge→north_counter (against wall), table→center_table,
  chair→chair_* slots, stove→cook_counter or counter.

Existing scene context (for reference only — do not recreate entities):
{context}

User request: {prompt}

Output JSON now (no prose, no markdown fences, just the JSON object):
"""

    def _parse_response(self, text: str) -> Dict:
        if not text or not text.strip():
            raise ValueError("Empty LLM response")

        # Remove thinking tags
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

        # Remove markdown fences
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```\s*$", "", text)

        start = text.find("{")
        if start == -1:
            raise ValueError(f"No JSON found in response:\n{text[:200]}")

        decoder = json.JSONDecoder()
        try:
            data, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in LLM response: {e}\n{text[:200]}")

        return {
            "pattern": data.get("pattern", "rectangle_room"),
            "dimensions": data.get("dimensions", {}),
            "slot_fills": data.get("slot_fills", {}),
            "arcs_overrides": data.get("arcs_overrides", []),
        }
