"""foundry.eval.augment — corpus augmentation via lexicon-driven slot-filling (Prompt 6).

Grow the eval corpus from ~60 to ~250 by building requests from
templates whose slots are filled from OUR real lexicons:

  - generator nouns (table/chair/shelf/cabinet + synonyms)
  - material keywords (from material_resolver)
  - wear words (from wear_words)

Use qwen ONLY to paraphrase a slot-combo into natural phrasing
(grammar-free — it's corpus text, not a spec).  A FAKE paraphraser
(format the template) makes the module deterministic in tests.

Also includes adversarial templates: conflicting material cues,
no-material, ambiguous nouns.

Dedup: hash-normalized (lowercase, strip punctuation/whitespace, hash;
drop collisions).

Validity: keep a request only if it plans + compiles without a hard
error.  KEEP requests that fire Decision Points (conflicts/defaults are
the valuable edge cases — do not drop them).

``--dry-run`` prints stats without writing.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from pathlib import Path

# ── Slot lexicons (single-sourced from resolver / wear_words) ─────────

_GENERATOR_NOUNS: dict[str, list[str]] = {
    "table": ["table", "desk", "coffee table", "dining table", "workbench", "side table"],
    "chair": ["chair", "stool", "seat", "dining chair", "armchair"],
    "shelf": ["shelf", "bookshelf", "bookcase", "wall shelf", "shelving unit"],
    "cabinet": ["cabinet", "cupboard", "storage cabinet", "wardrobe", "locker"],
}

# Material keywords — from the resolver itself so they always parse.
def _specific_keywords() -> list[str]:
    from material_resolver import _SPECIFIC_KW
    return list(_SPECIFIC_KW.keys())


def _family_keywords() -> list[str]:
    from material_resolver import _FAMILY_KW
    return list(_FAMILY_KW.keys())


def _aged_words() -> list[str]:
    from wear_words import AGED_WORDS
    return sorted(AGED_WORDS)


def _new_words() -> list[str]:
    from wear_words import NEW_WORDS
    return sorted(NEW_WORDS)


# Size adjectives
_SIZE_WORDS: list[str] = [
    "tall", "low", "wide", "narrow", "large", "small",
    "long", "short", "deep", "shallow", "sturdy", "heavy",
]

# Ambiguous nouns (for adversarial templates)
_AMBIG_NOUNS: list[str] = [
    "thing", "object", "item", "piece", "unit",
    "furniture", "furnishing",
]


# ── Templates ─────────────────────────────────────────────────────────
# {gen} = generator noun (e.g. "table", "desk")
# {mat} = material keyword (e.g. "oak", "wooden")
# {mat1}, {mat2} = two different-family material keywords
# {wear} = wear word (e.g. "old", "pristine")
# {size} = size word (e.g. "tall", "wide")
# {ambig} = ambiguous noun

_SYSTEMATIC_TEMPLATES: list[str] = [
    "a {gen}",
    "a {mat} {gen}",
    "a {wear} {gen}",
    "a {size} {gen}",
    "a {mat} {gen}, {wear}",
    "a {size} {mat} {gen}",
    "a {wear} {mat} {gen}",
    "a {size} {wear} {mat} {gen}",
    "a {wear} {size} {mat} {gen}",
]

_ADVERSARIAL_TEMPLATES: list[str] = [
    # Conflicting material cues (cross-family)
    "a {mat1}-look {mat2} {gen}",
    "a {mat1} {mat2} {gen}",
    # No material
    "a {ambig}",
    "give me a {gen}, {wear}",
    "make a {size} {gen}",
    # Ambiguous nouns
    "a {ambig} with legs",
    "something for storing things",
]


# ── Paraphraser ───────────────────────────────────────────────────────


def _fake_paraphrase(template: str, **slots) -> str:
    """FAKE paraphraser — just format the template.  Deterministic, for tests.

    The live paraphraser would use qwen (``FoundryLLM``) to rephrase the
    slot-combo into more natural language.  Since this is corpus text
    (not a spec), grammar-free is fine.
    """
    return template.format(**slots)


# ── Dedup ─────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation (keep spaces), collapse whitespace."""
    import re
    text = text.strip().lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _request_key(text: str) -> str:
    """Deterministic hash of the normalized request for dedup."""
    return hashlib.sha256(_normalize(text).encode()).hexdigest()[:16]


