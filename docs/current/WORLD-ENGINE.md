# Forge World Engine — Architecture & Strategy

**Date:** 2026-06-25
**Status:** CANONICAL DIRECTION (post-M1 north star). Documentation phase; implementation not started.
**Source:** synthesis of a 6-model external engineering survey (the "four hard problems" fan-out) +
Forge's own architecture. This doc is the reference the sub-project specs hang off; a cold session
can read this + `PROJECT-STATE.md` and move forward.

---

## 1. The vision (the north star)

Forge graduates from a **stateless scene generator** (prompt → disposable Godot scene, thrown away)
to a **stateful world engine**: a single *maker* grows ONE persistent, playable 3D world over time
by prompting — seeding it ("a misty hilltop keep"), stepping inside first-person, then **refining**
existing spaces ("make it dusk," "bigger throne"), **extending** with new linked spaces ("a courtyard
to the north"), and **populating** them (NPCs, simple quests). The world **persists and accumulates
across sessions**; it is theirs to keep extending.

**Who it's for / why:** the maker is a builder/problem-solver, not a consumer (see `PROJECT-STATE.md`
motivation). The deeper question Forge is probing: *is a prompt-grown, persistent, coherent, playable
3D world genuinely undoable, or merely **assumed** undoable?* "Genuinely usable, not slop" is the
**proof** we actually solved it; hitting a real wall is a **result**, not a failure.

## 2. The reckoning

This vision is **fundamentally incompatible with the current disposable-project architecture.** A world
you grow and keep needs the opposite of a fresh build per prompt: a **persistent world model** that the
engine reads and writes *incrementally*. This is the "disposable-project dead-end" we always knew we'd
have to **outgrow, not refactor**. It's a multi-epoch program (one external estimate: a 3–5y research
arc) — so we **scope ruthlessly** (start: ~10 connected rooms, human-authored edits, coherence enforced).

## 3. The meta-signal (why we're confident)

Six independent strong models, given the same framing, converged on **the same architecture** — down to
the same data structures and the same named failure modes. That convergence is decisive: **the
architecture is essentially solved on paper. The frontier is EXECUTION of two or three concrete walls,
not invention.** Answer to the frontier question: *unattempted, not intractable.* Nobody has shipped a
prompt-grown, persistent, editable, coherent, *playable* 3D world; the closest systems each solve ~2 of
the needed properties (see §8).

**Forge already stands on the recommended foundation** — we arrived at it independently:
- **Brief = the IR** (compiler analogy: prompt→interpreter→Brief→deterministic backend). ✓ have it.
- **Determinism via content-addressed caching** (Git/Bazel/Nix object model). ✓ "determinism is sacred."
- **Hybrid: LLM-interpreter → structured Brief → deterministic procedural execution.** Unanimously cited
  as *the reason it's possible* (pure-neural — Oasis/Sora/NeRF — is stateless & hallucinatory, can't
  persist). ✓ our exact pipeline.
- **Hierarchical "World Bible" constraint contract** = the **Cohesion Contract** we already designed
  (`docs/superpowers/specs/2026-06-24-cohesion-contract-design.md`). The models reinvented it.
- **Event-sourced edit log** = what **Brief-persistence (roadmap 0.10)** seeded.

## 4. The consensus architecture

```
edit operations (append-only log, AUTHORITATIVE)   ← prompts are provenance only, NOT authoritative
        │
        ▼
World = content-addressed DAG of SPACES
   • each SpaceNode: stable id, ISOLATED seed, structured Brief, entity list, portal/boundary contracts
   • edges = portals/connections between spaces
   • global "World Bible" (hierarchical Cohesion Contract): world → region → site layers
        │
        ▼
deterministic generation  (pure function: Brief → 3D)   ← per-node generator VERSION pinned for replay
        │
        ▼
content-addressed chunk cache  (regenerate only nodes whose input-hash changed; materialize on demand)
        │
        ▼
Godot 4 runtime (the mutable materialized instance)
```

**Key decision — operations, not prompts, are the source of truth.** Replaying *prompts* through an LLM
is not reproducible across model versions (the "same prompt → different world later" trust-breaker). So
the durable truth is the **structured edit operations / JSON-patches**; prompts are kept only as
provenance, and the generator/model **version is pinned per node** for replay.

