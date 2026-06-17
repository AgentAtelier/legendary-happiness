"""Scatter Planner — LLM-powered outdoor scatter generation.

Mirrors BuildingPlanner: builds a prompt, calls the LLM with a GBNF grammar,
parses the response into a garden JSON (region + keep_out + species list).

The LLM is a topologist — it never outputs a Vector3. It emits semantic
intent only: which plants, how many, how densely spaced, and where NOT to
place them (keep-out zones around buildings). The ScatterEngine resolves
everything into absolute transforms via Poisson-disk sampling.

See SPATIAL-STAGE-3-5-PLAN.md §3 for the full design.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from devforge.infrastructure.logger import logger
from devforge.spatial.lexicon import AssetLexicon


class ScatterPlanningError(Exception):
    """LLM scatter planning failed — retryable."""


class ScatterPlanner:
    """Generates garden JSON (region + species) from natural language.

    Usage::

        planner = ScatterPlanner(lexicon)
        garden_json = planner.plan(
            context=context,
            prompt="scatter trees and bushes around the house",
            llm_fn=llm.generate,
        )
        # garden_json → ScatterEngine.compile_garden()
    """

    DEFAULT_GRAMMAR_PATH = (
        Path(__file__).resolve().parent / "prompts" / "scatter_planner.gbnf"
    )

    def __init__(
        self,
        lexicon: AssetLexicon | None = None,
        grammar_path: str | Path | None = None,
    ):
        self._lexicon = lexicon or AssetLexicon()
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
        """Generate a garden JSON from a natural language prompt.

        Args:
            context: Existing scene/architecture context.
            prompt: User's natural language spec (e.g. "scatter trees around").
            llm_fn: Callable that takes a prompt string and returns LLM output.
            scene: Current scene tree (unused, for API compatibility).

        Returns:
            Garden JSON dict with ``region``, ``keep_out``, ``species``.

        Raises:
            ScatterPlanningError: On LLM failure or unparseable output.
        """
        llm_prompt = self._build_prompt(context, prompt)

        logger.info(
            "scatter_planner",
            "Calling LLM for scatter plan",
            prompt_preview=prompt[:100],
            grammar=self._grammar_text is not None,
        )

        try:
            response = llm_fn(llm_prompt)
            result = self._parse_response(response)

            total = sum(int(s.get("count", 0)) for s in result.get("species", []))
            logger.info(
                "scatter_planner",
                "Scatter plan parsed",
                species=len(result.get("species", [])),
                total_items=total,
            )

            return result

        except Exception as exc:
            logger.error("scatter_planner", f"LLM planning failed: {exc}")
            raise ScatterPlanningError(str(exc)) from exc

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
                    "scatter_planner",
                    f"Loaded grammar from {self._grammar_path}",
                )
            else:
                logger.warn(
                    "scatter_planner",
                    f"Grammar not found: {self._grammar_path}",
                )
        except Exception as exc:
            logger.error("scatter_planner", f"Failed to load grammar: {exc}")

    def _build_prompt(self, context: str, prompt: str) -> str:
        """Build the scatter planner prompt with plant asset catalog."""
        # Filter to outdoor/scatter assets only
        scatter_assets = [
            aid for aid in self._lexicon.asset_ids
            if any("scatter" in c or "outdoor" in c or "plant" in c
                   for c in self._lexicon.get(aid).get("category", []))
        ]
        asset_ids = ", ".join(scatter_assets) if scatter_assets else "tree, bush, flower, rock"

        asset_lines: list[str] = []
        for aid in (scatter_assets or ["tree", "bush", "flower", "rock"]):
            asset = self._lexicon.get(aid)
            if asset:
                fp = asset.get("footprint", {})
                h = asset.get("height", 1.0)
                asset_lines.append(
                    f"  {aid}: {asset.get('label', aid)} "
                    f"(footprint {fp.get('width',1)}×{fp.get('depth',1)}m, "
                    f"height {h}m)"
                )
        asset_summary = "\n".join(asset_lines) if asset_lines else "  (no plant assets)"

        return f"""You are an outdoor scatter planner for a Godot 4 game level editor.
Decide what plants/rocks to scatter in a garden region and how densely.

AVAILABLE PLANTS (assign by id):
{asset_summary}

OUTPUT SCHEMA — a JSON object:
{{
  "region": {{"width": <number>, "depth": <number>}},
  "keep_out": [
    {{"x": <number>, "z": <number>, "w": <number>, "d": <number>}}
  ],
  "species": [
    {{"id": "<asset_id>", "count": <integer>, "min_spacing": <number>}}
  ]
}}

RULES:
- "region" is the total garden area in metres. Default to 20×20.
- "keep_out" lists rectangles where nothing should be placed (e.g. building
  footprints, paths). Use the existing scene context to determine where
  buildings are.
- "species" lists what to place. Each entry has:
  - "id": one of: {asset_ids}
  - "count": how many to place (1-50, keep it reasonable)
  - "min_spacing": minimum distance between same-species in metres
    (trees: 3-5, bushes: 2-3, flowers: 1-2, rocks: 1-3)
- Think about natural clustering: groups of bushes near trees, flowers in
  clusters near the edges, rocks scattered randomly.
- Keep items away from building footprints — add keep_out zones around
  any buildings in the scene context.
- Total items should feel like a real garden, not a dense forest.

Existing scene context (for reference — use building positions to create
keep_out zones):
{context}

User request: {prompt}

Output JSON now (no prose, no markdown fences, just the JSON object):
"""

    def _parse_response(self, text: str) -> Dict:
        """Parse LLM output into a garden JSON dict."""
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
            raise ValueError(
                f"Invalid JSON in LLM response: {e}\n{text[:200]}"
            )

        return {
            "region": data.get("region", {"width": 20.0, "depth": 20.0}),
            "keep_out": data.get("keep_out", []),
            "species": data.get("species", []),
        }