# ── Validity filter ───────────────────────────────────────────────────


def _stub_llm_for_validity():
    """A stub LLM returning a valid table spec — just enough to make
    plan() + compile_spec() succeed for any request."""
    import json as _json
    spec = _json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    })

    def _stub(prompt: str, grammar) -> str:
        return spec

    return _stub


def _is_valid(request: str, llm=None) -> bool:
    """Return True if *request* plans + compiles without a hard error.

    Uses a FAKE llm by default (entirely deterministic).  The validity
    check is cheap — it only runs the planner + compiler, no build.
    """
    if llm is None:
        llm = _stub_llm_for_validity()
    try:
        from compiler import compile_spec
        from planner import AssetPlanner
        spec, _decisions = AssetPlanner().plan(request, llm)
        compile_spec(spec)
        return True
    except Exception:
        return False


def _fires_decision(request: str, llm=None) -> bool:
    """Return True if *request* causes plan() to emit at least one
    Decision Point (conflict / default — valuable edge cases)."""
    if llm is None:
        llm = _stub_llm_for_validity()
    try:
        from planner import AssetPlanner
        _spec, decisions = AssetPlanner().plan(request, llm)
        return len(decisions) > 0
    except Exception:
        return False


# ── Core generation ───────────────────────────────────────────────────


def _all_slot_combos(rng: random.Random) -> list[dict]:
    """Generate slot-fill dicts from our real lexicons."""
    combos: list[dict] = []

    gens = list(_GENERATOR_NOUNS.keys())
    specific_kws = _specific_keywords()
    family_kws = _family_keywords()
    aged = _aged_words()
    new = _new_words()

    for gen in gens:
        nouns = _GENERATOR_NOUNS[gen]
        for noun in nouns:
            # Generator-only (no material, no wear)
            combos.append({"gen": noun})
            # With each specific material keyword
            for mat in specific_kws:
                combos.append({"gen": noun, "mat": mat})
            # With each family keyword
            for mat in family_kws:
                combos.append({"gen": noun, "mat": mat})
            # With wear
            for wear in aged:
                combos.append({"gen": noun, "wear": wear})
            for wear in new:
                combos.append({"gen": noun, "wear": wear})
            # With material + wear
            for mat in specific_kws[:4]:  # subset to avoid blowout
                for wear in aged[:3] + new[:3]:
                    combos.append({"gen": noun, "mat": mat, "wear": wear})
            # With size
            for size in rng.sample(_SIZE_WORDS, min(6, len(_SIZE_WORDS))):
                combos.append({"gen": noun, "size": size})
                # Size + material
                for mat in specific_kws[:3]:
                    combos.append({"gen": noun, "size": size, "mat": mat})

    return combos


def _adversarial_combos(rng: random.Random) -> list[dict]:
    """Generate adversarial slot-fill dicts."""
    combos: list[dict] = []
    gens = list(_GENERATOR_NOUNS.keys())
    specific_kws = _specific_keywords()

    for gen in gens:
        noun = rng.choice(_GENERATOR_NOUNS[gen])
        # Conflicting materials: pick two keywords from different families
        mat_pairs = [
            ("oak", "iron"), ("granite", "wooden"), ("walnut", "metal"),
            ("pine", "stone"), ("wrought", "wooden"), ("oak", "stone"),
        ]
        for mat1, mat2 in mat_pairs:
            combos.append({"gen": noun, "mat1": mat1, "mat2": mat2})
        # No material
        combos.append({"gen": noun})
        # Ambiguous noun
        for ambig in _AMBIG_NOUNS:
            combos.append({"ambig": ambig})
            combos.append({"gen": noun, "ambig": ambig})

    return combos


# ── Public entry point ────────────────────────────────────────────────


