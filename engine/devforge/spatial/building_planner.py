"""Building Planner — LLM-powered multi-room building generation.

Mirrors LayoutPlanner: builds a prompt, calls the LLM with a GBNF grammar,
parses the response into a building JSON (split tree + footprint).

The LLM outputs semantic intent only: which rooms, how they split the
footprint, which furniture patterns and assets per room. The BSPPartitioner
resolves everything into absolute transforms via the spatial compiler.

See SPATIAL-STAGE-3-5-PLAN.md §2.1, §2.4 for the full design.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, Optional

from devforge.infrastructure.logger import logger
from devforge.spatial.compiler import SpatialCompiler
from devforge.spatial.lexicon import AssetLexicon


class BuildingPlanningError(Exception):
    """LLM building planning failed — retryable."""


class BuildingPlanner:
    """Generates building JSON (split tree + footprint) from natural language.

    Usage::

        planner = BuildingPlanner(lexicon, compiler)
        building_json = planner.plan(
            context=context,
            prompt="build a small house",
            llm_fn=llm.generate,
        )
        # building_json → BSPPartitioner.compile_building()
    """

    DEFAULT_GRAMMAR_PATH = Path(__file__).resolve().parent / "prompts" / "building_planner.gbnf"

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
        """Generate a building JSON from a natural language prompt.

        Args:
            context: Existing scene/architecture context.
            prompt: User's natural language spec (e.g. "build a small house").
            llm_fn: Callable that takes a prompt string and returns LLM output.
            scene: Current scene tree (unused, for API compatibility).

        Returns:
            Building JSON dict with ``building``, ``footprint``, ``tree``.

        Raises:
            BuildingPlanningError: On LLM failure or unparseable output.
        """
        llm_prompt = self._build_prompt(context, prompt)

        logger.info(
            "building_planner",
            "Calling LLM for building plan",
            prompt_preview=prompt[:100],
            grammar=self._grammar_text is not None,
        )

        try:
            response = llm_fn(llm_prompt)
            result = self._parse_response(response)

            room_count = self._count_rooms(result.get("tree", {}))
            logger.info(
                "building_planner",
                "Building plan parsed",
                building=result.get("building"),
                rooms=room_count,
            )

            return result

        except Exception as exc:
            logger.error("building_planner", f"LLM planning failed: {exc}")
            raise BuildingPlanningError(str(exc)) from exc

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
                    "building_planner",
                    f"Loaded grammar from {self._grammar_path}",
                )
            else:
                logger.warn(
                    "building_planner",
                    f"Grammar not found: {self._grammar_path}",
                )
        except Exception as exc:
            logger.error("building_planner", f"Failed to load grammar: {exc}")

    def _build_prompt(self, context: str, prompt: str) -> str:
        """Build the building planner prompt with asset/pattern catalog."""
        asset_summary = self._lexicon.summary_for_prompt()
        pattern_summary = self._compiler.pattern_summary_for_prompt()
        pattern_ids = ", ".join(self._compiler.pattern_ids)
        asset_ids = ", ".join(self._lexicon.asset_ids)

        return f"""You are a building layout planner for a Godot 4 game level editor.
Design a multi-room building by generating a split tree that partitions a
rectangular footprint into rooms.

AVAILABLE ROOM PATTERNS (assign one per room):
{pattern_summary}

ASSET CATALOG (assign to room slots by id):
{asset_summary}

OUTPUT SCHEMA — a JSON object with a recursive split tree:
{{
  "building": "<name of the building>",
  "footprint": {{"width": <number>, "depth": <number>}},
  "tree": <split-or-leaf>
}}

A node is a **split** if it has "axis", "ratio", "left", and "right":
{{
  "axis": "x" or "z",
  "ratio": 0.1–0.9,
  "left": <split-or-leaf>,
  "right": <split-or-leaf>
}}

A node is a **leaf** (a finished room) if it has "room", "pattern", and "slot_fills":
{{
  "room": "<room name>",
  "pattern": "<pattern id>",
  "slot_fills": {{"<slot id>": "<asset id>", ...}}
}}

RULES:
- The tree can have at most 4 levels of splits (max 16 rooms).
- "axis" must be "x" or "z". "x" splits left/right, "z" splits front/back.
- "ratio" must be between 0.1 and 0.9.
- "pattern" must be one of: {pattern_ids}
- Every asset in slot_fills must be from: {asset_ids}
- Room names should be descriptive: "kitchen", "living_room", "bedroom", etc.
- Split the footprint to match the room count — 3 rooms needs 2 splits (e.g. x-split
  then one side gets a z-split).
- Assign furniture to rooms by semantic fit: kitchen gets stove/fridge/counter,
  living room gets table/chair/shelf, bedroom gets table or cabinet, etc.

Existing scene context (for reference only — do not recreate entities):
{context}

User request: {prompt}

Output JSON now (no prose, no markdown fences, just the JSON object):
"""

    def _parse_response(self, text: str) -> Dict:
        """Parse LLM output into a building JSON dict."""
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
            "building": data.get("building", "Building"),
            "footprint": data.get("footprint", {"width": 12.0, "depth": 8.0}),
            "tree": data.get("tree", {}),
        }

    @staticmethod
    def _count_rooms(node: dict) -> int:
        """Count leaf rooms in a split tree."""
        if not isinstance(node, dict) or not node:
            return 0
        if "room" in node:
            return 1
        return BuildingPlanner._count_rooms(node.get("left", {})) + BuildingPlanner._count_rooms(node.get("right", {}))
