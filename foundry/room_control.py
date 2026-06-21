"""room_control — deterministic control layer over RoomPlanner (C-0).

Per-theme tables restrict what the LLM can choose; global guards clamp
the final plan.  The LLM fills *within* the table; guards emit Decision
Points when they correct the output.  Stochastic variety is preserved
inside the rules.

Decor categories (rug, painting) always pass through — they aren't
counted toward density and aren't restricted by theme tables.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from category_registry import BASE_FURNITURE, CARRYABLES, DECOR_CATEGORIES
from decisions import Choice, DecisionPoint

# ── Fabric family materials ─────────────────────────────────────────
# These are soft materials that should only be applied to chairs,
# rugs, and other soft-goods categories — never to hard furniture
# like tables or shelves.
_FABRIC_MATERIALS = frozenset({"linen", "wool", "silk"})

# ── Hard furniture categories (should never get fabric) ────────────
_FABRIC_SAFE_CATEGORIES = frozenset({"chair", "rug", "stool", "bench"})

# ── Theme tables ───────────────────────────────────────────────────
# Each row: required props (furniture only), allowed palette,
# density range (furniture only), must-include.
# The LLM output is validated/clamped against the matched row.
# Decor categories always pass through.

THEME_TABLE: List[dict] = [
    {
        "theme": "hermit",
        "required_categories": ("table", "chair", "shelf"),
        "allowed_palette": ("worn_oak", "rough_granite"),
        "density": {"min": 3, "max": 8},
        "must_include": ("chair",),
    },
    {
        "theme": "blacksmith",
        "required_categories": ("table", "cabinet", "shelf"),
        "allowed_palette": ("rough_granite", "wrought_iron"),
        "density": {"min": 4, "max": 12},
        "must_include": ("cabinet",),
    },
    {
        "theme": "wizard",
        "required_categories": ("table", "shelf", "cabinet"),
        "allowed_palette": ("worn_oak", "rough_granite", "wrought_iron"),
        "density": {"min": 4, "max": 10},
        "must_include": ("shelf",),
    },
    {
        "theme": "kitchen",
        "required_categories": ("table", "chair", "cabinet", "shelf"),
        "allowed_palette": ("worn_oak", "wrought_iron", "linen"),
        "density": {"min": 5, "max": 15},
        "must_include": ("table", "chair"),
    },
    {
        "theme": "noble",
        "required_categories": ("table", "chair", "cabinet"),
        "allowed_palette": ("worn_oak", "rough_granite", "silk", "wool"),
        "density": {"min": 3, "max": 8},
        "must_include": ("table",),
    },
    {
        "theme": "dungeon",
        "required_categories": ("shelf", "cabinet"),
        "allowed_palette": ("rough_granite", "wrought_iron"),
        "density": {"min": 2, "max": 6},
        "must_include": (),
    },
    {
        "theme": "attic",
        "required_categories": ("table", "shelf"),
        "allowed_palette": ("worn_oak",),
        "density": {"min": 3, "max": 10},
        "must_include": (),
    },
    {
        "theme": "ship",
        "required_categories": ("table", "shelf"),
        "allowed_palette": ("worn_oak", "wrought_iron"),
        "density": {"min": 2, "max": 6},
        "must_include": ("table",),
    },
    {
        "theme": "*",
        "required_categories": ("table", "chair", "shelf", "cabinet"),
        "allowed_palette": ("worn_oak", "rough_granite", "wrought_iron", "linen", "wool", "silk"),
        "density": {"min": 2, "max": 10},
        "must_include": (),
    },
]

# ── Global guards ──────────────────────────────────────────────────

_GLOBAL_MIN_DENSITY = 1
_GLOBAL_MAX_DENSITY = 20
_COUNT_HI = 8           # per-category max (mirrors RoomPlanner.COUNT_HI)
_DECOR_CATEGORIES = DECOR_CATEGORIES
# Theme tables only gate the BASE furniture categories. Carryables (P-E) and the
# extended prop set (P-F) pass through every theme — the theme still biases their
# palette/density — so they actually appear in rooms (and a carryable target exists).
_BASE_FURNITURE = BASE_FURNITURE
_AT_LEAST_ONE_SEAT = True


def _match_theme(request: str) -> dict:
    """Return the first matching theme row for *request* (case-insensitive
    keyword match), or the '*' default."""
    req_lower = request.lower()
    for row in THEME_TABLE:
        theme_kw = row["theme"]
        if theme_kw == "*":
            continue
        if theme_kw in req_lower:
            return row
    for row in THEME_TABLE:
        if row["theme"] == "*":
            return row
    return THEME_TABLE[-1]


def apply_rules(
    plan: dict, request: str,
    npc_count: int = 1,
) -> Tuple[dict, List[DecisionPoint]]:
    """Post-process an LLM-generated room plan against theme rules and
    global guards.  Returns (clamped_plan, decisions).

    Decor categories (rug, painting) always pass through unchanged.
    Guards clamp counts AND emit Decision Points.

    EB-7: *npc_count* drives the carryable-injection guard — a
    multi-NPC room must have at least that many distinct carryables.
    """
    decisions: List[DecisionPoint] = []
    row = _match_theme(request)

    room_size = dict(plan.get("room_size", {"w": 6.0, "d": 6.0}))
    props: list[dict] = list(plan.get("props", []) or [])

    allowed_cats = set(row["required_categories"])
    allowed_palette = row["allowed_palette"]
    density_lo = row["density"]["min"]
    density_hi = row["density"]["max"]
    must_include = set(row["must_include"])

    # ── 1. Filter & clamp per-prop ──────────────────────────
    clamped_props: list[dict] = []
    decor_props: list[dict] = []
    dropped_cats: set[str] = set()
    for p in props:
        cat = p.get("category", "")
        # Decor always passes through
        if cat in _DECOR_CATEGORIES:
            mat = p.get("material", "worn_oak")
            cnt = int(p.get("count", 1))
            decor_props.append(
                {"category": cat, "material": mat, "count": cnt}
            )
            continue
        # Drop only out-of-theme BASE furniture; carryables + extended props
        # pass through (they aren't theme-restricted — they fit any room).
        if cat in _BASE_FURNITURE and cat not in allowed_cats:
            dropped_cats.add(cat)
            continue
        # Clamp material to palette
        mat = p.get("material", allowed_palette[0])
        if mat not in allowed_palette:
            decisions.append(DecisionPoint(
                code="room.material_out_of_palette",
                technical=f"material {mat} → {allowed_palette[0]}",
                plain=f"Replaced {mat} with {allowed_palette[0]}",
                stage="control", severity="assumption",
                context={"category": cat, "raw": mat,
                         "resolved": allowed_palette[0]},
                choices=[Choice(label=f"Use {allowed_palette[0]}",
                                plain=f"Use {allowed_palette[0]}",
                                apply={"material": allowed_palette[0]})],
            ))
            mat = allowed_palette[0]
        # Clamp count to per-category max
        cnt = int(p.get("count", 1))
        clamped_cnt = min(max(cnt, 1), _COUNT_HI)
        if clamped_cnt != cnt:
            decisions.append(DecisionPoint(
                code="room.count_clamped",
                technical=f"count {cat}={cnt} → {clamped_cnt}",
                plain=f"Clamped {cat} count to {clamped_cnt}",
                stage="control", severity="assumption",
                context={"category": cat, "raw": cnt, "clamped": clamped_cnt},
                choices=[Choice(label=f"Use {clamped_cnt}",
                                plain=f"Use {clamped_cnt}",
                                apply={"count": clamped_cnt})],
            ))
        clamped_props.append(
            {"category": cat, "material": mat, "count": clamped_cnt}
        )

    # EB-7: Drop fabric from non-fabric-safe furniture
    # Fabric should only appear on chairs, rugs, stools, benches —
    # never on hard furniture like tables, shelves, or cabinets.
    fabric_dropped_count = 0
    for p in clamped_props:
        cat = p.get("category", "")
        mat = p.get("material", "")
        if mat in _FABRIC_MATERIALS and cat not in _FABRIC_SAFE_CATEGORIES:
            # Swap to first non-fabric palette material
            alt = next((m for m in allowed_palette if m not in _FABRIC_MATERIALS), allowed_palette[0])
            p["material"] = alt
            fabric_dropped_count += 1
    if fabric_dropped_count > 0:
        decisions.append(DecisionPoint(
            code="room.fabric_on_hard_furniture",
            technical=f"swapped fabric→non-fabric on {fabric_dropped_count} hard-furniture props",
            plain=f"Replaced fabric with appropriate material on {fabric_dropped_count} props",
            stage="control", severity="assumption",
            context={"count": fabric_dropped_count},
            choices=[Choice(label="Accept", plain="Accept", apply={})],
        ))

    # EB-7: Clamp decor materials to theme palette
    # Rugs and paintings currently bypass the palette — but rugs
    # should use fabric where the theme allows it.
    for p in decor_props:
        mat = p.get("material", "")
        if mat not in allowed_palette:
            # Try to pick a fabric if available (suitable for rugs)
            fabric_opts = [m for m in allowed_palette if m in _FABRIC_MATERIALS]
            if fabric_opts:
                p["material"] = fabric_opts[0]
            else:
                p["material"] = allowed_palette[0]

    if dropped_cats:
        decisions.append(DecisionPoint(
            code="room.category_dropped",
            technical=f"dropped {sorted(dropped_cats)}",
            plain=f"Dropped out-of-theme: {sorted(dropped_cats)}",
            stage="control", severity="assumption",
            context={"dropped": sorted(dropped_cats)},
            choices=[Choice(label="Accept", plain="Accept",
                            apply={})],
        ))

    # ── 2. Global density guard ──────────────────────────────
    furniture_total = sum(p["count"] for p in clamped_props)
    if furniture_total < density_lo:
        decisions.append(DecisionPoint(
            code="room.density_too_low",
            technical=f"total={furniture_total} < min={density_lo}",
            plain=f"Room has {furniture_total} items (min {density_lo})",
            stage="control", severity="ambiguous",
            context={"total": furniture_total, "min": density_lo},
            choices=[Choice(label="Accept", plain="Accept", apply={})],
        ))
    if furniture_total > _GLOBAL_MAX_DENSITY:
        # Clamp: reduce counts proportionally to fit max
        scale = _GLOBAL_MAX_DENSITY / furniture_total
        for p in clamped_props:
            p["count"] = max(1, int(p["count"] * scale))
        decisions.append(DecisionPoint(
            code="room.density_clamped",
            technical=f"total={furniture_total} > max={_GLOBAL_MAX_DENSITY}",
            plain=f"Clamped room from {furniture_total} to {_GLOBAL_MAX_DENSITY} items",
            stage="control", severity="ambiguous",
            context={"raw": furniture_total, "max": _GLOBAL_MAX_DENSITY},
            choices=[Choice(label="Accept", plain="Accept", apply={})],
        ))

    # ── 3. At-least-one-seat guard ───────────────────────────
    if _AT_LEAST_ONE_SEAT and "chair" not in {
        p["category"] for p in clamped_props
    }:
        chair_mat = allowed_palette[0]
        clamped_props.append(
            {"category": "chair", "material": chair_mat, "count": 1}
        )
        decisions.append(DecisionPoint(
            code="room.no_seat",
            technical="auto-added chair",
            plain="Auto-added one chair (at-least-one-seat guard)",
            stage="control", severity="assumption",
            context={},
            choices=[Choice(label="Accept", plain="Accept", apply={})],
        ))

    # ── 4. Must-include guard ────────────────────────────────
    present_cats = {p["category"] for p in clamped_props}
    for cat in must_include:
        if cat not in present_cats:
            mat = allowed_palette[0]
            clamped_props.append(
                {"category": cat, "material": mat, "count": 1}
            )
            decisions.append(DecisionPoint(
                code="room.must_include_missing",
                technical=f"auto-added {cat}",
                plain=f"Auto-added {cat} (must-include guard)",
                stage="control", severity="assumption",
                context={"missing": cat},
                choices=[Choice(label="Accept", plain="Accept", apply={})],
            ))

    # ── EB-7: Carryable guard for multi-NPC rooms ─────────────
    # When npc_count > 1, the room must have at least npc_count
    # distinct carryable items so each NPC can get a unique target.
    if npc_count > 1:
        carryable_in_plan = sum(
            p["count"] for p in clamped_props
            if p["category"] in CARRYABLES
        )
        if carryable_in_plan < npc_count:
            needed = npc_count - carryable_in_plan
            # Inject distinct carryable categories from the registry
            avail_carryables = [c for c in CARRYABLES if c not in {
                p["category"] for p in clamped_props
            }]
            # Prefer carryables not already in the plan
            # Use first non-fabric palette material for carryables
            mat = next((m for m in allowed_palette if m not in _FABRIC_MATERIALS), allowed_palette[0])
            for i in range(min(needed, len(avail_carryables))):
                clamped_props.append({
                    "category": avail_carryables[i],
                    "material": mat,
                    "count": 1,
                })
            remaining = needed - min(needed, len(avail_carryables))
            if remaining > 0:
                # Reuse existing carryable categories with different mat
                alt_mat = next((m for m in allowed_palette if m != mat and m not in _FABRIC_MATERIALS), mat)
                for i in range(remaining):
                    cat = CARRYABLES[i % len(CARRYABLES)]
                    clamped_props.append({
                        "category": cat,
                        "material": alt_mat if i % 2 == 0 else mat,
                        "count": 1,
                    })
            decisions.append(DecisionPoint(
                code="room.carryables_injected",
                technical=f"injected {needed} carryables for {npc_count} NPCs",
                plain=f"Added {needed} pickable items (multi-NPC room needs distinct targets)",
                stage="control", severity="assumption",
                context={"npc_count": npc_count, "injected": needed},
                choices=[Choice(label="Accept", plain="Accept", apply={})],
            ))

    # ── 5. Decor back on top ─────────────────────────────────
    clamped_props.extend(decor_props)

    # ── 6. U-5 / EB-7: Material variety guard ─────────────────
    # If the room only uses 1 material, has ≥2 furniture/carryable
    # props, and the palette has ≥2, inject a second material for
    # ~half the props so rooms aren't monochrome.
    # EB-7: Fabric materials are only applied to fabric-safe
    # categories (chairs, rugs, stools, benches), not hard furniture.
    furniture_props = [p for p in clamped_props if p["category"] not in _DECOR_CATEGORIES]
    used_materials = {p["material"] for p in clamped_props}
    if len(used_materials) == 1 and len(allowed_palette) >= 2 and len(furniture_props) >= 2:
        current_mat = next(iter(used_materials))
        # EB-7: prefer non-fabric alternates; only pick fabric for
        # fabric-safe categories
        non_fabric_alts = [m for m in allowed_palette if m != current_mat and m not in _FABRIC_MATERIALS]
        fabric_alts = [m for m in allowed_palette if m != current_mat and m in _FABRIC_MATERIALS]
        varied = 0
        for p in clamped_props:
            if p["category"] not in _DECOR_CATEGORIES:
                if varied > 0 and varied % 2 == 0:
                    # Pick alt: prefer fabric for fabric-safe cats
                    cat = p["category"]
                    if cat in _FABRIC_SAFE_CATEGORIES and fabric_alts:
                        p["material"] = fabric_alts[0]
                    elif non_fabric_alts:
                        p["material"] = non_fabric_alts[0]
                    else:
                        p["material"] = next(m for m in allowed_palette if m != current_mat)
                varied += 1
        if varied > 0:
            alt_used = next(
                (p["material"] for p in clamped_props
                 if p["category"] not in _DECOR_CATEGORIES and p["material"] != current_mat),
                "<none>"
            )
            decisions.append(DecisionPoint(
                code="room.material_variety_injected",
                technical=f"injected {alt_used} for material variety",
                plain=f"Added {alt_used} variation (room was monochrome)",
                stage="control", severity="assumption",
                context={"original": current_mat, "injected": alt_used},
                choices=[Choice(label="Accept", plain="Accept", apply={})],
            ))

    return {"room_size": room_size, "props": clamped_props}, decisions


# ── P-G: Per-theme lighting table ──────────────────────────────────
# Each theme maps to DirectionalLight colour+energy, ambient colour,
# and background colour.  Used by scene_compiler to vary the look
# per room theme.
# Colours are (r, g, b) tuples in [0, 1]; energy in [0, 4].

# B2: EB-5 fog/exposure per theme added to the existing LIGHTING_TABLE.
# Fog: (color_r, color_g, color_b, density, light_energy)
# Exposure: brightness multiplier (1.0 = neutral)

LIGHTING_TABLE: Dict[str, dict] = {
    "hermit": {
        "directional_color": (1.0, 0.9, 0.75),
        "directional_energy": 2.5,
        "ambient_color": (0.18, 0.16, 0.12, 1.0),
        "background_color": (0.08, 0.06, 0.04, 1.0),
        "fog_color": (0.35, 0.28, 0.2, 1.0),
        "fog_density": 0.012,
        "fog_light_energy": 0.6,
        "exposure": 1.05,
    },
    "blacksmith": {
        "directional_color": (1.0, 0.7, 0.4),
        "directional_energy": 3.5,
        "ambient_color": (0.2, 0.12, 0.06, 1.0),
        "background_color": (0.1, 0.05, 0.02, 1.0),
        "fog_color": (0.45, 0.22, 0.08, 1.0),
        "fog_density": 0.02,
        "fog_light_energy": 0.8,
        "exposure": 1.1,
    },
    "wizard": {
        "directional_color": (0.6, 0.7, 1.0),
        "directional_energy": 2.0,
        "ambient_color": (0.1, 0.1, 0.2, 1.0),
        "background_color": (0.04, 0.04, 0.1, 1.0),
        "fog_color": (0.12, 0.14, 0.35, 1.0),
        "fog_density": 0.015,
        "fog_light_energy": 0.5,
        "exposure": 0.9,
    },
    "kitchen": {
        "directional_color": (1.0, 0.95, 0.8),
        "directional_energy": 2.8,
        "ambient_color": (0.2, 0.18, 0.14, 1.0),
        "background_color": (0.08, 0.07, 0.05, 1.0),
        "fog_color": (0.3, 0.25, 0.18, 1.0),
        "fog_density": 0.008,
        "fog_light_energy": 0.7,
        "exposure": 1.1,
    },
    "noble": {
        "directional_color": (1.0, 0.85, 0.65),
        "directional_energy": 3.0,
        "ambient_color": (0.15, 0.12, 0.08, 1.0),
        "background_color": (0.06, 0.04, 0.02, 1.0),
        "fog_color": (0.25, 0.2, 0.1, 1.0),
        "fog_density": 0.01,
        "fog_light_energy": 0.6,
        "exposure": 1.05,
    },
    "dungeon": {
        "directional_color": (0.5, 0.55, 0.7),
        "directional_energy": 1.2,
        "ambient_color": (0.06, 0.06, 0.1, 1.0),
        "background_color": (0.02, 0.02, 0.04, 1.0),
        "fog_color": (0.08, 0.08, 0.13, 1.0),
        "fog_density": 0.03,
        "fog_light_energy": 0.3,
        "exposure": 0.75,
    },
    "attic": {
        "directional_color": (0.9, 0.85, 0.8),
        "directional_energy": 1.8,
        "ambient_color": (0.12, 0.11, 0.1, 1.0),
        "background_color": (0.05, 0.04, 0.03, 1.0),
        "fog_color": (0.25, 0.22, 0.15, 1.0),
        "fog_density": 0.018,
        "fog_light_energy": 0.5,
        "exposure": 0.95,
    },
    "ship": {
        "directional_color": (0.7, 0.8, 1.0),
        "directional_energy": 2.2,
        "ambient_color": (0.1, 0.13, 0.18, 1.0),
        "background_color": (0.04, 0.06, 0.1, 1.0),
        "fog_color": (0.15, 0.2, 0.3, 1.0),
        "fog_density": 0.014,
        "fog_light_energy": 0.55,
        "exposure": 1.0,
    },
    "*": {
        "directional_color": (1.0, 0.95, 0.85),
        "directional_energy": 2.5,
        "ambient_color": (0.15, 0.15, 0.2, 1.0),
        "background_color": (0.05, 0.05, 0.1, 1.0),
        "fog_color": (0.2, 0.18, 0.22, 1.0),
        "fog_density": 0.015,
        "fog_light_energy": 0.5,
        "exposure": 1.0,
    },
}


def get_lighting(theme: str) -> dict:
    """P-G: Return the (directional_color, directional_energy, ambient,
    background) for *theme* (case-insensitive keyword match, '*' default)."""
    theme_lower = theme.lower()
    for key, entry in LIGHTING_TABLE.items():
        if key == "*":
            continue
        if key in theme_lower:
            return entry
    return LIGHTING_TABLE["*"]


def check_guards_violated(decisions: List[DecisionPoint]) -> bool:
    """C-0 eval: True if any guard emitted a Decision Point (i.e. the
    LLM output needed correction beyond theme-appropriate variation)."""
    for d in (decisions or []):
        code = d.code if hasattr(d, "code") else d.get("code", "")
        if code.startswith("room."):
            return True
    return False
