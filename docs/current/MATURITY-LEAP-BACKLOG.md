# Maturity-Leap Backlog — topics to investigate later

Parked 2026-06-22. A component-maturity audit ("graybox → big leap") was started in a brainstorm but
deferred once the plate was full (the **exterior scene archetype** spec + the **CLI full-backlog**
prompts are already in flight). This file preserves the framing + findings so we can resume cleanly.

## Framing (decided in the brainstorm — durable)
- **Goal:** find easy / medium / hard purely-generative ways to lift each existing component out of
  prototype ("graybox") state and make a big quality leap.
- **Priorities:** visuals + worldbuilding first; **emphasize UX** (a flagged blindspot); surface other
  blindspots the user isn't tracking.
- **Generation philosophy (committed):** **pure generative toolbox, NO authored assets** — everything
  (incl. characters + rig) synthesized from code/primitives. The LLM *orchestrates the generative
  toolbox* (interpretation → structured intent → captured in the seeded spec → deterministic
  realization); it never produces geometry/positions directly. Today the reality is narrower than that
  vision: the LLM only *parameterizes a closed catalog of ~37 box-primitive generators* — so the
  primary graybox is **the toolbox itself**.

## 1. VISUALS — audited (resume from here)
| Layer | State | Note |
|---|---|---|
| Procedural PBR materials | Decent | wood/stone/iron/fabric + normal+AO + ACES/SSAO/bloom/fog + interior lights + day/night |
| Prop **geometry** | Prototype | box primitives only; no boolean/bevel/greeble/array; ~37 fixed generators |
| **Characters** | Worst graybox | box humanoid + capsule player; no rig/anim/face (code admits "off-ramp, P7+ ticket") |
| Global illumination | Missing | no SDFGI/VoxelGI → flat, bounce-less light |
| Texture variety | Thin | 3 materials, UV-unwrapped (no triplanar), little per-instance variation → samey |

**Leaps (pure-generative):**
- **EASY** — more material *families* (leather/ceramic/glazed/bronze/marble/painted-wood) + per-instance
  seeded variation; turn on **SDFGI** (toggle + tune, huge cheap win); procedural edge-wear/dirt masks.
- **MEDIUM** — second-gen geometry: composable Blender ops (bevel/solidify/array/boolean/greeble) + a
  small parts-grammar so generators make richer silhouettes; add triplanar.
- **HARD (flagship)** — a procedural **character + rig** system: parametric humanoid mesh → procedural
  armature → skinning → small procedural locomotion/idle/gesture set. The single biggest anti-slop move.

## 2. WORLDBUILDING — to investigate
Current: a themed interior box + NPC souls. `mood` exists in the Brief but is **unused**; only ~3
materials, 12 themes (palettes of 2–3 mats each); no history, no POI, no environmental story. (The
**exterior/biome** half is being handled separately — see the exterior spec, commit `476ff44`.)
- **EASY** — actually use `mood`; broaden the theme table (crypt/armory/workshop/kitchen…) + palettes.
- **MEDIUM** — environmental-storytelling prop clusters ("a scene happened here") + place naming/lore
  (the exterior spec already seeds this via the LLM naming fold — generalize it to interiors).
- **HARD** — generated history/lore the world is consistent with (a place's past shaping its props/NPCs).

## 3. UX — to investigate (flagged blindspot)
Current: **no UX shell at all** — boots straight into a room; no main menu, settings, pause, onboarding,
or tutorial. Legibility (the build report) is **dev-facing**, not player-facing.
- **EASY** — main menu + pause + settings (volume/sensitivity/quality); a prompt-entry screen.
- **MEDIUM** — first-30-seconds onboarding (controls surfaced in-world), a *player-facing* "what this
  place is" card derived from the Brief/build report.
- **HARD** — accessibility pass + a genuinely guided first-run experience.

## 4. BLINDSPOTS — surfaced for later (not yet audited in depth)
- **Motion / animation** — everything is static; even with a rig, locomotion/gesture/idle life is absent.
- **Generation variety & coherence** — do builds feel samey? does the whole scene actually match the
  prompt (not just per-prop)? Needs a variety metric + a coherence signal.
- **Audio depth** — synth ambient + footsteps are prototype; sound design as worldbuilding is untouched.
- **First-30-seconds / framing** — *why am I here, what do I do?* (overlaps UX).
- **Performance** — procedural build time + runtime budgets on the single GPU as scenes grow.

## 5. Parked optional LLM ideas (from the exterior brainstorm)
- **#3 semantic composition zones** for scatter (LLM describes landscape intent → deterministic masks).
- **#4 pre-build coherence critique** (LLM reviews the assembled spec for semantic mismatch before
  building — a cheap pre-V guard).
Both deferred as optional polish; revisit if cheap once the exterior archetype lands.

---
*When resuming: continue the audit from §2 (Worldbuilding) — §1 (Visuals) is done. Pick E/M/H items and
brainstorm the highest-leverage ones into their own specs, same as the exterior archetype.*
