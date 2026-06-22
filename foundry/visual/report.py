"""V Task 4: Visual report builder + baseline + regression delta.

``render_visual_report(items) -> dict`` produces a worst-first ranked
report (most flagged → least) with both JSON and Markdown output.

``save_baseline(items, path)`` / ``load_baseline(path)`` persist and
restore a visual baseline.

``regression_delta(current, baseline) -> dict`` compares current results
against a baseline, flagging items that got better, worse, or regressed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from eval.visual import compute_visual_signals


# ── Public API ───────────────────────────────────────────────────

def render_visual_report(
    items: List[Dict[str, Any]],
    *,
    title: str = "Visual Eval Report",
) -> Dict[str, Any]:
    """Build a visual report from a list of scored items.

    Each item MUST have:
      - ``id`` (str) — unique identifier (prop name, scene name, etc.)
      - ``checks`` (dict) — VLM check results from ``check_image()``
      - ``aesthetic`` (dict or None) — result from ``aesthetic_score()``

    Returns:
        ``{"json": dict, "md": str}`` — the report in both formats.
    """
    # Compute signals for each item + sort worst-first
    scored = []
    for item in items:
        signals = compute_visual_signals(
            item.get("checks", {}),
            item.get("aesthetic"),
        )
        scored.append({
            "id": item.get("id", "?"),
            "signals": signals,
        })

    # Sort worst-first: most flags, then lowest aesthetic (None sorts last)
    scored.sort(key=_sort_key, reverse=True)

    report_json = _build_json(scored, title)
    report_md = _build_md(scored, title)

    return {"json": report_json, "md": report_md}


def save_baseline(items: List[Dict[str, Any]], path: str) -> None:
    """Persist current visual results as a baseline JSON file.

    Stores ``{id: {signals}}`` keyed by item id for fast lookup.
    """
    baseline: Dict[str, Any] = {}
    for item in items:
        signals = compute_visual_signals(
            item.get("checks", {}),
            item.get("aesthetic"),
        )
        baseline[item.get("id", "?")] = signals
    Path(path).write_text(json.dumps(baseline, indent=2))


def load_baseline(path: str) -> Dict[str, Any]:
    """Load a previously saved baseline JSON file.

    Returns ``{id: {signals}}`` dict.  Returns empty dict if missing.
    """
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def regression_delta(
    current: List[Dict[str, Any]],
    baseline: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare current results against a baseline.

    Returns a dict with:
      - ``regressed``: list of items whose flag_count increased
      - ``improved``: list of items whose flag_count decreased
      - ``new``: items present in current but not baseline
      - ``removed``: items present in baseline but not current
      - ``aesthetic_deltas``: per-item aesthetic score change

    An item is "regressed" when its ``flag_count`` is higher than
    baseline, or its aesthetic score drops by >0.5.
    """
    regressed: List[Dict[str, Any]] = []
    improved: List[Dict[str, Any]] = []
    new_items: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    aesthetic_deltas: Dict[str, Dict[str, Any]] = {}

    current_signals: Dict[str, Dict[str, Any]] = {}
    for item in current:
        cid = item.get("id", "?")
        signals = compute_visual_signals(
            item.get("checks", {}),
            item.get("aesthetic"),
        )
        current_signals[cid] = signals

    current_ids = set(current_signals.keys())
    baseline_ids = set(baseline.keys())

    for cid in sorted(current_ids - baseline_ids):
        new_items.append({"id": cid, "signals": current_signals[cid]})

    for bid in sorted(baseline_ids - current_ids):
        removed.append({"id": bid, "signals": baseline[bid]})

    for cid in sorted(current_ids & baseline_ids):
        cur = current_signals[cid]
        prev = baseline[cid]
        delta = cur.get("flag_count", 0) - prev.get("flag_count", 0)

        cur_aes = cur.get("aesthetic_score")
        prev_aes = prev.get("aesthetic_score")
        aes_delta = None
        if isinstance(cur_aes, (int, float)) and isinstance(prev_aes, (int, float)):
            aes_delta = round(float(cur_aes) - float(prev_aes), 3)

        aesthetic_deltas[cid] = {
            "current": cur_aes,
            "previous": prev_aes,
            "delta": aes_delta,
        }

        entry = {
            "id": cid,
            "flag_count_delta": delta,
            "current_flags": cur.get("flag_count", 0),
            "previous_flags": prev.get("flag_count", 0),
            "aesthetic_delta": aes_delta,
        }

        if delta > 0 or (aes_delta is not None and aes_delta < -0.5):
            regressed.append(entry)
        elif delta < 0:
            improved.append(entry)

    return {
        "regressed": regressed,
        "improved": improved,
        "new": new_items,
        "removed": removed,
        "aesthetic_deltas": aesthetic_deltas,
    }


