# Quality Fix A–D — Delegation Prompts (from live playtest)

> **For the CLI AI:** implement task-by-task, TDD red→green, one commit per task. These are
> deterministic build-layer fixes (no spine/Brief changes) from a real 27B playtest of
> `builds/showcase_soul_qwen3-6-27b`. Root-cause diagnosis is in the orchestrator's notes;
> each task states the cause + the fix + concrete acceptance tests.

**Context — what the player saw and why:**
- Props look like grey boxes · "no ceiling" · broken light ⇒ the room has **zero interior
  lights**, a near-black environment, and a single dim directional "sun" lighting an enclosed box.
- Two NPCs stand inside furniture · a chair is under a table · a carryable floats · everything is
  crammed in one quadrant of an 8×7 m room ⇒ **placement** bugs in `room_layout`/`scene_compiler`.
- Carpet is marble ⇒ `rug_0` got `rough_granite`; fabric-on-decor didn't fire for `workshop`.
- Sound is weird ⇒ `audio.gd` synth.

**Asset texture quality (E) is OUT OF SCOPE here** — it's a separate brainstorm (Gen-2 props +
floor/wall visuals). Do not touch the Blender generators.

## Global Constraints

- **Testing split:** **[CLI]** runs the fast gates (`pytest tests/ -q` + `pytest
  tests/test_godot_smoke.py -q`, both green) per task, then hands off. **[ORCH]** does the live
  build + visual confirm — do NOT run it.
- After any `scene_compiler.py` / `godot_template/` change: scaffold a build, `godot --headless
  --path <build> --quit`, grep stderr for `SCRIPT ERROR|Parse Error|Failed to load` = 0.
- Geometry fixes must add **deterministic acceptance tests** on the compiled manifest/scene.
- Never touch `addons/godot_ai`. Commit per task with proof.

---

## Task 1 [CLI] — Interior lighting overhaul (biggest visual win)

**Cause:** an enclosed room (floor + 4 walls + ceiling at y=3) is lit like the outdoors — one
`DirectionalLight3D` (energy 2.2), `ambient_light_color (0.18,0.14,0.1)`, background near-black,
and **no `OmniLight3D` interior lights** (count = 0). Result: dark, flat — props read as grey
boxes, the ceiling reads black ("no ceiling"), shadows look broken.

**Files:** `foundry/scene_compiler.py` (environment + a new interior-light emitter),
`foundry/room_control.py` (`LIGHTING_TABLE` brightening); tests in `foundry/tests/`.

**Fix:**
- **Always emit interior lighting** sized to the room: one ceiling-mounted `OmniLight3D` per
  ~20–25 m² (at least 1), placed near the ceiling (y ≈ room_height − 0.4) over the room, warm per
  theme, `omni_range` ≈ room diagonal, energy tuned so the floor/props are clearly lit. This is
  independent of whether lantern/candle props exist (this room had none).
- **Raise ambient** so no theme is near-black: add/raise `ambient_light_energy` (e.g. ≥ 0.4) and
  lift the darkest `LIGHTING_TABLE` ambient values — keep dungeon/crypt *moody* but not pitch black;
  workshop/kitchen/tavern clearly lit.
- Demote the directional light to a soft fill (lower energy) or keep it; the interior omni(s) are
  now the primary source. The ceiling must read as lit from below.

**Acceptance tests:**
- [ ] Compiled scene for a default room contains ≥ 1 `OmniLight3D` not attached to a lantern/candle
  prop (an interior room light).
- [ ] `ambient_light_energy` (or equivalent) in the emitted Environment ≥ the new floor for every
  `LIGHTING_TABLE` theme.
- [ ] Headless-load clean.
- [ ] Commit: `fix(foundry): interior lighting so generated rooms read (quality A)`.

## Task 2 [CLI] — NPCs spawn in open floor, not inside furniture

**Cause:** both NPCs were placed at z = −2 (the furniture-packed back row): `npc_0 (−1.25,−2)`
overlapped `table_0 (−1.8,−1.8)`. NPC placement ignores prop footprints.

**Files:** `foundry/scene_compiler.py` (NPC positioning, ~L429 region); tests.

