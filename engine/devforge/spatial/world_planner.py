"""World Planner — LLM-powered multi-engine world orchestration.

Phase C of Guide 2: routes a natural-language prompt into a sequence
of engine intents — each routing a sub-request to a specific spatial
engine (scatter, voronoi, wfc, building, ssp, room, network) with
positional bounds and keep-out zones.

The LLM emits a world_intents JSON array. Each intent carries an
engine type, a region_id, optional bounds/keep_out/inside anchors,
and an opaque ``spec`` blob validated by the target engine's own
GBNF grammar.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

from devforge.infrastructure.logger import logger


class WorldPlanningError(Exception):
    """LLM world planning failed — retryable."""


class WorldPlanner:
    """Generates a list of engine intents from a natural-language prompt.

    Usage::

        planner = WorldPlanner()
        world_json = planner.plan(
            context=context,
            prompt="Generate a medieval village in a forest clearing",
            llm_fn=llm.generate,
        )
        # world_json["world_intents"] → [{engine, region_id, bounds, spec}, …]
    """

    DEFAULT_GRAMMAR_PATH = Path(__file__).resolve().parent / "prompts" / "world_planner.gbnf"

    # Available engines the LLM can route to
    AVAILABLE_ENGINES = [
        "scatter",
        "voronoi",
        "wfc",
        "building",
        "ssp",
        "room",
        "network",
    ]

    def __init__(self, grammar_path: str | Path | None = None):
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
        """Generate a world_intents JSON from a natural language prompt.

        Args:
            context: Existing scene/architecture/world context.
            prompt: User's natural language spec
                (e.g. "Generate a village in a forest clearing").
            llm_fn: Callable that takes a prompt string and returns LLM output.
            scene: Current scene tree (unused, for API compatibility).
            skip_cache: Forward-compatible cache bypass.

        Returns:
            Dict with ``world_intents`` — a list of intent dicts, each
            with engine, region_id, bounds, and optional spec/keep_out/etc.

        Raises:
            WorldPlanningError: On LLM failure or unparseable output.
        """
        llm_prompt = self._build_prompt(context, prompt)

        logger.info(
            "world_planner",
            "Calling LLM for world orchestration plan",
            prompt_preview=prompt[:100],
            grammar=self._grammar_text is not None,
        )

        try:
            response = llm_fn(llm_prompt)
            result = self._parse_response(response)

            intents = result.get("world_intents", [])
            logger.info(
                "world_planner",
                f"World plan parsed: {len(intents)} intent(s)",
                engines=[i.get("engine", "?") for i in intents],
            )

            return result

        except Exception as exc:
            logger.error("world_planner", f"LLM planning failed: {exc}")
            raise WorldPlanningError(str(exc)) from exc

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
                logger.info("world_planner", f"Loaded grammar from {self._grammar_path}")
            else:
                logger.warn("world_planner", f"Grammar not found: {self._grammar_path}")
        except Exception as exc:
            logger.error("world_planner", f"Failed to load grammar: {exc}")

    def _build_prompt(self, context: str, prompt: str) -> str:
        """Build the world planner prompt with engine catalog."""
        engine_list = ", ".join(self.AVAILABLE_ENGINES)

        return f"""You are a world orchestration planner for a Godot 4 game level editor.
Read the user's request and decompose it into a sequence of engine intents.
Each intent routes a sub-task to a specific spatial generation engine.

AVAILABLE ENGINES:
  scatter  — Outdoor plant/rock placement (Poisson-disk). Needs: region, species.
  voronoi  — Town/district generation (Voronoi tessellation). Needs: region, districts.
  wfc      — Dungeon/cave generation (Wave Function Collapse). Needs: size, tile_size.
  building — Multi-room BSP buildings. Needs: footprint, rooms.
  ssp      — Semantic room generation (legacy archetypes). Needs: archetype, dimensions.
  room     — Intent Descriptor room generation (richer LLM brief). Needs: room_type, size, style.
  network  — Roads/paths between regions (A* pathfinding). Needs: connects, width.

OUTPUT — a single JSON object with a "world_intents" array:

{{
  "world_intents": [
    {{
      "engine": "<one of {engine_list}>",
      "region_id": "<descriptive name for this region>",
      "bounds": {{"x": <number>, "z": <number>, "w": <number>, "d": <number>}},
      "keep_out": [{{"x": <number>, "z": <number>, "w": <number>, "d": <number>}}],
      "inside": "<region_id of containing region>",
      "spec": {{ ... engine-specific JSON ... }},
      "connects": ["<region_id>", "<region_id>"],
      "width": <number|road width in metres>,
      "type": "<road type e.g. dirt_road>"
    }}
  ]
}}

RULES:
- "engine" is REQUIRED. Must be one of: {engine_list}
- "region_id" is REQUIRED. A short, descriptive name (e.g. "dark_forest", "village_1").
- "bounds" specify where in world space (x, z) this region lives. Units are metres.
  Place regions so they don't overlap unless one is "inside" another.
- "keep_out" defines exclusion zones within a region. E.g. clearing for a village
  inside a forest: scatter the forest with keep_out at the village's position.
- "inside" references another region_id — use when one region is contained within
  another (e.g. a village inside a forest).
- "spec" is a JSON object passed directly to the target engine. Include the
  engine-specific parameters: for scatter → species list, for voronoi → district
  count, for building → room list, for room → room_type/size/style, etc.
- "connects" defines road network connections (for network engine).
- "width" sets road/path width in metres.
- "type" for network: "dirt_road", "paved_road", "river".
- Think TOPOLOGICALLY: place regions in non-overlapping world-space, with
  appropriate keep-out zones for contained regions.
- Output JSON only — no prose, no markdown fences.

ENGINE-SPECIFIC SPEC EXAMPLES:

scatter: {{"species": [{{"id": "pine_tree", "count": 200, "min_spacing": 4.0}}]}}
voronoi: {{"districts": 5, "tile_size": 4.0}}
wfc: {{"size": {{"width": 10, "depth": 10}}, "tile_size": 2.0}}
building: {{"footprint": {{"width": 20, "depth": 16}}, "tree": <split-or-leaf>}}
room: {{"room_type": "kitchen", "size": "normal", "style": "rustic"}}
network: {{"width": 3.0}}

Existing world context:
{context}

User request: {prompt}

Output JSON now:
"""

    def _parse_response(self, text: str) -> Dict:
        """Parse LLM output into a world_intents dict."""
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

        intents = data.get("world_intents", [])

        # Validate each intent has required fields
        validated: List[Dict] = []
        for i, intent in enumerate(intents):
            if not isinstance(intent, dict):
                logger.warn("world_planner", f"Intent {i} is not a dict; skipping")
                continue
            engine = intent.get("engine")
            region_id = intent.get("region_id")
            if not engine or not region_id:
                logger.warn(
                    "world_planner",
                    f"Intent {i} missing required 'engine' or 'region_id'; skipping",
                )
                continue
            if engine not in self.AVAILABLE_ENGINES:
                logger.warn(
                    "world_planner",
                    f"Intent {i} has unknown engine '{engine}'; skipping",
                )
                continue
            validated.append(intent)

        return {"world_intents": validated}
