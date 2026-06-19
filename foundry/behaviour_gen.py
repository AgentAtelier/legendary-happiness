"""QuestBehaviourPlanner — turns a room theme + placed-entity manifest into a
grammar-constrained quest spec (NPC role, target entity, dialogue, objective).

Mirrors :class:`AssetPlanner` (``foundry/planner.py``): injectable LLM,
build_prompt, parse, plan().  The LLM picks nouns + words; validation is
deterministic post-processing.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from decisions import DecisionPoint, make_decision
from dialogue_validator import validate_dialogue

log = logging.getLogger(__name__)

_GRAMMAR_PATH = str(Path(__file__).resolve().parent / "grammar" / "quest_spec.gbnf")

# ── Load grammar once at module level ────────────────────────────

from llm import load_grammar as _load_grammar

_GRAMMAR = _load_grammar(_GRAMMAR_PATH)

# ── Prompt template ──────────────────────────────────────────────

_QUEST_PLANNER_PROMPT = """You are a quest designer for a small RPG. Given a room theme and a list of placed props, create a simple fetch quest.

Room theme: {room_theme}

Placed props in the room:
{manifest_text}

Pick ONE of the props as the quest target. The NPC will ask the player to find it.

Output ONLY a JSON object — no prose, no explanation. The JSON MUST have these exact fields:
- "npc_role": a short role for the NPC that fits the room theme (e.g. "hermit", "blacksmith", "shopkeeper")
- "target_entity": the ID of the prop the player must find (MUST be one of the IDs listed above)
- "dialogue": an object with four short lines of dialogue:
  - "greet": what the NPC says when you first talk to them
  - "ask": what the NPC says to ask you to find the item
  - "wrong": what the NPC says if you bring the wrong item
  - "thank": what the NPC says when you bring the right item
- "objective": an object with fixed structure:
  - "type": always "fetch"
  - "target": same entity ID as target_entity
  - "giver": always "npc"

Example:
A room themed "hermit's shack" with props: [table_0 (table), shelf_0 (shelf), cabinet_0 (cabinet)]
{{
  "npc_role": "hermit",
  "target_entity": "shelf_0",
  "dialogue": {{
    "greet": "Ah, a visitor! Welcome to my humble shack.",
    "ask": "I have lost a small trinket on my shelf. Could you find it for me?",
    "wrong": "No, that is not what I am looking for.",
    "thank": "Yes, that is it! You have my gratitude, traveler."
  }},
  "objective": {{
    "type": "fetch",
    "target": "shelf_0",
    "giver": "npc"
  }}
}}

Room theme: {room_theme}

Output JSON now:"""


class QuestBehaviourPlanner:
    """LLM-driven quest-spec generator.

    The LLM picks the NPC role, target entity, and dialogue;
    deterministic validation (manifest membership, dialogue quality,
    objective shape) executes post-parse.  The *llm* parameter is
    injectable — tests pass a FAKE callable.
    """

    def build_prompt(self, room_theme: str, manifest: list[dict]) -> str:
        """Build the quest-planner prompt for *room_theme* and *manifest*.

        *manifest* is a list of dicts, each with at least ``id`` and
        ``category`` keys.
        """
        # Build a compact manifest text: one line per prop
        lines: list[str] = []
        for entry in manifest:
            eid = entry.get("id", "?")
            cat = entry.get("category", "?")
            lines.append(f"  {eid} ({cat})")
        manifest_text = "\n".join(lines)

        return _QUEST_PLANNER_PROMPT.format(
            room_theme=room_theme,
            manifest_text=manifest_text,
        )

    @staticmethod
    def parse(text: str) -> dict:
        """Parse LLM text output into a quest-spec dict.

        Strips markdown fences and <think> tags, then extracts the first
        JSON object found.  Raises ValueError on parse failure.
        """
        if not text or not text.strip():
            raise ValueError("Empty LLM response")

        # Remove think tags
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

    @staticmethod
    def _manifest_ids(manifest: list[dict]) -> set[str]:
        """Extract the set of valid entity IDs from *manifest*."""
        return {entry["id"] for entry in manifest if "id" in entry}

    @staticmethod
    def _target_category(manifest: list[dict], target_id: str) -> str:
        """Get the category of *target_id* from *manifest*."""
        for entry in manifest:
            if entry.get("id") == target_id:
                return entry.get("category", "thing")
        return "thing"

    def plan(
        self,
        room_theme: str,
        manifest: list[dict],
        llm: Callable[[str, Optional[str]], str],
    ) -> Tuple[dict, List[DecisionPoint]]:
        """Plan a quest spec from a room theme and placed-entity manifest.

        Args:
            room_theme: Short description (e.g. "a hermit's shack").
            manifest: List of placed-entity dicts, each with at least
                      ``id`` and ``category`` keys.
            llm: Callable (prompt, grammar) -> str.  Pass a FAKE for
                 tests, or ``FoundryLLM`` for production.

        Returns:
            ``(spec, decisions)`` — ``spec`` is a validated quest-spec
            dict; ``decisions`` is the list of Decision Points emitted.

        Raises:
            ValueError: if the manifest has no eligible targets, or the
                        LLM's target_entity is not in the manifest.
        """
        decisions: list[DecisionPoint] = []

        # ── Guard: manifest must have eligible targets ────────────
        valid_ids = self._manifest_ids(manifest)
        if not valid_ids:
            decisions.append(
                make_decision(
                    code="quest.no_eligible_target",
                    stage="planner",
                    severity="error",
                    context={},
                    choices=(),
                )
            )
            raise ValueError(
                "Manifest has no eligible target props for a fetch quest"
            )

        # ── Call the LLM ─────────────────────────────────────────
        prompt = self.build_prompt(room_theme, manifest)
        response = llm(prompt, _GRAMMAR)

        # ── Parse the response ───────────────────────────────────
        spec = self.parse(response)

        # ── Validate target_entity ───────────────────────────────
        target_entity = spec.get("target_entity", "")
        if target_entity not in valid_ids:
            decisions.append(
                make_decision(
                    code="quest.dangling_target",
                    stage="planner",
                    severity="error",
                    context={"entity": target_entity},
                    choices=(),
                )
            )
            raise ValueError(
                f"target_entity {target_entity!r} not found in manifest"
                f" (valid: {sorted(valid_ids)})"
            )

        # ── Validate / fallback dialogue ─────────────────────────
        category = self._target_category(manifest, target_entity)
        raw_dialogue = spec.get("dialogue", {})
        validated_dialogue, dialogue_decisions = validate_dialogue(
            raw_dialogue, category
        )
        decisions.extend(dialogue_decisions)

        # ── Build the objective (fixed shape) ────────────────────
        objective = {
            "type": "fetch",
            "target": target_entity,
            "giver": "npc",
        }

        # ── Assemble the validated spec ──────────────────────────
        validated_spec: dict = {
            "npc_role": spec.get("npc_role", "villager"),
            "target_entity": target_entity,
            "dialogue": validated_dialogue,
            "objective": objective,
        }

        return validated_spec, decisions
