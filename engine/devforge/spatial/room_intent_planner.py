"""Room Intent Planner — LLM authors a rich Intent Descriptor.

Replaces the SSP archetype-label model: instead of the LLM picking
"kitchen" from a catalog, it authors a structured creative brief
(type + size + style + clutter + mood + must-have props + features + seed)
that the SSPEngine resolves into a parameterized, seeded room.

See STAGE-4-REBALANCE-PLAN.md §Move 2 for the full design.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from devforge.infrastructure.logger import logger
from devforge.spatial.lexicon import AssetLexicon
from devforge.spatial.ssp import SSPEngine


class RoomPlanningError(Exception):
    """LLM room intent planning failed — retryable."""


class RoomIntentPlanner:
    """Generates a rich Intent Descriptor from natural language.

    Usage::

        planner = RoomIntentPlanner(lexicon, ssp_engine)
        intent = planner.plan(
            context=context,
            prompt="build a cramped abandoned kitchen with a poison cabinet",
            llm_fn=llm.generate,
        )
        # intent → SSPEngine.compile_room() resolves the descriptor
    """

    DEFAULT_GRAMMAR_PATH = (
        Path(__file__).resolve().parent / "prompts" / "room_intent.gbnf"
    )

    # ── Room type lexicon (for the prompt) ─────────────────────
    ROOM_TYPES = [
        "kitchen", "living_room", "bedroom", "bathroom", "study",
        "hallway", "dining_room", "office", "library", "workshop",
        "cellar", "attic", "porch", "pantry",
    ]

    # Distinctive features the LLM can request (engine handles known ones)
    KNOWN_FEATURES = [
        "secret_passage", "hidden_door", "elevated_platform",
        "sunken_floor", "skylight", "loft", "fireplace",
        "bay_window", "walk_in_closet", "dumbwaiter",
    ]

    # Mood tags the engine interprets
    KNOWN_MOODS = [
        "abandoned", "cozy", "grand", "sterile", "cramped_feel",
        "airy", "dark", "bright", "cluttered_feel", "minimal",
        "ancient", "pristine", "haunted", "lived_in",
    ]

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
        skip_cache: bool = False,  # forward-compat with cache threading
    ) -> Dict:
        """Generate a Room Intent Descriptor from a natural language prompt.

        Args:
            context: Existing scene/architecture context.
            prompt: User's natural language spec (e.g. "build a cramped
                abandoned kitchen with a poison cabinet").
            llm_fn: Callable that takes a prompt string and returns LLM output.
            scene: Current scene tree (unused, for API compatibility).
            skip_cache: Forward-compatible cache bypass (unused here since
                room planner has no internal cache; accepted for API
                compatibility with _run_spatial_path).

        Returns:
            Intent Descriptor dict with room_type, size, style, clutter,
            mood_tags, must_have, special_features, seed.

        Raises:
            RoomPlanningError: On LLM failure or unparseable output.
        """
        llm_prompt = self._build_prompt(context, prompt)

        logger.info(
            "room_intent_planner",
            "Calling LLM for Room Intent Descriptor",
            prompt_preview=prompt[:100],
            grammar=self._grammar_text is not None,
        )

        try:
            response = llm_fn(llm_prompt)
            result = self._parse_response(response)

            logger.info(
                "room_intent_planner",
                "Intent Descriptor parsed",
                room_type=result.get("room_type", "?"),
                size=result.get("size", "normal"),
                style=result.get("style", "?"),
                mood_tags=result.get("mood_tags", []),
            )

            return result

        except Exception as exc:
            logger.error("room_intent_planner", f"LLM planning failed: {exc}")
            raise RoomPlanningError(str(exc)) from exc

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
                    "room_intent_planner",
                    f"Loaded grammar from {self._grammar_path}",
                )
            else:
                logger.warn(
                    "room_intent_planner",
                    f"Grammar not found: {self._grammar_path}",
                )
        except Exception as exc:
            logger.error("room_intent_planner", f"Failed to load grammar: {exc}")

    def _build_prompt(self, context: str, prompt: str) -> str:
        """Build the Room Intent Descriptor prompt."""
        room_types = ", ".join(self.ROOM_TYPES)
        known_features = ", ".join(self.KNOWN_FEATURES)
        known_moods = ", ".join(self.KNOWN_MOODS)

        # Indoor assets only (no outdoor scatter objects)
        indoor_assets = [
            aid for aid in self._lexicon.asset_ids
            if not any(tag in c for c in self._lexicon.get(aid).get("category", [])
                       for tag in ("scatter", "outdoor", "plant", "rock"))
        ]
        asset_list = ", ".join(indoor_assets) if indoor_assets else ", ".join(self._lexicon.asset_ids)

        return f"""You are a room designer for a Godot 4 game level editor.
