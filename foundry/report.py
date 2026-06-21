"""Build Report — the legibility surface (spine slice 1).

Reflects back to the user *what was understood, assumed, and couldn't
be done* so a miss is visible and correctable, never silent.

Produces both a machine-readable dict and a human-readable string
from the Brief, pipeline Decision Points, and room manifest.
"""

from __future__ import annotations

from typing import Dict, List


def build_report_dict(
    brief: dict,
    decisions: list,
    manifest: list[dict] | None = None,
) -> dict:
    """Return a dict with four keys: ``understood``, ``built``,
    ``assumed``, ``couldnt_do``.

    Args:
        brief: A validated Brief dict (from brief.validate_brief).
        decisions: Pipeline Decision Points (flat list from all stages).
        manifest: Optional placed-entity manifest list.
    """
    manifest = manifest or []

    # ── Understood ─────────────────────────────────────────────
    understood: dict = {
        "setting": brief.get("setting", ""),
        "mood": brief.get("mood", []),
        "scale": brief.get("scale", "medium"),
        "theme_tag": brief.get("theme_tag", "*"),
    }
    mapped_texts = [
        f["text"]
        for f in brief.get("key_features", [])
        if f.get("status") == "mapped"
    ]
    understood["key_features"] = mapped_texts
    # Spine Slice 2: characters from Brief
    char_roles = [c["role"] for c in brief.get("characters", []) or [] if isinstance(c, dict) and c.get("role")]
    understood["characters"] = char_roles

    # ── Built ──────────────────────────────────────────────────
    prop_categories = sorted({e.get("category", "?") for e in manifest})
    built: dict = {
        "prop_count": len(manifest),
        "categories": prop_categories,
    }
    # Which mapped features made it into the manifest?
    feature_categories_in_manifest = set(prop_categories)
    features_built = [
        f["text"]
        for f in brief.get("key_features", [])
        if f.get("status") == "mapped"
        and f.get("category") in feature_categories_in_manifest
    ]
    built["key_features_built"] = features_built

    # Spine Slice 2: per-NPC dialogue source tags
    # Derive source from decisions: grammared > model > canned
    npc_dialogue_sources: dict[str, str] = {}
    for d in decisions:
        code = d.code if hasattr(d, "code") else d.get("code", "")
        ctx = d.context if hasattr(d, "context") else d.get("context", {})
        npc_id = ctx.get("npc_id", "")
        if not npc_id:
            continue
        if code == "quest.npc_grammared_fallback":
            npc_dialogue_sources[npc_id] = "grammared"
        elif code == "quest.missing_npc" and npc_id not in npc_dialogue_sources:
            npc_dialogue_sources[npc_id] = "canned"
    # Any NPC not tagged is "model" (from the multi-call)
    # Also fill from brief characters for NPCs with no decisions
    for i in range(max(len(npc_dialogue_sources), len(brief.get("characters", [])))):
        npc_id_loop = f"npc_{i}"
        if npc_id_loop not in npc_dialogue_sources:
            npc_dialogue_sources[npc_id_loop] = "model"
    built["npc_dialogue_sources"] = npc_dialogue_sources

    # ── Assumed ────────────────────────────────────────────────
    assumed_lines: list[str] = []
    for d in decisions:
        sev = d.severity if hasattr(d, "severity") else d.get("severity", "")
        if sev in ("assumption", "ambiguous"):
            plain = d.plain if hasattr(d, "plain") else d.get("plain", "")
            if plain:
                assumed_lines.append(plain)

    # ── Couldn't do ────────────────────────────────────────────
    couldnt_lines: list[str] = list(brief.get("unmapped", []) or [])
    for d in decisions:
        sev = d.severity if hasattr(d, "severity") else d.get("severity", "")
        if sev == "error":
            plain = d.plain if hasattr(d, "plain") else d.get("plain", "")
            if plain:
                couldnt_lines.append(plain)

    return {
        "understood": understood,
        "built": built,
        "assumed": assumed_lines,
        "couldnt_do": couldnt_lines,
    }


def render_build_report(
    brief: dict,
    decisions: list,
    manifest: list[dict] | None = None,
) -> str:
    """Return a human-readable, four-section build report string.

    Designed to be printed to stdout AND saved as
    ``builds/<scene>/build_report.txt``.
    """
    rpt = build_report_dict(brief, decisions, manifest)
    lines: list[str] = []

    # ── Understood ─────────────────────────────────────────────
    u = rpt["understood"]
    lines.append("═══ Understood ═══")
    lines.append(f"  Setting: {u['setting']}")
    if u.get("mood"):
        lines.append(f"  Mood: {', '.join(u['mood'])}")
    lines.append(f"  Scale: {u['scale']}")
    lines.append(f"  Theme: {u['theme_tag']}")
    if u.get("key_features"):
        lines.append(f"  Named features: {', '.join(u['key_features'])}")
    if u.get("characters"):
        lines.append(f"  Characters: {', '.join(u['characters'])}")

    # ── Built ──────────────────────────────────────────────────
    b = rpt["built"]
    lines.append("")
    lines.append("═══ Built ═══")
    lines.append(f"  {b['prop_count']} props placed")
    if b.get("categories"):
        lines.append(f"  Categories: {', '.join(b['categories'])}")
    if b.get("key_features_built"):
        lines.append(f"  Named features built: {', '.join(b['key_features_built'])}")
    # Spine Slice 2: quest dialogue sources
    if b.get("npc_dialogue_sources"):
        sources = b["npc_dialogue_sources"]
        lines.append("  NPC dialogue sources:")
        for npc_id in sorted(sources):
            lines.append(f"    {npc_id}: {sources[npc_id]}")

    # ── Assumed ────────────────────────────────────────────────
    if rpt["assumed"]:
        lines.append("")
        lines.append("═══ Assumed ═══")
        for item in rpt["assumed"]:
            lines.append(f"  • {item}")

    # ── Couldn't do ────────────────────────────────────────────
    if rpt["couldnt_do"]:
        lines.append("")
        lines.append("═══ Couldn't do ═══")
        for item in rpt["couldnt_do"]:
            lines.append(f"  • {item}")

    lines.append("")
    return "\n".join(lines)
