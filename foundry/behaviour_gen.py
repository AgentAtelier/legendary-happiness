"""QuestBehaviourPlanner — turns a room theme + placed-entity manifest into a
grammar-constrained quest spec (NPC role, target entity, dialogue, objective).

Mirrors :class:`AssetPlanner` (``foundry/planner.py``): injectable LLM,
build_prompt, parse, plan().  The LLM picks nouns + words; validation is
deterministic post-processing.

C-4: plan_multi() generates multiple quest specs (one per NPC) in a
      single LLM call so the LLM picks distinct targets and complementary
      NPC roles.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

from decisions import Choice, DecisionPoint, make_decision
from dialogue_validator import validate_dialogue, validate_idle_barks
from llm import load_grammar as _load_grammar
from soul import default_soul, tone_descriptor

log = logging.getLogger(__name__)

_GRAMMAR_PATH = str(Path(__file__).resolve().parent / "grammar" / "quest_spec.gbnf")

# ── Load grammar once at module level ────────────────────────────

_GRAMMAR = _load_grammar(_GRAMMAR_PATH)

# ── NPC role constants ───────────────────────────────────────────

_DEFAULT_NPC_ROLE = "villager"
_MAX_NPC_ROLE_LEN = 60


# ── NPC role validation ──────────────────────────────────────────

def _validate_npc_role(raw_role: object) -> tuple[str, list[DecisionPoint]]:
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


def _npc_role_choices(resolved: str) -> tuple[Choice, ...]:
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

{carryable_section}

EB-7b: You MUST pick one of the [CARRYABLE] items as the quest target — these are pickable objects the player can actually collect and carry. Only fall back to furniture items if NO carryables are listed above.

Pick ONE of the props as the quest target. The NPC will ask the player to find it.

Output ONLY a JSON object — no prose, no explanation. The JSON MUST have these exact fields:
- "npc_role": a short role for the NPC that fits the room theme (e.g. "hermit", "blacksmith", "shopkeeper")
- "target_entity": the ID of the prop the player must find (MUST be one of the [CARRYABLE] IDs if any exist)
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
A room themed "hermit's shack" with props: [table_0 (table), key_0 (key) [CARRYABLE], shelf_0 (shelf)]
Carryable items available: key_0
{{
  "npc_role": "hermit",
  "target_entity": "key_0",
  "dialogue": {{
    "greet": "Ah, a visitor! Welcome to my humble shack.",
    "ask": "I have lost a small key among my belongings. Could you find it for me?",
    "wrong": "No, that is not what I am looking for.",
    "thank": "Yes, that is it! You have my gratitude, traveler."
  }},
  "objective": {{
    "type": "fetch",
    "target": "key_0",
    "giver": "npc"
  }}
}}

Room theme: {room_theme}

Output JSON now:"""  # noqa: E501  prompt

# C-4: Multi-NPC prompt — one LLM call generates N quests with distinct
# roles and unique targets.  The LLM sees all NPC IDs so it can pick
# non-overlapping targets.

def _multi_npc_json_schema(npc_ids: list[str]) -> dict:
    """Build a per-*npc_ids* json_schema so the multi-NPC LLM call is
    constrained to clean dict-of-dicts JSON (the shape that doesn't fit
    one GBNF but is expressible as a json_schema).

    CB-1: objective now supports fetch | deliver | place | talk, with
    optional recipient/location/depends_on.  quest_id is a stable
    identifier for chain references."""
    objective_schema = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["fetch", "deliver", "place", "talk"]},
            "target": {"type": "string"},
            "giver": {"type": "string", "const": "npc"},
            "recipient": {"type": "string"},
            "location": {"type": "string"},
            "depends_on": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["type", "target", "giver"],
    }
    npc = {
        "type": "object",
        "properties": {
            "npc_role": {"type": "string"},
            "target_entity": {"type": "string"},
            "quest_id": {"type": "string"},
            "dialogue": {
                "type": "object",
                "properties": {
                    "greet": {"type": "string"},
                    "ask": {"type": "string"},
                    "wrong": {"type": "string"},
                    "thank": {"type": "string"},
                },
                "required": ["greet", "ask", "wrong", "thank"],
            },
            "idle_barks": {"type": "array", "items": {"type": "string"}},
            "objective": objective_schema,
        },
        "required": ["npc_role", "target_entity", "dialogue", "objective"],
    }
    return {
        "type": "object",
        "properties": {nid: npc for nid in npc_ids},
        "required": list(npc_ids),
    }


