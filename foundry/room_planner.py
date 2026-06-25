"""RoomPlanner — turns a room Brief into a grammar-constrained room plan
(room size + a prop set/counts over the closed grid). Mirrors AssetPlanner:
injectable LLM, single-line GBNF, deterministic post-validation → Decision Points.
The LLM picks nouns + numbers only; it never positions anything.

Spine slice 1: consumes a Brief dict instead of a raw string.  Accepts
either a Brief dict or a raw string (wrapped in Brief.minimal for
back-compat).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from decisions import Choice, DecisionPoint, make_decision
from llm import load_grammar as _load_grammar

_GRAMMAR_PATH = str(Path(__file__).resolve().parent / "grammar" / "room_plan.gbnf")
_GRAMMAR = _load_grammar(_GRAMMAR_PATH)

# Derive from the compiler's generator set so new generators (carryables P-E,
# extended props P-F, …) are accepted automatically and never remapped to 'table'.
# Excludes 'humanoid' (the NPC body, not a placeable room prop).
from compiler import GENERATORS as _GENERATORS  # noqa: E402

CATEGORIES = tuple(sorted(c for c in _GENERATORS if c != "humanoid"))
MATERIALS = ("worn_oak", "rough_granite", "wrought_iron")
SIZE_LO, SIZE_HI = 4.0, 12.0
COUNT_LO, COUNT_HI = 1, 8

_PROMPT = """You are a room planner for a 3D game. From the description below, output ONLY a JSON object — no prose.

Room: {setting}
Theme: {theme_tag}
Scale: choose room_size with w and d each between {scale_lo} and {scale_hi} m (a {scale_label} room).
{features_text}
Each prop has:
  - category: one of a 3D furniture category (see room theme for guidance)
  - material: one of "worn_oak", "rough_granite", "wrought_iron"
  - count: how many of that prop (1 to 8). Do NOT ask for more than fit the room.

Example category choices: table, chair, shelf, cabinet, rug, painting. Theme the choices: a blacksmith leans wrought_iron and denser; a hermit leans worn_oak and sparse.

Output JSON now:"""  # noqa: E501  literal


class RoomPlanner:
    """LLM-driven room-plan generator.

    The LLM picks the room size + prop set/counts inside the
    grammar; deterministic validation (size clamping, prop clamping,
    key_feature injection) executes post-parse.
    """

    def build_prompt(self, brief: dict) -> str:
        """Format the normalised Brief intent into the room-planning prompt.

        Accepts a Brief dict (from brief.minimal() or the Interpreter).
        """
        setting = brief.get("setting", "a room")
        theme_tag = brief.get("theme_tag", "*")
        scale = brief.get("scale", "medium")

        # Map scale to size band for the LLM
        from brief import SCALE_BANDS

        scale_lo, scale_hi = SCALE_BANDS.get(scale, (6, 9))

        # Build features text from mapped key_features
        mapped = [
            f for f in brief.get("key_features", [])
            if f.get("status") == "mapped" and f.get("category") in CATEGORIES
        ]
        if mapped:
            items = ", ".join(
                f"{f['text']} ({f['category']})" for f in mapped
            )
            features_text = (
                f"Named features to include (must place these): {items}."
            )
        else:
            features_text = ""

        return _PROMPT.format(
            setting=setting,
            theme_tag=theme_tag,
            scale_label=scale,
            scale_lo=scale_lo,
            scale_hi=scale_hi,
            features_text=features_text,
        )

    def parse(self, text: str) -> dict:
        """Parse LLM text output into a room-plan dict.

        Strips markdown fences and <think> tags, then extracts the
        first JSON object found.  Raises ValueError on parse failure.
        """
        if not text or not text.strip():
            raise ValueError("Empty LLM response")
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```\s*$", "", text)
        start = text.find("{")
        if start == -1:
            raise ValueError(f"No JSON found:\n{text[:200]}")
        return json.loads(text[start:])

    def plan(
        self,
        brief: dict | str,
        llm: Callable[[str, str | None], str],
        seed: int | None = None,
    ) -> tuple[dict, list[DecisionPoint]]:
        """Plan a room from a Brief dict (or raw string).

        Accepts a Brief dict or a raw string (wrapped in Brief.minimal
        for back-compat with existing callers).

        Returns ``({room_size, props}, decisions)`` — same output
        shape as before.
        """
        from brief import minimal

        # Back-compat: wrap raw strings in Brief.minimal
        if isinstance(brief, str):
            brief = minimal(brief)

        raw = self.parse(llm(self.build_prompt(brief), _GRAMMAR))
        decisions: list[DecisionPoint] = []

        size_in = raw.get("room_size", {}) or {}
        room_size = {}
        for axis in ("w", "d"):
            val = size_in.get(axis)
            fval = float(val) if isinstance(val, (int, float)) else SIZE_LO
            clamped = min(max(fval, SIZE_LO), SIZE_HI)
            if clamped != fval:
                decisions.append(make_decision(
                    "room.size_clamped", stage="room", severity="assumption",
                    context={"axis": axis, "raw": fval, "clamped": clamped,
                             "lo": SIZE_LO, "hi": SIZE_HI},
                    choices=[Choice(label="Accept size",
                                    plain="Use the adjusted room size",
                                    apply={"field": "room_size", "axis": axis})],
                ))
            room_size[axis] = clamped

        props = []
        for p in raw.get("props", []) or []:
            cat = p.get("category")
            mat = p.get("material")
            cnt = p.get("count")
            fixed_cat = cat if cat in CATEGORIES else CATEGORIES[0]
            fixed_mat = mat if mat in MATERIALS else MATERIALS[0]
            icnt = int(cnt) if isinstance(cnt, (int, float)) else COUNT_LO
            fixed_cnt = min(max(icnt, COUNT_LO), COUNT_HI)
            for field, raw_v, fixed_v in (("category", cat, fixed_cat),
                                          ("material", mat, fixed_mat),
                                          ("count", cnt, fixed_cnt)):
                if raw_v != fixed_v:
                    decisions.append(make_decision(
                        "room.prop_clamped", stage="room", severity="assumption",
                        context={"field": field, "raw": raw_v, "fixed": fixed_v},
                        choices=[Choice(label="Accept value",
                                        plain="Use the adjusted value",
                                        apply={"field": field, "value": fixed_v})],
                    ))
            props.append({"category": fixed_cat, "material": fixed_mat, "count": fixed_cnt})

        if not props:
            decisions.append(make_decision(
                "room.empty", stage="room", severity="ambiguous", context={},
                choices=[Choice(label="Add a prop",
                                plain="Add at least one furnishing",
                                apply={"field": "props"})],
            ))

        # ── Spine: inject mapped key_features as required props ──
        mapped_features = [
            f for f in brief.get("key_features", [])
            if f.get("status") == "mapped" and f.get("category") in CATEGORIES
        ]
        present_categories = {p["category"] for p in props}
        for feat in mapped_features:
            cat = feat["category"]
            text = feat["text"]
            if cat not in present_categories:
                props.append({
                    "category": cat,
                    "material": MATERIALS[0],
                    "count": 1,
                })
                present_categories.add(cat)
                decisions.append(make_decision(
                    "room.key_feature_injected",
                    stage="room",
                    severity="assumption",
                    context={"text": text, "category": cat},
                    choices=(
                        Choice(
                            label="Accept",
                            plain=f"Keep '{text}' ({cat}) in the room",
                            apply={"field": "props", "category": cat},
                        ),
                    ),
                ))

        return {"room_size": room_size, "props": props}, decisions
