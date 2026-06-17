"""SSP Planner — LLM-powered semantic room generation.

Mirrors BuildingPlanner: builds a prompt with archetype catalog, calls
the LLM with a GBNF grammar, parses the response into a room JSON.

The LLM only picks an archetype + optional overrides. The SSPEngine
fills in sensible defaults (pattern, dimensions, slot_fills) per
room type.

See SPATIAL-STAGE-3-5-PLAN.md §4 for the full design.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, Optional

from devforge.infrastructure.logger import logger
from devforge.spatial.lexicon import AssetLexicon
from devforge.spatial.ssp import SSPEngine


class SSPPlanningError(Exception):
    """LLM SSP planning failed — retryable."""


class SSPPlanner:
    """Generates room JSON (archetype + overrides) from natural language.

    Usage::

        planner = SSPPlanner(lexicon, ssp_engine)
        room_json = planner.plan(
            context=context,
            prompt="build a kitchen with an extra counter",
            llm_fn=llm.generate,
        )
        # room_json → SSPEngine.compile_room()
    """

    DEFAULT_GRAMMAR_PATH = Path(__file__).resolve().parent / "prompts" / "ssp_planner.gbnf"

    def __init__(
        self,
        lexicon: AssetLexicon | None = None,
        ssp_engine: SSPEngine | None = None,
        grammar_path: str | Path | None = None,
    ):
        self._lexicon = lexicon or AssetLexicon()
        self._ssp_engine = ssp_engine or SSPEngine(compiler=None)
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
        """Generate a room JSON from a natural language prompt.

        Args:
            context: Existing scene/architecture context.
            prompt: User's natural language spec (e.g. "build a kitchen").
            llm_fn: Callable that takes a prompt string and returns LLM output.
            scene: Current scene tree (unused, for API compatibility).

        Returns:
            Room JSON dict with ``archetype`` + optional overrides.

        Raises:
            SSPPlanningError: On LLM failure or unparseable output.
        """
        llm_prompt = self._build_prompt(context, prompt)

        logger.info(
            "ssp_planner",
            "Calling LLM for SSP room plan",
            prompt_preview=prompt[:100],
            grammar=self._grammar_text is not None,
        )

        try:
            response = llm_fn(llm_prompt)
            result = self._parse_response(response)

            archetype = result.get("archetype", "kitchen")
            overrides = len(result.get("slot_overrides", {}))
            logger.info(
                "ssp_planner",
                "SSP plan parsed",
                archetype=archetype,
                slot_overrides=overrides,
            )

            return result

        except Exception as exc:
            logger.error("ssp_planner", f"LLM planning failed: {exc}")
            raise SSPPlanningError(str(exc)) from exc

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
                    "ssp_planner",
                    f"Loaded grammar from {self._grammar_path}",
                )
            else:
                logger.warn(
                    "ssp_planner",
                    f"Grammar not found: {self._grammar_path}",
                )
        except Exception as exc:
            logger.error("ssp_planner", f"Failed to load grammar: {exc}")

    def _build_prompt(self, context: str, prompt: str) -> str:
        """Build the SSP planner prompt with archetype catalog."""
        archetype_summary = self._ssp_engine.archetype_summary_for_prompt()
        archetype_ids = ", ".join(self._ssp_engine.archetype_ids)
        # Filter to indoor/furniture assets only (not outdoor plants/rocks)
        indoor_assets = [
            aid
            for aid in self._lexicon.asset_ids
            if not any(
                tag in c
                for c in self._lexicon.get(aid).get("category", [])
                for tag in ("scatter", "outdoor", "plant", "rock")
            )
        ]
        asset_ids = ", ".join(indoor_assets) if indoor_assets else ", ".join(self._lexicon.asset_ids)

        return f"""You are a room layout planner for a Godot 4 game level editor.
Choose a room archetype that best matches the user's request. Optionally
override specific slots, dimensions, or use ARCS for custom placements.

AVAILABLE ROOM ARCHETYPES (choose one):
{archetype_summary}

ASSET CATALOG (assign to slots by id):
{asset_ids}

OUTPUT SCHEMA — a JSON object:
{{
  "archetype": "<archetype_id>",
  "dimensions": {{"width": <number>, "height": <number>, "depth": <number>}},
  "slot_overrides": {{"<slot_id>": "<asset_id>", ...}},
  "arcs_overrides": [
    {{"asset": "<asset_id>", "anchor": "...", "offset": [x, y, z]}}
  ],
  "pattern": "<pattern_id>"
}}

RULES:
- "archetype" must be one of: {archetype_ids}
- "dimensions" is optional — the archetype has sensible defaults.
  Only override if the user specifies a different size.
- "slot_overrides" is optional — the archetype has default furniture.
  Only list slots you want to CHANGE from the default.
- Every asset_id must be from: {asset_ids}
- "arcs_overrides" is optional — for custom placements.
- "pattern" is optional — defaults to the archetype's pattern.
  Valid patterns: rectangle_room, l_shape_room, corridor.
- Think about SEMANTIC FIT: kitchen → stove/fridge/counter,
  living room → table/chairs/shelf, bedroom → table/cabinet,
  bathroom → sink/cabinet.

Existing scene context (for reference only — do not recreate entities):
{context}

User request: {prompt}

Output JSON now (no prose, no markdown fences, just the JSON object):
"""

    def _parse_response(self, text: str) -> Dict:
        """Parse LLM output into a room JSON dict."""
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
            "archetype": data.get("archetype", "kitchen"),
            "dimensions": data.get("dimensions", {}),
            "slot_overrides": data.get("slot_overrides", {}),
            "arcs_overrides": data.get("arcs_overrides", []),
            "pattern": data.get("pattern"),
        }