# ── Internal helpers ─────────────────────────────────────────────

def _sort_key(scored_item: Dict[str, Any]) -> tuple:
    """Sort key: (flag_count, -aesthetic_score).  None aesthetic → 0.

    Sorted descending (reverse=True) so worst items come first:
    most flags, then lowest aesthetic."""
    s = scored_item["signals"]
    aes = s.get("aesthetic_score")
    aes_key = aes if isinstance(aes, (int, float)) else 0
    return (s.get("flag_count", 0), -aes_key)


def _build_json(scored: List[Dict[str, Any]], title: str) -> Dict[str, Any]:
    """Build the machine-readable JSON report."""
    return {
        "title": title,
        "total": len(scored),
        "flagged_count": sum(1 for s in scored if s["signals"].get("flagged")),
        "items": [
            {"id": s["id"], "signals": s["signals"]}
            for s in scored
        ],
    }


def _build_md(scored: List[Dict[str, Any]], title: str) -> str:
    """Build the human-readable Markdown report (worst-first)."""
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")

    flagged = [s for s in scored if s["signals"].get("flagged")]
    clean = [s for s in scored if not s["signals"].get("flagged")]

    lines.append(f"- **Total items:** {len(scored)}")
    lines.append(f"- **Flagged:** {len(flagged)}")
    lines.append(f"- **Clean:** {len(clean)}")
    lines.append("")

    if flagged:
        lines.append("## Flagged (worst-first)")
        lines.append("")
        lines.append("| # | Item | Flags | Aesthetic | Notes |")
        lines.append("|---|---|---|---|---|")
        for i, s in enumerate(flagged, 1):
            sig = s["signals"]
            aes = sig.get("aesthetic_score")
            aes_str = f"{aes:.2f}" if isinstance(aes, (int, float)) else "—"
            notes = sig.get("notes", "")[:60]
            lines.append(
                f"| {i} | {s['id']} | {sig['flag_count']} | {aes_str} | {notes} |"
            )
        lines.append("")

        # Detail per flagged item
        for s in flagged:
            sig = s["signals"]
            lines.append(f"### {s['id']} ({sig['flag_count']} flag(s))")
            failures = [k for k in _BOOL_KEYS if sig.get(k) is False]
            if failures:
                lines.append(f"- **Issues:** {', '.join(failures)}")
            aes = sig.get("aesthetic_score")
            if isinstance(aes, (int, float)):
                lines.append(f"- **Aesthetic:** {aes:.2f}")
            notes = sig.get("notes", "")
            if notes:
                lines.append(f"- **Notes:** {notes}")
            lines.append("")

    if clean:
        lines.append("## Clean")
        lines.append("")
        for s in clean:
            sig = s["signals"]
            aes = sig.get("aesthetic_score")
            aes_str = f" ({aes:.2f})" if isinstance(aes, (int, float)) else ""
            lines.append(f"- {s['id']}{aes_str}")
        lines.append("")

    return "\n".join(lines) + "\n"


_BOOL_KEYS = [
    "no_floaters", "textured", "material_reads", "no_holes",
    "no_clipping", "ceiling_ok", "npcs_ok",
    "composition_ok", "theme_ok",
]
