# DevForge Capability Roadmap — From Node Generator to Development Companion

**Date:** June 11, 2026
**Target game:** 3D open-world first-person RPG (solo developer, ~18-month horizon)
**Synthesizes:** `Research/` (ZAI, QWEN, Buffy/Codebuff manifesto, deep-research report,
Qwen strategic-pivot PDF) + a fact-check against the actual godot-ai tool inventory
and the DevForge codebase as of Round 8.

---

## 0. What the research got right — and the two things it got wrong

All five documents converge on one principle, and it is correct:

> **The LLM is a classifier, not a creator.** Deterministic core, LLM wrapper.
> The LLM selects, customizes, and explains; human-written rules, templates,
> and algorithms do the work. (Validated by every benchmark cited in
> `Research/report.md`.)

Two factual corrections, both verified against the code rather than assumed:

1. **"Godot doesn't expose runtime state through MCP" is false for this stack.**
   godot-ai's plugin dispatcher (verified June 2026) registers `run_project`,
   `stop_project`, `game_eval`, `game_command`, `get_logs`, `take_screenshot`,
   `get_performance_monitors`, and — critically — **`run_tests` and
   `get_test_results`**. The manifesto's anti-roadmap priced "runtime
   observation" at 80–120 hours of new capability; in reality the primitives
   exist and the work is orchestration, not capability-building. Bounded
   runtime tools move from "don't build" to "moderate."

2. **"The model is fixed at Gemma-4B-active" is a config knob, not a law.**
   DevForge already ships a Claude backend (`DEVFORGE_LLM_BACKEND=claude`).
   The right architecture is **graceful degradation tiers**: every feature's
   core must work with *no* LLM at all (deterministic), get explanations from
   the local model (free, private, always on), and *optionally* hand the few
   genuinely creative tasks (dialogue prose, lore drafts) to a cloud model
   when you choose to spend money. Design for tier 0; tiers 1–2 are upgrades,
   never requirements.

One more under-appreciated asset: godot-ai ships **polish primitives as
presets** — `animation_preset_shake/fade/slide/pulse`, `camera_apply_preset`,
`material_apply_preset`, `particle_apply_preset`, `physics_shape_autofit`,
`audio_player_create`. The "90/10 polish" items the research says distinguish
amateur from professional games are *one batch command away*, not a
generation problem.

---

## 1. The Master Matrix

Two axes, as requested:

- **Implementation** — 🟢 Easy (≤ 2 days) · 🟡 Moderate (3–7 days) ·
  🟠 Hard (2–4 weeks) · 🔴 Very hard (months / research-grade)
- **Workload relief** — how much of *your* work it removes over the life of an
  open-world FP RPG: ★ marginal · ★★ noticeable · ★★★ significant ·
  ★★★★ major · ★★★★★ transformative

Plus **When it pays** — the development phase where it earns its keep
(your requirement: useful from first day to last).