_MULTI_NPC_PROMPT = """You are a quest designer for a small RPG. This room has {npc_count} NPCs, each needing their own quest. Create ONE quest per NPC.

NPC IDs: {npc_ids}

Room theme: {room_theme}

Placed props in the room:
{manifest_text}

{carryable_section}

Important rules:
- Each NPC must have a DISTINCT target entity — no two NPCs can ask for the same item.
- Each NPC must have a DISTINCT role that fits the room theme.
- EB-7b: You MUST choose [CARRYABLE] items as quest targets. Only fall back to furniture if there aren't enough carryables.
- EB-6: Also generate 3 short idle-bark lines per NPC — things they might mutter to themselves when the player is nearby but not talking to them. These should be atmospheric, not quest-related. Put them in an "idle_barks" list inside each NPC's object.

CB-1: Each NPC's "objective" can be one of these types:
- "fetch" — player must find and pick up the target item, then bring it to the giver NPC.
- "deliver" — player must pick up the target item and bring it to a DIFFERENT NPC (set "recipient" to that NPC's id, e.g. "npc_1").
- "place" — player must pick up the target item and place it on a furniture surface (set "location" to a furniture entity id).
- "talk" — player must speak with another NPC (set "target" to that NPC's id, e.g. "npc_1").

Default to "fetch" unless the room theme strongly suggests a different type. If using "deliver" or "talk", make sure the recipient/target NPC actually exists in the NPC IDs list.

You MAY also set "depends_on" (a list of quest_id strings) to chain quests — a quest with depends_on is locked until its prereqs are complete. Also include a "quest_id" field (e.g. "q_npc_0") for chain references.

Output ONLY a JSON object — no prose, no explanation. The JSON MUST be keyed by NPC ID:
{{
  "npc_0": {{
    "npc_role": "<role>",
    "target_entity": "<prop_id>",
    "quest_id": "q_npc_0",
    "dialogue": {{
      "greet": "...",
      "ask": "...",
      "wrong": "...",
      "thank": "..."
    }},
    "objective": {{"type": "fetch", "target": "<prop_id>", "giver": "npc"}},
    "idle_barks": ["bark 1", "bark 2", "bark 3"]
  }},
  "npc_1": {{ ... }}
}}

Example with 2 NPCs in a blacksmith's forge:
{{
  "npc_0": {{
    "npc_role": "blacksmith",
    "target_entity": "key_0",
    "quest_id": "q_npc_0",
    "dialogue": {{
      "greet": "Hail, traveler! Welcome to my forge.",
      "ask": "I've misplaced my brass key. Could you find it among these shelves?",
      "wrong": "That's not my key. Keep looking.",
      "thank": "Aha, my key! You have my thanks, friend."
    }},
    "objective": {{"type": "fetch", "target": "key_0", "giver": "npc"}},
    "idle_barks": ["Another day at the anvil...", "This steel won't temper itself.", "Hmm, the forge-fire is low."]
  }},
  "npc_1": {{
    "npc_role": "apprentice",
    "target_entity": "gem_0",
    "quest_id": "q_npc_1",
    "dialogue": {{
      "greet": "Oh, a customer! The master is busy at the anvil.",
      "ask": "I dropped a gem somewhere. Can you find it for me?",
      "wrong": "No, that's not the gem I lost.",
      "thank": "That's it! The master will be pleased."
    }},
    "objective": {{"type": "fetch", "target": "gem_0", "giver": "npc"}},
    "idle_barks": ["The master works so fast...", "I hope I don't drop anything else.", "The bellows need more strength."]
  }}
}}

Example with a deliver quest (npc_0 asks player to bring item to npc_1):
{{
  "npc_0": {{
    "quest_id": "q_npc_0",
    "objective": {{"type": "deliver", "target": "gem_0", "giver": "npc", "recipient": "npc_1"}}
  }}
}}

Room theme: {room_theme}
NPC IDs: {npc_ids}

Output JSON now:"""  # noqa: E501  prompt


