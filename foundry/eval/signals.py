"""foundry.eval.signals — objective signal layer.

``compute_signals(record)`` is a PURE function that returns a set of
short, machine-readable tags describing the outcome of one RunRecord.
It is the cheapest layer (100% coverage, no model) and feeds the
sampler downstream.

Rules (per spec):
    "build_error"     - record.error is set (pipe raised for this request)
    "gate_rejected"   - record.gate_passed is False (built but the gate
                        refused it)
    "decision_fired"  - record.decisions is non-empty
    "size_mismatch"   - request contains a size word but the spec sits at
                        the OPPOSITE end of its PARAM_RANGES band
                        (regression guard against qwen misreading "tall")
    "material_mismatch" - a specific material keyword (oak/walnut/pine/
                        granite/marble/iron/steel/wrought) is in the
                        request but spec["material"] disagrees (this
                        should never fire post-pre-pass; it's a
                        regression guard).
    "material_conflict" (slice 2) - request's matched material cues span
                        MORE THAN ONE distinct family (e.g. "stone-look
                        wooden cabinet").  Same-family multi-cue (oak +
                        walnut → both wood) does NOT fire.
    "age_mismatch"    (slice 2) - request's wear intent (aged | new |
                        neutral) disagrees with spec["age"] at the 0.4
                        band split.  Specifically:
                          AGED + age <  0.4  → mismatch
                          NEW  + age >= 0.4  → mismatch
                          neutral + age >= 0.4 → mismatch (the original
                                                    high-lean regression
                                                    guard for the few-shot
                                                    age fix)
    "clean"           - the only tag set when none of the above apply.

A record with multiple tags is normal: a build that errored AND would
also be gated counts both.

The ``size_mismatch_detail`` and ``age_mismatch_detail`` helpers
expose the same logic in detail-returning form so the friction report
can surface WHY a record was flagged.
"""

from __future__ import annotations

import re
from typing import List, Optional, Set

from compiler import PARAM_RANGES
from material_resolver import material_cues, resolve_material
from category_registry import DECOR_CATEGORIES


# ── Size words ────────────────────────────────────────────────────────
# Each size word maps to:
#   - dimension keys it cares about (any that exist in the spec's params
#     vs its generator's PARAM_RANGES)
#   - the EXPECTED direction ("high" or "low") on that dimension
#
# The OPPOSITE direction triggers size_mismatch.
#
# Note on "small": the spec is silent on which dimension; we use the
# height keys (the most common "small thing is short" reading).  A more
# permissive mapping would add width keys here.

_HEIGHT_KEYS: tuple[str, ...] = ("height", "leg_height", "back_height")
_WIDTH_KEYS:  tuple[str, ...] = ("width", "top_width", "seat_width")

_SIZE_WORDS: dict[str, tuple[tuple[str, ...], str]] = {
    "tall":  (_HEIGHT_KEYS, "high"),
    "high":  (_HEIGHT_KEYS, "high"),
    "low":   (_HEIGHT_KEYS, "low"),
    "small": (_HEIGHT_KEYS, "low"),
    "large": (_WIDTH_KEYS,  "high"),
    "wide":  (_WIDTH_KEYS,  "high"),
}

# "opposite end" = bottom 20% (when expected high) or top 20% (when expected low)
_OPPOSITE_FRACTION = 0.20


# ── Material keywords ────────────────────────────────────────────────
# Same specific-keyword → canonical-material map the resolver uses.  Kept
# inline here so this layer has no coupling to material_resolver and is
# independently testable.
_MATERIAL_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("oak",     "worn_oak"),
    ("walnut",  "dark_walnut"),
    ("pine",    "weathered_pine"),
    ("granite", "rough_granite"),
    ("marble",  "rough_granite"),  # resolver also maps marble→granite
    ("iron",    "wrought_iron"),
    ("steel",   "wrought_iron"),   # resolver maps steel→wrought_iron
    ("wrought", "wrought_iron"),
)


# ── Wear lexicons ────────────────────────────────────────────────────
# Single-sourced in foundry/wear_words.py; imported for backward compat
# so other modules can continue to reference signals.AGED_WORDS etc.
from wear_words import AGED_WORDS, NEW_WORDS, _AGE_BAND_SPLIT  # noqa: F401