| # | Capability | Implementation | Relief | When it pays | Origin |
|---|------------|:---:|:---:|---|---|
| 1 | **Scene Doctor** (deterministic audit rules) | 🟢 | ★★★★ | All phases — daily | Buffy P1 |
| 2 | **Batch Operator** (filtered mass edits) | 🟢 | ★★★★ | Mid → polish | Buffy P2, ZAI |
| 3 | **Error Triage** (`get_logs` → classify → explain) | 🟢 | ★★★ | All phases | ZAI "live debugging", lite |
| 4 | **Polish Pass** (preset-driven game-feel audit + apply) | 🟢 | ★★★ | Polish/ship | Report §4.5 + tool inventory |
| 5 | **Project Navigator** ("where is X?" via `find_symbols`/`search_filesystem`) | 🟢 | ★★ | Mid → late (big codebase) | New |
| 6 | **Progress Journal / Session Brief** | 🟡 | ★★★ | Mid → last day (survival tool) | Buffy P5 |
| 7 | **Template Forge** (tested system templates) | 🟡 engine + content | ★★★★★ | First day → mid | Buffy P4, PDF |
| 8 | **Lorekeeper** (content DB + referential integrity) | 🟡 | ★★★★★ | Mid → last day | New (RPG-specific) |
| 9 | **Quest Graph Validator** (progression reachability) | 🟡 | ★★★★ | Mid → ship | New (RPG-specific) |
| 10 | **Performance Sentinel** (perf budgets per area, regression tracking) | 🟡 | ★★★★ | Mid → ship (open world!) | New, enabled by `get_performance_monitors` |
| 11 | **Signal/Dependency Mapper** | 🟡 | ★★★ | Mid | ZAI |
| 12 | **Test Harness** (deterministic scaffolds + `run_tests` loop) | 🟡 | ★★★ | Mid → ship | QWEN #1, descoped per report |
| 13 | **Balance Simulator** (Monte Carlo over content DB) | 🟡 | ★★★ | Late | QWEN #5 |
| 14 | **Design Companion** (genre pattern database) | 🟠 | ★★★ | Early-mid | Buffy P3 |
| 15 | **Smoke Runner / "Dailies"** (scripted auto-playtest + report) | 🟠 | ★★★★ | Mid → last day | New; bounded Game Doctor |
| 16 | **Dialogue Engine** (schema-constrained, Lorekeeper-fed) | 🟠 | ★★★★★ | Mid → late | QWEN #4, constrained |
| 17 | **Scene Refactorer** (extract subtree → .tscn instance) | 🟠 | ★★★ | Mid | ZAI |
| 18 | **Shader Studio** (template + grammar-constrained) | 🟠 | ★★ | Polish | QWEN #2 |
| 19 | **Surgical Script Editing** (LLM-driven semantic edits) | 🔴 local / 🟠 cloud-tier | ★★★ | Mid | ZAI; report says avoid locally |
| 20 | **Autonomous Game Doctor** ("fixes bugs while you sleep") | 🔴 | ★★★★ | — | QWEN #3; keep as north star, not next step |
| 21 | **Behavioral test generation** (LLM invents test logic) | 🔴 | ★★ | — | Anti-roadmap (all docs agree) |
| 22 | **Iteration/feel tuning loops** ("make the jump snappier") | 🔴 | ★ | — | Anti-roadmap: you feel faster than it thinks |

**Reading the matrix:** items 1–5 are the quick wins (build in days, pay off
immediately). Items 6–13 are the production backbone — this is where an
open-world RPG lives or dies. Items 14–18 are worth building once the
backbone proves itself. Items 19–22 stay on the shelf until the model tier
or the evidence changes.

---

## 2. The quick wins (🟢 — build first, days each)

### 1. Scene Doctor — ★★★★
Deterministic rules walk the scene tree; the LLM only writes the explanations.
The manifesto's 15 rules are the start (CollisionShape3D parentage, zero mass,
dangling script refs, no current camera, null meshes…). **RPG addition:** rules
scale superlinearly with scene size — an open world with thousands of nodes is
exactly where "did I check everything?" becomes impossible by hand.
*Already in the stack:* `get_scene_tree`, `find_nodes`, `get_node_properties`,
the validator's `VALID_GODOT_TYPES`, and `physics_shape_autofit` for one-command
fixes of the most common violation class.

### 2. Batch Operator — ★★★★
`filter(type/name/subtree/no-script) → preview → confirm → batch_execute`.
Regex-parse the common query shapes; LLM-parse only the exotic ones (hybrid,
per the manifesto). Forty hand-edits become one command. The preview-confirm
step is non-negotiable — it's the trust feature, not a UX nicety.

