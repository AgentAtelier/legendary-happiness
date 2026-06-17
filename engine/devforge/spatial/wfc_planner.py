"""WFC Planner — LLM-powered dungeon/cave generation.

Mirrors BuildingPlanner: builds a prompt with tile catalog, calls
the LLM with a GBNF grammar, parses the response into a dungeon JSON.

The LLM specifies dungeon size and tile size only. The WFCEngine runs
Wave Function Collapse to produce the tile map deterministically.

See SPATIAL-STAGE-3-5-PLAN.md §5 for the full design.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, Optional

from devforge.infrastructure.logger import logger


class WFCPlanningError(Exception):
    """LLM WFC planning failed — retryable."""


class WFCPlanner:
    """Generates dungeon JSON (size + tile_size) from natural language.

    Usage::

        planner = WFCPlanner()
        dungeon_json = planner.plan(
            context=context,
            prompt="generate a dungeon",
            llm_fn=llm.generate,
        )
        # dungeon_json → WFCEngine.compile_dungeon()
    """

    DEFAULT_GRAMMAR_PATH = Path(__file__).resolve().parent / "prompts" / "wfc_planner.gbnf"

    def __init__(
        self,
        grammar_path: str | Path | None = None,
    ):
        self._grammar_path = str(grammar_path or self.DEFAULT_GRAMMAR_PATH)
        self._grammar_text: Optional[str] = None
        self._load_grammar()

    # ── public API ──────────────────────────────────────────

    # ── keyword → (width, depth, tile_size) heuristic ──────────
    _KEYWORD_DEFAULTS: Dict[str, tuple] = {
        "dungeon": (10, 10, 2.0),
        "cave": (8, 8, 2.5),
        "cavern": (8, 8, 2.5),
        "corridor": (12, 12, 1.5),
        "maze": (12, 12, 1.5),
        "tunnel": (10, 6, 2.0),
        "labyrinth": (12, 12, 1.5),
        "catacomb": (10, 10, 2.0),
        "mine": (8, 8, 2.0),
        "ruin": (8, 8, 2.5),
        "tomb": (8, 8, 2.0),
        "fortress": (10, 10, 2.0),
    }

    def _try_heuristic(self, prompt: str) -> Dict | None:
        """Return a default dungeon JSON from keyword matching, or None."""
        lower = prompt.lower()
        for keyword, (w, d, ts) in self._KEYWORD_DEFAULTS.items():
            if keyword in lower:
                logger.info(
                    "wfc_planner",
                    f"Keyword heuristic matched '{keyword}' → {w}×{d}, tile={ts}m — skipping LLM",
                )
                return {
                    "size": {"width": w, "depth": d},
                    "tile_size": ts,
                }
        return None

    def plan(
        self,
        *,
        context: str,
        prompt: str,
        llm_fn: Callable[[str], str],
        scene: Optional[Dict] = None,
        skip_cache: bool = False,
    ) -> Dict:
        """Generate a dungeon JSON from a natural language prompt.

        Uses a keyword heuristic for common dungeon types, falling back
        to the LLM only for unusual or ambiguous requests.

        Args:
            context: Existing scene/architecture context.
            prompt: User's natural language spec (e.g. "build a dungeon").
            llm_fn: Callable that takes a prompt string and returns LLM output.
            scene: Current scene tree (unused, for API compatibility).

        Returns:
            Dungeon JSON dict with ``size``, ``tile_size``, optional ``seed``.

        Raises:
            WFCPlanningError: On LLM failure or unparseable output.
        """
        # Try keyword heuristic first
        heuristic = self._try_heuristic(prompt)
        if heuristic is not None:
            return heuristic

        llm_prompt = self._build_prompt(context, prompt)

        logger.info(
            "wfc_planner",
            "Calling LLM for WFC dungeon plan",
            prompt_preview=prompt[:100],
            grammar=self._grammar_text is not None,
        )

        try:
            response = llm_fn(llm_prompt)
            result = self._parse_response(response)

            size = result.get("size", {})
            logger.info(
                "wfc_planner",
                "WFC plan parsed",
                width=size.get("width"),
                depth=size.get("depth"),
            )

            return result

        except Exception as exc:
            logger.error("wfc_planner", f"LLM planning failed: {exc}")
            raise WFCPlanningError(str(exc)) from exc

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
                    "wfc_planner",
                    f"Loaded grammar from {self._grammar_path}",
                )
            else:
                logger.warn(
                    "wfc_planner",
                    f"Grammar not found: {self._grammar_path}",
                )
        except Exception as exc:
            logger.error("wfc_planner", f"Failed to load grammar: {exc}")

    def _build_prompt(self, context: str, prompt: str) -> str:
        """Build the WFC planner prompt with tile catalog."""
        return f"""You are a dungeon layout planner for a Godot 4 game level editor.
Decide the dungeon grid size and tile size for a Wave Function Collapse generator.

TILE TYPES (auto-generated by the WFC engine):
  floor    — traversable interior space
  wall     — boundary / barrier
  corridor — connecting passages between rooms
  door     — transition between rooms and corridors
  empty    — void / ungenerated space

OUTPUT SCHEMA — a JSON object:
{{
  "size": {{"width": <integer>, "depth": <integer>}},
  "tile_size": <number>,
  "seed": <integer>
}}

RULES:
- "size" is the grid dimensions. Typical dungeons: 6×6 to 16×16.
  Larger = more elaborate dungeons. Keep it reasonable (8-12 per axis).
- "tile_size" is the size of each grid cell in metres. Default 2.0.
  Use 1.5-3.0 for rooms, 1.0-1.5 for tight corridors.
- "seed" is optional — deterministic generation. Omit for random.
- Think about the kind of dungeon the user wants:
  - "dungeon" → 10×10, tile_size=2.0
  - "caves" → 8×8, tile_size=2.5
  - "tight corridors" → 12×12, tile_size=1.5
  - "large halls" → 6×6, tile_size=3.0

Existing scene context (for reference only):
{context}

User request: {prompt}

Output JSON now (no prose, no markdown fences, just the JSON object):
"""

    def _parse_response(self, text: str) -> Dict:
        """Parse LLM output into a dungeon JSON dict."""
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
            "size": data.get("size", {"width": 8, "depth": 8}),
            "tile_size": data.get("tile_size", 2.0),
            "seed": data.get("seed"),
        }
