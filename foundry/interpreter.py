"""Interpreter — prompt → Brief (spine slice 1).

Maps free-form user imagination onto the engine's vocabulary so
the user never learns a secret grammar.  Mirrors the planner pattern:
injectable LLM, build_prompt (injects closed vocabularies), parse
(raw_decode — never json.loads on a slice), interpret (never raises).

Two hard-won lessons baked in:
  1. Never ``llm(prompt, None)`` — ``None`` applies the default asset
     grammar.  Pass ``""`` for free-form output.
  2. Never ``json.loads(text[start:])`` — use
     ``json.JSONDecoder().raw_decode(text[start:])`` so trailing prose /
     unclosed ``<think>`` blocks don't blow up the parse.
"""

from __future__ import annotations

import json
import re
from typing import Callable, List, Optional, Tuple

from brief import THEMES, CATEGORIES, VALID_SCALES, minimal, validate_brief
from decisions import Choice, DecisionPoint, make_decision


# ── Prompt template ────────────────────────────────────────────────

_INTERPRETER_PROMPT = """You are an interpreter that maps free-form user descriptions to a structured room Brief for a 3D game engine.

Given a user's description, output ONLY a JSON object — no prose, no explanation. The JSON must have these fields:

- "setting": a short place label (e.g. "a blacksmith's forge"). If the user's description is already a short label, use it directly.
- "mood": 2–4 single-word atmosphere descriptors (e.g. ["industrious", "smoky", "warm"]).
- "scale": one of "small", "medium", or "large". Pick based on what the user described:
    "small"  → a cramped room, 4–6 metres
    "medium" → a normal room, 6–9 metres
    "large"  → a spacious room, 9–12 metres
- "theme_tag": ONE of these known themes: {theme_list}
  Pick the best match. If nothing fits, use "*".
- "key_features": a list of notable PHYSICAL OBJECTS/PROPS the user named to put IN the room
  (e.g. "anvil", "many tools", "a sword on the wall"). For each, include:
    - "text": the object, in the user's own words (e.g. "anvil", "many tools")
    - "category": the CLOSEST matching category from the available list below, or null if nothing fits.
  Do NOT put the setting/room-type here (that is "setting"/"theme_tag"), and do NOT put people
  here (those are "characters"). Only concrete things that sit in the room. If the user named no
  specific objects, use an empty list [].
- "characters": a list of people/NPCs the description names or clearly implies. Each entry has:
    - "role": a short label for the character (e.g. "blacksmith", "apprentice", "shopkeeper"). Free-form — no closed set.
    - "note": optional short note about the character, or null.
    - "soul": (optional) inferred personality from the user's words. Contains a "substrate" object with three stable traits (courage, generosity, stability), each a float in -1.0..1.0:
        - courage: 1.0=bold/brave, -1.0=fearful/timid. Words like "wary", "fearful", "cautious" → negative; "brave", "proud", "confident" → positive.
        - generosity: 1.0=warm/generous, -1.0=selfish/guarded. Words like "generous", "kind", "welcoming" → positive; "greedy", "stingy" → negative.
        - stability: 1.0=steady/calm, -1.0=anxious/nervous. Words like "nervous", "jittery", "skittish" → negative; "calm", "steady" → positive.
      If the prompt implies nothing about a character's personality, omit the soul or set all traits to 0. You may optionally include an "axes" object (security, belonging, agency, satiation), all 0.0 if unsure."

Available placeable object categories (pick from these for key_features[].category):
{category_list}

User's description: {prompt}

Output JSON now:"""