def augment_corpus(
    out_path: str,
    *,
    target: int = 250,
    seed: int = 1337,
    dry_run: bool = False,
    llm: Callable | None = None,
    paraphrase: Callable | None = None,
) -> tuple[list[str], dict]:
    """Generate an augmented corpus via lexicon-driven slot-filling.

    Args:
        out_path: Where to write the .txt corpus (ignored when dry_run=True).
        target: Maximum number of requests to produce (default 250).
        seed: RNG seed for reproducibility.
        dry_run: When True, print stats but don't write.
        llm: Injectable LLM for the validity/paraphrase steps.
        paraphrase: Injectable paraphraser — defaults to _fake_paraphrase
            (just formats templates).  Pass a FoundryLLM wrapper for live
            qwen paraphrasing.

    Returns:
        ``(requests, stats_dict)``.
    """
    rng = random.Random(seed)
    if paraphrase is None:
        paraphrase = _fake_paraphrase

    # 1. Generate systematic combos
    slot_combos = _all_slot_combos(rng)
    rng.shuffle(slot_combos)

    # 2. Generate adversarial combos
    adv_combos = _adversarial_combos(rng)

    # 3. Fill templates → raw requests
    raw_requests: list[str] = []

    # Systematic
    for combo in slot_combos:
        tmpl = rng.choice(_SYSTEMATIC_TEMPLATES)
        try:
            raw_requests.append(paraphrase(tmpl, **combo))
        except KeyError:
            # Template references a slot not in this combo; skip.
            continue

    # Adversarial (insert at front so they're always included)
    adv_requests: list[str] = []
    for combo in adv_combos:
        tmpl = rng.choice(_ADVERSARIAL_TEMPLATES)
        try:
            adv_requests.append(paraphrase(tmpl, **combo))
        except KeyError:
            continue

    # 4. Dedup
    seen: set[str] = set()
    unique: list[str] = []
    for req in adv_requests + raw_requests:
        key = _request_key(req)
        if key not in seen:
            seen.add(key)
            unique.append(req)

    dedup_rate = 1.0 - (len(unique) / max(len(adv_requests) + len(raw_requests), 1))

    # 5. Validity filter
    valid: list[str] = []
    rejected: int = 0
    for req in unique:
        if _is_valid(req, llm):
            valid.append(req)
        else:
            rejected += 1

    # 6. Cap to target
    if len(valid) > target:
        valid = valid[:target]

    # 7. Count decision firers among final output
    decision_firers: int = 0
    for req in valid:
        if _fires_decision(req, llm):
            decision_firers += 1

    # 8. Compute stats
    generator_counts: dict[str, int] = {}
    for req in valid:
        for gen in _GENERATOR_NOUNS:
            for noun in _GENERATOR_NOUNS[gen]:
                if noun in req.lower():
                    generator_counts[gen] = generator_counts.get(gen, 0) + 1
                    break

    stats = {
        "target": target,
        "seed": seed,
        "raw_generated": len(raw_requests) + len(adv_requests),
        "unique_after_dedup": len(unique),
        "dedup_rate": round(dedup_rate, 4),
        "valid": len(valid),
        "rejected_by_validity": rejected,
        "decision_firers": decision_firers,
        "adversarial_count": len(adv_requests),
        "generator_counts": generator_counts,
    }

    # 9. Output
    if not dry_run:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(valid) + "\n", encoding="utf-8")

    return valid, stats


# ═══════════════════════════════════════════════════════════════════════
#  P6: fetch-quest corpus augmentation (room-themed prompts)
# ═══════════════════════════════════════════════════════════════════════

# ── Room-themed lexicons ────────────────────────────────────────

_NPC_ROLES: list[str] = [
    "hermit", "blacksmith", "wizard", "innkeeper", "alchemist",
    "shopkeeper", "tinker", "woodcutter", "sage", "miner",
    "fisherman", "potter", "weaver", "carpenter", "hunter",
]

_ROOM_TYPES: list[str] = [
    "shack", "study", "workshop", "back room", "chamber", "hut",
    "cellar", "attic", "cabin", "forge", "laboratory", "storeroom",
    "cottage", "den", "loft",
]

