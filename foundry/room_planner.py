"""RoomPlanner — turns a room prompt into a grammar-constrained room plan
(room size + a prop set/counts over the closed grid). Mirrors AssetPlanner:
injectable LLM, single-line GBNF, deterministic post-validation → Decision Points.
The LLM picks nouns + numbers only; it never positions anything.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from decisions import Choice, DecisionPoint, make_decision
from llm import load_grammar as _load_grammar

_GRAMMAR_PATH = str(Path(__file__).resolve().parent / "grammar" / "room_plan.gbnf")
_GRAMMAR = _load_grammar(_GRAMMAR_PATH)

CATEGORIES = ("table", "chair", "shelf", "cabinet", "rug", "painting")
MATERIALS = ("worn_oak", "rough_granite", "wrought_iron")
SIZE_LO, SIZE_HI = 4.0, 12.0
COUNT_LO, COUNT_HI = 1, 8

_PROMPT = """You are a room planner for a 3D game. From the user's description, output ONLY a JSON object — no prose.

First choose room_size (a rectangle in metres): w and d each between 4 and 12. Pick a size that fits the scene.
Then choose props: a list of furnishings appropriate to the room you just sized. Each prop has:
  - category: one of "table", "chair", "shelf", "cabinet", "rug", "painting"
  - material: one of "worn_oak", "rough_granite", "wrought_iron"
  - count: how many of that prop (1 to 8). Do NOT ask for more than fit the room.

Theme the choices: a blacksmith leans wrought_iron and denser; a hermit leans worn_oak and sparse.

Request: {request}

Output JSON now:"""


class RoomPlanner:
    def build_prompt(self, request: str) -> str:
        return _PROMPT.format(request=request)

    def parse(self, text: str) -> dict:
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
        self, request: str, llm: Callable[[str, Optional[str]], str],
        seed: int | None = None,
    ) -> Tuple[dict, List[DecisionPoint]]:
        """Plan a room from a request.  When *seed* is provided,
        the LLM should use it for reproducible output (the caller
        is responsible for configuring the LLM with the seed)."""
        raw = self.parse(llm(self.build_prompt(request), _GRAMMAR))
        decisions: List[DecisionPoint] = []

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

        return {"room_size": room_size, "props": props}, decisions
