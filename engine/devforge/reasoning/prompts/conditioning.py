"""System-owned planner conditioning — the one place that frames output quality.

A neutral user prompt yields thin output; an explicit "be ambitious / varied"
directive multiplies it. That directive must be OWNED BY THE SYSTEM, not typed by
the user — the non-coder owner should never need "magic words". This module is the
single source of truth; the pipeline prepends it to the prompt every planner sees.

Toggle (for A/B measurement): DEVFORGE_PLANNER_CONDITIONING=0 disables it. Any
other value (or unset) leaves it enabled.
"""

from __future__ import annotations

import os

# Deliberately SCOPE-AWARE: it must not pad a simple request (the "a simple wooden
# box should stay simple" objection from review) while unlocking richness when the
# request warrants it.
CONDITIONING_BLOCK = """\
SCENE QUALITY DIRECTIVE (from the system):
- Match the scope of the request. A simple request stays simple; a rich request
  becomes rich. Do not pad trivial requests, and never collapse a rich request
  into a single repeated primitive.
- When the request warrants richness, be ambitious: use a variety of element
  types, vary their positions and sizes, and include supporting detail — not only
  the one named object.
- Prefer a few meaningful, distinct elements over many identical copies."""


def conditioning_enabled() -> bool:
    """True unless DEVFORGE_PLANNER_CONDITIONING is set to '0'."""
    return os.getenv("DEVFORGE_PLANNER_CONDITIONING", "1") != "0"


def prepend_conditioning(prompt: str, enabled: bool | None = None) -> str:
    """Prepend the system conditioning directive to a planner prompt.

    Returns the prompt unchanged when disabled. When ``enabled`` is None, reads the
    env toggle; pass True/False explicitly in tests.
    """
    if enabled is None:
        enabled = conditioning_enabled()
    if not enabled:
        return prompt
    return f"{CONDITIONING_BLOCK}\n\n{prompt}"
