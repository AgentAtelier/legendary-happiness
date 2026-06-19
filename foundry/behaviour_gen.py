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

from decisions import Choice, DecisionPoint, make_decision
from dialogue_validator import validate_dialogue

log = logging.getLogger(__name__)

_GRAMMAR_PATH = str(Path(__file__).resolve().parent / "grammar" / "quest_spec.gbnf")

# ── Load grammar once at module level ────────────────────────────

from llm import load_grammar as _load_grammar

_GRAMMAR = _load_grammar(_GRAMMAR_PATH)

# ── NPC role constants ───────────────────────────────────────────

_DEFAULT_NPC_ROLE = "villager"
_MAX_NPC_ROLE_LEN = 60


# ── NPC role validation ──────────────────────────────────────────

def _validate_npc_role(raw_role: object) -> Tuple[str, List[DecisionPoint]]:
    """Validate and clean an NPC role string.

    Returns ``(cleaned_role, decisions)``.  Never raises — always
    returns a usable role, emitting Decision Points for recoverable
    issues (mirrors how ``material_resolver`` never blocks).

    Checks:
        - **empty**: role is empty or non-string → default to
          ``"villager"``, emit ``quest.npc_role_empty``.
        - **too long**: role exceeds *_MAX_NPC_ROLE_LEN* → truncate,
          emit ``quest.npc_role_malformed``.
        - **repeated words**: e.g. ``"hermit hermit"`` → collapse
          adjacent duplicate words, emit ``quest.npc_role_malformed``.
    """
    decisions: list[DecisionPoint] = []

    # Coerce to string
    if not isinstance(raw_role, str):
        raw_role = str(raw_role) if raw_role is not None else ""
    role = raw_role.strip()

    # Empty check
    if not role:
        decisions.append(
            make_decision(
                code="quest.npc_role_empty",
                stage="planner",
                severity="assumption",
                context={"resolved": _DEFAULT_NPC_ROLE},
                choices=_npc_role_choices(_DEFAULT_NPC_ROLE),
            )
        )
        return _DEFAULT_NPC_ROLE, decisions

    # Too-long check
    if len(role) > _MAX_NPC_ROLE_LEN:
        truncated = role[:_MAX_NPC_ROLE_LEN].rstrip()
        decisions.append(
            make_decision(
                code="quest.npc_role_malformed",
                stage="planner",
                severity="assumption",
                context={"original": role, "resolved": truncated},
                choices=_npc_role_choices(truncated),
            )
        )
        return truncated, decisions

    # Duplicate adjacent words check (e.g. "hermit hermit")
    words = role.split()
    collapsed_words: list[str] = []
    changed = False
    for w in words:
        if collapsed_words and collapsed_words[-1].lower() == w.lower():
            changed = True
            continue
        collapsed_words.append(w)
    if changed:
        cleaned = " ".join(collapsed_words)
        if not cleaned:
            cleaned = _DEFAULT_NPC_ROLE
        decisions.append(
            make_decision(
                code="quest.npc_role_malformed",
                stage="planner",
                severity="assumption",
                context={"original": role, "resolved": cleaned},
                choices=_npc_role_choices(cleaned),
            )
        )
        return cleaned, decisions

    return role, decisions


def _npc_role_choices(resolved: str) -> Tuple[Choice, ...]:
    """Build the standard set of NPC role override choices."""
    return (
        Choice(
            label=resolved.title(),
            plain=f"Keep '{resolved}' as the NPC role.",
            apply={"field": "npc_role", "value": resolved},
        ),
        Choice(
            label="Custom role",
            plain="Provide a different NPC role.",
            apply={"field": "npc_role", "action": "custom"},
        ),
    )


def _target_choice(entity_id: str, category: str) -> Choice:
    """Build a Choice to set a specific target entity."""
    label = entity_id
    plain = f"Make '{entity_id}' ({category}) the quest target."
    return Choice(
        label=label,
        plain=plain,
        apply={"field": "target_entity", "value": entity_id},
    )


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
            ValueError: only when the manifest has no eligible targets
                        (unrecoverable — a quest needs at least one prop).
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
                    choices=(
                        Choice(
                            label="Add props",
                            plain="Add placed props to the manifest so there is something to fetch.",
                            apply={"action": "add_props"},
                        ),
                    ),
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

        # ── Validate NPC role (non-blocking) ────────────────────
        raw_role = spec.get("npc_role", "")
        npc_role, role_decisions = _validate_npc_role(raw_role)
        decisions.extend(role_decisions)

        # ── Validate target_entity (non-blocking, auto-recover) ──
        target_entity = spec.get("target_entity", "")
        if target_entity not in valid_ids:
            # Auto-pick the first available prop as fallback
            fallback_id = sorted(valid_ids)[0]
            cat = self._target_category(manifest, fallback_id)
            decisions.append(
                make_decision(
                    code="quest.dangling_target",
                    stage="planner",
                    severity="error",
                    context={"entity": target_entity},
                    choices=(
                        _target_choice(fallback_id, cat),
                        Choice(
                            label="Re-run",
                            plain="Re-run the LLM to pick a different target.",
                            apply={"action": "retry"},
                        ),
                    ),
                )
            )
            target_entity = fallback_id

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
            "npc_role": npc_role,
            "target_entity": target_entity,
            "dialogue": validated_dialogue,
            "objective": objective,
        }

        return validated_spec, decisions
