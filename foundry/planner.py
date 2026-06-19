"""AssetPlanner — turns a natural-language asset request into a
grammar-constrained, buildable asset-spec, then drives the foundry pipeline.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from compiler import PARAM_RANGES, compile_spec
from decisions import DecisionPoint
from material_resolver import resolve_material

log = logging.getLogger(__name__)

_GRAMMAR_PATH = str(Path(__file__).resolve().parent / "grammar" / "asset_spec.gbnf")

# ── Load grammar once at module level ────────────────────────────

from llm import load_grammar as _load_grammar

_GRAMMAR = _load_grammar(_GRAMMAR_PATH)

# ── Prompt template ──────────────────────────────────────────────

_ASSET_PLANNER_PROMPT = """You are an asset planner for a 3D game. Convert the user's natural-language description into an asset specification JSON. Output ONLY the JSON — no prose, no explanation.

Choose the generator that best matches the request:
- "table" — a table (flat top + four legs). Request about tables, desks, coffee tables, dining tables → use "table".
- "chair" — a chair (seat box + four legs + backrest). Request about chairs, stools, seats → use "chair".
- "shelf" — a shelf unit (two side panels + N horizontal boards). Request about shelves, bookshelves, wall shelves → use "shelf".
- "cabinet" — a storage cabinet (closed box on a short plinth). Request about cabinets, cupboards, storage units → use "cabinet".

Set asset_id to the same value as generator.

Table params (generator="table"):
{{
  "top_width": <number: width of tabletop (X)>,
  "top_depth": <number: depth of tabletop (Z)>,
  "top_thickness": <number: thickness of the tabletop board>,
  "leg_height": <number: height from floor to underside of top>,
  "leg_radius": <number: radius of each cylindrical leg>,
  "leg_inset": <number: how far in from edges the legs sit>
}}

Chair params (generator="chair"):
{{
  "seat_width": <number: width of the seat (X)>,
  "seat_depth": <number: depth of the seat (Z)>,
  "seat_thickness": <number: thickness of the seat board>,
  "leg_height": <number: height from floor to underside of seat>,
  "leg_radius": <number: radius of each leg>,
  "leg_inset": <number: how far in from edges the legs sit>,
  "back_height": <number: height of the backrest above the seat>
}}

Shelf params (generator="shelf"):
{{
  "width": <number: overall width of the shelf unit (X)>,
  "depth": <number: depth of the shelf unit (Z)>,
  "height": <number: overall height from floor to top (Y)>,
  "board_thickness": <number: thickness of each horizontal shelf board>,
  "n_shelves": <number: how many horizontal shelf boards>,
  "side_thickness": <number: thickness of the two side panels>
}}

Cabinet params (generator="cabinet"):
{{
  "width": <number: overall width of the cabinet (X)>,
  "depth": <number: depth of the cabinet (Z)>,
  "height": <number: overall height from floor to top (Y)>,
  "panel_thickness": <number: wall thickness of the cabinet body>,
  "base_height": <number: height of the bottom plinth>
}}

All param values are positive floats (decimals).

Table defaults: top_width ~1.2-1.5, top_depth ~0.6-1.0, top_thickness ~0.05-0.08, leg_height ~0.5-0.7, leg_radius ~0.04-0.06, leg_inset ~0.05-0.15.
Chair defaults: seat_width ~0.45-0.5, seat_depth ~0.45-0.5, seat_thickness ~0.05-0.06, leg_height ~0.4-0.5, leg_radius ~0.03-0.04, leg_inset ~0.03-0.05, back_height ~0.3-0.4.
Shelf defaults: width ~0.8-1.0, depth ~0.25-0.3, height ~1.0-1.2, board_thickness ~0.03-0.04, n_shelves 3-4, side_thickness ~0.03-0.04.
Cabinet defaults: width ~0.7-0.8, depth ~0.4-0.5, height ~1.2-1.5, panel_thickness ~0.03-0.04, base_height ~0.05-0.08.

"age": <number between 0.15 and 1.0 — controls wear and imperfection.>
0.15 = lightly imperfect (baseline, always slightly off from CAD-perfect).
0.7-1.0 = old / battered / rustic / weathered.
0.15-0.3 = new / fine / polished / pristine.
Default is 0.15.

Examples:

(note: schema is asset_id, generator, age, params — NONE of these examples include a "material" key; the pre-pass resolver chooses material from the request text above, not from this JSON)

Request: "a low plain coffee table"
{{
  "asset_id": "table",
  "generator": "table",
  "age": 0.15,
  "params": {{
    "top_width": 1.1, "top_depth": 0.65, "top_thickness": 0.05,
    "leg_height": 0.4, "leg_radius": 0.04, "leg_inset": 0.08
  }}
}}