class QuestBehaviourPlanner:
    """LLM-driven quest-spec generator.

    The LLM picks the NPC role, target entity, and dialogue;
    deterministic validation (manifest membership, dialogue quality,
    objective shape) executes post-parse.  The *llm* parameter is
    injectable — tests pass a FAKE callable.
    """

    def build_prompt(self, room_theme: str, manifest: list[dict],
                     carryable_ids: set[str] | None = None) -> str:
        """Build the quest-planner prompt for *room_theme* and *manifest*.

        *manifest* is a list of dicts, each with at least ``id``,
        ``category``, and ``material`` keys.
        *carryable_ids* optionally provides the set of entity IDs that
        are carryable (quest targets). When set, those items are tagged
        ``[CARRYABLE]`` in the manifest text and a separate carryable
        summary section is included.
        """
        # Build a compact manifest text: one line per prop
        carryable_set = carryable_ids or set()
        lines: list[str] = []
        carryable_list: list[str] = []
        for entry in manifest:
            eid = entry.get("id", "?")
            cat = entry.get("category", "?")
            mat = entry.get("material", "?")
            adj = self._material_adjective(mat)
            tag = " [CARRYABLE]" if eid in carryable_set else ""
            lines.append(f"  {eid} ({adj} {cat}){tag}")
            if eid in carryable_set:
                carryable_list.append(eid)
        manifest_text = "\n".join(lines)
        # Build carryable summary section
        if carryable_list:
            carryable_section = (
                f"Carryable items available: {', '.join(carryable_list)}"
            )
        else:
            carryable_section = (
                "No carryable items are available — you must use a furniture target."
            )

        return _QUEST_PLANNER_PROMPT.format(
            room_theme=room_theme,
            manifest_text=manifest_text,
            carryable_section=carryable_section,
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

        # Use raw_decode, NOT json.loads(text[start:]): ungrammared models
        # (the multi-NPC path) routinely append trailing prose or an unclosed
        # <think> block AFTER the JSON object. json.loads() rejects that as
        # "Extra data" and the whole quest collapses to canned fallbacks. We
        # only want the first complete JSON value; raw_decode stops at its end
        # and ignores whatever trails.
        try:
            data, _end = json.JSONDecoder().raw_decode(text[start:])
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

    @staticmethod
    def _target_material(manifest: list[dict], target_id: str) -> str:
        """Get the material of *target_id* from *manifest*."""
        for entry in manifest:
            if entry.get("id") == target_id:
                return entry.get("material", "default")
        return "default"

    @staticmethod
    def _material_adjective(material: str) -> str:
        """Map a material id to a short descriptive adjective."""
        return {
            "worn_oak": "wooden",
            "dark_walnut": "dark",
            "weathered_pine": "pine",
            "rough_granite": "stone",
            "wrought_iron": "brass",
        }.get(material, material)

    def plan(
        self,
        room_theme: str,
        manifest: list[dict],
        llm: Callable[[str, str | None], str],
        seed: int | None = None,
        carryable_ids: set[str] | None = None,
    ) -> tuple[dict, list[DecisionPoint]]:
        """Plan a quest spec from a room theme and placed-entity manifest.

        Args:
            room_theme: Short description (e.g. "a hermit's shack").
            manifest: List of placed-entity dicts, each with at least
                      ``id``, ``category``, and ``material`` keys.
            llm: Callable (prompt, grammar) -> str.  Pass a FAKE for
                 tests, or ``FoundryLLM`` for production.
            seed: Optional random seed for reproducible output.
            carryable_ids: Optional set of entity IDs that are carryable
                           (quest targets). If None, all non-decor entities
                           are eligible.

        Returns:
            ``(spec, decisions)`` — ``spec`` is a validated quest-spec
            dict; ``decisions`` is the list of Decision Points emitted.

        Raises:
            ValueError: only when the manifest has no eligible targets
                        (unrecoverable — a quest needs at least one prop).
        """
        decisions: list[DecisionPoint] = []

        # ── Guard: manifest must have eligible targets ────────────
        # P-E: prefer a carryable target; but fall back to any non-decor prop so
        # a room without carryables still yields a winnable quest (was a hard fail).
        all_manifest_ids = self._manifest_ids(manifest)
        non_decor_ids = {e["id"] for e in manifest if "id" in e and not e.get("decor")}
        if carryable_ids is None:
            valid_ids = all_manifest_ids
        else:
            valid_ids = (carryable_ids & all_manifest_ids) or non_decor_ids
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
        prompt = self.build_prompt(room_theme, manifest,
                                   carryable_ids=carryable_ids)
        response = llm(prompt, _GRAMMAR)

        # ── Parse the response ───────────────────────────────────
        spec = self.parse(response)

        # ── EB-7b: Track when LLM ignores available carryables ──
        raw_target = spec.get("target_entity", "")
        if carryable_ids and raw_target not in carryable_ids:
            decisions.append(
                make_decision(
                    code="quest.ignored_available_carryable",
                    stage="planner",
                    severity="assumption",
                    context={"picked": raw_target,
                             "available": sorted(carryable_ids)[:8]},
                    choices=(
                        Choice(
                            label="Use carryable",
                            plain=f"Override target to a carryable item instead of '{raw_target}'.",
                            apply={"action": "use_carryable"},
                        ),
                    ),
                )
            )

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
        # P-E: use category + material adjective for dialogue item naming
        category = self._target_category(manifest, target_entity)
        material = self._target_material(manifest, target_entity)
        adjective = self._material_adjective(material)
        raw_dialogue = spec.get("dialogue", {})
        validated_dialogue, dialogue_decisions = validate_dialogue(
            raw_dialogue, category, adjective=adjective
        )
        decisions.extend(dialogue_decisions)

        # ── EB-6: Validate idle barks ────────────────────────────
        raw_idle = spec.get("idle_barks", [])
        if not isinstance(raw_idle, list):
            raw_idle = []
        idle_barks, idle_decisions = validate_idle_barks(raw_idle, theme=room_theme)
        decisions.extend(idle_decisions)

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
            "idle_barks": idle_barks,
        }

        return validated_spec, decisions

    # ── C-4: Multi-NPC plan ────────────────────────────────────

    def plan_multi(
        self,
        brief: dict | str,
        manifest: list[dict],
        llm: Callable[[str, str | None], str],
        *,
        npc_count: int = 2,
        seed: int | None = None,
        carryable_ids: set[str] | None = None,
    ) -> tuple[list[dict], list[DecisionPoint]]:
        """C-4: Generate *npc_count* quest specs for multiple NPCs in
        a single LLM call so the LLM picks distinct targets and roles.

        Spine Slice 2: consumes a Brief (dict) with normalized intent
        and character roles.  Back-compat: accepts a raw str, wrapped
        via ``brief.minimal()``.

        Args:
            brief: Brief dict or raw string (back-compat).
            manifest: List of placed-entity dicts.
            llm: Callable (prompt, grammar) -> str.
            npc_count: How many NPCs to generate quests for (default 2).
            seed: Optional random seed.
            carryable_ids: Optional set of entity IDs that are carryable.

        Returns:
            ``(specs, decisions)`` — *specs* is a list of validated
            quest-spec dicts, one per NPC; *decisions* is the combined
            Decision Points.
        """
        from brief import minimal as brief_minimal

        decisions: list[DecisionPoint] = []

        # Back-compat: wrap raw strings in Brief.minimal
        if isinstance(brief, str):
            brief = brief_minimal(brief)

        # Normalized intent from Brief
        room_theme = brief.get("theme_tag", "*")
        brief_setting = brief.get("setting", brief.get("source_prompt", "a room"))
        brief_characters: list[dict] = list(brief.get("characters", []) or [])

        # Generate NPC IDs
        npc_ids = [f"npc_{i}" for i in range(npc_count)]
        npc_id_list = ", ".join(npc_ids)

        # Build manifest text, tagging carryables
        carryable_set = carryable_ids or set()
        lines: list[str] = []
        carryable_list: list[str] = []
        for entry in manifest:
            eid = entry.get("id", "?")
            cat = entry.get("category", "?")
            mat = entry.get("material", "?")
            adj = self._material_adjective(mat)
            tag = " [CARRYABLE]" if eid in carryable_set else ""
            lines.append(f"  {eid} ({adj} {cat}){tag}")
            if eid in carryable_set:
                carryable_list.append(eid)
        manifest_text = "\n".join(lines)
        # Build carryable summary section
        if carryable_list:
            carryable_section = (
                f"Carryable items available: {', '.join(carryable_list)}"
            )
        else:
            carryable_section = (
                "No carryable items are available — use furniture targets as last resort."
            )

        # Build character hint for the prompt (if the Brief named characters)
        char_hint = ""
        if brief_characters:
            roles = [c["role"] for c in brief_characters]
            char_hint = (
                f"\nThe user described these characters: {', '.join(roles)}. "
                f"Assign these roles to the NPCs where they fit the count."
            )

        # Spine Slice 3: tone hints from per-NPC souls
        tone_hints: list[str] = []
        for i in range(npc_count):
            if i < len(brief_characters) and brief_characters[i].get("soul"):
                soul = brief_characters[i]["soul"]
            else:
                soul = default_soul()
            tone = tone_descriptor(soul)
            role = brief_characters[i]["role"] if i < len(brief_characters) else f"npc_{i}"
            tone_hints.append(f"{role} is a {tone} character")

        # Build prompt with normalized Brief setting
        prompt = _MULTI_NPC_PROMPT.format(
            npc_count=npc_count,
            npc_ids=npc_id_list,
            room_theme=f"{brief_setting} ({room_theme})",
            manifest_text=manifest_text,
            carryable_section=carryable_section,
        ) + char_hint

        # Append tone hints to the prompt so the LLM writes in-character dialogue
        if tone_hints:
            prompt += (
                f"\nCharacter tones (write each NPC's dialogue to match): "
                f"{'; '.join(tone_hints)}. "
            )

        # Constrain the multi-NPC call via json_schema so capable models
        # reliably emit clean dict-of-dicts JSON (the old grammar="" path
        # let verbose thinkers ramble in prose, collapsing to canned).
        # json_schema wins over grammar — no grammar key is sent.
        response = llm(
            prompt,
            json_schema=_multi_npc_json_schema(npc_ids),
        )

        # Parse the response. The multi-NPC call is ungrammared (dict-of-dicts
        # doesn't fit one GBNF), so weak/stochastic models often emit malformed
        # or truncated JSON. Recover instead of crashing: an empty dict routes
        # every NPC through the per-NPC default-quest path below.
        try:
            data = self.parse(response)
        except (ValueError, json.JSONDecodeError):
            data = {}

        # Validate each NPC's quest
        all_manifest_ids = self._manifest_ids(manifest)
        non_decor_ids = {e["id"] for e in manifest if "id" in e and not e.get("decor")}
        if carryable_ids is None:
            valid_ids = all_manifest_ids
        else:
            valid_ids = (carryable_ids & all_manifest_ids) or non_decor_ids

        # EB-7: ≥npc_count carryables for npc_count NPCs is layout_room's
        # invariant (it auto-injects missing carryables upstream).  We used
        # to raise ValueError here (AUDIT-02 L1 / AUDIT-01 A10) — a second,
        # fatal enforcement that would crash with a misleading message if
        # layout_room regressed.  Now this is a soft-fallback: emit a
        # 'warning' Decision Point and proceed round-robin through whichever
        # valid_ids actually exist (the dangling_target handler below already
        # round-robins via ``sorted(valid_ids - used_targets)`` and falls
        # back to sorted(valid_ids)[0] when the pool is exhausted).  Plan
        # generation no longer aborts the build.
        #
        # Gated on len(valid_ids) > 0 so the truly-empty case (zero
        # carryables AND zero non-decor props) keeps its pre-existing
        # crash path instead of being preceded by a lying DP that claims
        # we will "share targets" when no targets exist.
        if 0 < len(valid_ids) < npc_count:
            decisions.append(
                make_decision(
                    code="quest.carryables_short",
                    stage="planner",
                    severity="warning",
                    context={"npc_count": npc_count, "carryable_count": len(valid_ids)},
                    choices=(),
                )
            )

        used_targets: set[str] = set()
        specs: list[dict] = []

        # Spine Slice 3: resolve souls per NPC (store on every spec)
        npc_souls: list[dict] = []
        for i in range(npc_count):
            if i < len(brief_characters) and brief_characters[i].get("soul"):
                npc_souls.append(brief_characters[i]["soul"])
            else:
                npc_souls.append(default_soul())

        for i, npc_id in enumerate(npc_ids):
            raw = data.get(npc_id, {})
            npc_soul = npc_souls[i]
            npc_tone = tone_descriptor(npc_soul)

            # ── Spine Slice 2 Task 3: Per-NPC grammared fallback ──
            # When the ungrammared multi-call yields no usable data for an NPC,
            # retry that NPC through the grammar-constrained single-NPC plan(),
            # which is reliable, to get themed dialogue (NOT canned "villager").
            # Spine Slice 3: prepend soul tone to room_theme for themed fallback.
            if not raw or not isinstance(raw, dict):
                try:
                    # Retry via the reliable grammar-constrained single-NPC path,
                    # prepending the soul tone so fallback dialogue reflects it.
                    themed_room = f"{npc_tone} — {brief_setting}"
                    spec_fb, dpx_fb = self.plan(
                        themed_room, manifest, llm,
                        seed=seed, carryable_ids=carryable_ids,
                    )
                    decisions.extend(dpx_fb)
                    decisions.append(
                        make_decision(
                            code="quest.npc_grammared_fallback",
                            stage="planner",
                            severity="assumption",
                            context={"npc_id": npc_id},
                            choices=(),
                        )
                    )
                    # Use the grammared spec as the raw data for this NPC
                    raw = {
                        "npc_role": spec_fb.get("npc_role", ""),
                        "target_entity": spec_fb.get("target_entity", ""),
                        "dialogue": spec_fb.get("dialogue", {}),
                        "idle_barks": spec_fb.get("idle_barks", []),
                    }
                    # Enforce a distinct target vs already-used ones
                    fb_target = raw["target_entity"]
                    if fb_target in used_targets or fb_target not in valid_ids:
                        available = sorted(valid_ids - used_targets)
                        if available:
                            raw["target_entity"] = available[0]
                except Exception:
                    # plan() itself failed → fall through to canned default
                    pass

            if not raw or not isinstance(raw, dict):
                # Both multi-call and grammared fallback failed → canned default.
                # Phase 0.3: emit quest.llm_retry_failed (loud failure).
                decisions.append(
                    make_decision(
                        code="quest.llm_retry_failed",
                        stage="planner",
                        severity="error",
                        context={
                            "npc_id": npc_id,
                            "exception_class": "LLM/parse-failure",
                        },
                        choices=(),
                    )
                )
                raw = {}

            # ── Spine Slice 2 Task 2: Seed NPC role from Brief characters ──
            raw_role = raw.get("npc_role", "")
            role_from_brief = None
            if i < len(brief_characters):
                role_from_brief = brief_characters[i].get("role", "")

            if role_from_brief:
                # Brief character role wins over model output.
                # Always emit quest.role_from_brief when a brief character
                # sets the role (spec requirement).
                if raw_role and raw_role != role_from_brief:
                    decisions.append(
                        make_decision(
                            code="quest.role_from_brief",
                            stage="planner",
                            severity="assumption",
                            context={"npc_id": npc_id, "role": role_from_brief},
                            choices=(),
                        )
                    )
                else:
                    decisions.append(
                        make_decision(
                            code="quest.role_from_brief",
                            stage="planner",
                            severity="info",
                            context={"npc_id": npc_id, "role": role_from_brief},
                            choices=(),
                        )
                    )
                # Override with brief character role for validation
                npc_role, role_decisions = _validate_npc_role(role_from_brief)
            else:
                npc_role, role_decisions = _validate_npc_role(raw_role)
            decisions.extend(role_decisions)

            # Validate target_entity
            target_entity = raw.get("target_entity", "")

            # EB-7b: Track when LLM ignores available carryables
            if carryable_set and target_entity not in carryable_set:
                decisions.append(
                    make_decision(
                        code="quest.ignored_available_carryable",
                        stage="planner",
                        severity="assumption",
                        context={"picked": target_entity, "npc_id": npc_id,
                                 "available": sorted(carryable_set)[:8]},
                        choices=(
                            Choice(
                                label="Use carryable",
                                plain=f"Override target to a carryable item instead of '{target_entity}'.",
                                apply={"action": "use_carryable"},
                            ),
                        ),
                    )
                )

            if target_entity not in valid_ids or target_entity in used_targets:
                # Auto-pick an unused eligible target
                available = sorted(valid_ids - used_targets)
                if available:
                    fallback_id = available[0]
                else:
                    fallback_id = sorted(valid_ids)[0]
                cat = self._target_category(manifest, fallback_id)
                decisions.append(
                    make_decision(
                        code="quest.dangling_target",
                        stage="planner",
                        severity="error",
                        context={"entity": target_entity, "npc_id": npc_id},
                        choices=(
                            _target_choice(fallback_id, cat),
                        ),
                    )
                )
                target_entity = fallback_id
            used_targets.add(target_entity)

            # Validate dialogue
            category = self._target_category(manifest, target_entity)
            material = self._target_material(manifest, target_entity)
            adjective = self._material_adjective(material)
            raw_dialogue = raw.get("dialogue", {})
            validated_dialogue, dialogue_decisions = validate_dialogue(
                raw_dialogue, category, adjective=adjective
            )
            decisions.extend(dialogue_decisions)

            # EB-6: Validate idle barks
            raw_idle = raw.get("idle_barks", [])
            if not isinstance(raw_idle, list):
                raw_idle = []
            idle_barks, idle_decisions = validate_idle_barks(raw_idle, theme=room_theme)
            decisions.extend(idle_decisions)

            # Build objective from model output, defaulting to fetch
            raw_obj = raw.get("objective", {})
            if not isinstance(raw_obj, dict):
                raw_obj = {}
            otype = raw_obj.get("type", "fetch")
            otarget = raw_obj.get("target", target_entity)
            ogiver = raw_obj.get("giver", "npc")
            objective = {
                "type": otype,
                "target": otarget,
                "giver": ogiver,
            }
            # CB-1: Carry optional fields for deliver/place/talk
            if otype == "deliver" and raw_obj.get("recipient"):
                objective["recipient"] = str(raw_obj["recipient"])
            if otype == "place" and raw_obj.get("location"):
                objective["location"] = str(raw_obj["location"])
            depends = raw_obj.get("depends_on", [])
            if isinstance(depends, list):
                objective["depends_on"] = [str(d) for d in depends]

            # CB-1: Extract quest_id from model output
            quest_id = raw.get("quest_id", f"q_{npc_id}")
            if not isinstance(quest_id, str) or quest_id.strip() == "":
                quest_id = f"q_{npc_id}"

            spec: dict = {
                "npc_id": npc_id,
                "quest_id": quest_id,
                "npc_role": npc_role,
                "target_entity": target_entity,
                "dialogue": validated_dialogue,
                "objective": objective,
                "idle_barks": idle_barks,
                "soul": npc_soul,
            }
            specs.append(spec)

        # ── CB-1: Validate every objective + chain via quest_validator ──
        from quest_validator import chain_solvable, objective_winnable
        npc_id_set: set[str] = set(npc_ids)
        for i, spec in enumerate(specs):
            obj = spec.get("objective", {})
            winnable, reason = objective_winnable(
                obj, manifest=manifest, npc_ids=npc_id_set,
            )
            if not winnable:
                # Fall back to a winnable fetch objective
                decisions.append(
                    make_decision(
                        code="quest.objective_not_winnable",
                        stage="planner",
                        severity="assumption",
                        context={
                            "npc_id": spec["npc_id"],
                            "original_type": obj.get("type", "?"),
                            "reason": reason,
                        },
                        choices=(),
                    )
                )
                spec["objective"] = {
                    "type": "fetch",
                    "target": spec["target_entity"],
                    "giver": "npc",
                }
                # Re-validate the fallback (must be winnable)
                w2, _r2 = objective_winnable(
                    spec["objective"], manifest=manifest, npc_ids=npc_id_set,
                )
                if not w2:
                    decisions.append(
                        make_decision(
                            code="quest.fallback_unwinnable",
                            stage="planner",
                            severity="error",
                            context={
                                "npc_id": spec["npc_id"],
                                "reason": _r2,
                            },
                            choices=(),
                        )
                    )

        # CB-1: Validate chain solvability
        solvable, chain_reason = chain_solvable(specs)
        if not solvable:
            decisions.append(
                make_decision(
                    code="quest.chain_unsolvable",
                    stage="planner",
                    severity="assumption",
                    context={"reason": chain_reason},
                    choices=(),
                )
            )
            # Flatten: remove all depends_on to make chain solvable
            for spec in specs:
                obj = spec.get("objective", {})
                if isinstance(obj, dict) and "depends_on" in obj:
                    del obj["depends_on"]

        return specs, decisions
