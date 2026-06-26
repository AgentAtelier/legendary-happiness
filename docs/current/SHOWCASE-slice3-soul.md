# Showcase — Spine Slice 3: Layered Soul (G1)

**Date:** 2026-06-21. **Model:** `qwen3-6-27b` (the most capable local model — best-quality, not a stress test).
**Build kept at:** `builds/showcase_soul_qwen3-6-27b/` · **Stable across 2 runs.**

This is a *best-results* showcase of the first Anvil port (G1 Layered Soul) running end-to-end
through the interpretation spine, after the `json_schema` fix made structured output reliable on
capable models.

## The prompt (verbatim)

```
a fearful hermit and a proud, generous blacksmith share a workshop
```

Two contrasting personalities, named only through adjectives — the interpreter must infer the
souls; nothing is hand-specified.

## What the engine understood (build report)

```
═══ Understood ═══
  Setting: a workshop
  Scale: medium
  Theme: workshop
  Characters: timid, anxious hermit, bold, warm blacksmith

═══ Built ═══
  8 props placed
  Categories: book, cabinet, chair, key, rug, shelf, table
  NPC dialogue sources:
    npc_0: model
    npc_1: model
```

- The free-form adjectives became **souls**, surfaced in plain language (pillar 3 — legibility):
  *"timid, anxious hermit"*, *"bold, warm blacksmith"*.
- `dialogue sources: model` — the constrained multi-NPC call succeeded directly (no canned/grammared
  fallback). Signals: **winnable ✓ · targets_distinct ✓ · room_varied ✓ · smoke_ok ✓**.

## The souls the interpreter inferred

| NPC | role | courage | generosity | stability | → tone |
|-----|------|--------:|-----------:|----------:|--------|
| npc_0 | hermit | **−0.7** | 0.0 | **−0.5** | timid, anxious |
| npc_1 | blacksmith | **+0.8** | **+0.9** | 0.0 | bold, warm |

"fearful" → low courage; "proud" → high courage; "generous" → high generosity. The interpreter
mapped the user's words onto the engine's −1..1 Substrate with no help.

## The dialogue those souls produced

**The fearful hermit (timid, anxious):**
> greet: *"Oh! You startled me... I didn't hear you come in."*
> ask: *"I... I think I left my journal on one of the shelves. Could you... could you find it for me?"*
> wrong: *"No, that's not it... please, be careful."*
> thank: *"Oh, thank you. You've saved me a great worry."*

**The proud, generous blacksmith (bold, warm):**
> greet: *"Well, hello there! Welcome to my workshop."*
> ask: *"I've misplaced my workshop key. Could you give me a hand finding it?"*
> wrong: *"That's not the key I'm after. Keep your eyes peeled!"*
> thank: *"There she is! You've got a keen eye, friend."*

The hermit hesitates and flinches ("Oh!", "I... I", "please, be careful"); the blacksmith is open and
hearty ("Well, hello there!", "friend"). Two NPCs from one sentence, reading as distinct characters —
the exact "interchangeable canned villager" gap, closed.

## What this proves

The whole spine fired end-to-end on the best model:
`prompt → Interpreter (infers souls) → Brief.characters[].soul → plan_multi (tone-biased dialogue,
souls on specs) → quest_data → Build Report (souls in plain words)`. A *new capability* (Anvil G1)
shipped with its **interpretation** (souls from free text) and **legibility** (souls explained in the
report) from day one — the three-pillar definition-of-done.

## Known minor follow-up (not blocking)

The "Assumed" section lists 8 lines of *"No value was given for axes.X, so a neutral 0.0 was used."*
The 4 emotional axes are stored as initial state but not yet used (event-nudging is B8), and the
interpreter doesn't fill them — so each character emits 4 `soul.defaulted` DPs. Cosmetic report noise;
suppress axes-defaulting DPs (or stop asking for axes until B8) in a small cleanup.
