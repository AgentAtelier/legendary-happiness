"""Brief schema v1 — the shared structured intent (spine slice 1).

One structured Brief sits between the prompt and every generator.
The Interpreter produces it; every generator consumes it; the Build
Report reflects it back.

This module owns the schema shape, closed-vocab constants, and
deterministic validation — no LLM calls.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from decisions import Choice, DecisionPoint, make_decision

# Tiny stopword set for the feature subsumption guard — articles/preposition
# noise that shouldn't count when deciding if a feature merely restates the
# setting/theme/a character.
_STOPWORDS = {"a", "an", "the", "of", "with", "and", "s", "in", "on"}


def _content_words(text: str) -> set[str]:
    """Lowercase content words of *text* (punctuation stripped, stopwords and
    1-char tokens dropped). Used to test whether a key_feature is subsumed by
    what the Brief already understood."""
    return {
        w for w in re.split(r"[^a-z0-9]+", (text or "").lower())
        if w and len(w) > 1 and w not in _STOPWORDS
    }

# ── Closed vocabularies (imported live, not hardcoded) ─────────────

from room_control import THEME_TABLE  # noqa: E402

THEMES: Tuple[str, ...] = tuple(r["theme"] for r in THEME_TABLE)

from room_planner import CATEGORIES  # noqa: E402

VALID_SCALES: Tuple[str, ...] = ("small", "medium", "large")

# Size band mapping: scale → (min, max) metres for the room.
SCALE_BANDS: dict = {"small": (4, 6), "medium": (6, 9), "large": (9, 12)}


# ── Brief.minimal (tiny constructor, back-compat) ──────────────────


def _infer_theme(prompt: str) -> str:
    """Case-insensitive substring match against THEMES, else '*'."""
    prompt_lower = prompt.lower()
    for theme in THEMES:
        if theme == "*":
            continue
        if theme in prompt_lower:
            return theme
    return "*"


def minimal(prompt: str) -> dict:
    """Build a valid Brief v2 from a raw prompt string.

    Used as a back-compat pass-through when no LLM Interpreter is
    available (tests, fallback paths).
    """
    return {
        "schema_version": 2,
        "source_prompt": prompt,
        "setting": prompt,
        "mood": [],
        "scale": "medium",
        "theme_tag": _infer_theme(prompt),
        "key_features": [],
        "unmapped": [],
        "characters": [],
        "exterior": {"enabled": False},
        "place_names": {"scene_name": "", "landmark_lore": []},
    }


# ── json schema (Spine Fix — constrains structured LLM output) ──────


def brief_json_schema() -> dict:
    """Build a json_schema for the Brief shape, importing live vocabularies
    so it never drifts from the engine's truth."""
    return {
        "type": "object",
        "properties": {
            "setting": {"type": "string"},
            "mood": {"type": "array", "items": {"type": "string"}},
            "scale": {"enum": list(VALID_SCALES)},
            "theme_tag": {"enum": list(THEMES)},  # 12 themes + "*"
            "key_features": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "category": {"type": ["string", "null"]},
                    },
                    "required": ["text"],
                },
            },
            "characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "note": {"type": ["string", "null"]},
                        "soul": {
                            "type": "object",
                            "properties": {
                                "substrate": {
                                    "type": "object",
                                    "properties": {
                                        "courage": {"type": "number"},
                                        "generosity": {"type": "number"},
                                        "stability": {"type": "number"},
                                    },
                                },
                            },
                        },
                    },
                    "required": ["role"],
                },
            },
            "exterior": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean"},
                    "structure": {"type": "string"},
                    "biome_recipe": {"type": "object"},
                },
            },
            "place_names": {
                "type": "object",
                "properties": {
                    "scene_name": {"type": "string"},
                    "landmark_lore": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
        "required": ["setting", "scale", "theme_tag", "key_features", "characters"],
    }


# ── validate_brief ─────────────────────────────────────────────────


def validate_brief(
    raw: dict,
    themes: Tuple[str, ...] = THEMES,
    categories: Tuple[str, ...] = CATEGORIES,
) -> Tuple[dict, List[DecisionPoint]]:
    """Normalise and validate a raw dict into a clean Brief dict.

    Every deviation from the closed vocabularies emits a Decision Point
    instead of raising.  Returns ``(brief_dict, decisions)``.
    """
    decisions: List[DecisionPoint] = []

    # --- schema_version (always 1) ---
    brief: dict = {"schema_version": raw.get("schema_version", 1)}

    # --- source_prompt (preserve provenance) ---
    brief["source_prompt"] = raw.get("source_prompt", "")

    # --- theme_tag (closed set + '*' fallback) ---
    raw_theme = raw.get("theme_tag")
    theme_tag = str(raw_theme).strip().lower() if raw_theme is not None else ""
    if not theme_tag or theme_tag not in themes:
        decisions.append(
            make_decision(
                "brief.theme_unmapped",
                stage="interpreter",
                severity="assumption",
                context={"requested": theme_tag or "<empty>", "resolved": "*"},
                choices=(
                    Choice(
                        label="Accept",
                        plain="Use '*' (general room)",
                        apply={"field": "theme_tag", "value": "*"},
                    ),
                ),
            )
        )
        theme_tag = "*"
    brief["theme_tag"] = theme_tag

    # --- scale (enum) ---
    scale = raw.get("scale", "")
    scale = str(scale).strip().lower() if scale else ""
    if scale not in VALID_SCALES:
        decisions.append(
            make_decision(
                "brief.scale_defaulted",
                stage="interpreter",
                severity="assumption",
                context={"requested": scale or "<empty>", "resolved": "medium"},
                choices=(
                    Choice(
                        label="Accept medium",
                        plain="Use a medium-sized room",
                        apply={"field": "scale", "value": "medium"},
                    ),
                ),
            )
        )
        scale = "medium"
    brief["scale"] = scale

    # --- setting (free text, defaulted if empty) ---
    setting = raw.get("setting", "")
    setting = str(setting).strip() if setting else ""
    if not setting:
        resolved_setting = f"a {theme_tag} room" if theme_tag != "*" else "a room"
        decisions.append(
            make_decision(
                "brief.setting_defaulted",
                stage="interpreter",
                severity="assumption",
                context={"resolved": resolved_setting},
                choices=(
                    Choice(
                        label="Accept",
                        plain=f"Use '{resolved_setting}' as the room name",
                        apply={"field": "setting", "value": resolved_setting},
                    ),
                ),
            )
        )
        setting = resolved_setting
    brief["setting"] = setting

    # --- mood (free-text list) ---
    mood = raw.get("mood", [])
    brief["mood"] = list(mood) if isinstance(mood, (list, tuple)) else []

    # --- characters (open vocabulary, keep verbatim) ---
    from soul import default_soul, validate_soul  # noqa: E402
    raw_characters = raw.get("characters", []) or []
    validated_characters: list[dict] = []
    for ch in raw_characters:
        if not isinstance(ch, dict):
            continue
        role_val = ch.get("role", "")
        # Guard: None → treat as empty (not "None" string)
        if role_val is None:
            continue
        role = str(role_val).strip()
        if not role:
            continue  # drop empty-role entries silently
        note = ch.get("note")
        note = str(note).strip() if note else None
        # Spine Slice 3: validate soul per character
        raw_soul = ch.get("soul", {})
        if isinstance(raw_soul, dict) and raw_soul:
            char_soul, soul_decisions = validate_soul(raw_soul)
            decisions.extend(soul_decisions)
        else:
            char_soul = default_soul()
        validated_characters.append({
            "role": role,
            "note": note,
            "soul": char_soul,
        })
    brief["characters"] = validated_characters

    # --- key_features (validate each) ---
    raw_features = raw.get("key_features", []) or []
    brief["unmapped"] = list(raw.get("unmapped", [])) or []

    # Subsumption terms: what the Brief already represents (theme/setting/
    # characters). An "unmapped" feature whose words are all covered by these
    # merely restates something we DID handle (e.g. "blacksmith's forge",
    # "an apprentice") — we drop it silently rather than contradict the build
    # report with "I can't build a blacksmith's forge" right after building one.
    understood_terms: set[str] = set()
    understood_terms |= _content_words(brief["theme_tag"])
    understood_terms |= _content_words(brief["setting"])
    for ch in brief["characters"]:
        understood_terms |= _content_words(ch["role"])

    validated_features: list[dict] = []
    for feat in raw_features:
        if not isinstance(feat, dict):
            continue
        text = str(feat.get("text", "")).strip()
        if not text:
            continue
        cat = feat.get("category")
        cat = str(cat).strip() if cat else None
        # Drop features that merely restate the setting/theme/a character
        # before they reach the "unmapped"/couldn't-do path.
        if (not cat or cat not in categories):
            fwords = _content_words(text)
            if fwords and fwords <= understood_terms:
                continue
        if cat and cat not in categories:
            # Feature named something we can't map
            decisions.append(
                make_decision(
                    "brief.feature_unmapped",
                    stage="interpreter",
                    severity="error",
                    context={"text": text},
                    choices=(
                        Choice(
                            label="Skip feature",
                            plain=f"Skip '{text}' (not supported yet)",
                            apply={"field": "key_features", "text": text},
                        ),
                    ),
                )
            )
            validated_features.append(
                {"text": text, "status": "unmapped", "category": None}
            )
            if text not in brief["unmapped"]:
                brief["unmapped"].append(text)
        elif cat:
            validated_features.append(
                {"text": text, "status": "mapped", "category": cat}
            )
        else:
            # No category at all → unmapped
            decisions.append(
                make_decision(
                    "brief.feature_unmapped",
                    stage="interpreter",
                    severity="error",
                    context={"text": text},
                    choices=(
                        Choice(
                            label="Skip feature",
                            plain=f"Skip '{text}' (not mapped to a category)",
                            apply={"field": "key_features", "text": text},
                        ),
                    ),
                )
            )
            validated_features.append(
                {"text": text, "status": "unmapped", "category": None}
            )
            if text not in brief["unmapped"]:
                brief["unmapped"].append(text)

    brief["key_features"] = validated_features

    # --- exterior (light normalize; heavy validation lives in biome_recipe /
    #     exterior_planner, which consume the raw biome_recipe downstream) ---
    ext = raw.get("exterior")
    if isinstance(ext, dict):
        norm_ext: dict = {"enabled": bool(ext.get("enabled", False))}
        if ext.get("structure"):
            norm_ext["structure"] = str(ext["structure"])
        if isinstance(ext.get("biome_recipe"), dict):
            norm_ext["biome_recipe"] = ext["biome_recipe"]
        brief["exterior"] = norm_ext
    else:
        brief["exterior"] = {"enabled": False}

    # --- place_names (text flavor; normalized pass-through) ---
    pn = raw.get("place_names")
    if isinstance(pn, dict):
        lore = pn.get("landmark_lore")
        brief["place_names"] = {
            "scene_name": str(pn.get("scene_name", "") or ""),
            "landmark_lore": [x for x in lore if isinstance(x, dict)] if isinstance(lore, list) else [],
        }
    else:
        brief["place_names"] = {"scene_name": "", "landmark_lore": []}

    return brief, decisions
