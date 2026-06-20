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

from decisions import Choice, DecisionPoint

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
        "allowed_palette": ("worn_oak", "wrought_iron"),
        "density": {"min": 5, "max": 15},
        "must_include": ("table", "chair"),
    },
    {
        "theme": "noble",
        "required_categories": ("table", "chair", "cabinet"),
        "allowed_palette": ("worn_oak", "rough_granite"),
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
        "allowed_palette": ("worn_oak", "rough_granite", "wrought_iron"),
        "density": {"min": 2, "max": 10},
        "must_include": (),
    },
]

# ── Global guards ──────────────────────────────────────────────────

_GLOBAL_MIN_DENSITY = 1
_GLOBAL_MAX_DENSITY = 20
_COUNT_HI = 8           # per-category max (mirrors RoomPlanner.COUNT_HI)
_DECOR_CATEGORIES = {"rug", "painting"}
# Theme tables only gate the BASE furniture categories. Carryables (P-E) and the
# extended prop set (P-F) pass through every theme — the theme still biases their
# palette/density — so they actually appear in rooms (and a carryable target exists).
_BASE_FURNITURE = {"table", "chair", "shelf", "cabinet"}
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
    plan: dict, request: str
) -> Tuple[dict, List[DecisionPoint]]:
    """Post-process an LLM-generated room plan against theme rules and
    global guards.  Returns (clamped_plan, decisions).

    Decor categories (rug, painting) always pass through unchanged.
    Guards clamp counts AND emit Decision Points.
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

    # ── 5. Decor back on top ─────────────────────────────────
    clamped_props.extend(decor_props)

    return {"room_size": room_size, "props": clamped_props}, decisions


# ── P-G: Per-theme lighting table ──────────────────────────────────
# Each theme maps to DirectionalLight colour+energy, ambient colour,
# and background colour.  Used by scene_compiler to vary the look
# per room theme.
# Colours are (r, g, b) tuples in [0, 1]; energy in [0, 4].

LIGHTING_TABLE: Dict[str, dict] = {
    "hermit": {
        "directional_color": (1.0, 0.9, 0.75),
        "directional_energy": 2.5,
        "ambient_color": (0.18, 0.16, 0.12, 1.0),
        "background_color": (0.08, 0.06, 0.04, 1.0),
    },
    "blacksmith": {
        "directional_color": (1.0, 0.7, 0.4),
        "directional_energy": 3.5,
        "ambient_color": (0.2, 0.12, 0.06, 1.0),
        "background_color": (0.1, 0.05, 0.02, 1.0),
    },
    "wizard": {
        "directional_color": (0.6, 0.7, 1.0),
        "directional_energy": 2.0,
        "ambient_color": (0.1, 0.1, 0.2, 1.0),
        "background_color": (0.04, 0.04, 0.1, 1.0),
    },
    "kitchen": {
        "directional_color": (1.0, 0.95, 0.8),
        "directional_energy": 2.8,
        "ambient_color": (0.2, 0.18, 0.14, 1.0),
        "background_color": (0.08, 0.07, 0.05, 1.0),
    },
    "noble": {
        "directional_color": (1.0, 0.85, 0.65),
        "directional_energy": 3.0,
        "ambient_color": (0.15, 0.12, 0.08, 1.0),
        "background_color": (0.06, 0.04, 0.02, 1.0),
    },
    "dungeon": {
        "directional_color": (0.5, 0.55, 0.7),
        "directional_energy": 1.2,
        "ambient_color": (0.06, 0.06, 0.1, 1.0),
        "background_color": (0.02, 0.02, 0.04, 1.0),
    },
    "attic": {
        "directional_color": (0.9, 0.85, 0.8),
        "directional_energy": 1.8,
        "ambient_color": (0.12, 0.11, 0.1, 1.0),
        "background_color": (0.05, 0.04, 0.03, 1.0),
    },
    "ship": {
        "directional_color": (0.7, 0.8, 1.0),
        "directional_energy": 2.2,
        "ambient_color": (0.1, 0.13, 0.18, 1.0),
        "background_color": (0.04, 0.06, 0.1, 1.0),
    },
    "*": {
        "directional_color": (1.0, 0.95, 0.85),
        "directional_energy": 2.5,
        "ambient_color": (0.15, 0.15, 0.2, 1.0),
        "background_color": (0.05, 0.05, 0.1, 1.0),
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
