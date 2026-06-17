# ADR 003 — External survey verdict: the approach holds; the gap is a shared world-state

**Date:** 2026-06-17
**Status:** Accepted (with one falsifiable bet still open)

## Context
Before committing months to the "hard environment" frontier (terrain, forests,
streets, weather), we ran an adversarial pre-mortem of the whole architecture
through ~12 external AIs (varied lenses), explicitly asking *why it will fail*.
The responses were brutal and highly convergent.

## What the survey got right (the real risks)
1. **Expressiveness ceiling → "4B and 27B look identical."** Raised by nearly
   every responder, and it independently corroborates our **own** multi-model
   bench (27B was the zero-variety outlier; no clean scaling). If the engine
   collapses a rich brief back into a few sliders, model size is invisible and the
   premise is hollow. GBNF/validators guarantee *validity*, not *richness* — they
   do nothing for this. **This is the make-or-break risk.**
2. **Macro-scale coordination gap.** A flat, per-call brief expresses *isolated*
   objects, not *continuous interdependent* systems (river runs downhill, forest
   thins near the road, city needs buildable flatness). Our current engines
   (room/building/scatter/BSP/Voronoi) are all bounded and local — the easy case.
3. **VRAM + latency.** A 27B + a live Godot viewport on 16 GB won't be
   interactive. The live loop and the rich "considered" pass likely need
   *different* models.

## What the survey got wrong (it attacked a cruder system than we built)
- "Small models botch JSON" — we use **GBNF grammar-constrained decoding**;
  malformed briefs are structurally impossible.
- "Regenerates from scratch, wipes tweaks" — DevForge already does **atomic
  edit-ops** on the live scene via the MCP, not seed-regeneration.
- "Can't validate / Godot can't take live mutation" — we have a
  validator + completeness checker + testbench, and already drive Godot live
  (rooms/buildings/dungeons/screenshots) today.
- **Internal contradiction in their cure.** Half prescribed "let the LLM write
  the GDScript/scene directly + a validator"; the other half named AI-written
  code as the death spiral. "LLM authors the spatial scene code" also leans
  *hardest* on the spatial weakness they all decry. Their cure reintroduces the
  exact disease this architecture exists to prevent: model-dependent correctness
  and unmaintainable AI-authored code. We reject the "just flip it" consensus.

## Decision
1. **Keep the split.** It is proven for bounded scenes and the popular
   alternative is the thing we deliberately rejected.
2. **Add the missing layer for macro environments: a persistent, shared spatial
   world-state** — a heightfield + masks/zones (water, slope, buildable, "near
   road") that deterministic engines read and write so they coordinate, and a
   brief that can address *space* ("denser near the river"), not just flat
   globals. This is a bounded addition, not a rewrite, and it dissolves failure
   modes #2–#3.
3. **Settle the central bet empirically before scaling.** Build *one* macro slice
   (terrain + a forest that reads slope/water + a road that carves) on the shared
   world-state, with a deliberately **wide** brief (Stage-4 Intent Descriptor
   pushed to its limit). Run the **same prompt on the 4B and the 27B and look at
   the two Godot scenes.**
   - Indistinguishable → the critics win; pivot the LLM to the narrative layer
     and let humans/visual tools own structure. **No sunk-cost defense.**
   - Visibly richer on 27B → the bet holds; scale the world-state pattern with
     evidence, not faith.

## Consequences
- The "two walls" map gains a third, sharper one: **the coordination/state wall**
  (continuous interdependent environments need shared world-state) alongside the
  modality wall (raw media synthesis) and the feedback wall (playtest-tuned
  balance).
- The richness test is non-negotiable and must be built to be *failable*; if a
  wide brief + wide engine still can't make 4B≠27B visible, we pivot.

## Method note
The adversarial multi-AI survey is kept as a standing tool: a forcing function to
engage with the project under a hostile reading. Treat it as a *provocation, not
an oracle* — every critique is reconciled against the real system, because cold
AIs attack a generic strawman and will anchor toward consensus if allowed.
