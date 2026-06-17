"""Voronoi Planner — LLM-powered district/town generation.

Mirrors the established planner pattern: builds a prompt with district
type catalog, calls the LLM with a GBNF grammar, parses the response
into a town JSON.

The LLM specifies region size and district count.  The VoronoiEngine
computes Voronoi cells, roads, and buildings deterministically.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, Optional

from devforge.infrastructure.logger import logger


class VoronoiPlanningError(Exception):
    """LLM Voronoi planning failed — retryable."""


class VoronoiPlanner:
    """Generates town JSON (region + district count) from natural language.

    Usage::

        planner = VoronoiPlanner()
        town_json = planner.plan(
            context=context,
            prompt="generate a town",
            llm_fn=llm.generate,
        )
        # town_json → VoronoiEngine.compile_town()
    """

    DEFAULT_GRAMMAR_PATH = Path(__file__).resolve().parent / "prompts" / "voronoi_planner.gbnf"

    def __init__(
        self,
        grammar_path: str | Path | None = None,
    ):
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
        """Generate a town JSON from a natural language prompt.

        Args:
            context: Existing scene/architecture context.
            prompt: User's natural language spec (e.g. "build a town").
            llm_fn: Callable that takes a prompt string and returns LLM output.
            scene: Current scene tree (unused, for API compatibility).

        Returns:
            Town JSON dict with ``region``, ``districts``, optional ``tile_size``, ``seed``.

        Raises:
            VoronoiPlanningError: On LLM failure or unparseable output.
        """
        llm_prompt = self._build_prompt(context, prompt)

        logger.info(
            "voronoi_planner",
            "Calling LLM for Voronoi town plan",
            prompt_preview=prompt[:100],
            grammar=self._grammar_text is not None,
        )

        try:
            response = llm_fn(llm_prompt)
            result = self._parse_response(response)

            region = result.get("region", {})
            logger.info(
                "voronoi_planner",
                "Voronoi plan parsed",
                width=region.get("width"),
                depth=region.get("depth"),
                districts=result.get("districts"),
            )

            return result

        except Exception as exc:
            logger.error("voronoi_planner", f"LLM planning failed: {exc}")
            raise VoronoiPlanningError(str(exc)) from exc

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
                logger.info(
                    "voronoi_planner",
                    f"Loaded grammar from {self._grammar_path}",
                )
            else:
                logger.warn(
                    "voronoi_planner",
                    f"Grammar not found: {self._grammar_path}",
                )
        except Exception as exc:
            logger.error("voronoi_planner", f"Failed to load grammar: {exc}")

    def _build_prompt(self, context: str, prompt: str) -> str:
        """Build the Voronoi planner prompt with district type catalogue."""
        return f"""You are a town layout planner for a Godot 4 game level editor.
Decide the region size and number of districts for a Voronoi-based town generator.

DISTRICT TYPES (auto-assigned by the Voronoi engine):
  residential  — houses, apartments (4-8 buildings per district)
  commercial   — shops, offices (2-5 buildings per district)
  industrial   — factories, warehouses (1-3 buildings per district)
  park         — green spaces (1-3 small structures)
  civic        — town hall, library, plaza (1-2 large buildings)

The ENGINE handles:
  - Voronoi tessellation (district boundaries)
  - Road generation (boundaries between districts)
  - Building placement (within each district)
  - District type assignment (weighted random, centre = civic)

OUTPUT SCHEMA — a JSON object:
{{
  "region": {{"width": <integer>, "depth": <integer>}},
  "districts": <integer>,
  "tile_size": <number>,
  "seed": <integer>
}}

RULES:
- "region" is the total town area in metres. Typical: 60×60 to 120×120.
  Larger region = more spread out. Use 80×80 for a medium town.
- "districts" is the number of Voronoi cells. Typical: 4-10.
  - 4-5: small village
  - 6-8: medium town
  - 9-12: large town / small city
  Match the region size: bigger region → more districts.
- "tile_size" is Voronoi cell resolution in metres. Default 4.0.
  Use 2.0-4.0 for fine roads, 4.0-8.0 for large blocks.
- "seed" is optional — deterministic generation. Omit for random.
- Think about the kind of settlement the user wants:
  - "village" → 60×60, 4 districts
  - "town" → 80×80, 6 districts
  - "city" → 100×100, 10 districts
  - "industrial park" → 100×80, 5 districts

Existing scene context (for reference only):
{context}

User request: {prompt}

Output JSON now (no prose, no markdown fences, just the JSON object):
"""

    def _parse_response(self, text: str) -> Dict:
        """Parse LLM output into a town JSON dict."""
        if not text or not text.strip():
            raise ValueError("Empty LLM response")

        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
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
            "region": data.get("region", {"width": 80, "depth": 80}),
            "districts": data.get("districts", 5),
            "tile_size": data.get("tile_size", 4.0),
            "seed": data.get("seed"),
        }