# ── Severity classification (slice 2) ───────────────────────────────────────
# Each objective-signal tag is bucketed into a severity tier so the
# sampler can weight the probe set toward real friction and away from
# benign assumptions.  High = must be included; low = sampled to a cap;
# unlisted tags (e.g. "clean") are not a severity and handled separately.
#
# Deterministic; the sampler and the regression tests share this map.
SIGNAL_SEVERITY: dict[str, str] = {
    # High — the user's request lined up with the asset badly enough that
    # we should ALWAYS look at it; the live-run reported benign assumptions
    # because low-severity entries bloated the probe set.
    "build_error":       "high",
    "gate_rejected":     "high",
    "size_mismatch":     "high",
    "material_mismatch": "high",
    "material_conflict": "high",
    "age_mismatch":      "high",
    # Low — mild assumptions / decisions; informative but not a fail.
    "decision_fired":    "low",
    # ── Quest signals (P8) ────────────────────────────────────
    # High — these mean the quest is literally broken / unwinnable.
    "quest_build_error":        "high",
    "quest_no_target":          "high",
    "quest_no_npc":             "high",
    "quest_unwinnable":         "high",
    # Low — mild assumptions, informative.
    "quest_dialogue_fallback":  "low",
    "quest_decision_fired":     "low",
}


def _has_word(text: str, kw: str) -> bool:
    """Whole-word case-insensitive match; hyphens are non-word boundaries
    so 'wrought-iron' still matches the keyword 'wrought'."""
    return re.search(rf"\b{re.escape(kw)}\b", text, flags=re.IGNORECASE) is not None


# ── Public entry points ───────────────────────────────────────────────


def compute_signals(record) -> Set[str]:
    """Return the set of objective signal tags for *record*."""
    tags: Set[str] = set()

    if record.error:
        tags.add("build_error")
    if record.gate_passed is False:
        tags.add("gate_rejected")
    if record.decisions:
        tags.add("decision_fired")

    # Conflicting material cues: pure request-level check — fires when
    # the matched cues span MORE THAN ONE distinct family.  Same-family
    # multi-cue (oak + walnut → both wood) does NOT fire.
    cues = material_cues(record.request or "")
    if len({fam for _, fam in cues}) > 1:
        tags.add("material_conflict")

    if record.spec is not None and isinstance(record.spec, dict):
        if size_mismatch_detail(record.request, record.spec) is not None:
            tags.add("size_mismatch")
        if _material_mismatch(record.request, record.spec):
            tags.add("material_mismatch")
        if _age_mismatch(record.request, record.spec):
            tags.add("age_mismatch")

    if not tags:
        tags.add("clean")
    return tags


def decision_codes(record) -> List[str]:
    """Return the list of Decision-Point codes on *record* (used for
    ``decision_code_freq`` aggregation in the friction report)."""
    return [d.get("code", "?") for d in (record.decisions or [])]


def size_mismatch_detail(request: str, spec: dict) -> Optional[dict]:
    """Public, detail-returning twin of the internal size-mismatch check
    used by ``compute_signals``.  Returns None when there is no size
    mismatch; otherwise a flat dict so the friction report can render
    a human-readable line.

    Returned fields (per Task 4 design):
        word:                 the matched size word (e.g. "tall")
        expected_direction:   "high" or "low"  (the direction the user
                              implied with the word)
        dimension:            the spec param key that decided ("height")
        value:                the actual value present in spec["params"]
        range:                [lo, hi] from PARAM_RANGES[generator][key]
        generator:            the spec's generator ("cabinet", ...)
    """
    if not isinstance(spec, dict):
        return None
    params = spec.get("params") or {}
    generator = spec.get("generator")

    if generator is None:
        return None

    ranges_for_gen = PARAM_RANGES.get(generator, {})

    for word, (keys, expected_direction) in _SIZE_WORDS.items():
        if not _has_word(request or "", word):
            continue
        for key in keys:
            if key not in params or key not in ranges_for_gen:
                continue
            lo, hi = ranges_for_gen[key]
            val = params[key]
            if not isinstance(val, (int, float)):
                continue
            if expected_direction == "high" and _is_at_low_end(val, lo, hi):
                return _mismatch_detail(word, expected_direction, key, val,
                                        [lo, hi], generator)
            if expected_direction == "low" and _is_at_high_end(val, lo, hi):
                return _mismatch_detail(word, expected_direction, key, val,
                                        [lo, hi], generator)
    return None