**Edit = JSON-patch against the current Brief, NOT regenerate-the-scene.** Naive "prompt → regenerate"
dies immediately — the moment "move the throne" regenerates the walls, trust is destroyed. NL is a
*patch generator*; the operation log is what rebuilds the world.

## 5. The real walls (prioritized) + Forge's stance

| # | Wall | Real? | Forge's commitment |
|---|------|-------|--------------------|
| **W1** | **Local edit without global cascade** (seed-ripple / topology rupture; "80% of the engineering") | **REAL** | **Per-node seed isolation**; **boundary/portal contracts** (regenerate a space's *interior* freely, but its doorways/seams are FIXED — Wave-Function-Collapse style); **rooms immutable once placed — the world grows via portals, never by repositioning existing spaces**; global edits ("dusk") apply as **non-destructive overlays**, never base-geometry regen. |
| **W2** | **Semantic grounding / reference resolution** ("the throne near the window" → which?) | **REAL (research-grade)** | **Stable entity IDs live in the Brief**; the pipeline **writes back a "Read-State"** after generation (entity IDs + bounding boxes + compact spatial index); the interpreter is **world-aware** — it gets a `query_world` tool to ask "what's north of the hall?" *before* proposing an edit. #1 source of "the AI did the wrong thing" bugs. |
| **W3** | **Spatial conflict on expansion** (a new space intersecting geometry from sessions ago) | **REAL** | A **validation gate that REJECTS impossible Briefs *before* Godot** and returns the error to the LLM to auto-correct (*"that courtyard intersects the armory; shrink it or attach to the north portal"*). Keep the **architectural shell procedural** (clean parametric boundaries you can bounds-check & cut openings in); use **neural assets only for decoration** inside the shell (neural meshes have no clean seams — don't make them load-bearing). |
| **W4** | **Coherence at scale** (drift → "AI slop" after 50+ edits) | **REAL** | Give the Cohesion Contract **teeth**: enforce as **hard mechanical constraints** (clamp to palette, lock the asset kit, constrain scale) — NOT prompt text; a **validator suite after every generation** ("CI/CD for worlds": scale / palette / connectivity / "throne-room-has-a-throne"); **drift detection** over time. Prompts are *requests*; the world model is *authority*. |
| **W5** | **Meaning / playability** (the "empty courtyard / beautiful lonely dollhouse"; procedural gen nails variation, fails at purpose) | **REAL (design wall)** | Named, deferred. Needs authored scaffolding or emergent systems (economy/factions/ecology — Dwarf Fortress's real innovation). This is where "tech demo vs. actual game" is decided. |
| — | Generator/model drift on replay | REAL (infra) | Pin generator + model version per node (see §4). |

**Assumed walls that are NOT the hard part** (don't over-invest): 3D-gen quality (commoditizing fast),
determinism/caching (solved — content-addressing), persistence/storage (solved — event sourcing),
context-window limits (RAG + a compact world index).

## 6. Build order (the single most important directive)

**Build the deterministic stateful machinery FIRST, driven by HUMAN-authored JSON patches, with NO LLM.
Prove the World-DAG + operation-log + per-node regen + the validation gate are flawless and reproducible
*by hand*. THEN plug the LLM in as a patch-generator.** Starting with the LLM turns the state into
"intractable soup immediately." Bonus: machinery-first surfaces the real W1/W3 topology walls *without*
LLM ambiguity confounding the diagnosis — which is exactly how we want to meet the frontier.

### Sub-project decomposition

- **(a) The machinery — BUILD FIRST.** World-DAG + event-sourced operation log + **human JSON-patch
  editing** + deterministic Godot assembly + the **W3 validation gate**. No LLM. This is the spine that
  proves the whole bet and hits W1/W3 first.
- **(b) NL → patch.** LLM emits JSON-patches against the current Brief + **W2 entity-grounding** +
  `query_world` tool. (This is the **iterative-editing** thread the user wanted "sooner" — it's (a)+(b).)
- **(c) Coherence with teeth.** The parked **Cohesion Contract** enforced as hard constraints + the
  validator suite + locked asset kit + drift detection. (W4.)
- **(d) Meaning / playability.** Authored scaffolding / emergent systems. (W5, later.)

The **exterior thread** (futurelog) lands *inside* this — "spaces + portals" is the exterior/linking work,
now built on the World-DAG instead of the disposable path.

## 7. The first concrete step

Sub-project (a)'s spine: **human-authored JSON-patch → World-DAG → deterministic Godot assembly, with the
validation gate — no LLM.** A human writes `{op: add_space, ...}` / `{op: add_portal, ...}` /
`{op: move_entity, target: throne_001, ...}`, the engine assembles it deterministically, and the gate
rejects impossible patches with a correctable error. When that machinery is flawless and reproducible,
(b) plugs the LLM in to *generate* those patches.

## 8. Prior art (what to study / what broke)

- **Minecraft** — base `f(seed,coord)` + sparse player-edit deltas (region/Anvil format). The
  "deterministic base + sparse overlay" pattern, battle-tested. But spatial (16×16) not *semantic*
  chunking, and not deterministic across versions.
- **No Man's Sky** — pure deterministic seed→universe; *stateless by design*; base-building was a painful
  bolt-on overlay. Lesson: plan the mutable overlay from day one.
- **Dwarf Fortress** — deterministic world+history gen, then **frozen** into a mutable sim; can't insert a
  mountain post-gen. Save files store realized state (scaling wall) not derivation.
- **Houdini / USD / Substance / Blender Geometry Nodes** — non-destructive, deterministic, editable
  procedural graphs (the gold standard for *editable procedural*), but no NL interface, offline not
  real-time.
- **AI Dungeon** — NL-driven, persistent, growing; no state engine → tonal/logical drift (the canonical
  coherence failure).
- **Townscaper** — masterclass in coherence via strict constraint solving (forces coherent style).
- **World Labs "Marble" (Fei-Fei Li)** — NL→3D, "editable," but persistence = manual export/human-in-loop
  3D editing; NOT growing NL-driven world state.
- **Promethean AI** — NL-ish asset placement, but a tool inside an existing engine with fixed libraries.
- **Voyager (MineDojo)** — LLM writes code to build in Minecraft; world mutated by side-effecting code,
  not deterministic.
- Research surfacing in 2025–26: **WorldGen** (text→traversable 3D), Microsoft **PERSIST** / Persistent
  Embodied World Models (3D memory) — closest academic neighbors, not interactive NL creation.

*Why unattempted:* it needs a rare intersection — LLM prompt-engineering + compiler theory (ASTs/diffs) +
advanced procedural gen + game-engine architecture — "most AI labs don't know game dev; most game devs
don't trust AI" — plus the **demo trap** (one beautiful room is easy; 100 coherent rooms is years of
unglamorous infra: spatial indexing, boundary contracts, validators, entity resolution).

## 9. Open decisions for the user (to add before/at implementation)

- **Scope of the first milestone:** confirm "~10 connected rooms, human-patch editing, Cohesion enforced"
  as the first proof target.
- **W5 (meaning) stance:** how much authored scaffolding vs. pure-sandbox at first? (Probably defer, but
  flag your intent.)
- **Operation vocabulary:** the initial set of JSON-patch ops to support in (a) (`add_space`, `add_portal`,
  `move_entity`, `set_property`, `add_entity`, …) — worth a short spec of its own.

## 10. Relationship to existing docs

- `PROJECT-STATE.md` — read-this-first live status (updated to point here).
- `docs/superpowers/specs/2026-06-24-cohesion-contract-design.md` — the Cohesion Contract = sub-project (c)
  / W4. Now has a concrete home.
- `FUTURELOG.md` — iterative-editing = (a)+(b); exterior lands inside the World-DAG; UX is its own parked
  thread (see its approach notes); Cohesion = (c).
- `ROADMAP.md` — M1 (the engine epoch) is essentially complete; the World Engine is the next epoch.

> The raw 6-model survey responses are not reproduced here; their actionable signal is fully captured
> above. If verbatim preservation is wanted, paste them into `WORLD-ENGINE-SURVEY-RAW.md`.
