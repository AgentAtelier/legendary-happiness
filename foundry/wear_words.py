"""Wear lexicons — shared between the eval signal layer and the age resolver.

These are the single source of truth for classifying a request's wear
intent.  Both ``foundry/eval/signals.py`` and ``foundry/age_resolver.py``
import from here — the lists are never duplicated.
"""

# ── Wear lexicons ───────────────────────────────────────────────────
# Deterministic, pre-LLM signal of the user's intent for THE AGE of the
# asset.  Whole-word, case-insensitive match.  The split between AGED and
# NEW is at age = 0.4: above is "weathered/old" by convention, below is
# "fresh/new" by convention.
#
# NEW_WORDS contains both hyphen and space forms of "brand-new" — each
# entry is matched with \b boundaries so the hyphen entry matches ONLY
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
