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
from material_resolver import material_cues


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


# ── Wear lexicons (slice 2) ────────────────────────────────────────────
# Deterministic, pre-LLM signal of the user's intent for THE AGE of the
# asset.  Whole-word, case-insensitive match.  The split between AGED and
# NEW is at age = 0.4: above is "weathered/old" by convention, below is
# "fresh/new" by convention.
#
# NEW_WORDS contains both hyphen and space forms of "brand-new" — each
# entry is matched with `\b` boundaries so the hyphen entry matches ONLY
# the hyphen form and vice-versa.  This keeps the matcher a single
# whole-word regex without per-phrase rules.
AGED_WORDS: set[str] = {
    "old", "aged", "ancient", "antique", "battered", "weathered",
    "worn", "rustic", "vintage", "distressed",
}
NEW_WORDS: set[str] = {
    "new", "brand-new", "brand new",
    "pristine", "polished", "fresh", "mint", "unused",
}

_AGE_BAND_SPLIT = 0.4  # below = "fresh" intent, above = "weathered" intent


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