_ROOM_MOODS: list[str] = [
    "cluttered", "dusty", "dim", "cozy", "worn", "ancient",
    "cramped", "forgotten", "shadowy", "musty",
]

_FURNITURE_ITEMS: list[str] = [
    "worn furniture", "wooden shelves", "old tables", "scattered chairs",
    "a heavy cabinet", "stacked crates", "dusty bookshelves",
    "a rickety table", "iron-bound chests", "a potion-stained workbench",
    "towering bookcases", "a weathered desk", "stone-topped counters",
]

# ── Room prompt templates ───────────────────────────────────────

_QUEST_SYSTEMATIC_TEMPLATES: list[str] = [
    "a {role}'s {room}",
    "a {mood} {room} with {furniture}",
    "a {role}'s {room} with {furniture}",
    "a {mood} {role}'s {room}",
    "a {role}'s {mood} {room} with {furniture}",
]

_QUEST_ADVERSARIAL_TEMPLATES: list[str] = [
    # Empty room
    "an empty {room}",
    # Ambiguous / underspecified
    "a room",
    "a {mood} room with something in it",
    # Minimal
    "a {room}",
]


# ── Quest-slot combo generation ─────────────────────────────────

def _quest_slot_combos(rng: random.Random) -> list[dict]:
    """Generate slot-fill dicts from room-themed lexicons."""
    combos: list[dict] = []

    for role in _NPC_ROLES:
        for room in _ROOM_TYPES:
            # Base: role + room
            combos.append({"role": role, "room": room})
            # With mood
            for mood in rng.sample(_ROOM_MOODS, min(3, len(_ROOM_MOODS))):
                combos.append({"role": role, "room": room, "mood": mood})
            # With furniture
            for furn in rng.sample(_FURNITURE_ITEMS, min(2, len(_FURNITURE_ITEMS))):
                combos.append({"role": role, "room": room, "furniture": furn})
                # With mood + furniture
                for mood in rng.sample(_ROOM_MOODS, min(2, len(_ROOM_MOODS))):
                    combos.append({
                        "role": role, "room": room,
                        "mood": mood, "furniture": furn,
                    })

    return combos


def _quest_adversarial_combos(rng: random.Random) -> list[dict]:
    """Generate adversarial quest combos."""
    combos: list[dict] = []

    for room in rng.sample(_ROOM_TYPES, min(6, len(_ROOM_TYPES))):
        combos.append({"room": room})
        for mood in rng.sample(_ROOM_MOODS, min(3, len(_ROOM_MOODS))):
            combos.append({"room": room, "mood": mood})

    return combos


# ── Quest validity filter (stub for tests) ──────────────────────

def _stub_quest_llm():
    """A stub LLM that returns a valid quest spec JSON.

    Used by the validity filter so augment_quest_corpus is fully
    deterministic when no live LLM is injected.
    """
    import json as _json
    spec = _json.dumps({
        "npc_role": "hermit",
        "target_entity": "shelf_0",
        "dialogue": {
            "greet": "Ah, a visitor! Welcome.",
            "ask": "Find my lost book on the shelf.",
            "wrong": "No, that is not my book.",
            "thank": "You found it! Thank you.",
        },
        "objective": {
            "type": "fetch",
            "target": "shelf_0",
            "giver": "npc",
        },
    })

    def _stub(prompt: str, grammar) -> str:
        return spec

    return _stub


def _quest_is_valid(room_theme: str, manifest: list[dict], llm=None) -> bool:
    """Return True if *room_theme* produces a valid quest spec.

    Runs QuestBehaviourPlanner.plan() + compile_scene() in a temp dir.
    Uses a FAKE llm by default (deterministic).
    """
    if llm is None:
        llm = _stub_quest_llm()
    try:
        import tempfile

        from behaviour_gen import QuestBehaviourPlanner
        from scene_compiler import compile_scene

        planner = QuestBehaviourPlanner()
        spec, _decisions = planner.plan(room_theme, manifest, llm)
        with tempfile.TemporaryDirectory() as td:
            compile_scene(spec, manifest, f"{td}/test.tscn")
        return True
    except Exception:
        return False