### 3. Error Triage — ★★★
`get_logs` → deterministic parse (DevForge's `ErrorParser` already exists!) →
classify against a table of the ~30 most common Godot runtime errors → explain
and point at the file/line. *Not* auto-fix — triage. The "fix it for me" step
can come later behind a confirm gate. Cheapest high-value loop in the list.

### 4. Polish Pass — ★★★
The Bayreuth game-feel taxonomy as an audit: missing screen shake, unsmoothed
cameras, zero-energy lights, missing pickup particles, untweened UI. Detection
is property checks; **application is godot-ai presets** (`animation_preset_shake`,
`camera_apply_preset`, `particle_apply_preset`). The research's "10% of polish
produces 90% of perceived quality" — this is that 10%, mechanized.

### 5. Project Navigator — ★★
"Which script handles falling damage?" → `find_symbols` + `search_filesystem` +
signal lists → ranked answer with paths. Trivial plumbing, and it compounds:
every other feature gets better when the agent can locate things reliably.

---

## 3. The production backbone (🟡 — the RPG-critical tier)

### 7. Template Forge — ★★★★★ (the single biggest lever for your game)
Human-written, tested system templates; the LLM selects and parameterizes.
For an open-world FP RPG the Phase-1 template list writes itself:

| Template | Why it's day-one for your genre |
|---|---|
| `fps_controller` (sprint/crouch/head-bob/interact raycast) | You need it before anything else |
| `interaction_system` (raycast + prompt UI + interface) | Every door, NPC, item touches it |
| `inventory_system` | RPG staple |
| `save_system` (slot + autosave + versioned schema) | Retrofitting saves into an open world is agony — do it first |
| `quest_system` (data-driven, feeds #9) | The spine of the genre |
| `dialogue_ui` (typewriter, choices — feeds #16) | The other spine |
| `day_night_cycle` + `weather_hooks` | Open-world atmosphere |
| `world_streaming_cell` (chunk load/unload skeleton) | THE open-world template; nobody ships without it |
| `npc_schedule` (time-of-day waypoint routine) | Makes the world feel alive |
| `lootable_container` / `pickup` | Used hundreds of times |

Engine first (slot system, parameter prompts, collision-safe instancing),
then 2–3 templates per week as you need them — **build each template the week
your game needs that system, and extract it from working code**. The forge
grows alongside the game instead of ahead of it.

### 8. Lorekeeper — ★★★★★ (new; the RPG data backbone)
An open-world RPG is a content database wearing a game engine as a coat:
items, NPCs, quests, dialogue, loot tables, spawn tables, recipes. Keep them
as data (`.tres`/JSON — godot-ai has full resource tools), and DevForge becomes
the **referential-integrity engine**: every quest reward exists in the item DB;
every dialogue speaker exists as an NPC; every loot table sums to 100%; no
orphaned lore entries; schema migrations when you add a field to 400 items.
Deterministic checks, LLM explanations — and the existing **GBNF grammar
infrastructure constrains LLM-generated *content* (item descriptions, name
variants) to your schema** exactly the way it constrains architecture deltas
today. This reuses DevForge's most battle-hardened component for the thing
your genre needs most.

### 9. Quest Graph Validator — ★★★★ (new)
Quests-as-data form a directed graph (prerequisites, items, flags, area
unlocks). Validating it is **reachability analysis, not AI** — the same
discipline as railway-interlocking verification: can the player always reach
the main quest's end from every save point? Does any side quest soft-lock if
the player sells a key item? Which content is unreachable? Run it on every
quest edit. A soft-lock found by a player costs a refund; found by a graph
algorithm it costs nothing. The LLM narrates the violation path in plain
language ("Quest 'Iron Debt' requires 'Smith's Hammer', which only drops in
the mine you lock behind 'Iron Debt'").

### 10. Performance Sentinel — ★★★★ (new; open-world-specific)
`get_performance_monitors` + `run_project` + per-area budgets (FPS, draw
calls, node count, physics bodies) stored in the Progress Journal's history.
Open worlds die by accumulation — every week the forest gets 5% heavier and
nobody notices until it's 23 FPS. The sentinel runs the game, teleports
through your POI list (`game_eval`), samples each, and diffs against last
week. CI performance budgets, applied to a game world.

### 6. Progress Journal — ★★★ · 11. Signal Mapper — ★★★ · 12. Test Harness — ★★★ · 13. Balance Simulator — ★★★
As specced in the research, with two corrections: the **Test Harness descopes
QWEN's Autopilot** to what's reliable — deterministic test *scaffolds* from
parsed signatures (no invented logic), executed via godot-ai's existing
`run_tests`/`get_test_results`, LLM explains failures. And the **Balance
Simulator is only 🟡, not visionary** — once the Lorekeeper exists, Monte
Carlo over the content DB is a Python afternoon, and "can a level-10 player
afford the endgame sword?" becomes a query. Build it when balancing starts
to hurt (late-mid production).

---

## 4. The earned tier (🟠 — build after the backbone proves itself)

### 15. Smoke Runner / "Dailies" — ★★★★
Film productions watch yesterday's footage every morning; you should watch
yesterday's build. A *scripted* (not autonomous) probe: launch the game,
teleport through POIs, exercise the interaction template on known objects,
capture screenshots + logs + perf samples, produce one morning report.
Every primitive exists (`run_project`, `game_eval`, `take_screenshot`,
`get_logs`, `get_performance_monitors`). 🟠 only because orchestration and
flakiness-hardening take iterations. This is the bounded, honest version of
the Game Doctor — hypothesis-free, so the small model can't hallucinate;
it just runs the checklist and triages what it saw.

### 16. Dialogue Engine — ★★★★★ relief, but earn it
50,000 words of branching dialogue is the single largest content cost in your
genre. The trap is open-ended generation; the discipline: **structure first**
(dialogue trees as data, validated by the Quest Graph Validator), **prose
second** (lines generated *into* the structure, grammar-constrained, fed by
Lorekeeper facts so NPCs don't contradict the world). Local model drafts
plenty well at this temperature of task; the Claude backend is the optional
quality tier for hero NPCs. Needs #8 first — without the Lorekeeper it
hallucinates lore.

### 14. Design Companion · 17. Scene Refactorer · 18. Shader Studio
As specced in the research. For your genre, seed the Design Companion's
pattern DB with *open-world FP RPG* patterns (interaction prompts, stamina
gating, fast travel, lockpicking minigames, radiant encounters, rest
mechanics) rather than platformer patterns. The Shader Studio is ★★ for you
— important shaders (water, sky, foliage wind) are better sourced than
generated; build it last or never.

---

## 5. The shelf (🔴 — not now, and why)

| Item | Why it stays shelved | What would un-shelve it |
|---|---|---|
| Surgical script editing (local) | ~15% reliability for semantic edits at this model class — a productivity *tax* | Claude-tier backend used deliberately, with diff-preview + confirm; or a dramatically better local model |
| Autonomous Game Doctor | Needs hypothesis formation across runs — exactly the multi-step causal reasoning the benchmarks say fails | The Smoke Runner's data corpus + a stronger model. Keep as north star |
| Behavioral test generation | Plausible-but-wrong tests are worse than no tests (all five docs agree) | Same as above |
| Feel-tuning loops | You can feel a jump in 2 seconds; the loop costs minutes per iteration | Nothing foreseeable — this one is genuinely misconceived |

---

## 6. Recommended build order (both axes combined)

The sequencing principle: **every item must be useful for the game you are
building the week you build it** — dogfooding is the gimmick filter.

```
Phase A — prove it (1–2 weeks):
  1. Scene Doctor (5 rules)  →  2. Batch Operator  →  3. Error Triage
  Success test: one real session on YOUR project where each fired usefully.

Phase B — the spine (3–6 weeks, interleaved with actual game work):
  7. Template Forge engine + fps_controller + save_system + interaction_system
  8. Lorekeeper v1 (item/NPC/quest schemas + integrity checks)
  6. Progress Journal v1 (session brief)

Phase C — the open-world insurance (as the world grows):
  9. Quest Graph Validator   10. Performance Sentinel   4. Polish Pass
  12. Test Harness           15. Smoke Runner

Phase D — the content engine (when writing begins):
  16. Dialogue Engine (on top of Lorekeeper)   13. Balance Simulator
  14. Design Companion
```

Phase A is deliberately the manifesto's Week 1 — that part of the research
is right and needs no improvement. The step further is B/C: the research
optimized for "any solo dev, any genre"; this order optimizes for *your*
game, where data integrity (8, 9), performance accumulation (10), and
content volume (16) are the actual 18-month killers.

---

## 7. Architecture rules for everything above

Carried over from the research (they're correct) plus two additions:

1. **LLM = classifier/explainer.** Rules, templates, graph algorithms, and
   simulations are human-written and deterministic.
2. **Deterministic core must work with the LLM off.** Tier 0: no LLM
   (raw findings). Tier 1: local model explains (default). Tier 2: cloud
   model creates prose (opt-in, per-call).
3. **One tool, one job.** `/audit`, `/batch`, `/triage`, `/template`,
   `/lore`, `/quests`, `/perf`, `/journal`, `/dailies` — separate MCP tools.
4. **Preview → confirm → apply.** Nothing mutates the project unconfirmed.
5. **Explain everything.** Findings name the node/file/line and the fix.
6. **NEW — Everything emits to the Journal.** Every audit score, perf
   sample, and batch op is a time-series datapoint. The history *is* the
   product after month 6: "show me when the forest got slow."
7. **NEW — Schemas are contracts.** Lorekeeper schemas, quest-graph shape,
   template slots: versioned, validated, migrated. The GBNF infrastructure
   already enforces this for deltas; extend, don't reinvent.

---

## 8. The one-line summary

The research is unanimous and right about the *paradigm* (classifier, not
creator) and the *first week* (Doctor, Batch, Triage). Where this roadmap
goes further: the godot-ai inventory makes bounded runtime tools (Smoke
Runner, Performance Sentinel, Test Harness) **moderate instead of impossible**,
and for an open-world RPG specifically, the highest-value tier is not scene
tooling at all — it is **data tooling** (Lorekeeper, Quest Graph Validator,
Balance Simulator) wrapped around the engine DevForge already has. A node
generator helps you on day one. A referential-integrity engine for your
world's data is still saving you from soft-locks on the day you ship.