Read the user's request and author a creative Intent Descriptor — a
structured brief the build engine will resolve into a fully-furnished room.

AUTHOR WITH INTENT: «cramped abandoned kitchen» → size=cramped,
mood_tags=["abandoned"]. «spacious noble dining room» → size=spacious,
style=noble. The engine reads EVERY field you set — each one changes
the build. Don't just pick a label; describe the room.

OUTPUT — a single JSON object with these fields:

{{
  "room_type": "<one of the room types below>",
  "size": "cramped|normal|spacious",
  "style": "rustic|industrial|noble|derelict",
  "clutter": <0.0–1.0, how many extra props>,
  "mood_tags": ["<tag>", ...],
  "must_have": ["<asset_id>", ...],
  "special_features": ["<feature>", ...],
  "seed": <integer or omit for random>
}}

ROOM TYPES (pick one): {room_types}

SIZES:
  cramped  → small, tight (~3×3m footprint)
  normal   → medium (~5×4m)
  spacious → large (~8×6m)

STYLES (affect greybox colour palette + prop variants):
  rustic    → warm browns, wood tones
  industrial→ greys, metal tones
  noble     → rich colours, ornate feel
  derelict  → desaturated, worn

CLUTTER (0.0–1.0):
  0.0 → essentials only (minimal props)
  0.5 → moderate decoration
  1.0 → densely furnished (items biased to walls/corners)

MOOD TAGS (zero or more): {known_moods}
  Each tag modifies the greybox — abandoned=darker/desaturated,
  cozy=warmer/centered, grand=taller ceiling feel, etc.
  You may also use other mood tags; unknown ones are logged and
  degraded gracefully.

MUST-HAVE ASSETS (zero or more asset IDs from this catalog): {asset_list}
  These are GUARANTEED to appear; the engine forces them in.

SPECIAL FEATURES (zero or more): {known_features}
  Known features get built; unknown ones are logged and skipped.

SEED: optional integer for reproducible variation. Omit for random.

RULES:
- "room_type" is REQUIRED; all other fields are optional.
- Every field you DO set changes the build — be intentional.
- "must_have" assets must be from the catalog above.
- Think about semantic fit: kitchen→stove/fridge, bedroom→cabinet,
  library→shelves, workshop→counter, etc.
- Output JSON only — no prose, no markdown fences.

Existing scene context (for reference only):
{context}

User request: {prompt}

Output Intent Descriptor now:
"""

    def _parse_response(self, text: str) -> Dict:
        """Parse LLM output into an Intent Descriptor dict."""
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

        # Build the descriptor with defaults for missing fields
        descriptor: Dict = {
            "room_type": data.get("room_type", "kitchen"),
        }

        # Enumerated fields — validate against known values
        size = data.get("size")
        if size in ("cramped", "normal", "spacious"):
            descriptor["size"] = size
        elif size is not None:
            logger.warn("room_intent_planner", f"Unknown size '{size}', defaulting to normal")

        style = data.get("style")
        if style in ("rustic", "industrial", "noble", "derelict"):
            descriptor["style"] = style
        elif style is not None:
            logger.warn("room_intent_planner", f"Unknown style '{style}', skipping")

        # Numeric field with clamping
        clutter = data.get("clutter")
        if isinstance(clutter, (int, float)):
            descriptor["clutter"] = max(0.0, min(1.0, float(clutter)))

        # Array fields
        mood_tags = data.get("mood_tags")
        if isinstance(mood_tags, list):
            descriptor["mood_tags"] = [
                str(t) for t in mood_tags if isinstance(t, str)
            ]

        must_have = data.get("must_have")
        if isinstance(must_have, list):
            valid_assets = [
                str(a) for a in must_have
                if isinstance(a, str) and a in self._lexicon.asset_ids
            ]
            if len(valid_assets) != len(must_have):
                invalid = [a for a in must_have if isinstance(a, str) and a not in self._lexicon.asset_ids]
                logger.warn("room_intent_planner", f"Unknown must_have assets dropped: {invalid}")
            if valid_assets:
                descriptor["must_have"] = valid_assets

        special_features = data.get("special_features")
        if isinstance(special_features, list):
            descriptor["special_features"] = [
                str(f) for f in special_features if isinstance(f, str)
            ]

        # Seed (integer or omit)
        seed = data.get("seed")
        if isinstance(seed, int):
            descriptor["seed"] = seed

        return descriptor
