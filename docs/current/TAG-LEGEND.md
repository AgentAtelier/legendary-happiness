# Tag-Legend — One canonical place to decode inline tag prefixes

_Phase 0.9. Solves [AUDIT-03 Q6](../current/AUDIT-03-quality.md): the same comments cite `B0`/`CB-3`/`EB-6`/`P-A`/`FIX-1`/`Quality A`/`Item 4`/`T-4`/`X7`/`Q12`/`B!`/`R!!` and there is no single place to look them up._

**Reader's guide.** Hit an unfamiliar tag in source? Find its prefix in one of the three sections below.
Section 1 is the by-far-most-common lookup (programmatic task IDs in comments — `// CB-3 …`,
`# E1 Task 5`). Section 2 covers our audit-severity marks. Section 3 covers cross-cutting audit
patterns and round-finding IDs. Section 4 lists prefixes that are dead or superseded and should
not introduce a new tag.

If a tag you want isn't here, **don't invent one** — see "Adding new tags" at the bottom.

---

## 1. Capability / task-batch tags (the everyday lookup)

These are the prefixes most readers will hit on a daily basis. The "Status" column reflects
`docs/current/ROADMAP.md` (Phase 0–3 status) and `docs/current/FUTURELOG.md` (parked threads).

| Prefix           | Meaning                                                            | Origin doc                                            | Status (as of 2026-06-24) |
|------------------|--------------------------------------------------------------------|-------------------------------------------------------|---------------------------|
| `B0`             | Gate & eval hardening (multi-NPC playthrough probe + winnable oracle) | `docs/current/ROADMAP-BUNDLES.md`                | **done** (shipped)        |
| `B1`             | Playability polish (EB-2 + EB-1: quest log, juice, title icons…)   | `docs/current/ROADMAP-BUNDLES.md`                     | **done**                  |
| `B2`             | Atmosphere (EB-5/EB-4 + day/night cycle)                           | `docs/current/ROADMAP-BUNDLES.md`                     | **done**                  |
| `B3`             | Item verbs (use/consume, throw, place, open, lock, weight, durability) | `docs/current/ROADMAP-BUNDLES.md`                | partly done (place/lock/open live; durability dropped) |
| `B4`–`B5`        | Content & narrative-lite / NPC character (Soul, memory)           | `docs/current/ROADMAP-BUNDLES.md`                     | B4 done; B5 partly done   |
| `B6`–`B8`        | Living NPCs / Multi-room world / Emergent events                  | `docs/current/ROADMAP-BUNDLES.md`                     | **done**                  |
| `B9`             | Gold gameplay (multi-type quests, chains, environmental vignettes) | `docs/current/ROADMAP-BUNDLES.md`                  | **done**                  |
| `B10`            | Combat + skills                                                    | `docs/current/ROADMAP-BUNDLES.md`                     | **done** — CB-6 supersedes |
| `B11`            | Frontier (rigged humanoid + exteriors)                            | `docs/current/ROADMAP-BUNDLES.md`                     | partly done — parked exteriors per `FUTURELOG.md` |
| `CB-1`           | Quest depth (objective types + chains)                            | `docs/current/CLI-FULL-BACKLOG-PROMPTS.md`            | features shipped via `B9` (Gold gameplay) per `ROADMAP-BUNDLES.md` |
| `CB-2`           | Item verbs (the rest of B3 — needs CB-1 for `place`)              | `docs/current/CLI-FULL-BACKLOG-PROMPTS.md`            | features shipped via `B3`; place/lock/door live; durability dropped |
| `CB-3`           | Living NPCs (navmesh + needs/utility)                             | `docs/current/CLI-FULL-BACKLOG-PROMPTS.md`            | features shipped via `B6` per `ROADMAP-BUNDLES.md` |
| `CB-4`           | Multi-room world structure (room graph + doors + persistence)      | `docs/current/CLI-FULL-BACKLOG-PROMPTS.md`            | features shipped via `B7` per `ROADMAP-BUNDLES.md` |
| `CB-5`           | Emergent events                                                    | `docs/current/CLI-FULL-BACKLOG-PROMPTS.md`            | features shipped via `B8` per `ROADMAP-BUNDLES.md` |
| `CB-6`           | Combat + skills (overlaps with B10)                               | `docs/current/CLI-FULL-BACKLOG-PROMPTS.md`            | features shipped via `B10` per `ROADMAP-BUNDLES.md` |
| `CB-7`           | Frontier — rigged humanoid + exteriors (overlaps with B11)        | `docs/current/CLI-FULL-BACKLOG-PROMPTS.md`            | partly shipped via `B11`; exteriors **parked** in `FUTURELOG.md` |
| `CB-8`           | Visual-eval hardening + content (per V follow-ups + EB-6)         | `docs/current/CLI-FULL-BACKLOG-PROMPTS.md`            | shipped via `V` core + `EB-6` content (VLM CLIP head still open per `WS5-CODE-REVIEW r7`) |
| `EB-1`           | Movement & camera feel (sprint/crouch + camera juice + idle anim)  | `docs/current/EASY-BATCH-PROMPTS.md`                  | **done**                  |
| `EB-2`           | Interaction & HUD (quest log, reticle, target glow, juice)         | `docs/current/EASY-BATCH-PROMPTS.md`                  | **done**                  |
| `EB-3`           | Item verbs (use, throw, place, open, lock, weight, durability)     | `docs/current/EASY-BATCH-PROMPTS.md`                  | partly done               |
| `EB-4`           | Audio depth (ambient beds + footstep surfaces)                    | `docs/current/EASY-BATCH-PROMPTS.md`                  | **done**                  |
| `EB-5`           | Visual richness (post-proc stack + light-emitting props)          | `docs/current/EASY-BATCH-PROMPTS.md`                  | **done**                  |
| `EB-6`           | Content & narrative-lite (examine, idle barks, more themes)        | `docs/current/EASY-BATCH-PROMPTS.md`                  | **done**                  |
| `EB-7`           | Fixes (folded) — multi-NPC target integrity + fabric-on-decor      | `docs/current/EASY-BATCH-PROMPTS.md`                  | **done**                  |
| `P-A`            | Already-planned big-slices (sequenced)                            | `docs/current/BACKLOG-CONSOLIDATED.md` (`LIST 3 §A`) | **open** (sequencing reference; supersedes C-N) |
| `P-B`            | Gold gameplay (quest variety, chains, crafting, puzzles…)         | `docs/current/BACKLOG-CONSOLIDATED.md` (`LIST 3 §B`) | partly done (CB-1 covers multi-type + chains) |
| `P-C`            | NPC depth & society sim — mostly anvil_sim port                  | `docs/current/BACKLOG-CONSOLIDATED.md` (`LIST 3 §C`) | partly done (Soul/Skills shipped); Joy/catastrophe **parked** |
| `P-D`            | Generation depth (mood sliders, asset composition, layout grammar) | `docs/current/BACKLOG-CONSOLIDATED.md` (`LIST 3 §D`) | **open**                  |
| `P-E`            | World / exploration extras (overworld, weather, verticality)      | `docs/current/BACKLOG-CONSOLIDATED.md` (`LIST 3 §E`) | partly done (overworld weather — no-op for now) |
| `P-F`            | Pipeline & eval (winnable oracle, variety metrics, screenshot-diff) | `docs/current/BACKLOG-CONSOLIDATED.md` (`LIST 3 §F`) | partly done (B0 winnable oracle shipped; rest open) |
| `P-G`            | Parking (LOD, adaptive music, mounts, vehicles)                   | `docs/current/BACKLOG-CONSOLIDATED.md` (`LIST 3 §G`) | **parked**                |
| `P-H`–`P-K`      | Adjacent batched slices (referenced in older audit; mostly superseded by CB-/EB-/B-) | `docs/current/BACKLOG-CONSOLIDATED.md`         | **archived** — use B-/CB-/EB- instead |
| `FIX-1`          | Chair-under-table fix                                              | `docs/current/FIX-BATCH-1-PROMPTS.md` (Task 1)       | **done**                  |
| `FIX-2`          | Prop distribution across the room                                 | `docs/current/FIX-BATCH-1-PROMPTS.md` (Task 2)       | **done**                  |
| `FIX-3`          | Wire occlusionTexture (apply baked AO)                            | `docs/current/FIX-BATCH-1-PROMPTS.md` (Task 3)       | **done**                  |
| `FIX-4`          | Wire the room-shell tiling textures                               | `docs/current/FIX-BATCH-1-PROMPTS.md` (Task 4)       | **done**                  |
| `FIX-5`–`FIX-5e` | Other fix-batch items (chairs fix ups, fabric clamps, …)          | `docs/current/FIX-BATCH-2-PROMPTS.md`                | **done** (FIX-5e folded into EB-7) |
| `FIX-6`–`FIX-9`  | Bundle-fix follow-ups (referenced by scene_compiler comments)     | `docs/current/FIX-BATCH-2-PROMPTS.md`                | **archived**              |
| `Quality-A`      | Interior lighting overhaul (ceiling-mounted OmniLight, ambient ≥ 0.4) | `docs/current/QUALITY-FIX-AD-PROMPTS.md` (Task 1)| **done**                  |
| `Quality-B1`     | NPCs spawn in open floor, not inside furniture                    | `docs/current/QUALITY-FIX-AD-PROMPTS.md` (Task 2)   | **done**                  |
| `Quality-B2`     | Chair offset + carryable surface-snap + prop distribution         | `docs/current/QUALITY-FIX-AD-PROMPTS.md` (Task 3)   | **done**                  |
| `Quality-C`      | Rug/decor uses fabric, never stone                                 | `docs/current/QUALITY-FIX-AD-PROMPTS.md` (Task 4)   | **done**                  |
| `Quality-D`      | Simpler sensible ambient audio                                     | `docs/current/QUALITY-FIX-AD-PROMPTS.md` (Task 5)   | **done**                  |
| `E1` (Task N)    | Procedural PBR material pipeline (Task 1–5)                        | `docs/current/E1-MATERIAL-PIPELINE-PROMPTS.md`       | **done**                  |
| `C-0`–`C-9`      | Earlier capability numbers (table) — see AUDIT-03 history          | `docs/current/BACKLOG-PROMPTS-READY.md`              | **archived** — superseded by `CB-N` |
| `T-1`–`T-5`      | Tiny-room-era task IDs (T-1 RoomPlanner parse fallback, T-4 single-source registry, T-5 tiny-room scaling) | (roots in early spine prompts)              | **archived** for T-1/T-4/T-5 (these all shipped); **deprecated form**, use the new `CB-N`/`FIX-N` contrast |
| `U-1`–`U-7`      | "Upgrade" slice IDs (informal; chair-around-table = `U-4`)         | `docs/current/BACKLOG-PROMPTS-READY.md`              | **archived** — superseded by `EB-N` / `FIX-N` |
| `V-1`            | Visual-eval gate v1 (screenshot harness + VLM + CLIP aesthetic)    | `docs/current/V-VISUAL-EVAL-DESIGN.md`               | **done**                  |
| `V-2`            | Visual-eval gate v2 + memory `vlm-vision-api-gotcha`               | `docs/current/CODE-AUDIT.md` (evolved from V-1)      | partly done               |
| `Item 1`         | Light defaults (scene_compiler.py, dead breadcrumb)                | `docs/current/QUALITY-FIX-AD-PROMPTS.md` history     | **dead** — delete during Phase 1.4 `scene_compiler` decompose |
| `Item 2`         | Room dimensions                                                    | (same)                                                | **dead** — same as Item 1  |
| `Item 3`         | Deterministic AABB separation pass + grid                          | (same)                                                | **dead**                  |
| `Item 4`         | Player visible body                                                | (same)                                                | **dead**                  |

