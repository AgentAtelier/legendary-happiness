"""foundry.eval.signals — objective signal layer (slice 1).

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
    "clean"           - the only tag set when none of the above apply.

A record with multiple tags is normal: a build that errored AND would
also be gated counts both.
"""

from __future__ import annotations

import re
from typing import List, Set

from compiler import PARAM_RANGES


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

    if record.spec is not None and isinstance(record.spec, dict):
        if _size_mismatch(record.request, record.spec):
            tags.add("size_mismatch")
        if _material_mismatch(record.request, record.spec):
            tags.add("material_mismatch")

    if not tags:
        tags.add("clean")
    return tags


def decision_codes(record) -> List[str]:
    """Return the list of Decision-Point codes on *record* (used for
    ``decision_code_freq`` aggregation in the friction report)."""
    return [d.get("code", "?") for d in (record.decisions or [])]


# ── Inner helpers ─────────────────────────────────────────────────────


def _size_mismatch(request: str, spec: dict) -> bool:
    """True when a size word in *request* expects one direction on a
    dimension and the spec sits at the opposite end of PARAM_RANGES."""
    params = spec.get("params") or {}
    generator = spec.get("generator")

    if generator is None:
        return False

    ranges_for_gen = PARAM_RANGES.get(generator, {})

    for word, (keys, expected_direction) in _SIZE_WORDS.items():
        if not _has_word(request or "", word):
            continue
        # Among the keys this word cares about, find any that exist in
        # the spec's params AND have a known range.
        for key in keys:
            if key not in params or key not in ranges_for_gen:
                continue
            lo, hi = ranges_for_gen[key]
            val = params[key]
            if not isinstance(val, (int, float)):
                # Defensive: non-numeric param — can't size-mismatch a non-value.
                continue
            if expected_direction == "high" and _is_at_low_end(val, lo, hi):
                return True
            if expected_direction == "low" and _is_at_high_end(val, lo, hi):
                return True
    return False


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
