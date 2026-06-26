# Generation-Reveal Showcase — design spec

**Date:** 2026-06-22
**Status:** Design (approved in brainstorm) → `writing-plans`
**Goal:** A **playable** showcase that demonstrates "the best we can achieve": an audience gives an
in-domain prompt and the engine **live-assembles a walkable world** from a deep pre-built library,
which they then explore (biome → building → interior → soul-driven NPC → small quest). The reveal *is*
the thesis — prompt → generated, embodied, playable world.

## 1. Constraints (hard)
- **Local + free only.** One AMD **RX 6800** (gfx1030/RDNA2, 16 GB), no cloud, no paid services.
- **Deterministic** build path (content-addressed caches make neural output reproducible per spec).
- **Anti-slop quality bar** — every in-domain prompt must produce a result that reads as bespoke.

## 2. Decided shape (from brainstorm)
- **Deliverable:** a playable build (interactive walk-through).
- **Timeline:** no hard deadline; quality over speed.
- **Concept:** *generation reveal* — prompt → **live assembly** → walk it.
- **Liveness:** the **world assembly** is live (seconds); **all assets are pre-built/cached** (Hunyuan
  is far too slow to be live on this card).
- **Domain:** **one deep domain — medieval-fantasy "wilderness & settlement"** (where 100% of our
  existing depth lives: theme table, materials, NPC roles/souls, the exterior biomes). Reliable +
  genuinely open within-genre, not canned. Multi-genre is a later stretch.

## 3. The asset strategy (the crux — "massive library on a free GPU")
Per-asset neural generation does **not** scale to a massive library locally (~4 min/asset × tens of
thousands = months). The scalable model is **bounded neural archetypes × unbounded procedural
variation**, grown at idle:

1. **Procedural = the breadth backbone (massive, today).** Every category already has a parametric
   generator → unlimited variants, instant, free, deterministic. The library already exists at
   box-quality; this is what makes "massive" scale and gives graceful degradation.
2. **Hunyuan = a progressive HERO quality overlay (~hundreds of *base* meshes).** Neural gen upgrades
   the *bases* one at a time (~500 archetypes: categories × a few style variants × genre). ~500 × ~4
   min ≈ a weekend of idle compute — feasible.
3. **Procedural variation of the neural bases** (parametric deform, material/wear, kitbash
   composition) turns ~500 bases into effectively unlimited perceptual breadth. Variety comes from
   variation + composition, not raw unique-mesh count.
4. **Idle-time asset server** (the free-throughput engine): a persistent process that **loads the
   Hunyuan model once** (kills the ~1-min/asset reload overhead) and **drains a job queue whenever the
   GPU is free** (not gaming, not serving the LLM), low priority, demand-prioritized. The library
   **grows forever, for free**, over calendar time.
5. **Adoption < 100% → automated:** gate (watertight/poly) → V visual check → **auto-reroll** on
   failure (the V-reroll loop); humans curate only the ~500 *bases*, not every variant.

### Validated Hunyuan config (spike, on the RX 6800)
- Runs via ROCm: **fp16**, **pure-PyTorch fp16 math attention** (flash/mem-efficient kernels are NOT
  compiled for RDNA2 and won't be — AMD's FA roadmap stops at RDNA3), `PYTORCH_CUDA/HIP_ALLOC_CONF=
  expandable_segments:True`. (A torch-2.8/ROCm-6.4 upgrade is in flight — *only* matters if it ships a
  mem-efficient SDPA kernel for gfx1030; not a blocker.)
- **`octree_resolution=256`, `num_inference_steps≈30`** → **~3.9 min/base** (down 3.4× from the 512
  default; the mesh-extraction octree was the bottleneck, NOT attention/steps). We decimate to the
  poly budget afterward, so 256 costs us nothing.
- **Shape-only.** Hunyuan texture stage is fragile on RDNA2 and we don't use it — we apply our own
  procedural PBR. This sidesteps the one genuinely broken part.
- **Control:** Hunyuan-Omni **voxel/bbox conditioning** from our deterministic box-proxy → the mesh
  tracks our determined shape (validated: a mug input → a faithful mug mesh). Control stays ours.

### Asset pipeline (offline)
```
procedural generator → box proxy → voxelize → Hunyuan-Omni (voxel-conditioned, fp16, octree256)
  → decimate to poly budget → scale-normalize to lexicon envelope → gate (watertight/poly)
  → V visual check (auto-reroll on fail) → our procedural PBR → content-addressed CACHE → GLB base
        → [runtime] procedural variation/kitbash of the base → placed instances
```