If the prefix you hit is `B0`-`B11` (capability bundles), a bundled `CB-N` reference means
**the same task in its later, post-spine form** — use the `CB-N` row's origin doc, not the
older bundle.

---

## 2. Audit-severity marks (in `CODE-AUDIT.md`, `AUDIT-00…05`, `WS5-CODE-REVIEW.md`)

These are severity ornaments on a finding ID, not capability tags. They mean the same thing
wherever you see them.

| Mark     | Meaning                                                   | Origin doc                                  |
|----------|-----------------------------------------------------------|---------------------------------------------|
| `B!`     | confirmed bug, high impact                                | `docs/current/CODE-AUDIT.md`                |
| `B!!`    | bug under specific inputs                                 | (same)                                      |
| `B???!`, `B??!` | bug, severity marked infra-`!!` (very rare, ad-hoc) | (same, occasional)                          |
| `R!`     | robustness, fragile in environment-sensitive paths        | (same)                                      |
| `R!!`    | robustness nit / fallback could fail                      | (same)                                      |
| `R!!!`   | robustness nit (cleanups) — safe to defer                | (same)                                      |
| `N!` / `N` | design note (not a bug)                                 | (same)                                      |
| `?`      | uncertain finding (would need deeper verification)       | `docs/current/CODE-AUDIT.md` (footer)       |
| `!` / `!!` / `!!!` (standalone) | bare severity ornaments used in CODE-AUDIT standalone | (same)                          |