**Fix:** choose each NPC's (x,z) from **open floor** — at least `clearance` (e.g. 0.6 m) from every
placed prop's footprint AND from the player spawn (0,0) AND from other NPCs; distribute them (don't
stack both on the back wall). Face them toward room center / player.

**Acceptance test:**
- [ ] In a compiled multi-NPC scene, every NPC (x,z) is ≥ clearance from every prop footprint and
  from every other NPC. (Compute footprints from category half-extents.)
- [ ] Commit: `fix(foundry): place NPCs in open floor, clear of furniture (quality B1)`.

## Task 3 [CLI] — Furniture & carryable geometry: chair-under-table, floaters, distribution

**Files:** `foundry/room_layout.py` (U-4 chairs ~L204, P-E carryables ~L109, grid distribution);
tests.

**Three deterministic fixes, each with a test:**
1. **Chair not under table** — the U-4 chair offset must be ≥ `table_half_depth + chair_half_depth`
   so the chair tucks to the table edge, not under the top. *Test:* every chair's distance to its
   assigned table ≥ that sum (no footprint overlap).
2. **No floating carryables** — a carryable placed "on" furniture must sit at that furniture's
   `FURNITURE_TOP_Y[cat]` **and** within its XZ footprint; if no valid host surface, place it on the
   floor (y ≈ its own half-height). *Test:* every carryable's y equals a real host-surface top with
   (x,z) inside that host's footprint, OR it's a floor item at floor height — never a height with no
   surface under it.
3. **Distribute props across the room** — props currently cluster in one quadrant of an 8×7 room.
   Spread placement over the room grid. *Test:* the placed-prop bounding box spans ≥ ~55% of each
   room dimension (or props occupy cells in ≥ 3 of the 4 quadrants) for a normally-furnished room.
- [ ] Commit: `fix(foundry): chair offset, carryable surface-snap, prop distribution (quality B2)`.

## Task 4 [CLI] — Rug/decor uses fabric, never stone

**Cause:** `rug_0` rendered as `rough_granite` (marble). The fabric-on-decor guard didn't fire for
the `workshop` theme.

**Files:** `foundry/room_control.py` (palette / `fabric_on_decor`); tests.

**Fix:** rugs/carpets (and other soft decor) must resolve to a **fabric** material for ALL themes —
if a theme palette has no fabric, inject one for the rug. Never allow `rough_granite`/`wrought_iron`
on a rug. (Generalize the existing `room.fabric_on_decor` so it covers `workshop` and any theme.)

**Acceptance test:**
- [ ] For every `THEME_TABLE` theme, a room containing a rug yields the rug with a material in the
  fabric family (assert across all themes, including `workshop`).
- [ ] Commit: `fix(foundry): rugs always fabric, never stone, across all themes (quality C)`.

## Task 5 [CLI] — Simpler, sensible ambient audio

**Cause:** the procedural synth ambience sounds wrong/weird.

**Files:** `foundry/godot_template/scripts/audio.gd`; mirror the existing smoke audio assertion.

**Fix:** replace the 3-layer drone with a **simple, quiet, sensible** ambient bed — a soft low room
tone at low volume, subtle, theme-flavored but unobtrusive. The goal (user's words): "simpler, but
makes sense." Keep footstep/pickup/talk/win cues. Keep the autoload + ambient stream instantiable
without error (the smoke test checks this).

**Acceptance test:**
- [ ] Existing audio smoke assertion still passes (autoload + ambient stream instantiate).
- [ ] Commit: `fix(foundry): simpler sensible ambient audio (quality D)`.

---

## [ORCH] Verification — orchestrator only

After handoff (fast gates green), the orchestrator:
1. Generates a fresh build (≥9B) and checks the **deterministic** fixes from the manifest/scene:
   interior `OmniLight3D` present + ambient raised; every NPC clear of furniture; chairs not under
   tables; carryables on real surfaces (no floaters); props distributed across the room; rug
   material in fabric family; ceiling node lit.
2. Hands the build to the user for the **visual** confirm (lighting readability, audio feel) — the
   headless gate can't see those. Iterate on anything that still reads wrong.
