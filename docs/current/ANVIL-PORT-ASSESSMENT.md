# Anvil → Forge: Port Assessment (gold / silver / bronze / dismissed)

**Date:** 2026-06-20. Source: `anvil-main/crates/anvil_sim` (+ `anvil_world`, `anvil_core`).
**Framing:** "Port" = adopt the **design/data-model/algorithm into the Python foundry** (LLM fills the
nouns/traits within a closed grammar; deterministic Python runs the logic; Godot reads state) — *not*
copy Rust. This keeps our chosen stack while reusing Anvil's done design. Same data shapes on both
sides also make a future "anvil_sim as a service over FFI" swap cheap, so porting the design now
doesn't burn the Rust option. Anvil **is** the design for LIST 3 §C (NPC depth & society sim).

---

## 🥇 GOLD — port these (highest value-per-effort, compose with current NPCs)

### G1. Layered Soul — `soul.rs` / `soul/axes.rs`  [S–M] ★ start here
- **Substrate** (3 stable traits, −1..+1): courage↔fear, generosity↔selfishness, stability↔anxiety.
- **Emotional axes** (4, −1..+1, each *filters a category of perception*): security↔threat,
  belonging↔isolation, agency↔helplessness, satiation↔desperation.
- **Why gold:** tiny model (7 floats + simple update rules) that turns today's interchangeable
  `villager` NPCs into *characters* — the exact "canned/identical NPC" gap we saw in playtests. The
  LLM already picks `npc_role`; extend the grammar so it also picks a substrate; events nudge the axes;
  dialogue tone + idle-bark + action choice read them. Persists via the C-3 world-model log.
- **Forge touch:** behaviour_gen grammar + a `soul.py` model + quest_data field + npc.gd reads tone.

### G2. Needs + utility-action loop — `needs.rs` / `actions.rs` / `actions/catalogue.rs` / `utility/scoring.rs`  [M]
- 7 needs (food/water/shelter/safety/sleep/companionship/**joy** — joy only from catalyst events),
  per-need decay; a ~21-action catalogue (each tagged primary_need, coping_type, time_preference,
  communal, major/minor, duration); NPCs pick the **utility-max** action.
- **Why gold:** the engine that makes NPCs *do things* instead of standing still — the backbone of
  "living world," and the design is fully worked out. Pairs directly with C-6 pathfinding (path to
  satisfy a need) and the greenlit day/night cycle (time-of-day action preferences).
- **Forge touch:** new deterministic `npc_sim.py` (needs decay + action utility) + Godot behavior states.

### G3. Catastrophe / world-events engine — `catastrophe/{event,propagation,signal}.rs`  [M–L]
- 7 event types (flood/earthquake/wildfire/blizzard/drought/landslide/blight), each with a dominant
  **consequence** (resource loss / structural / displacement / deaths / disease), **precursor signals**
  (foreshadowing), and **spatial propagation** from an epicentre.
- **Why gold:** a *generative emergent-event engine* — the "something happened here / find the gold"
  wildcard. An event mutates the world + spikes NPC needs → produces emergent quests ("the blight
  ruined the stores — fetch grain"). Novel, and composes with rooms, needs (G2), and quest-gen.
- **Forge touch:** `world_events.py` (themed event pick + deterministic propagation/consequence) →
  feeds room-gen + quest-gen.

---

## 🥈 SILVER — port when the host system exists

- **Connection layers + mood contagion** — `settlement/connection.rs`: Family(1.0)/Proximity(0.5)/
  Village(0.1) weighted social graph; emotion spreads along it. Cheap + emergent, but wants persistent
  multi-NPC context (we have the seeds). Becomes gold once NPCs persist across rooms.
- **Memory (event recollection)** — `settlement/memory.rs`: NPCs remember events. Natural home is the
  existing C-3 world-model log; value appears when dialogue references memories.
- **Skill domains / affordances / fluency / practice** — `skill/*`: 7 domains, unlockable affordances,
  practice/decay, perceptibility→animation. Real RPG progression, but premature until there are
  *verbs to practice* (combat/crafting). Port alongside C-8.
- **TimeBlock day-phase preferences** — `actions.rs::TimeBlock`: actions preferred by time of day.
  The natural companion to the greenlit **day/night cycle** (NPCs sleep at night, work by day).
- **CatalystEvent / Joy** — `settlement/catalyst.rs` / `system/joy.rs`: the positive counterpart to
  catastrophe (joy only from celebrations). Port after G2 needs.
- **Continuous age + physical capability** — `age.rs`: age curve gates actions / characterization.

---

## 🥉 BRONZE — small/nice, low priority

- **Settlement economy pools** (`settlement/settlement_type.rs`) — shared stores; matters with trading.
- **Family structures** (`settlement/family.rs`) — matters with a settlement layer.
- **Targeting / SocialPriority** (`targeting.rs`) — a small AI target-selection helper for G2.
- **Perceptibility → animation-state mapping** (`skill/perceptibility.rs`) — only visible once NPCs
  are rigged/animated (C-9).

---

## 🗑 DISMISSED — don't port (one-line why)

- **Physics (`system/physics*`, RigidBody/Collider save-state)** — Godot/Jolt already gives us physics.
- **DeterministicRng / xorshift64\*** — we already have deterministic seeding in Python; no need.
- **WorldRuntime / SimContext / SimEvent / SimError plumbing** — Rust engine-boundary scaffolding; we'd reimplement idiomatically, not port.
- **anvil_core newtype IDs / ValidationErrors / error buffers** — Rust idioms; Python uses dataclasses + exceptions (concept, not code).
- **`#![deny(warnings)]` / clippy lints / Bevy-boundary notes** — Rust tooling; N/A.
- **`physics_save` / EntityHandle** — save-state for Rust physics; Godot serializes its own scenes.

---

## Recommended sequence
**G1 Soul first** (smallest, fixes the "canned NPC" gap immediately) → fold **TimeBlock** in with the
**day/night cycle** → **G2 needs+utility** (living NPCs, pairs with C-6) → **Connection+contagion** +
**Memory** (emergent social texture on the C-3 log) → **G3 catastrophe events** (emergent quests) →
skills with C-8. Each is a LIST-3 §C item with the design already done in Anvil.