Request: "an old battered weathered oak workbench"
{{
  "asset_id": "table",
  "generator": "table",
  "age": 0.85,
  "params": {{
    "top_width": 1.7, "top_depth": 0.95, "top_thickness": 0.07,
    "leg_height": 0.7, "leg_radius": 0.06, "leg_inset": 0.12
  }}
}}

Request: "a wooden bookcase with a slightly worn look"
{{
  "asset_id": "shelf",
  "generator": "shelf",
  "age": 0.4,
  "params": {{
    "width": 0.9, "depth": 0.28, "height": 1.15,
    "board_thickness": 0.035, "n_shelves": 3, "side_thickness": 0.03
  }}
}}

Request: {request}

Output JSON now:"""


class AssetPlanner:
    """LLM-driven asset-spec generator.

    The LLM picks dimensions; determinism (compile_spec, ranges, build)
    executes.  The llm parameter is injectable — tests pass a FAKE callable.
    """

    def build_prompt(self, request: str) -> str:
        """Build the planner prompt for the given natural-language request."""
        return _ASSET_PLANNER_PROMPT.format(request=request)

    def parse(self, text: str) -> dict:
        """Parse LLM text output into a spec dict.

        Strips markdown fences and <think> tags, then extracts the first
        JSON object found.  Raises ValueError on parse failure.
        """
        if not text or not text.strip():
            raise ValueError("Empty LLM response")

        # Remove think tags (some models emit these even with grammar)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

        # Remove markdown fences
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```\s*$", "", text)

        start = text.find("{")
        if start == -1:
            raise ValueError(f"No JSON found in response:\n{text[:200]}")

        try:
            data = json.loads(text[start:])
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in LLM response: {e}\n{text[:200]}")

        return data

    def plan(self, request: str, llm: Callable[[str, Optional[str]], str]) -> Tuple[dict, List[DecisionPoint]]:
        """Plan an asset-spec from a natural-language request.

        Args:
            request: Natural-language description (e.g. "a low wooden coffee table").
            llm: Callable with signature (prompt, grammar) -> str.  Pass a
                 FAKE for tests, or foundry.llm.FoundryLLM for production.

        Returns:
            ``(spec, decisions)`` — ``spec`` is a dict guaranteed to pass
            ``compiler.compile_spec()``; ``decisions`` is the list of
            Decision Points emitted by the material pre-pass
            (lexical material matching is the resolver's job, not qwen's).
        """
        # ── Resolve material BEFORE the LLM call ────────────────────
        # The prompt no longer asks qwen to pick a material; the resolver
        # is authoritative. Returning its decisions lets the caller
        # surface them (CLI, sidecar, future UI).
        material, decisions = resolve_material(request)

        # Build the prompt (no material lines — see _ASSET_PLANNER_PROMPT).
        prompt = self.build_prompt(request)

        # Call the LLM with the pre-loaded grammar
        response = llm(prompt, _GRAMMAR)

        # Parse the response
        spec = self.parse(response)

        # ── Clamp out-of-range numeric params ─────────────────────
        gen = spec.get("generator", "table")
        params = spec.get("params", {})
        ranges = PARAM_RANGES.get(gen, {})
        clamped_params: dict[str, float] = {}

        for key, (lo, hi) in ranges.items():
            val = params.get(key)
            if val is None:
                # Missing param — use the midpoint as default
                default = (lo + hi) / 2.0
                log.info(f"clamp: {key!r} missing → default {default}")
                clamped_params[key] = default
            elif not isinstance(val, (int, float)):
                default = (lo + hi) / 2.0
                log.info(f"clamp: {key!r} non-numeric ({type(val).__name__}) → default {default}")
                clamped_params[key] = default
            else:
                fval = float(val)
                if fval < lo:
                    log.info(f"clamp: {key!r}={fval} < {lo} → {lo}")
                    clamped_params[key] = lo
                elif fval > hi:
                    log.info(f"clamp: {key!r}={fval} > {hi} → {hi}")
                    clamped_params[key] = hi
                else:
                    clamped_params[key] = fval

        spec["params"] = clamped_params
        if "generator" not in spec:
            spec["generator"] = gen
        # Material comes from the resolver, not from the LLM — its verdict
        # is authoritative (overrides any stale/hallucinated material the
        # LLM might have emitted while the grammar change rolls out).
        spec["material"] = material
        if "asset_id" not in spec:
            spec["asset_id"] = spec.get("generator", "table")

        # ── Clamp age ───────────────────────────────────────────
        age = spec.get("age", 0.15)
        if not isinstance(age, (int, float)):
            log.info(f"age: non-numeric ({type(age).__name__}) → default 0.15")
            age = 0.15
        age = float(age)
        if age < 0.15:
            log.info(f"age={age} < 0.15 → 0.15")
            age = 0.15
        elif age > 1.0:
            log.info(f"age={age} > 1.0 → 1.0")
            age = 1.0
        spec["age"] = age

        # Verify the final spec passes compile_spec
        compile_spec(spec)

        return spec, decisions
