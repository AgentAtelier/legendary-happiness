"""foundry.eval.visual — visual signal layer (V Task 4).

``compute_visual_signals(checks, aesthetic) -> dict`` is a PURE function
that translates VLM check results + an aesthetic score into flat boolean
signals.  Deterministic, no model dependencies — tested with canned inputs.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ── Public API ───────────────────────────────────────────────────

def compute_visual_signals(
    checks: Dict[str, Any],
    aesthetic: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute flat visual signal booleans from structured VLM checks
    and an optional aesthetic score.

    Args:
        checks: Dict from ``check_image()`` (vlm.py), with keys like
            ``floater``, ``textured``, ``composition_ok``, etc.
        aesthetic: Optional dict from ``aesthetic_score()``, with a
            ``score`` key.

    Returns:
        A flat dict of signals:
          - ``no_floaters`` (bool)
          - ``textured`` (bool, for props)
          - ``material_reads`` (bool, for props)
          - ``no_holes`` (bool, for props)
          - ``no_clipping`` (bool, for scenes)
          - ``ceiling_ok`` (bool, for scenes)
          - ``npcs_ok`` (bool, for scenes)
          - ``composition_ok`` (bool, for scenes)
          - ``theme_ok`` (bool, for scenes)
          - ``aesthetic_score`` (float or None)
          - ``flag_count`` (int) — how many signals are ``False``
          - ``flagged`` (bool) — True when any signal is ``False``
          - ``notes`` (str) — free-text notes from the VLM
    """
    aesthetic_score_val = _extract_aesthetic(aesthetic)

    signals: Dict[str, Any] = {}
    signals["notes"] = checks.get("notes", "")

    # ── Prop signals ─────────────────────────────────────────
    signals["no_floaters"] = not checks.get("floating_bits", False)
    signals["textured"] = checks.get("textured", True)
    signals["material_reads"] = checks.get("material_reads_right", True)
    signals["no_holes"] = not checks.get("has_holes_or_deformity", False)

    # ── Scene signals ────────────────────────────────────────
    signals["no_floaters"] = (
        signals["no_floaters"] and not checks.get("floater", False)
    )
    signals["no_clipping"] = not checks.get("clipping", False)
    signals["ceiling_ok"] = checks.get("ceiling_visible", True)
    signals["npcs_ok"] = checks.get("npcs_on_floor", True)
    signals["composition_ok"] = checks.get("composition_ok", True)
    signals["theme_ok"] = checks.get("theme_coherent", True)

    # ── Aesthetic ────────────────────────────────────────────
    signals["aesthetic_score"] = aesthetic_score_val

    # ── Flagging ─────────────────────────────────────────────
    bool_signals = [
        "no_floaters", "textured", "material_reads", "no_holes",
        "no_clipping", "ceiling_ok", "npcs_ok",
        "composition_ok", "theme_ok",
    ]
    flag_count = sum(1 for k in bool_signals if signals[k] is False)
    signals["flag_count"] = flag_count
    signals["flagged"] = flag_count > 0

    return signals


# ── Internal helpers ────────────────────────────────────────────

def _extract_aesthetic(aesthetic: Optional[Dict[str, Any]]) -> Optional[float]:
    """Extract the numeric score from an aesthetic result dict."""
    if aesthetic is None:
        return None
    if isinstance(aesthetic, dict):
        score = aesthetic.get("score")
        if isinstance(score, (int, float)):
            return float(score)
    return None
