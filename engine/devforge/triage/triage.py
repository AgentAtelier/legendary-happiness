"""Triage engine — parse, classify, and deduplicate Godot errors.

Tier 0: no LLM.  Classification comes from the knowledge table;
unrecognized messages get a fallback explanation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from devforge.reasoning.ai.repair.error_parser import ErrorParser, ParsedError
from devforge.triage.knowledge import KNOWN_ERRORS


@dataclass
class TriagedError:
    """A classified and explained Godot runtime error."""

    file: str
    line: int
    raw_message: str
    category: str  # from the table, or "unrecognized"
    known_id: str | None  # E01..E20, or None
    explanation: str  # table entry, or fallback
    fix_hint: str | None
    occurrence_count: int = 1

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "raw_message": self.raw_message,
            "category": self.category,
            "known_id": self.known_id,
            "explanation": self.explanation,
            "fix_hint": self.fix_hint,
            "occurrence_count": self.occurrence_count,
        }


def triage_text(raw_log: str) -> dict:
    """Parse a raw Godot log, classify errors, and deduplicate.

    Returns::

        {
          \"total_raw\": 5,
          \"findings\": [
            {
              \"file\": \"player.gd\", \"line\": 42,
              \"raw_message\": \"Invalid call...\",
              \"category\": \"missing_member\", \"known_id\": \"E01\",
              \"explanation\": \"...\", \"fix_hint\": \"...\",
              \"occurrence_count\": 3
            }
          ],
          \"by_category\": {\"missing_member\": 1, \"unrecognized\": 1}
        }

    Findings are sorted by (file, line).  Identical errors
    (same file, line, and known_id) are counted once with an
    occurrence_count.
    """
    # Parse raw log into structured errors
    parser = ErrorParser()
    try:
        parsed: list[ParsedError] = parser.parse_report_from_text(raw_log)
    except Exception as exc:
        return {
            "total_raw": 0,
            "findings": [],
            "by_category": {},
            "error": f"ErrorParser failed: {exc}",
        }

    if not parsed:
        return {
            "total_raw": 0,
            "findings": [],
            "by_category": {},
        }

    # Classify each parsed error against the knowledge table
    classified: list[TriagedError] = []
    for pe in parsed:
        triaged = _classify(pe)
        classified.append(triaged)

    # Deduplicate: same (file, line, known_id) → one entry with count
    deduped: list[TriagedError] = []
    seen: dict[tuple, TriagedError] = {}
    for te in classified:
        key = (te.file, te.line, te.known_id)
        if key in seen:
            seen[key].occurrence_count += 1
        else:
            seen[key] = te
            deduped.append(te)

    # Sort by (file, line)
    deduped.sort(key=lambda te: (te.file, te.line))

    # Build by_category counts
    by_category: dict[str, int] = {}
    for te in deduped:
        by_category[te.category] = by_category.get(te.category, 0) + 1

    return {
        "total_raw": len(parsed),
        "findings": [te.to_dict() for te in deduped],
        "by_category": by_category,
    }


def _classify(pe: ParsedError) -> TriagedError:
    """Classify a ParsedError against the knowledge table.

    First matching entry wins.  Unrecognized messages get a fallback.
    """
    for known in KNOWN_ERRORS:
        if re.search(known.pattern, pe.message, re.IGNORECASE):
            return TriagedError(
                file=pe.file or "",
                line=pe.line or 0,
                raw_message=pe.message,
                category=known.category,
                known_id=known.id,
                explanation=known.explanation,
                fix_hint=known.fix_hint,
            )

    # Fallback for unrecognized errors
    return TriagedError(
        file=pe.file or "",
        line=pe.line or 0,
        raw_message=pe.message,
        category="unrecognized",
        known_id=None,
        explanation=(
            "Unrecognized error — the knowledge table doesn't have a "
            "specific classification for this message. Read the raw "
            "message and the Godot documentation to diagnose it."
        ),
        fix_hint=None,
    )