class Interpreter:
    """LLM-driven prompt-to-Brief interpreter.

    The LLM maps free-form user text onto the engine's closed
    vocabularies; deterministic validation (validate_brief) handles
    any deviations.  The *llm* parameter is injectable — tests pass a
    FAKE callable.
    """

    def build_prompt(self, prompt: str) -> str:
        """Inject the closed vocabularies into the LLM prompt.

        The LLM sees the full list of known themes and placeable
        categories so it can make capability-aware choices.
        """
        theme_list = ", ".join(t for t in THEMES if t != "*") + ", or \"*\""
        category_chunks = _chunk_list(CATEGORIES, 8)
        category_list = "\n".join(
            "  " + ", ".join(chunk) for chunk in category_chunks
        )
        return _INTERPRETER_PROMPT.format(
            theme_list=theme_list,
            category_list=category_list,
            prompt=prompt,
        )

    @staticmethod
    def parse(text: str) -> dict:
        """Parse LLM output into a raw Brief dict.

        Strips markdown fences and <think> tags, then extracts the
        first complete JSON object via ``raw_decode`` so trailing
        prose or unclosed ``<think>`` blocks don't crash the parse.
        Never uses ``json.loads(text[start:])`` — that rejects
        trailing data.
        """
        if not text or not text.strip():
            raise ValueError("Empty LLM response")

        # Strip <think>…</think> blocks (including unclosed)
        text = re.sub(r"<think>.*?(?:</think>)?", "", text, flags=re.DOTALL)

        # Strip markdown ``` fences
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```\s*$", "", text)

        start = text.find("{")
        if start == -1:
            raise ValueError(f"No JSON found in response:\n{text[:200]}")

        # raw_decode: parse the first complete JSON value, ignore trailing
        # prose / unclosed <think> blocks.  This is the hard-won lesson.
        try:
            data, _end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in LLM response: {e}\n{text[:200]}")

        return data

    def interpret(
        self,
        prompt: str,
        llm: Callable[[str, Optional[str]], str],
        seed: int | None = None,
    ) -> Tuple[dict, List[DecisionPoint]]:
        """Interpret a free-form user prompt into a validated Brief.

        Args:
            prompt: Raw user text (e.g. "a wizard's tower study").
            llm: Callable (prompt, grammar) -> str.  Pass a FAKE for
                 tests, or ``FoundryLLM`` for production.
            seed: Optional random seed for reproducible output.

        Returns:
            ``(brief_dict, decisions)`` — *brief_dict* is a validated
            Brief dict; *decisions* is the list of Decision Points
            emitted during interpretation and validation.

        Never raises — on any parse failure, returns
        ``Brief.minimal(prompt)`` plus a ``brief.parse_fallback``
        decision.
        """
        decisions: List[DecisionPoint] = []

        # Call the LLM with grammar="" (empty string, NOT None).
        # None would apply the default asset-spec GBNF, silently
        # straitjacketing the model into {asset_id, generator, params}.
        try:
            raw_text = llm(self.build_prompt(prompt), "")
        except Exception as exc:
            decisions.append(
                make_decision(
                    "brief.parse_fallback",
                    stage="interpreter",
                    severity="error",
                    context={"error": str(exc)},
                    choices=(
                        Choice(
                            label="Use default",
                            plain="Build a default room instead.",
                            apply={"action": "fallback"},
                        ),
                    ),
                )
            )
            return minimal(prompt), decisions

        # Parse the response
        try:
            raw = self.parse(raw_text)
        except (ValueError, json.JSONDecodeError) as exc:
            decisions.append(
                make_decision(
                    "brief.parse_fallback",
                    stage="interpreter",
                    severity="error",
                    context={"error": str(exc)},
                    choices=(
                        Choice(
                            label="Use default",
                            plain="Build a default room instead.",
                            apply={"action": "fallback"},
                        ),
                    ),
                )
            )
            return minimal(prompt), decisions

        # Set source_prompt (provenance) before validation
        raw["source_prompt"] = prompt

        # Validate and normalise
        brief, val_decisions = validate_brief(raw, THEMES, CATEGORIES)
        decisions.extend(val_decisions)

        return brief, decisions


# ── Helpers ────────────────────────────────────────────────────────


def _chunk_list(items: Tuple[str, ...], chunk_size: int) -> list[list[str]]:
    """Split a tuple of strings into chunks for readable formatting."""
    chunks: list[list[str]] = []
    for i in range(0, len(items), chunk_size):
        chunks.append(list(items[i : i + chunk_size]))
    return chunks
