# Fix-Batch 1 — Delegation Prompts (consolidation)

> **For the CLI AI:** implement task-by-task, TDD red→green, one commit per task. Deterministic
> build-layer fixes from orchestrator verification (A–D leftovers + E1 "baked-but-not-wired" gaps).
> No new features. Exact locations + test assertions below (the asserts are the ones the orchestrator
> already used to *find* these).

## Global Constraints

- **Testing split:** **[CLI]** runs the fast gates (`pytest tests/ -q` + `pytest
  tests/test_godot_smoke.py -q`, green) per task, then hands off. **[ORCH]** regenerates builds + visual
  confirm — do NOT run it.
- After `scene_compiler.py` / `build_asset.py` / `godot_template/` changes: scaffold a build, `godot
  --headless --path <build> --quit`, grep stderr for `SCRIPT ERROR|Parse Error|Failed to load` = 0.
- Geometry/structural fixes add deterministic acceptance tests. Never touch `addons/godot_ai`.

---

## Task 1 [CLI] — Chair-under-table: offset along the approach axis

**Cause:** `room_layout.py` (~L240) sets `chair_standoff = table_half_depth + chair_half_depth` =
0.4 + 0.25 = 0.65 m — but the table is **1.2 m wide × 0.8 m deep**. A chair approaching along the *width*
needs 0.6 + 0.25 = 0.85 m, so it still overlaps the tabletop.

**Fix:** make the standoff **axis-aware**. From the chair→table vector `(dx, dz)`, if `|dx| >= |dz|` the
chair approaches along the table's X extent → use `table_size[0]/2`; else use `table_size[2]/2`. Add the
chair's half-extent on that axis + a small gap (e.g. 0.08 m). (A simpler safe fallback:
`max(table_size[0], table_size[2])/2 + max(chair_size[0], chair_size[2])/2 + 0.08`.)

**Test:**
- [ ] In a compiled scene with chairs + tables, every chair's distance to its assigned table ≥
  `table_half_extent_along_approach + chair_half_extent + gap` → no footprint overlap from any direction.
- [ ] Commit: `fix(foundry): chair offset along approach axis (no table overlap)`.

## Task 2 [CLI] — Prop distribution across the room

**Cause:** `room_layout.py` (~L69) does `placed = furniture[: len(cells)]` then `zip(placed, cells)` —
the first N grid cells (row-major from a corner), so few props cluster in one quadrant of an 8×7 room.

**Fix:** when `len(placed) < len(cells)`, **spread** the props across the full cell set deterministically
— e.g. pick cells at an even stride (`stride = len(cells) / len(placed)`) so they cover the room, instead
of the first N. Keep it deterministic (seeded if you shuffle).

**Test:**
- [ ] For a normally-furnished room, the placed-prop bounding box spans ≥ ~55% of **each** room dimension
  (or props occupy ≥ 3 of 4 quadrants). (This is the orchestrator's verification check — it currently
  fails at ~46–50%.)
- [ ] Commit: `fix(foundry): distribute props across the room grid`.

## Task 3 [CLI] — Wire occlusionTexture (apply the baked AO)

**Cause:** `build_asset.py` bakes AO into the ORM image's **R** channel, but the exported glTF material
has **no `occlusionTexture`** — so Godot never applies the AO (the bake is wasted). The existing
"AO-in-ORM" test checks the channel data, not the material reference.

**Fix:** ensure the glTF export emits an **`occlusionTexture`** referencing the ORM image (glTF ORM
convention: occlusion=R, roughness=G, metallic=B; `occlusionTexture` and `metallicRoughnessTexture` point
to the *same* image). In Blender this means connecting AO through the glTF-settings node group's
`Occlusion` input (or setting the occlusion texture on export) so the exporter writes the entry.

**Test:**
- [ ] A freshly-built asset GLB's material now contains an `occlusionTexture` referencing the ORM image
  (parse the GLB JSON: `materials[0].occlusionTexture` present). Determinism preserved.
- [ ] Commit: `fix(foundry): wire occlusionTexture so baked AO is applied (E1)`.

## Task 4 [CLI] — Wire the room-shell tiling textures

**Cause:** `build_shell_textures.py` (bakes tiling albedo/normal/ORM for floor/wall/ceiling) **is never
invoked**; `scene_compiler.py` (~L805 `get_shell_material`) emits `StandardMaterial3D` with a flat
`albedo_color` only — so the shell reads as colored boxes, not textured surfaces.

**Fix:**
- Invoke `build_shell_textures.py` (Blender, like `build_asset`) to generate per-theme floor/wall/ceiling
  tiling textures, and ensure they land in the build's `assets/` (an `asset_ensure`-style step for the
  shell). Deterministic + cached (don't rebake if present).
- `scene_compiler.py`: emit the floor/wall/ceiling `StandardMaterial3D` with `albedo_texture` +
  `normal_texture` + roughness/metallic/AO from the ORM (set the texture sub-resources), keeping
  `uv1_scale` for tiling — instead of a flat `albedo_color`.

**Test:**
- [ ] A compiled scene's floor/wall/ceiling material references real **textures** (not just an
  `albedo_color`); headless-load clean; deterministic.
- [ ] Commit: `fix(foundry): wire room-shell tiling textures into the scene (E1)`.

---

## [ORCH] Verification — orchestrator only

After handoff, the orchestrator regenerates a fresh-asset build and checks deterministically: chair never
overlaps its table; prop bounding box spans ≥55% per dimension; built GLBs carry `occlusionTexture`; the
shell materials reference textures; same-seed determinism holds; headless-load clean. Then hands a build
to the **user** for the visual confirm (props *and* now the room shell reading as real materials).
