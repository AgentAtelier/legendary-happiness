# Forge — Project State (read this first)

**Updated:** 2026-06-22. Single source of truth for *where we are*. The many `*-PROMPTS.md` /
`*-DESIGN.md` files in this dir are per-task artifacts (mostly historical once implemented); this file
is the live status.

## What Forge is

A **generation-first engine that builds small playable embodied-3D games** from a text prompt, at a
quality bar that must not read as "AI slop." Python drives Blender to generate assets (~37 categories
as GLBs), a deterministic layout places them, quests/NPCs are generated, and a **disposable Godot 4.x
project** is scaffolded and rendered. Goal: a *general* tool (RPG is the first bundle of mechanics, not
the definition). Single local 16 GB GPU runs the LLMs (llama.cpp at `:8002`, hub swap at `:8003`).

## Architecture (the spine)

```
prompt
  └─► Interpreter (LLM, json_schema)  →  Brief  (shared structured intent: setting, theme, scale,
                                          key_features, characters[].soul)
        └─► RoomPlanner(brief) → room_control/layout → manifest
        └─► behaviour_gen.plan_multi(brief) → per-NPC quests (themed dialogue, souls)
        └─► asset foundry: Blender bakes per-material PBR GLBs (albedo/roughness/metallic/normal/AO)
        └─► scene_compiler → Godot .tscn (PBR props + textured shell + interior lighting)
  └─► Build Report (Brief + Decision Points: understood / built / assumed / couldn't-do)
```

**Three pillars = definition of done:** Capability + **Interpretation** (free prompt → engine
vocabulary) + **Legibility** (the build report). Every capability ships with its interpretation +
legibility. See `SPINE-DESIGN.md`.

**Build-time vs run-time:** *Python builds the world, Godot lives it* — Python decides everything at
build time and bakes it; Godot renders/loops. (Memory: `python-builds-godot-lives`.)

## Done (shipped + verified)

- **Spine Slice 1** (rooms ride the Brief), **Slice 2** (quests + per-NPC grammared dialogue fallback),
  **Slice 3 — G1 Layered Soul** (interpreter infers Substrate/axes per NPC → dialogue tone; showcase in
  `SHOWCASE-slice3-soul.md`).
- **json_schema fix** — structured LLM output (interpreter + multi-NPC) via llama.cpp `json_schema`
  (fixed the "verbose models ramble → fallback" bug; never `grammar=None`). Memory:
  `canned-npc-means-pipeline-bug`.
- **E1 material pipeline** — Blender bakes layered PBR (wood/stone/iron/fabric) + normal maps + AO into
  GLBs; room shell textured; interior lighting (fix-A). `E1-MATERIAL-PIPELINE-DESIGN.md`.
- **Quality fixes** — A–D (lighting/placement/materials/audio), Fix-Batch-1 (chair offset, prop spread,
  AO occlusionTexture wiring, shell textures), Fix-Batch-2 (granite roughness in-band), AO-injection
  struct bug, soul axes-DP noise.
- **V visual-eval — code Tasks 1–5** (screenshot harness via Godot EGL SubViewport [works for real],
  Qwen3-VL `check_image`, CLIP aesthetic, visual signals + report + regression, batch driver
  `python -m foundry visual-eval`). `V-VISUAL-EVAL-DESIGN.md`.
- Suite: **920 passed**, Godot smoke 8/8 at HEAD.

## Open / next

- **⚠ V can't run for real yet (infra gap, the next [ORCH] step):** `vlm.py` POSTs to `:8002/completion`
  expecting Qwen3-VL served. `Qwen3-VL-8B` GGUF is on disk but the **`mmproj` vision projector is
  missing**, the llama server serves text models (needs `--mmproj` / hub support for a vision model),
  and **`open_clip` isn't installed** (CLIP aesthetic degrades to None gracefully). To run V: download
  the Qwen3-VL mmproj, serve it, `pip install open_clip_torch` + the LAION aesthetic head. Then [ORCH]
  runs the real batch on the prop catalog + scenes and calibrates thresholds; user confirms the VLM
  matches their eye.
- **V Task 6** (closed auto-reroll) — deferred until the real checks earn trust.
- **Visual confirm pending:** user to eyeball `builds/chk_fb1` (textured props + shell; granite matte).
- **MolmoPoint-8B** — deferred (no GGUF; separate runtime) unless Qwen3-VL spatial precision is short.

## The plan from here (consolidation — agreed)

Make real progress on what's designed before opening new fronts. Order: **V real-run + calibrate →
then drive the `ROADMAP-BUNDLES.md` backlog through the spine, one shipped-and-verified bundle at a
time** (B6 living-NPCs/G2 needs, B7 multi-room, B8 events/G3, …). Each bundle ships its interpretation
(Brief section) + legibility (report) + passes the FULL suite + (when V runs) the visual gate.

## Operating rules (also in AGENTS.md + memories)

- **Testing split:** CLI AI runs the FULL fast gates (`pytest tests/ -q` + smoke) and hands off;
  **orchestrator owns time-intensive/live/visual verification** ([CLI]/[ORCH] tags in prompts).
- **Always the FULL suite**, never a subset (subset-reporting shipped real bugs).
- **Structured LLM output → json_schema**, never `grammar=None` (asset-default footgun).
- **[ORCH] verification builds pollute `asset_lexicon.json`** → build into a throwaway lib + `git
  checkout` the lexicon after (memory: `verification-builds-pollute-lexicon`).
