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
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from decisions import Choice, DecisionPoint, make_decision
from dialogue_validator import validate_dialogue, validate_idle_barks, get_canned_idle_barks

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

Output JSON now:"""

# C-4: Multi-NPC prompt — one LLM call generates N quests with distinct
# roles and unique targets.  The LLM sees all NPC IDs so it can pick
# non-overlapping targets.

_MULTI_NPC_PROMPT = """You are a quest designer for a small RPG. This room has {npc_count} NPCs, each needing their own fetch quest. Create ONE quest per NPC.

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

Output ONLY a JSON object — no prose, no explanation. The JSON MUST be keyed by NPC ID:
{{
  "npc_0": {{
    "npc_role": "<role>",
    "target_entity": "<prop_id>",
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

Room theme: {room_theme}
NPC IDs: {npc_ids}

Output JSON now:"""


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
        llm: Callable[[str, Optional[str]], str],
        seed: int | None = None,
        carryable_ids: set[str] | None = None,
    ) -> Tuple[dict, List[DecisionPoint]]:
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
        room_theme: str,
        manifest: list[dict],
        llm: Callable[[str, Optional[str]], str],
        *,
        npc_count: int = 2,
        seed: int | None = None,
        carryable_ids: set[str] | None = None,
    ) -> Tuple[list[dict], List[DecisionPoint]]:
        """C-4: Generate *npc_count* quest specs for multiple NPCs in
        a single LLM call so the LLM picks distinct targets and roles.

        Args:
            room_theme: Short description (e.g. "a blacksmith's forge").
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
        decisions: list[DecisionPoint] = []

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

        # Build prompt
        prompt = _MULTI_NPC_PROMPT.format(
            npc_count=npc_count,
            npc_ids=npc_id_list,
            room_theme=room_theme,
            manifest_text=manifest_text,
            carryable_section=carryable_section,
        )

        # Call LLM with NO grammar — the multi-NPC output is a dict-of-dicts
        # which doesn't fit a single GBNF schema easily.
        # ⚠ Pass "" (empty), NOT None: FoundryLLM treats grammar=None as
        # "use my default grammar" (= the ASSET-spec GBNF), which silently
        # straitjacketed every model into {asset_id, generator, params} and
        # made all multi-NPC dialogue collapse to canned fallbacks. An empty
        # string is falsy → no grammar is sent → the model answers freely.
        response = llm(prompt, "")

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

        # EB-7: Hard fail when carryables < npc_count — every NPC
        # needs a distinct pickable target.  If the room doesn't have
        # enough, it's a pipeline error (room_layout must guarantee this).
        if len(valid_ids) < npc_count:
            decisions.append(
                make_decision(
                    code="quest.insufficient_carryables",
                    stage="planner",
                    severity="error",
                    context={"npc_count": npc_count, "carryable_count": len(valid_ids)},
                    choices=(
                        Choice(
                            label="Add carryables",
                            plain=f"Need at least {npc_count} pickable items (have {len(valid_ids)}).",
                            apply={"action": "add_carryables"},
                        ),
                    ),
                )
            )
            raise ValueError(
                f"Room has {len(valid_ids)} carryables, need ≥ {npc_count}"
            )

        used_targets: set[str] = set()
        specs: list[dict] = []

        for npc_id in npc_ids:
            raw = data.get(npc_id, {})
            if not raw:
                # No usable LLM data for this NPC — emit a DP but DON'T drop the
                # NPC; fall through so role/target/dialogue validation below
                # builds a winnable default quest (canned dialogue, unused target).
                decisions.append(
                    make_decision(
                        code="quest.missing_npc",
                        stage="planner",
                        severity="assumption",
                        context={"npc_id": npc_id},
                        choices=(),
                    )
                )
                raw = {}

            # Validate NPC role
            raw_role = raw.get("npc_role", "")
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

            # Build objective
            objective = {
                "type": "fetch",
                "target": target_entity,
                "giver": "npc",
            }

            spec: dict = {
                "npc_id": npc_id,
                "npc_role": npc_role,
                "target_entity": target_entity,
                "dialogue": validated_dialogue,
                "objective": objective,
                "idle_barks": idle_barks,
            }
            specs.append(spec)

        return specs, decisions