# ── Inner helpers ─────────────────────────────────────────────────────


def _mismatch_detail(word, direction, key, value, rng, generator) -> dict:
    return {
        "word": word,
        "expected_direction": direction,
        "dimension": key,
        "value": float(value),
        "range": [float(rng[0]), float(rng[1])],
        "generator": generator,
    }


def _is_at_low_end(value: float, lo: float, hi: float) -> bool:
    """True when *value* is in the bottom _OPPOSITE_FRACTION of the range."""
    return value <= lo + _OPPOSITE_FRACTION * (hi - lo)


def _is_at_high_end(value: float, lo: float, hi: float) -> bool:
    """True when *value* is in the top _OPPOSITE_FRACTION of the range."""
    return value >= lo + (1.0 - _OPPOSITE_FRACTION) * (hi - lo)


def _material_mismatch(request: str, spec: dict) -> bool:
    """True when a material keyword in *request* expects one canonical
    material and spec["material"] is different."""
    spec_material = spec.get("material")
    if spec_material is None:
        return False
    for kw, expected in _MATERIAL_KEYWORDS:
        if _has_word(request or "", kw) and spec_material != expected:
            return True
    return False


# ── Age-appropriateness (slice 2) ──────────────────────────────────────────
#
# The first live run couldn't measure whether the few-shot age-anchoring
# fix had stuck for a given request; we had to hand-extract capture.jsonl
# to learn it.  This signal closes that loop with deterministic rules:
# classify the REQUEST's wear intent (aged | new | neutral) and compare
# to the SPEC's ``age`` value at the 0.4 band split.


def _wear_class_for(request: str) -> str:
    """Return one of ``"aged"``, ``"new"``, ``"neutral"`` for *request*.

    AGED wins over NEW when both fire (rare; the natural read is "the
    wear word ages the new one").  Whole-word match via ``_has_word``.
    ``NEW_WORDS`` contains both hyphen and space forms of "brand-new"
    so each is matched under the same whole-word rule.
    """
    req = request or ""
    for word in AGED_WORDS:
        if _has_word(req, word):
            return "aged"
    for word in NEW_WORDS:
        if _has_word(req, word):
            return "new"
    return "neutral"


def _age_mismatch(request: str, spec: dict) -> bool:
    """True when the request's wear-class disagrees with the spec's
    ``age`` (band split at ``_AGE_BAND_SPLIT``); ALSO True when the
    request has no wear word but ``age >= _AGE_BAND_SPLIT`` (the
    regression guard for the few-shot age fix).

    Rules:
        - request AGED + age <  band  → mismatch
        - request NEW  + age >= band  → mismatch
        - request neutral + age >= band → mismatch (interpreted "weathered")
        - request neutral + age <  band → OK (interpreted "fresh/new")
    """
    if not isinstance(spec, dict):
        return False
    age = spec.get("age")
    if not isinstance(age, (int, float)):
        return False
    wear = _wear_class_for(request)
    if wear == "aged":
        return age < _AGE_BAND_SPLIT
    if wear == "new":
        return age >= _AGE_BAND_SPLIT
    # wear == "neutral"
    return age >= _AGE_BAND_SPLIT


def age_mismatch_detail(request: str, spec: dict):
    """Public, detail-returning twin of ``_age_mismatch`` so the friction
    report can surface WHY a record was flagged (the wear class + age).

    Returns ``None`` when there's no mismatch; otherwise a flat dict::

        {
            "wear_class": "aged" | "new" | "neutral",
            "age":        <float>,
        }
    """
    if not isinstance(spec, dict):
        return None
    age = spec.get("age")
    if not isinstance(age, (int, float)):
        return None
    if not _age_mismatch(request, spec):
        return None
    wear = _wear_class_for(request)
    return {"wear_class": wear, "age": float(age)}