### Idle asset server (implemented)
The slow neural step never blocks the foundry. A content-addressed **queue/cache**
(`foundry/hunyuan_queue.py`) decouples it: the foundry **enqueues** asset jobs +
reads the **cache**; the **idle server** drains the queue during free GPU time.
- **Tested drain logic** (GPU-independent): `foundry/hunyuan_worker.py` —
  `drain(infer_fn)` = dequeue (priority) → infer → `hunyuan_postprocess`
  (decimate/scale/sit) → cache → archive. Inference injected → unit-tested with a stub.
- **GPU glue** (spike venv, py3.10): `/home/mrg/dev/hunyuan-spike/Hunyuan3D-Omni/asset_server.py`
  loads Hunyuan **once** (amortizing the ~1-min load over the whole queue), injects
  the validated voxel inference, and swaps `forge-llama` out/in around the run.
  - `python asset_server.py --dry-run` — plumbing only (no GPU); verified end-to-end.
  - `python asset_server.py --swap-llama --max N` — real overnight drain.

## 4. Runtime — the generation-reveal loop (live, seconds)
```
prompt → Interpreter(LLM)→Brief → assemble: RoomPlanner + ExteriorPlanner + behaviour_gen
       → select assets from the warm library (Hunyuan base where available, else procedural)
       → scene_compiler (exterior biome + building + interior + NPC + quest)
       → Build Report (understood / built / assumed / couldn't)  → playable Godot world
```
The audience sees: prompt entry → "interpreting…" → the **Build Report** (the legibility flex) → the
world spawns → they walk the biome, enter the building, talk to a soul-driven NPC, complete a small
quest → win.

## 5. Visual / atmosphere bar
SDFGI bounce light + post-processing (ACES/SSAO/bloom/fog) + per-theme lighting + day/night — applied
to exterior and interior. The anti-slop pass.

## 6. 🔑 Delegation (me = hard; CLI = medium/easy; chatAI = content)
**ME — hard core:**
- **Hunyuan asset pipeline productionized** (proxy→voxel→Omni→decimate→scale→gate→cache) + the
  **idle-time asset server** (model-loaded-once queue drainer) + content-addressed cache determinism.
- **Live-assembly integration**: Interpreter→Brief→library selection→`scene_compiler` exterior+interior
  fuse (finish the exterior archetype I started: scene_compiler emit + Brief foldings + terrain).
- **Control tuning** (voxel conditioning fidelity) + the gate adapted for organic meshes.

**CLI — medium (can start NOW, independent of my core):**
- **Deepen the procedural breadth** (more categories/materials/themes + parametric variation/kitbash)
  — the massive-library backbone; pure procedural, gate-tested.
- **Generation-reveal UX shell** (prompt screen, player-facing Build-Report panel, "world building…").
- **Atmosphere/lighting** (SDFGI/post-proc/per-theme/day-night), building on B2.
- **Probes/V gating** for the showcase loop + library QA + the auto-reroll wiring.

**CLI — easy:**
- Generate the **deterministic proxies** (voxelize the box generators) = Hunyuan's conditioning inputs.
- Library **curation/lexicon entries**, asset QA renders via V.

**chatAI — offline content:** dialogue/lore, theme-table expansions, demo prompt examples.

## 7. Risks & fallbacks
- Hunyuan quality/control insufficient for a category → **procedural fallback** (always present).
- Throughput → the idle-server + archetypes×variation model makes it free/continuous, not a batch wall.
- Adoption < 100% → auto-reroll + base-only human curation.
- Live-assembly latency → assembly is already fast; pre-warm the interpreter.

## 8. Testing
- Pipeline unit tests (proxy/voxel/cache determinism, scale-normalize, decimate).
- V visual-gate on every library base (+ auto-reroll).
- A Godot **showcase-loop probe** (prompt→assemble→walk→talk→quest→win).
- Full `pytest tests/` + the Godot smoke gate green (pasted), per AGENTS.md.

## 9. Workstreams (each → its own implementation plan)
1. **Hunyuan asset pipeline + idle server** (me).
2. **Exterior archetype finish + live-assembly integration** (me).
3. **Procedural-breadth deepening + variation/kitbash** (CLI).
4. **Generation-reveal UX shell + atmosphere** (CLI).
5. **Proxies + library build-out + V auto-reroll QA** (CLI/easy).
