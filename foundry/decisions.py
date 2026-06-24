"""Decision Points — the pipeline's explainable, recoverable-failure layer.

The foundry pipeline NEVER blocks. When it has to make an ambiguous or
assumption-laden choice (most commonly: which material to use for a
request that didn't specify one), it emits a structured Decision Point
the user can act on (now via CLI, later via a UI).

Two-register messages (plain + technical) come from HAND-AUTHORED
templates filled with the context dict — deterministic and local,
never LLM-generated prose (reliability + on-premise).

Data is separate from presentation: this module owns decisions as data;
only ``render_cli`` knows about presentation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Tuple

# SEVERITY string constants — the four known severities.
# "warning" was added in the AUDIT-02 L1 / AUDIT-01 A10 fix so that
# plan_multi can soft-fallback on missing carryables (layout_room is
# the invariant's owner; plan_multi mustn't re-raise on layout_room
# regressing).  "warning" sits between "assumption" and "error" —
# rendered in CLI (unlike "info") but not blocking.
SEVERITY: Tuple[str, ...] = ("info", "assumption", "ambiguous", "warning", "error")


# ── Data classes ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Choice:
    """One concrete override the user can take instead of the default."""

    label: str           # short ("Wrought iron")
    plain: str           # one-line non-technical description
    apply: dict          # e.g. {"field": "material", "value": "wrought_iron"}


@dataclass(frozen=True)
class DecisionPoint:
    """One structured, emit-able event. Templates fill ``technical`` and
    ``plain`` deterministically from ``context``."""

    code: str            # "material.family_defaulted" | "material.unspecified_defaulted" | ...
    stage: str           # "planner" | "compiler" | "gate" | ...
    severity: str        # one of SEVERITY
    technical: str       # dev-facing message
    plain: str           # non-technical message
    context: dict        # {request, resolved, alternatives, ...}
    choices: Tuple[Choice, ...]


# ── Template registry ──────────────────────────────────────────────
# Authoring a NEW Decision Point type = one entry here + caller filling
# the right context keys.  Adding cases here is the only place prose
# lives.


_TEMPLATES: dict[str, tuple[str, str]] = {
    "exterior.biome_fallback": (
        # technical
        "biome '{requested}' unknown; used '{resolved}'.",
        # plain
        "I didn't recognize the biome '{requested}', so I used a generic landscape. You can name a known one.",
    ),
    "exterior.recipe_clamped": (
        # technical
        "biome recipe adjusted to safe ranges: {changes}.",
        # plain
        "I tuned the landscape recipe to stay coherent ({changes}).",
    ),
    "material.family_defaulted": (
        # technical
        "material family={family} has multiple members; defaulted to {resolved}.",
        # plain
        "You asked for {family}, so I used {resolved}. You can switch to another {family}.",
    ),
    "material.unspecified_defaulted": (
        # technical
        "no material keyword matched; defaulted to {resolved}.",
        # plain
        "You didn't name a material, so I used {resolved}.",
    ),
    "age.unspecified_defaulted": (
        # technical
        "no wear word matched; defaulted to age={resolved}.",
        # plain
        "You didn't describe the condition, so I assumed a fresh/new asset (age {resolved}).",
    ),
    "age.conflict": (
        # technical
        "both aged and new wear words present; resolved to age={resolved} (aged wins tie).",
        # plain
        "You mentioned both worn and new words — I went with aged ({resolved}). You can change it.",
    ),
    "material.conflict": (
        # technical
        "conflicting material families detected: {families}; resolved to {resolved} (cues: {cues}).",
        # plain
        "Your request mentions {families} — I went with {resolved}. You can switch.",
    ),
    "world.referential_integrity": (
        # technical
        "placement {placement_id}: material {material} not in known palette.",
        # plain
        "Placement {placement_id} uses an unknown material ({material}).",
    ),
    "world.zone_budget_exceeded": (
        # technical
        "zone {zone}: {count} placements exceed budget of {max}.",
        # plain
        "Zone '{zone}' has too many placements ({count} — max {max}).",
    ),
    "world.material_monoculture": (
        # technical
        "zone {zone}: all {placement_count} placements share material {material}.",
        # plain
        "Every placement in zone '{zone}' uses {material} — consider variety.",
    ),
    "quest.dangling_target": (
        # technical
        "target_entity {entity} not found in the placed-entity manifest.",
        # plain
        "The LLM picked an item ({entity}) that is not in the room.",
    ),
    "quest.dialogue_fallback": (
        # technical
        "dialogue field {field} failed validation (original: {original}); substituted canned line.",
        # plain
        "The model's '{field}' line was unusable, so I used a template instead.",
    ),
    "quest.dialogue_target_mismatch": (
        # technical
        "dialogue field {field} failed category-ref check (original: {original!r}); "
        "the ask/thank line should mention '{category}' (or a known synonym) so "
        "the player knows what to fetch. C4: winnable-by-manifest, "
        "unplayable-by-text.",
        # plain
        "The model's '{field}' line didn't name the requested item ({category}); "
        "a template line is used instead — otherwise the quest would be "
        "winnable-by-manifest but unplayable-by-text.",
    ),
    "quest.no_eligible_target": (
        # technical
        "manifest has no eligible target props for a fetch quest.",
        # plain
        "The room has nothing to fetch — add a prop so there is something to find.",
    ),
    "quest.npc_role_empty": (
        # technical
        "npc_role was empty; defaulted to {resolved}.",
        # plain
        "The model didn't name the NPC's role, so I used {resolved}.",
    ),
    "quest.npc_role_malformed": (
        # technical
        "npc_role was malformed (original: {original!r}); cleaned to {resolved}.",
        # plain
        "The model produced a garbled NPC role, so I cleaned it up to '{resolved}'.",
    ),
    "quest.missing_npc": (
        # technical
        "no usable quest data for {npc_id}; built a default quest.",
        # plain
        "The model didn't return a quest for one NPC, so a simple default was used.",
    ),
    "quest.ignored_available_carryable": (
        # technical
        "{npc_id}: target {picked!r} is not a carryable; carryables available ({available}).",
        # plain
        "The model picked '{picked}' for one NPC even though pick-up-able items were available.",
    ),
    # AUDIT-02 L1 / AUDIT-01 A10: plan_multi soft-fallback when layout_room
    # has fewer carryables than npc_count.  Severity='warning' (not 'error')
    # because plan_multi is NOT the invariant's owner — layout_room is, and
    # it auto-injects missing carryables upstream; if it ever regresses,
    # plan_multi must degrade gracefully (round-robin among existing
    # targets) rather than crash the build.
    "quest.carryables_short": (
        # technical
        "room has {carryable_count} carryables for {npc_count} NPCs; layout_room should have injected the missing ones — proceeding round-robin.",
        # plain
        "Only {carryable_count} pick-up-able item(s) for {npc_count} NPCs — sharing targets so the build can still finish.",
    ),
    "quest.idle_bark_fallback": (
        # technical
        "idle bark #{index} failed validation (original: {original!r}); substituted canned line.",
        # plain
        "One of the NPC's idle lines was unusable, so a template line was used instead.",
    ),
    "examine.flavour_fallback": (
        # technical
        "examine flavour for {prop_id} ({category}) failed validation (original: {original!r}); used {fallback!r}.",
        # plain
        "The model's examine text for '{prop_id}' was unusable, so a canned description was used.",
    ),
    "room.size_clamped": (
        # technical
        "room_size {axis}={raw} clamped to {clamped} (bounds [{lo}, {hi}]).",
        # plain
        "The room was an unusual size, so it was nudged to a sensible {clamped} m.",
    ),
    "room.prop_clamped": (
        # technical
        "prop {field}={raw!r} invalid → {fixed!r}.",
        # plain
        "One furnishing choice ({field}) didn't fit the catalogue, so it was adjusted to {fixed}.",
    ),
    "room.empty": (
        # technical
        "room plan had no props.",
        # plain
        "The room came out empty, so there's nothing to furnish it with yet.",
    ),
    "room.planner_parse_fallback": (
        # technical
        "RoomPlanner output failed to parse ({error}); fell back to default room.",
        # plain
        "The room layout couldn't be read, so a simple default room was used.",
    ),
    "room.over_capacity": (
        # technical
        "{placed} of {requested} floor props placed; {dropped} over capacity for {w}x{d} room.",
        # plain
        "The model asked for more furniture than the room holds; {placed} fit and {dropped} were left out.",
    ),
    "room.key_feature_injected": (
        # technical
        "key_feature {text!r} ({category}) injected as required prop.",
        # plain
        "You asked for '{text}' — I made sure it appears in the room.",
    ),
    # ── Brief (spine slice 1) ──
    "brief.theme_unmapped": (
        # technical
        "theme_tag {requested!r} not in known set; resolved to {resolved!r}.",
        # plain
        "I don't know the theme '{requested}', so I picked the closest or a general room ({resolved}).",
    ),
    "brief.scale_defaulted": (
        # technical
        "scale {requested!r} invalid; defaulted to {resolved!r}.",
        # plain
        "The room scale '{requested}' wasn't recognised, so I used a medium-sized room.",
    ),
    "brief.feature_unmapped": (
        # technical
        "key_feature {text!r} could not be mapped to a known category.",
        # plain
        "You asked for '{text}' but I don't know how to build that yet — it's noted in the report.",
    ),
    "brief.setting_defaulted": (
        # technical
        "setting was empty; defaulted to {resolved!r} from theme.",
        # plain
        "No room name was given, so I called it '{resolved}'.",
    ),
    "brief.parse_fallback": (
        # technical
        "Brief parse failed ({error}); fell back to Brief.minimal.",
        # plain
        "I couldn't understand the request format, so I built a default room instead.",
    ),
    # ── Quest spine (spine slice 2) ──
    "quest.role_from_brief": (
        # technical
        "{npc_id}: role set to {role!r} from Brief characters.",
        # plain
        "The Brief named '{role}' — so I used that for the NPC's role instead of the model's guess.",
    ),
    "quest.npc_grammared_fallback": (
        # technical
        "{npc_id}: multi-call failed; retried via grammar-constrained plan().",
        # plain
        "The ungrammared multi-NPC call failed for one NPC, so I retried that NPC through the reliable single-NPC path to get themed dialogue.",
    ),
    # ── CB-1: quest depth (objective types + chains) ──
    "quest.objective_not_winnable": (
        # technical
        "{npc_id}: objective type={original_type} is not winnable ({reason}); downgraded to fetch.",
        # plain
        "The model created a {original_type} quest that can't be completed, so it was changed to a simple fetch quest.",
    ),
    "quest.fallback_unwinnable": (
        # technical
        "{npc_id}: fetch fallback also not winnable ({reason}).",
        # plain
        "Even the fallback fetch quest can't be completed for one NPC — this may need room layout adjustment.",
    ),
    "quest.chain_unsolvable": (
        # technical
        "quest dependency chain is unsolvable ({reason}); flattened to independent quests.",
        # plain
        "The quest dependencies would make some quests impossible to start, so all quests were made independent.",
    ),
    # ── Soul (spine slice 3) ──
    "soul.clamped": (
        # technical
        "soul {field}={raw} clamped to {clamped} (bounds [-1.0, 1.0]).",
        # plain
        "The {field} trait was out of range ({raw}) and was nudged to {clamped}.",
    ),
    "soul.defaulted": (
        # technical
        "soul {field} missing/invalid; defaulted to 0.0.",
        # plain
        "No value was given for {field}, so a neutral 0.0 was used.",
    ),
    # ── Phase 0.3: loud failures (no more silent degradation) ──
    "bake.cycles_failed": (
        # technical
        "lighting bake failed ({exception_class}: {exception_reason}); fell back to realtime tier-0.",
        # plain
        "The lighting bake failed ({exception_reason}), so the scene uses realtime lights instead.",
    ),
    "shell.blender_unavailable": (
        # technical
        "Blender binary not found on PATH; fell back to inline box shell.",
        # plain
        "Blender isn't installed, so the room uses a simple box instead of a detailed shell.",
    ),
    "shell.build_failed": (
        # technical
        "room shell Blender build failed (rc={returncode}); fell back to inline box shell.",
        # plain
        "The detailed room shell couldn't be built, so a simple box shell was used instead.",
    ),
    # ── Phase 2.4: Resource caps ──
    "asset.rss_guard": (
        # technical
        "process RSS {rss_mb:.0f} MB exceeds threshold {threshold_mb:.0f} MB; falling back to serial build.",
        # plain
        "Memory is running low ({rss_mb:.0f} MB used), so assets are being built one at a time to avoid crashing.",
    ),
    "navmesh.too_dense": (
        # technical
        "navmesh carve skipped: {reason}.",
        # plain
        "The room has too many obstacles for pathfinding — using a simple walkable area instead.",
    ),
    "flora.scatter_capped": (
        # technical
        "scatter_placements capped from {original} to {kept}.",
        # plain
        "The terrain had too many plants ({original}), so only {kept} were placed to keep the scene manageable.",
    ),
    "quest.llm_retry_failed": (
        # technical
        "{npc_id}: multi-call AND grammared-fallback BOTH failed ({exception_class}); fell back to canned default NPC.",
        # plain
        "The quest generator failed completely for one NPC, so a default NPC with canned dialogue was used.",
    ),
}


# ── Factory + serialisation + presentation ─────────────────────────


def make_decision(
    code: str,
    stage: str,
    severity: str,
    context: dict,
    choices: Iterable[Choice],
) -> DecisionPoint:
    """Build a DecisionPoint, filling ``technical`` and ``plain`` from the
    template registry. Raises KeyError on unknown code — that's a
    programming error, not runtime data.
    """
    if code not in _TEMPLATES:
        raise KeyError(f"unknown decision code: {code!r} (known: {sorted(_TEMPLATES)})")
    technical_tmpl, plain_tmpl = _TEMPLATES[code]
    return DecisionPoint(
        code=code,
        stage=stage,
        severity=severity,
        technical=technical_tmpl.format(**context),
        plain=plain_tmpl.format(**context),
        context=dict(context),
        choices=tuple(choices),
    )


def to_dict(dp: DecisionPoint) -> dict:
    """JSON-serialisable dict view of a DecisionPoint. ``choices``
    become dicts in order."""
    return {
        "code": dp.code,
        "stage": dp.stage,
        "severity": dp.severity,
        "technical": dp.technical,
        "plain": dp.plain,
        "context": dp.context,
        "choices": [
            {"label": c.label, "plain": c.plain, "apply": c.apply}
            for c in dp.choices
        ],
    }


def render_cli(decisions: list[DecisionPoint]) -> str:
    """Human-readable dual-register block. ``info`` decisions are carried
    but not rendered. ONLY this function knows about presentation."""
    lines: list[str] = []
    for dp in decisions:
        if dp.severity == "info":
            continue
        lines.append(dp.plain)
        lines.append(f"  [technical: {dp.technical}]")
        for i, choice in enumerate(dp.choices, start=1):
            # apply is a dict like {"field": "material", "value": "wrought_iron"};
            # render the structured override as "field=value" (the spec example).
            # Fall back to all k=v pairs for non-structured overrides.
            if "field" in choice.apply and "value" in choice.apply:
                override = f"{choice.apply['field']}={choice.apply['value']}"
            else:
                override = ", ".join(f"{k}={v}" for k, v in choice.apply.items())
            lines.append(f"  {i}) {choice.label} — {choice.plain}  "
                         f"[set {override}]")
        lines.append("")  # blank line between decisions
    return "\n".join(lines)