def record_tier(tags) -> str:
    """Classify a record's signal set into a severity tier:

      - "high" : any tag is SIGNAL_SEVERITY=high
      - "low"  : no high tag, but at least one low tag (e.g. decision_fired)
      - "clean": only "clean" (or no tags)

    Used by the severity-weighted sampler (slice 2) to decide whether
    a record goes in unconditionally (high), gets sampled to a cap
    (low), or participates in the clean baseline.
    """
    tags = tags or set()
    if not tags or tags == {"clean"}:
        return "clean"
    for tag in tags:
        if SIGNAL_SEVERITY.get(tag) == "high":
            return "high"
    return "low"


def material_conflict_detail(request: str):
    """Public, detail-returning twin of the material_conflict signal so
    the friction report can surface WHY a record was flagged (the
    competing cues + the planner's single resolved material).

    Returns ``None`` when there's no family conflict; otherwise::

        {
            "request":  <str>,
            "cues":     [(keyword, family), ...]   # all matched cues
            "resolved": <material_id>              # from resolve_material
        }

    No spec dependency: this signal is purely request-level.
    """
    cues = material_cues(request or "")
    families = {fam for _, fam in cues}
    if len(families) <= 1:
        return None
    resolved, _ = resolve_material(request or "")
    return {
        "request": request,
        "cues": list(cues),
        "resolved": resolved,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Spine: brief_valid — Brief schema validation signal (spine slice 1)
# ═══════════════════════════════════════════════════════════════════════

from brief import THEMES as _BRIEF_THEMES  # noqa: E402


def check_brief_valid(brief: dict | None) -> dict:
    """Return a signal dict for the Brief validity.

    Returns a dict with:
      - `tag`: "brief_valid" if the Brief passes all checks, else "brief_invalid"
      - `theme_ok`: bool — theme_tag in THEMES ∪ {"*"}
      - `scale_ok`: bool — scale in {small, medium, large}
      - `features_consistent`: bool — every key_feature status matches its category
    """
    if not isinstance(brief, dict):
        return {"tag": "brief_invalid", "theme_ok": False,
                "scale_ok": False, "features_consistent": False}

    theme_tag = brief.get("theme_tag", "")
    theme_ok = theme_tag in _BRIEF_THEMES

    scale = brief.get("scale", "")
    scale_ok = scale in ("small", "medium", "large")

    features_consistent = True
    for f in brief.get("key_features", []) or []:
        if not isinstance(f, dict):
            continue
        status = f.get("status", "")
        cat = f.get("category")
        if status == "mapped" and (cat is None or not isinstance(cat, str)):
            features_consistent = False
        if status == "unmapped" and cat is not None:
            features_consistent = False

    tag = "brief_valid" if (theme_ok and scale_ok and features_consistent) else "brief_invalid"
    return {
        "tag": tag,
        "theme_ok": theme_ok,
        "scale_ok": scale_ok,
        "features_consistent": features_consistent,
    }


# ═══════════════════════════════════════════════════════════════════════
#  P8: quest playability oracle — deterministic quest-level signals
# ═══════════════════════════════════════════════════════════════════════


def compute_quest_signals(record) -> Set[str]:
    """Return the set of objective signal tags for a QuestRecord.

    Mirrors ``compute_signals`` for the quest pipeline.  Pure function —
    checks only the fields already populated in the record (no file I/O).

    Quest signal tags:
      ``quest_build_error``      — record.error is set or compiled is False
      ``quest_dialogue_fallback`` — any decision code starts with "quest.dialogue_"
      ``quest_no_target``        — target_entity not in manifest
      ``quest_no_npc``           — npc_role is missing or empty in quest_spec
      ``quest_unwinnable``       — target_entity reaches no tagged node
                                   (can't be picked up)
      ``quest_decision_fired``   — decisions is non-empty
      ``clean``                  — none of the above
    """
    tags: Set[str] = set()

    # 1. Build error
    if record.error or not getattr(record, "compiled", True):
        tags.add("quest_build_error")

    # 2. Dialogue fallback
    for d in (record.decisions or []):
        code = d.get("code", "")
        if code.startswith("quest.dialogue_"):
            tags.add("quest_dialogue_fallback")
            break

    # 3. Decision fired (quest-specific)
    if record.decisions:
        tags.add("quest_decision_fired")

    # 4. Target entity exists in manifest (check ALL NPC specs)
    specs_to_check = getattr(record, "quest_specs", None)
    if not specs_to_check:
        single = getattr(record, "quest_spec", None)
        if single and isinstance(single, dict):
            specs_to_check = [single]

    manifest = getattr(record, "manifest", None) or []

    if specs_to_check and isinstance(specs_to_check, (list, tuple)) and manifest:
        manifest_ids = {e.get("id") for e in manifest if "id" in e}
        for spec in specs_to_check:
            if not isinstance(spec, dict):
                continue
            target_id = spec.get("target_entity", "")

            if target_id not in manifest_ids:
                tags.add("quest_no_target")

            # 5. NPC exists (npc_role present and non-empty)
            npc_role = spec.get("npc_role", "")
            if not npc_role or not str(npc_role).strip():
                tags.add("quest_no_npc")

            # 6. Win reachability: target must have a known tag AND
            #    NPC must exist.  The compiler maps target_entity → "pickup"
            #    tag and NPC → "talk" tag.  If either is missing, the quest
            #    is unwinnable.
            if target_id in manifest_ids and npc_role and str(npc_role).strip():
                # NPC and target both structurally present → check if the
                # quest_spec has the required objective shape
                obj = spec.get("objective", {})
                if obj.get("type") != "fetch":
                    tags.add("quest_unwinnable")

        # P-K: decor-never-target invariant (decor items must not be targets)
        decor_tag = check_decor_never_target(record)
        if decor_tag:
            tags.add(decor_tag)

        # P-E: target must be a carryable (not furniture)
        carryable_tag = check_target_is_carryable(record)
        if carryable_tag:
            tags.add(carryable_tag)

        # P-E: target must be named in dialogue
        dialogue_tag = check_target_named_in_dialogue(record)
        if dialogue_tag:
            tags.add(dialogue_tag)

        # C-2: multi-item inventory possible (>=2 carryables in manifest)
        multi_tag = check_multi_item_possible(record)
        if multi_tag:
            tags.add(multi_tag)

        # EB-7: multi-NPC distinct targets check (for multi-NPC records)
        npc_count = getattr(record, "npc_count", 1)
        if npc_count > 1:
            distinct_tag = check_multi_npc_distinct_targets(record, npc_count)
            if distinct_tag:
                tags.add(distinct_tag)

        # EB-7: room material variety check
        variety_tag = check_room_not_monochrome(record)
        if variety_tag:
            tags.add(variety_tag)

        # EB-7: fabric in fabric-themes check
        room_theme = getattr(record, "room_theme", "")
        fabric_tag = check_fabric_in_fabric_themes(record, room_theme)
        if fabric_tag:
            tags.add(fabric_tag)

        # B0: Winnable oracle — positive assertion (all NPCs gettable+deliverable)
        winnable_tag = check_all_npcs_winnable(record)
        if winnable_tag:
            tags.add(winnable_tag)

    if not tags:
        tags.add("clean")
    return tags


def quest_decision_codes(record) -> List[str]:
    """Return the list of Decision-Point codes on a QuestRecord."""
    return [d.get("code", "?") for d in (record.decisions or [])]


# P-K: decor-never-target invariant ───────────────────────────────────

def check_decor_never_target(record) -> Optional[str]:
    """P-K: Return a signal tag if the quest target_entity is a decor item.

    Decor items (rugs, paintings) should never be fetch-quest targets
    — they are wall/floor decorations, not pickup-able props.

    Returns "decor_never_target" if violated, None if clean.
    """
    spec = getattr(record, "quest_spec", None)
    manifest = getattr(record, "manifest", None) or []
    if not isinstance(spec, dict) or not manifest:
        return None
    target_id = spec.get("target_entity", "")
    for entry in manifest:
        if entry.get("id") == target_id and entry.get("decor"):
            return "decor_never_target"
    return None


# P-K: room variety scoring ───────────────────────────────────────────

def compute_room_variety(records) -> dict:
    """P-K: Score the variety across multiple QuestRecords for the same
    room prompt (run with different seeds).

    Returns a dict:
      - prompt: the room theme
      - count: number of records
      - size_spread: (min_w, max_w, min_d, max_d) or None
      - prop_count_spread: (min, max) or None
      - material_diversity: number of unique materials across all rooms
      - distinct: True if at least 2 records differ meaningfully
    """
    from collections import Counter

    if not records:
        return {"prompt": "", "count": 0, "distinct": False}

    theme = getattr(records[0], "room_theme", "")
    prop_counts: list[int] = []
    materials: Counter = Counter()

    for r in records:
        manifest = getattr(r, "manifest", None) or []
        prop_counts.append(len(manifest))
        for entry in manifest:
            mat = entry.get("material", "")
            if mat:
                materials[mat] += 1

    result: dict = {
        "prompt": theme,
        "count": len(records),
        "prop_count_spread": (min(prop_counts), max(prop_counts)) if prop_counts else None,
        "material_diversity": len(materials),
        "distinct": len(set(prop_counts)) > 1 or len(materials) > 1,
    }
    return result


# P-K: headless-load-clean signal ─────────────────────────────────────

def check_headless_load_clean(stderr: str) -> bool:
    """P-K: Return True if stderr from a headless Godot launch contains
    0 lines matching SCRIPT ERROR|Parse Error|Failed to load script."""
    patterns = ("SCRIPT ERROR", "Parse Error", "Failed to load script")
    for line in stderr.splitlines():
        for pat in patterns:
            if pat.lower() in line.lower():
                return False
    return True


# P-E: target-is-carryable signal ───────────────────────────────────

_CARRYABLE_CATEGORIES = {
    "key", "book", "cup", "gem", "bottle", "scroll", "coin-pouch",
    "candle", "dagger", "ring",
}


# C-2: multi-item inventory check ────────────────────────────────────

def check_multi_item_possible(record) -> Optional[str]:
    """C-2: Return a signal tag if the manifest has ≥2 carryable items,
    making multi-item inventory testable.  Low-severity — informative."""
    manifest = getattr(record, "manifest", None) or []
    carryable_count = sum(
        1 for e in manifest
        if e.get("category") in _CARRYABLE_CATEGORIES
    )
    if carryable_count >= 2:
        return "multi_item_possible"
    return None

# ═══════════════════════════════════════════════════════════════════════
#  EB-7: Multi-NPC target integrity signals
# ═══════════════════════════════════════════════════════════════════════


def check_multi_npc_distinct_targets(record, npc_count: int = 2) -> Optional[str]:
    """EB-7: Return None if all NPC quest specs have distinct targets.
    Returns 'multi_npc_distinct_targets' signal tag if any two NPCs
    share the same target_entity (which should be impossible post-fix).

    Also checks that carryable count ≥ npc_count — if not, returns
    'insufficient_carryables_for_npcs'."""
    specs = getattr(record, "quest_specs", None)
    manifest = getattr(record, "manifest", None) or []

    # Count carryables in manifest
    carryable_count = sum(
        1 for e in manifest
        if e.get("category") in _CARRYABLE_CATEGORIES
    )
    if carryable_count < npc_count:
        return "insufficient_carryables_for_npcs"

    # Check distinct targets across NPC quest specs
    if not specs or not isinstance(specs, (list, tuple)):
        # Single spec or no specs — can't have duplicates
        return None

    targets = []
    for spec in specs:
        if isinstance(spec, dict):
            targets.append(spec.get("target_entity", ""))

    if len(set(targets)) < len(targets):
        return "multi_npc_distinct_targets"

    return None


def check_room_not_monochrome(record) -> Optional[str]:
    """EB-7: Return 'room_not_monochrome' signal if the manifest uses
    ≥2 distinct materials (excluding decor). Low-severity — informative.
    Returns None if monochrome."""
    manifest = getattr(record, "manifest", None) or []
    materials = {
        e.get("material", "")
        for e in manifest
        if e.get("category") not in DECOR_CATEGORIES and e.get("material")
    }
    if len(materials) >= 2:
        return "room_not_monochrome"
    return None


def check_fabric_in_fabric_themes(record, theme: str = "") -> Optional[str]:
    """EB-7: Return 'fabric_in_fabric_themes' signal if the manifest
    contains any fabric material (linen, wool, silk). Low-severity —
    informative.  Fabric materials should appear in themes that allow
    them; this signal confirms they actually surfaced in the build.

    Returns None if no fabric material is used."""
    manifest = getattr(record, "manifest", None) or []
    _FABRIC_MATERIALS = {"linen", "wool", "silk"}

    for e in manifest:
        mat = e.get("material", "")
        if mat in _FABRIC_MATERIALS:
            return "fabric_in_fabric_themes"

    return None


def check_target_is_carryable(record) -> Optional[str]:
    """P-E: Return a signal tag if the quest target_entity is NOT a
    carryable item (i.e. it's furniture or decor) AND carryables exist
    in the manifest.  If there are no carryables at all, the room is
    pre-P-E and furniture-targeting is fine.

    Returns "target_not_carryable" if violated, None if clean."""
    spec = getattr(record, "quest_spec", None)
    manifest = getattr(record, "manifest", None) or []
    if not isinstance(spec, dict) or not manifest:
        return None
    # Only fire when carryables exist in the manifest
    has_carryable = any(
        e.get("category") in _CARRYABLE_CATEGORIES for e in manifest
    )
    if not has_carryable:
        return None
    target_id = spec.get("target_entity", "")
    for entry in manifest:
        if entry.get("id") == target_id:
            cat = entry.get("category", "")
            if cat not in _CARRYABLE_CATEGORIES:
                return "target_not_carryable"
            return None
    return None  # target not in manifest (handled by quest_no_target)


def check_target_named_in_dialogue(record) -> Optional[str]:
    """P-E: Return a signal tag if the quest target's category or material
    adjective is not mentioned in any dialogue line, AND carryables exist.

    Returns "target_not_named_in_dialogue" if violated, None if clean."""
    spec = getattr(record, "quest_spec", None)
    manifest = getattr(record, "manifest", None) or []
    if not isinstance(spec, dict) or not manifest:
        return None
    # Only fire when carryables exist in the manifest
    has_carryable = any(
        e.get("category") in _CARRYABLE_CATEGORIES for e in manifest
    )
    if not has_carryable:
        return None
    target_id = spec.get("target_entity", "")
    category = ""
    material_adj = ""
    for entry in manifest:
        if entry.get("id") == target_id:
            category = entry.get("category", "")
            mat = entry.get("material", "")
            # Map material to adjective (same mapping as behaviour_gen)
            material_adj = {
                "worn_oak": "wooden",
                "dark_walnut": "dark",
                "weathered_pine": "pine",
                "rough_granite": "stone",
                "wrought_iron": "brass",
            }.get(mat, mat)
            break
    if not category:
        return None

    dialogue = spec.get("dialogue", {})
    # Check if category OR adjective appears in any dialogue line
    all_lines = " ".join(str(v) for v in dialogue.values() if v).lower()
    if category.lower() in all_lines or material_adj.lower() in all_lines:
        return None
    return "target_not_named_in_dialogue"


# P-K: decor-never-target tag in SIGNAL_SEVERITY ──────────────────────
SIGNAL_SEVERITY["decor_never_target"] = "high"
SIGNAL_SEVERITY["headless_not_clean"] = "high"
# P-E: carryable targeting signals
SIGNAL_SEVERITY["target_not_carryable"] = "high"
SIGNAL_SEVERITY["target_not_named_in_dialogue"] = "high"
# C-0: room control signals
SIGNAL_SEVERITY["guards_violated"] = "high"
SIGNAL_SEVERITY["theme_out_of_bounds"] = "high"
# P-G: painting mode + per-theme lighting signals
SIGNAL_SEVERITY["painting_mode_honored"] = "low"
SIGNAL_SEVERITY["lighting_not_theme_aware"] = "high"
# C-2: multi-item inventory signal
SIGNAL_SEVERITY["multi_item_possible"] = "low"


# ═══════════════════════════════════════════════════════════════════════
#  B0: Multi-NPC winnable/reachability oracle
# ═══════════════════════════════════════════════════════════════════════

def check_all_npcs_winnable(record) -> Optional[str]:
    """B0: Return 'quest_all_npcs_winnable' if every NPC in the quest
    specs has a target that is both gettable (exists in manifest AND is
    a carryable category) and deliverable (NPC role present + objective
    type is fetch).

    This is a POSITIVE signal — it fires when the quest is structurally
    winnable.  Its ABSENCE in a multi-NPC record flags a broken quest.
    Low severity (informative / oracle-assertion).
    """
    # Get all quest specs for this record
    specs = getattr(record, "quest_specs", None)
    if not specs:
        # Single spec fallback
        single = getattr(record, "quest_spec", None)
        if single and isinstance(single, dict):
            specs = [single]

    if not specs or not isinstance(specs, (list, tuple)):
        return None

    manifest = getattr(record, "manifest", None) or []
    if not manifest:
        return None

    manifest_ids = {e.get("id") for e in manifest if "id" in e}
    manifest_cats = {e.get("id"): e.get("category", "") for e in manifest if "id" in e}

    for spec in specs:
        if not isinstance(spec, dict):
            return None  # malformed spec — can't assert winnable

        target_id = spec.get("target_entity", "")
        npc_role = spec.get("npc_role", "")
        obj = spec.get("objective", {})

        # Target must exist in manifest
        if target_id not in manifest_ids:
            return None

        # Target must be carryable (gettable)
        cat = manifest_cats.get(target_id, "")
        if cat not in _CARRYABLE_CATEGORIES:
            return None

        # NPC must have a role (deliverable)
        if not npc_role or not str(npc_role).strip():
            return None

        # Objective must be fetch (deliverable to NPC)
        if obj.get("type") != "fetch":
            return None

    # All NPCs pass → quest is structurally winnable
    return "quest_all_npcs_winnable"

# B0: winnable oracle
SIGNAL_SEVERITY["quest_all_npcs_winnable"] = "low"
# EB-7: multi-NPC target integrity
SIGNAL_SEVERITY["multi_npc_distinct_targets"] = "high"
SIGNAL_SEVERITY["insufficient_carryables_for_npcs"] = "high"
# EB-7: material variety
SIGNAL_SEVERITY["room_not_monochrome"] = "low"
SIGNAL_SEVERITY["fabric_in_fabric_themes"] = "low"

# ═══════════════════════════════════════════════════════════════════════
#  Spine Slice 2: dialogue-not-all-canned signal
# ═══════════════════════════════════════════════════════════════════════


def check_dialogue_not_all_canned(record) -> Optional[str]:
    """Spine Slice 2: Return 'dialogue_not_all_canned' when at least one
    NPC's dialogue source is 'model' or 'grammared' (i.e. the build is
    NOT 100% canned fallbacks).

    Positive signal — fires when the pipeline produced at least some
    real themed dialogue.  Returns None when every NPC is canned
    (every NPC has a quest.missing_npc decision and no
    quest.npc_grammared_fallback or original model data).
    """
    decisions = getattr(record, "decisions", None) or []
    npc_count = getattr(record, "npc_count", 1)

    # Collect dialogue source per NPC from decisions
    canned_npcs: set[str] = set()
    grammared_npcs: set[str] = set()
    model_npcs: set[str] = set()

    for d in decisions:
        code = d.get("code", "") if isinstance(d, dict) else getattr(d, "code", "")
        ctx = d.get("context", {}) if isinstance(d, dict) else getattr(d, "context", {})
        npc_id = ctx.get("npc_id", "")
        if not npc_id:
            continue
        if code == "quest.missing_npc":
            canned_npcs.add(npc_id)
        elif code == "quest.npc_grammared_fallback":
            grammared_npcs.add(npc_id)

    # Any NPC NOT in canned or grammared = had model output
    for i in range(npc_count):
        npc_id_loop = f"npc_{i}"
        if npc_id_loop not in canned_npcs and npc_id_loop not in grammared_npcs:
            model_npcs.add(npc_id_loop)

    # Positive when at least one NPC is model or grammared
    if model_npcs or grammared_npcs:
        return "dialogue_not_all_canned"
    return None


SIGNAL_SEVERITY["dialogue_not_all_canned"] = "low"