Audit-finding **IDs** (`A1`–`A21`, `T1`–`T19`, `C1`–`C-N`, `R1`–`R3`, `P1`–`P-N`, `L1`–`L-N`,
`Q1`–`Q20`, `X1`–`X20`, `B!`–`B!`-prefixed numeric, `r1`–`r9` review rounds, `R!!` ad-hoc) are
**NOT** in this table — those are *finding-IDs* scoped to a single audit document. Cite the
their audit doc (e.g. `AUDIT-02`, `WS5-CODE-REVIEW.md`) directly.

---

## 3. Cross-cutting audit patterns (`X1`–`X20`)

Used only inside `CODE-AUDIT.md` as section anchors. Cited verbatim from `CODE-AUDIT.md`
"Cross-cutting Concerns":

| Pattern | Where                                                              | Severity   |
|---------|--------------------------------------------------------------------|------------|
| `X1`    | Module-level mutable globals (`_GRAMMAR`, `_LIGHT_HEIGHTS`)        | R — hidden coupling |
| `X2`    | Hardcoded filesystem paths to `engine/devforge/...`                | R — conflicts with AGENTS.md |
| `X3`    | Massive functions (>400 lines) with nested fallbacks               | R — testing/ext pain |
| `X4`    | Magic numbers everywhere                                           | R — refactor brittleness |
| `X5`    | Loop-variable shadowing (scene_compiler `:998`)                    | B — confusing |
| `X6`    | `except Exception:` swallowing everything                          | R — invisible failures |
| `X7`    | Hardcoded seed `Random(42)` (nondeterministic shuffle)              | R — non-reproducible  |
| `X8`    | `sys.exit(main())` at module bottom (no `__name__` guard)          | R — import side-effects |
| `X9`    | Empty placeholder files (`__init__.py`, `conftest.py`)             | !!! — confusing     |
| `X10`   | Late imports inside functions (cycle avoidance)                    | R — spaghetti risk  |
| `X11`   | Category list duplicated across GBNF grammars                      | R — drift           |
| `X12`   | `main()` runs at module load (no `__name__` guard) in `blender/`   | B — bpy side-effects |
| `X13`   | Hardcoded endpoint `127.0.0.1:8002`                                | R — pairing with grammar=None footgun |
| `X14`   | Singular Decision-Point dataclass + dict branches both exercised   | R — signal-aggregator undercount |
| `X15`   | Hardcoded RNG without seeding (`randf_range`, `randi %`)           | R — non-reproducible in V-1 regression |
| `X16`   | Global `_load_attempted` / lazy-init pattern without locks         | R — multi-thread race |
| `X17`   | Magic carryable/role/theme lists in `eval/signals.py`              | R — silent drift   |
| `X18`   | `set("collision_layer", N)` string-bypass of typed setters         | R — static-analysis off  |
| `X19`   | Function-level `if OS.has_feature("headless")` guard for tests     | N — good pattern, copy elsewhere |
| `X20`   | Godot `_process`/`_physics_process` raycasts per frame              | R — scene-complexity perf cliff |

---

## 4. Adding new tags

**Don't introduce ad-hoc prefixes.** New capability work belongs in one of:
- a new `CB-N` row in CLI-FULL-BACKLOG-PROMPTS (large multi-bundle work)
- a new `EB-N` row in EASY-BATCH-PROMPTS (small self-contained work)
- a new `FIX-N` row in FIX-BATCH-N (targeted bug repair)
- a new `Quality-X` row in QUALITY-FIX-AD-PROMPTS (playtest-driven polish)

If you must add an entirely new prefix: add a row to Section 1 in this doc **in the same commit**
that introduces the prefix in code. (See `WS5-CODE-REVIEW.md` r3 B!! for why — informally invented
prefixes such as `U-7`, `S-N`, `R!` are exactly the noise this legend eliminates.)

## 5. Superseded prefixes (do not use)

`A1`–`A21`, `C1`–`C-N`, `T1`–`T19`, `P1`–`P-N`, `L1`–`L-N`, `Q1`–`Q20`, `B!`-prefixed numeric,
`r1`–`r9`, `U-N`, `S-N` — these are scoped to a single audit document. They are **finding IDs**, not
tracker prefixes. If you want to *cite* one, write `AUDIT-02 C3`, `WS5-CODE-REVIEW r5`, etc.
