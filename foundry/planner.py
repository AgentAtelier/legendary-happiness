"""AssetPlanner — turns a natural-language asset request into a
grammar-constrained, buildable asset-spec, then drives the foundry pipeline.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable, Optional

from compiler import MATERIALS, PARAM_RANGES, compile_spec

log = logging.getLogger(__name__)

_GRAMMAR_PATH = str(Path(__file__).resolve().parent / "grammar" / "asset_spec.gbnf")

# ── Load grammar once at module level ────────────────────────────

from llm import load_grammar as _load_grammar

_GRAMMAR = _load_grammar(_GRAMMAR_PATH)

# ── Prompt template ──────────────────────────────────────────────

_ASSET_PLANNER_PROMPT = """You are an asset planner for a 3D game. Convert the user's natural-language description into an asset specification JSON. Output ONLY the JSON — no prose, no explanation.

Schema:
{{
  "asset_id": "table",
  "generator": "table",
  "material": "<pick from the palette below>",
  "params": {{
    "top_width": <number: width of tabletop (X)>,
    "top_depth": <number: depth of tabletop (Z)>,
    "top_thickness": <number: thickness of the tabletop board>,
    "leg_height": <number: height from floor to underside of top>,
    "leg_radius": <number: radius of each cylindrical leg>,
    "leg_inset": <number: how far in from edges the legs sit>
  }}
}}

Allowed values:
- asset_id: "table"
- generator: "table"
- material: one of "worn_oak" (light warm brown), "dark_walnut" (dark brown), "weathered_pine" (pale desaturated).
  Choose the one that best matches the request's wood tone.
- All param values are positive floats (decimals). Reasonable defaults: top_width ~1.2-1.5, top_depth ~0.6-1.0, top_thickness ~0.05-0.08, leg_height ~0.5-0.7, leg_radius ~0.04-0.06, leg_inset ~0.05-0.15.

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

    def plan(self, request: str, llm: Callable[[str, Optional[str]], str]) -> dict:
        """Plan an asset-spec from a natural-language request.

        Args:
            request: Natural-language description (e.g. "a low wooden coffee table").
            llm: Callable with signature (prompt, grammar) -> str.  Pass a
                 FAKE for tests, or foundry.llm.FoundryLLM for production.

        Returns:
            A dict that is guaranteed to pass compiler.compile_spec().
        """
        # Build the prompt
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
        if "material" not in spec or spec["material"] not in MATERIALS:
            old = spec.get("material")
            spec["material"] = "worn_oak"
            if old is not None:
                log.info(f"material: {old!r} not in palette → default worn_oak")
            else:
                log.info("material: missing → default worn_oak")
        if "asset_id" not in spec:
            spec["asset_id"] = spec.get("generator", "table")

        # Verify the final spec passes compile_spec
        compile_spec(spec)

        return spec