def _quest_fires_decision(room_theme: str, manifest: list[dict], llm=None) -> bool:
    """Return True if *room_theme* causes QuestBehaviourPlanner to emit
    at least one Decision Point."""
    if llm is None:
        llm = _stub_quest_llm()
    try:
        from behaviour_gen import QuestBehaviourPlanner
        planner = QuestBehaviourPlanner()
        _spec, decisions = planner.plan(room_theme, manifest, llm)
        return len(decisions) > 0
    except Exception:
        return False


# ── Public entry point (quest) ──────────────────────────────────

def augment_quest_corpus(
    out_path: str,
    *,
    manifest: list[dict],
    target: int = 60,
    seed: int = 1337,
    dry_run: bool = False,
    llm: Callable | None = None,
    paraphrase: Callable | None = None,
) -> tuple[list[str], dict]:
    """Generate a fetch-quest corpus via room-themed slot-filling.

    Produces room prompts (like "a hermit's shack", "a dusty workshop
    with old tables") that are test cases for the full quest pipeline
    (asset-gen → quest-spec → scene-compile).

    Args:
        out_path: Where to write the .txt corpus (ignored when dry_run=True).
        manifest: A placed-entity manifest (list of dicts with id, category,
                  material, x/y/z).  Shared by all generated prompts — the
                  prompts describe the ROOM, not individual props.
        target: Maximum number of requests to produce (default 60).
        seed: RNG seed for reproducibility.
        dry_run: When True, print stats but don't write.
        llm: Injectable LLM for the quest validity filter.
        paraphrase: Injectable paraphraser — defaults to _fake_paraphrase.

    Returns:
        ``(room_themes, stats_dict)``.
    """
    rng = random.Random(seed)
    if paraphrase is None:
        paraphrase = _fake_paraphrase

    # 1. Generate systematic quest combos
    slot_combos = _quest_slot_combos(rng)
    rng.shuffle(slot_combos)

    # 2. Generate adversarial quest combos
    adv_combos = _quest_adversarial_combos(rng)

    # 3. Fill templates → raw room themes
    raw_themes: list[str] = []

    for combo in slot_combos:
        tmpl = rng.choice(_QUEST_SYSTEMATIC_TEMPLATES)
        try:
            raw_themes.append(paraphrase(tmpl, **combo))
        except KeyError:
            continue

    adv_themes: list[str] = []
    for combo in adv_combos:
        tmpl = rng.choice(_QUEST_ADVERSARIAL_TEMPLATES)
        try:
            adv_themes.append(paraphrase(tmpl, **combo))
        except KeyError:
            continue

    # 4. Dedup
    seen: set[str] = set()
    unique: list[str] = []
    for req in adv_themes + raw_themes:
        key = _request_key(req)
        if key not in seen:
            seen.add(key)
            unique.append(req)

    dedup_rate = 1.0 - (len(unique) / max(len(adv_themes) + len(raw_themes), 1))

    # 5. Quest validity filter
    valid: list[str] = []
    rejected: int = 0
    for req in unique:
        if _quest_is_valid(req, manifest, llm):
            valid.append(req)
        else:
            rejected += 1

    # 6. Cap to target
    if len(valid) > target:
        valid = valid[:target]

    # 7. Count decision firers
    decision_firers: int = 0
    for req in valid:
        if _quest_fires_decision(req, manifest, llm):
            decision_firers += 1

    # 8. Compute stats
    role_counts: dict[str, int] = {}
    for req in valid:
        for role in _NPC_ROLES:
            if role in req.lower():
                role_counts[role] = role_counts.get(role, 0) + 1
                break

    stats = {
        "target": target,
        "seed": seed,
        "raw_generated": len(raw_themes) + len(adv_themes),
        "unique_after_dedup": len(unique),
        "dedup_rate": round(dedup_rate, 4),
        "valid": len(valid),
        "rejected_by_validity": rejected,
        "decision_firers": decision_firers,
        "adversarial_count": len(adv_themes),
        "role_counts": role_counts,
    }

    # 9. Output
    if not dry_run:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(valid) + "\n", encoding="utf-8")

    return valid, stats
