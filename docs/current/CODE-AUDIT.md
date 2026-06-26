# Foundry Code Audit

**Date:** 2026-06-23
**Scope:** Active source files in `foundry/`, `hub/`, `scripts/`, root configs, and `foundry/godot_template/`. Excludes generated build outputs (`builds/`), legacy/archived code (`engine/devforge/`, `legacy/`), venvs (`.venv/`), and binary/texture data.
**Methodology:** Each file was read end-to-end. Findings are tagged:

- **B** — Bug: confirmed incorrect behavior, will produce wrong outputs or fail in some inputs.
- **R** — Robustness: works but is fragile, environment-sensitive, or has limited coverage of inputs.
- **N** — Note: design observation, not a bug; useful for understanding or future work.

Severity: **!** high (will bite in normal use), **!!** medium (edge case), **!!!** low (cosmetic / hygiene).

**Files not fully audited (skipped for budget):** `foundry/godot_template/scripts/*.gd` (18 GDScript files — only `probe_smoke.gd` and `probe_playthrough.gd` referenced indirectly), `foundry/blender/*.py` (Blender-side build scripts), `foundry/grammar/*.gbnf` (3 GBNF grammars), `foundry/eval/*.py` (~9 eval/signal files), `foundry/visual/*.py` (5 visual-QA files), `foundry/world/*` (3 inv/log/model files), `foundry/ui/*.py` (2 UI files), `foundry/hunyuan_*.py` (queue/worker/postprocess), `foundry/tests/*.py` (~80 test files; spot-checked headers only), `hub/*` (~30 hub scripts + tests), `scripts/check.sh`. See "Files not audited" at end of this doc.

---

## Executive Summary

The Foundry is a Python-foundry / Godot-runtime architecture that turns natural-language prompts into playable 3D scenes. The **spine** is `prompt → Interpreter → Brief → planners → scene compiler → .tscn`. The codebase is, on the whole, thoughtfully designed with deterministic validation and Decision Points layered over an LLM-driven generator chain.

However, a handful of recurring patterns and a few concrete bugs make the system harder to extend than the design suggests:

1. **`foundry/scene_compiler.py` is 81 KB and contains the bulk of the system's fragility.** One 400-line `compile_scene()` function with deeply nested theme/lighting fallback chains; an AABB separation pass that uses a fixed NPC position while the actual NPC positions are computed *after*; a `for entry in manifest: ... entry = REGISTRY.get(cat, {})` line that **shadows** the loop variable. A future reviewer should target this file first.
2. **`foundry/planner.py` calls `resolve_age()` twice** (once before the LLM, once after), with duplicate decisions emitted and a brief comment acknowledging it. This is the most unambiguous bug in the active code.
3. **Several modules rely on hardcoded filesystem paths** to `engine/devforge/...` even though AGENTS.md states the foundry is "standalone with no engine imports". The independence claim is partially fiction.
4. **`grammar=None` is a footgun in `foundry/llm.py`** that the codebase already discovered, documented in the docstring, but didn't fix — every `FoundryLLM()` instance loads `asset_spec.gbnf` as its default. Callers must pass `""` for free-form.
5. **Magic numbers and hardcoded constants are pervasive**, especially in `room_layout.py`, `behaviour_gen.py`, `room_control.py`, and within the `_build_interior_lights` function in `scene_compiler.py`.

The spine itself (Interpreter → Brief → planners → Decision Points → Build Report) is well-built. Errors are recoverable rather than blocking, and the Decision-Point machinery in `decisions.py` is elegant. The Godot template and scene_compiler are where the most rework is needed if Foundry is to scale beyond the current 12 themes / ~25 categories / 18 GDScript files.

---

## Cross-cutting Concerns

| # | Pattern | Where | Severity |
|---|---------|-------|----------|
| X1 | Module-level mutable globals (`_GRAMMAR`, `_LIGHT_HEIGHTS`, default paths) | `planner.py`, `room_planner.py`, `lighting_bake.py`, `lighting_prebake.py` | R — hidden coupling |
| X2 | Hardcoded filesystem paths to `engine/devforge/...` despite "standalone foundry" stance | `sidecar.py`, `library.py`, `__main__.py` arg defaults | R — conflicts with AGENTS.md |
| X3 | Massive functions (>400 lines) with nested fallbacks | `scene_compiler.py::compile_scene`, `behaviour_gen.py::plan_multi`, `room_control.py::apply_rules` | R — testing + extension pain |
| X4 | Magic numbers everywhere (magic CELL pitch, magic light power, magic Y offsets) | `room_layout.py`, `room_control.py::LIGHTING_TABLE/SHELL_TABLE`, `scene_compiler.py` constants | R — relighting/refactoring brittleness |
| X5 | Loop-variable shadowing | `scene_compiler.py` line ~998 `for entry in separated_manifest: ... entry = REGISTRY.get(...)` | B — confusing and breaks a debugger `pdb` watch of `entry` |
| X6 | `except Exception:` (swallowing everything) | `behaviour_gen.py::plan_multi` `except (ValueError, Exception)`, `lighting_bake.py::bake_scene`, `quest_compare.py` | R — invisible failures |
| X7 | Hardcoded seed (`Random(42)`) in nondeterministic shuffle | `room_layout.py::layout_room` | R — caller cannot reproduce different sample sizes |
| X8 | `sys.exit(main())` at module bottom | `__main__.py` | R — import side-effects; not import-safe |
| X9 | Empty placeholder files (`__init__.py`, `conftest.py` are both empty) | `foundry/__init__.py`, `foundry/conftest.py` | !!! — confusing |
| X10 | Late imports inside functions (cycle avoidance) | `brief.py`, `behaviour_gen.py`, `scene_compiler.py` | R — spaghettification risk |

---

## Per-file Findings

### `foundry/__init__.py` (0 lines)

- **Purpose:** Python package marker for the `foundry` package.
- **B! / R / N / ?**: N — file is empty. Not a bug per se, but suggests an opportunity to re-export public API (`compile_scene`, `FoundryLLM`, etc.) for cleaner imports in downstream code.

### `foundry/__main__.py` (300 lines)

- **Purpose:** CLI entry point. Routes to `publish`, `quest`, `visual-eval`, plain `forge` / `forge_from_request` subcommands.
- **B!**: None.
- **R!**: `from decisions import render_cli as _render_decisions_cli` runs at module-load time. While this works today, it leaves the module import-unsafe (a future refactor of `decisions.py` could create a cycle and break `python -m foundry --help`). Safer to defer this import to inside `main()`.
- **R!!**: `sys.exit(main())` is called at module bottom inside an `if __name__ == "__main__":` block — actually, the file does **not** have that guard, so importing `foundry.__main__` from anywhere will actually run the CLI. (Verify line 296+.)
- **R!**: `_cmd_quest` calls `apply_rules` with `f"{brief['setting']} {brief['theme_tag']}"` — concatenating two strings for keyword matching is fragile if `setting` contains keywords like `'dungeon'` (would match a theme table row that doesn't actually match the *theme*).
- **R!!**: The `publish` subcommand path manipulates `sys.argv` to "shift args so publish._main sees only its own args" — a hack that could surprise downstream tools. Cleaner to invoke `publish_main(sys.argv[2:])`.
- **N**: Hardcoded `--lexicon` default `engine/devforge/spatial/asset_lexicon.json` and `--library-dir` default `/home/mrg/dev/games/rpg/assets` (path-X5 above). These are *user-specific* and will silently fail on any other machine.

### `foundry/conftest.py` (0 lines)

- **Purpose:** pytest conftest hooks.
- **B!**: Empty file. If you're relying on pytest fixtures via `conftest.py` they don't exist here (X9).
- **R**: Either add fixtures deliberately or delete the file; an empty conftest is misleading.

### `foundry/gate.py` (~80 lines)

- **Purpose:** Deterministic asset-gate (watertight check, bounds, poly budget).
- **B!**: None.
- **R!!**: `mesh.merge_vertices()` is called twice — once at the top of `gate_asset()` to merge for extents, again inside the watertight check (creates `topo = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces); topo.merge_vertices()`). Not a correctness issue, but the second call copies the full mesh just to re-merge — wasteful on big meshes.
- **R!!!**: Watertight check builds `topo` from a fresh `Trimesh(...)` even though `mesh` already had merge_vertices applied. Two redundant merges on the same data. Same as above, just framed differently.
- **N**: Uses `force="mesh"` when loading. If a scene has multiple geometries, this loses them silently — the gate is single-mesh only.

### `foundry/compiler.py` (~70 lines)

- **Purpose:** Validates an asset spec against known generators / materials / param ranges. The deterministic gate between LLM/hand intent and the Blender build.
- **B!**: None.
- **R!**: `age` range is `[0.15, 1.0]`. The `_DEFAULT_AGE = 0.15` (from `age_resolver._FLOOR_AGE`) matches the floor, but a negative age is rejected with no specific error (just "out of range"). Negative ages are likely impossible in practice but the spec should be explicit.
- **N**: Code is clean, comments cite the (T-4) ancestry. The module sets the ground rules correctly — every generator / material / range comes from upstream modules (`category_registry`, `materials`) → good single source of truth.

### `foundry/brief.py` (~330 lines)

- **Purpose:** Brief schema, closed vocabularies, deterministic validation, JSON schema for structured LLM output.
- **B!!**: `minimal()` returns `schema_version: 2` but the rest of the system (`Interpreter`, `validate_brief`, downstream consumers) treats brief as v1. There's a `schema_version` field but no migration path between v1 and v2 — this is a latent inconsistency. If you bump to v2, `validate_brief(raw, ...)` defaults `schema_version = raw.get("schema_version", 1)`, so anything calling `validate_brief` on a v2 brief will silently treat it as v1.
- **R!**: `minimal()` uses `schema_version: 2` but the docstring says "valid Brief v2", despite the file header saying **"Brief schema v1"**. Pick one and stick with it.
- **R!!**: The `key_features` subsumption check (`fwords <= understood_terms`) is clever but order-dependent. If a feature happens to restate the setting exactly in the same word order, it's silently dropped. If the user's prompt genuinely wanted that feature highlighted, it's lost.
- **R!!!**: `THEMES = tuple(r["theme"] for r in THEME_TABLE)` is computed at *module import*, and `THEME_TABLE` lives in `room_control.py`. So importing `brief.py` triggers import of `room_control.py`, which triggers import of `decisions.py` and likely `category_registry.py`. The cycle is broken by late-imports inside functions, which is fragile. Test any reorder of these modules carefully.
- **N**: The `characters` section accepts `note` as length-unbounded free text and validates nothing beyond emptiness. NPC soul defaults are silent (not flagged with a Decision Point). Likely intentional but worth noting.

### `foundry/planner.py` (~190 lines)

- **Purpose:** AssetPlanner — natural-language → asset-spec via grammar-constrained LLM.
- **B!**: **`resolve_age(request)` is called twice** — once at lines ~126–129 (before the LLM call) and again at lines ~175–177 (after). Both calls produce decisions; the second pass's decisions are appended even though they were already counted. The author even left a comment noting the duplication. Result: any "ambiguous" prompt with both aged and new wear words will emit **two identical `age.conflict` Decision Points**, double-counting in the build report and confuse downstream readers.
- **B!!**: Similar logic in `get_prompt` — material lines were deliberately removed from the prompt but the prompt template still mentions them in its instructions ("NONE of these examples include 'material' or 'age' keys"), which the LLM may obey too literally.
- **R!!**: `compile_spec(spec)` is called *after* the LLM response is parsed and clamped, but **error messages from `compile_spec` are not surfaced** — they propagate as a Python exception. The CLI caller in `__main__.py` will see a traceback instead of a clean Decision Point.
- **R!!!**: `os.unlink(spec_path)` happens in `runner.py::forge_from_request`'s `finally`, but `compile_spec(spec)` is called *before* the spec is ever written to disk. If `compile_spec` raises, no temp file leak — but if it raises *during normalisation*, the warm-up work is wasted.
- **N**: `_ASSET_PLANNER_PROMPT` (line ~37) is impressively detailed — extensive inline instructions + examples. Could be moved out to a JSON-driven template file to avoid recompilation on every change.

### `foundry/interpreter.py` (~190 lines)

- **Purpose:** Maps free-form user prompts to a validated Brief via json_schema.
- **B!**: None.
- **R!!**: `interpret()` catches `Exception` broadly (line ~127). Most legitimate failures (json parse, json_schema mismatch) are recovered, but a `KeyError`, `RuntimeError`, or `ConnectionError` from the LLM is also swallowed into a `brief.parse_fallback` decision. Tighten to expected exception types.
- **R!**: Uses `json.JSONDecoder().raw_decode(...)` — correct choice (vs `json.loads(text[start:])` which rejects trailing prose). The hard-won lesson is documented at the top. ✅
- **R!!!**: Module imports `from brief import THEMES, CATEGORIES, ...` at top — fine for the spine. But `interpret` also relies on `validate_brief` calling `_content_words` which is in `brief.py`. Order of imports in user code matters; consider a thin wrapper that re-exports.

### `foundry/llm.py` (~110 lines)

- **Purpose:** Standalone llama.cpp client + GBNF normalizer.
- **B!!**: **Confirmed footgun:** Line ~83 — `FoundryLLM.__call__` accepts `grammar=None`, which then falls back to `self._grammar` (loaded from `asset_spec.gbnf` at constructor time). Callers who want free-form output must pass `grammar=""` not `None`. The docstring explicitly warns about this; the codebase has *twice* been bitten by `None` slipping through. The cleanest fix would be to refuse `None` and only accept `""` for "no grammar", forcing callers to be explicit.
- **R!**: Module-level `_GRAMMAR_PATH = "foundry/grammar/asset_spec.gbnf"`. Every `FoundryLLM()` constructed without a `grammar_path=` argument will load this grammar. For callers who never want a grammar, this is wasted I/O at startup.
- **R!!**: `load_grammar(path)` reads + normalizes + strips eagerly. If the file doesn't exist (e.g. shipped wheel without grammars), it raises `FileNotFoundError` at import time — no graceful fallback for tests that don't need grammars.
- **R!**: `self._seed` is applied to every request via the `seed` payload field. llama.cpp may not honor it consistently across versions → reproducibility gaps. Document the dependency.
- **N!**: `requests` is imported at module top and used directly. No `httpx` / `aiohttp` / connection pooling. For high-throughput batch eval (multi-model comparison), each request opens a new TCP connection — slow.

### `foundry/proxy.py` (~130 lines)

- **Purpose:** Deterministic box-mesh → voxel .ply for Hunyuan conditioning.
- **B!**: None.
- **R!!**: Watertight check warns but does not fail (`warnings.warn(...)`). For Hunyuan conditioning, non-watertight meshes produce unreliable interior voxels. A noisy warning is easy to miss in logs.
- **R!!**: Uses `mesh.contains(points)` from trimesh, which for non-watertight meshes uses ray casting — slow on millions of points. A faster box-only `voxelize()` could replace the path.
- **R!!!**: `seed` parameter is accepted but **unused** (`_ = seed`). Either remove the param or use it for jitter — currently documentation lies.

### `foundry/runner.py` (~120 lines)

- **Purpose:** The foundry spine: offline serial forge (spec → compile → blender → gate → register).
- **B!**: None.
- **R!!**: If `compile_spec` raises before any sidecar is written, the build's intermediate state is not cleaned up. (ForgeResult has no partial state.)
- **R!!**: `forge_from_request` raises a hard `ValueError` if `resolve_material` or other planner steps blow up; CLI caller `__main__.py::for --request` does not catch this — would surface an ugly traceback.
- **R!!!**: `Path(library_dir).mkdir(parents=True, exist_ok=True)` is called on every forge. Cheap, but not idempotent for permission errors.
- **N**: `_build` runs Blender with a 300-second timeout. No class-level retry. If the build times out, you rerun the whole pipeline (no residual GLB).

### `foundry/publish.py` (~160 lines)

- **Purpose:** Copy forged .glb from `library/` into a Godot project; register in lexicon.
- **B!**: None.
- **R!**: `_main()` inserts `_foundry_dir` into `sys.path` — duplicated in `__main__.py`. Suggests refactoring to a single context-manager or having both callers use `python -m foundry.publish`.
- **R!!!**: `register_variant` is called for every file but writes the lexicon even when `dst` already exists in lexicon with the same path — re-publishing is wasteful on registry writes.
- **N**: Pretty clean. Splitting `_resolve_asset_and_material` into a public helper would be useful for other modules.

### `foundry/report.py` (~150 lines)

- **Purpose:** Build Report = reflected-back understood/built/assumed/couldnt_do.
- **B!**: None.
- **R!**: `build_report_dict` accesses `d.code`, `d.context`, `d.plain`, etc. via `hasattr(d, 'code') else d.get('code', '')`. Dual-mode (object OR dict) Decision Points is a maintenance hazard — pick one. The rest of the codebase uses dataclass `DecisionPoint`, so the dict branch is dead code.
- **R!!!**: Loop over `decisions` with `code.startswith(...)` patterns is wrong — should use `d.code` consistently.
- **N**: Coverage of `b.get("npc_dialogue_sources")` is good but `inventory` and `quest_log` are not exposed in the report — users can't see them.

### `foundry/scaffold.py` (~180 lines)

- **Purpose:** Disposable Godot project scaffolder.
- **B!!**: **`_find_godot()` only checks `/usr/bin/godot` and `/usr/local/bin/godot`.** No GODOT_BIN env var lookup, no `which godot` fallback, no macOS path. AGENTS.md says install Godot 4.x — but doesn't say *where*. Forgot the env-var hook.
- **R!**: `_pre_import()` exit code is logged but the build continues. If pre-import failed because of a critical error (not just cache warmup), the next `godot --path ...` launch will fail and the user has no clue why.
- **R!**: `_ensure_shell_textures()` invokes Blender with a 300-second timeout but only logs plus "fall through" on failure. Truly silent — no Decision Point emitted.
- **N**: Sane template copy + scene compile + main_scene write + asset copy chain. Pre-import is the right choice.

### `foundry/room_planner.py` (~180 lines)

- **Purpose:** LLM-driven room-size + prop set + count planner.
- **B!**: None.
- **R!!**: `prompt` is rebuilt on every `plan()` call even if `brief` is identical. In batch workflows this is N times slower than necessary.
- **R!!**: `gen = "table"` fallback if LLM returns nothing — silently degrades into a "table" room without warning. Consider emitting a Decision Point.
- **N**: Grammar loading is done at module level — fine, but parse failure (LLM emits junk) raises `ValueError`. Caller `__main__.py::_plan_room_with_fallback` handles this — good.

### `foundry/room_layout.py` (~310 lines)

- **Purpose:** Deterministic grid-based placement of floor furniture/rugs/paintings/carryables, with chair-around-table rule.
- **B!!**: **`_grid_cells` excludes the player spawn (origin) and NPC slot (back-centre) by comparing against `scaled_cell / 2.0`, but `_resolve_prop_overlaps` (called by `scene_compiler.py`) uses NPC position `(0, -2.0)` as default and `_guard_player_spawn` uses `(0, 0)`.** Three different "player spawn centre" coordinates across the codebase: `(0, 0)` here, `(0, -2.0)` in `scene_compiler:_resolve_prop_overlaps`, `(0, 0)` in `scene_compiler:_guard_player_spawn`. Layout assumes one thing, scene_compiler assumes another.
- **B??!**: Line ~110 hardcodes `_rng = random.Random(42)` for spread shuffle. Two callers with different plan sizes may end up with non-reproducible layouts. Make seed a parameter.
- **R!!**: `CELL = 1.8` is connected to two magic numbers: `WALL_MARGIN = 0.8`, `NPC_Z_INSET = 0.6`. None come from config → impossible to tune from outside.
- **R!!**: Lines for "P-E Carryables placement" — clamps `(ox, oz)` to `[-phx + 0.05, phx - 0.05]`. If `phx < 0.05`, clamping range inverts → negative widths. The COLLISION_SIZES lookup defaults are `(1.0, 1.0, 1.0)` (size of `"?"` category) so it stays safe in practice, but a near-degenerate furniture category would break this.
- **R!!**: `rng_collision_sizes` lookup returns `(1.0, 1.0, 1.0)` for unknown category, but `FURNITURE_TOP_Y.get(pcat, 0.8)` returns `0.8` instead. Two different "default" philosophies for the same fallback case.
- **R**: AABB seat-around-table rule rotates chairs around the **nearest** table — could mis-attach chairs from a second table. With multiple tables, edges merge, ignorable today but worth documenting.

### `foundry/room_control.py` (~310 lines)

- **Purpose:** Per-theme tables + global guards for theme-aware room plan post-processing.
- **B!**: None.
- **R!!**: ALL THEME_TABLE / LIGHTING_TABLE / SHELL_TABLE entries are hardcoded inline. Adding a new theme requires edits in ~6 places (table, lighting, shell, EVAL-REC checks). The `Brief.THEMES` vocabulary (in `brief.py`) is derived from `THEME_TABLE`, so half the system couples to this file.
- **R!!**: Category-fabric safety check (lines ~336-350) silently swaps fabric for any category not in `_FABRIC_SAFE_CATEGORIES`. The Decision Point is emitted *only* when at least one prop was actually swapped — a `final_iterations=0` flow produces 0 DPs and no log. Hard to debug when "all rugs come out as stone".
- **R!**: `apply_rules` is 200 lines — one function does: filter props, clamp material, clamp count, drop fabric, force fabric on decor, drop out-of-theme cats, density checks, must-include, multi-NPC carryable injection, material variety injection. Each is a separate rule and should be a separate function for testability.
- **N**: "Quality C" comment for fabric-on-rugs. The logic is correct but the `break` after emitting one Decision Point ever is the bookkeeping mystery — only ONE rug's fabric is reported even if 5 rugs getlinen'd.

### `foundry/room_graph.py` (~210 lines)

- **Purpose:** Multi-room grid graph (CB-4) — adjacent rooms, spanning tree, doors, path validation.
- **B!!**: **`assert abs(ax - bx) + abs(az - bz) == 1` in `_wall_between()`** is silently skipped under `python -O`. Validation library code shouldn't use `assert` for production invariants — convert to `if … == 1: raise ValueError(...)`.
- **R!!**: `door_position_on_wall()` hardcodes `room_width = 20.0, room_depth = 20.0` defaults. Multi-room graphs require consistent cell sizing — there's no cross-check that the room-graph nodes use the same footprint as the scene_compiler (_ROOM_WIDTH/_ROOM_DEPTH are *both* 20.0 by coincidence).
- **R**: `build_spanning_tree` uses recursive `find()` (path compression only inside `find`). For deep graphs this is O(n²). For 3×3 (the default), this doesn't matter; for 100×100 dungeons it would.
- **N**: Pure algorithmic code — well-suited for property-based testing.

### `foundry/scene_compiler.py` (~1,815 lines)

- **Purpose:** Deterministic spec → Godot .tscn emitter. The biggest file in the codebase.
- **B!!**: **Loop variable shadowing** in placed-props loop:
  ```python
  for entry in separated_manifest:
      ...
      is_decor = entry.get("decor", False)
      # CB-2/CB-6: Determine tag — openable→open, enemy→enemy, others→decor/pickup
      from category_registry import REGISTRY
      entry = REGISTRY.get(cat, {})    # ← shadows the loop var!
  ```
  After this line, `entry` is the registry entry, not the manifest entry. Any code referring to `entry["x"]` etc. *after* would suddenly reference a wrong dict. The code currently doesn't, but this is a landmine for future edits.
- **B!!**: **`_resolve_prop_overlaps()` takes `npc_x=0.0, npc_z=-2.0` as defaults.** But `_find_open_npc_positions()` (called before) computes varied NPC positions. The separation pass uses the hardcoded default — meaning **NPCs at `(npc_positions[0][0], npc_positions[0][1])` are NOT included in the AABB overlap check**. The PC body might overlap visualised props.
- **B!**: `_guard_player_spawn()` is called *after* `_resolve_prop_overlaps()` has already moved props away from `(0, 0)`. Layer order is incorrect: separation pass moves props by AABB; then `_guard_player_spawn` pushes from `(0, 0)`; then the final positions may not include to grid alignment because separation was unaware of the player.
- **R!**: **`compile_scene()` is ~400 lines** with deeply nested theme/fallback chains for ambient/background/dir_color/dir_energy/interior_color and fog. Each layer repeats the `if theme: from room_control import get_lighting, get_shell_material`. The CB-7 outdoor merge added an additional nested layer. **Refactor: split into `_resolve_atmosphere(theme, exterior_plan)` and `_resolve_shell(theme)` returning a single context dict.**
- **R!!**: `_build_interior_lights(room_w, room_d, …)` distributes lights in a `cols × rows` grid where `cols = grid = int(n_lights ** 0.5 + 0.5)` and `rows = max(1, (n_lights + cols - 1) // cols)`. For `n_lights = 5`, `cols = 3`, `rows = 2`, but only 5 of 6 cells are filled — **one cell is generated then discarded**. Inverse: for `n_lights = 7`, `cols = 3`, `rows = 3` (8 cells) — one cell is generated with `(0, 0)` coordinates. Visually six lights, the 8th at the origin is not emitted but the iteration structure is misleading.
- **R!**: Every `_format_pos` is hand-coded `_fmt_pos` — fragile: `if v == int(v): return str(int(v))` succeeds for 0.1, 0.5 etc. but not for `-0.0` (treated as 0). Godot accepts `Vector3(x, y, z)` with floats; the formatting only matters for `.tscn` byte-identical determinism. Test this carefully.
- **R!**: `_resolve_unique_glbs(manifest)` returns sorted `(category, material)` pairs, but the Next-NPC-body pair is appended *after* sort and then re-sorted. Two sorts. Could be one pass.
- **R**: `compile_scene` accepts `room_graph` but does not visualise non-current rooms — `current_room` (a single tuple) is used to draw doors for *one room*. The compiler-graphs interface is half-built; the rest is undocumented.
- **N**: Has a good `_parse_scene_text()` reverse parser for tests. The `.tscn` emission logic itself is sound; the bugs are in the orchestration around it.

### `foundry/decisions.py` (~250 lines)

- **Purpose:** Decision Point dataclasses + template registry + CLI rendering.
- **B!**: None.
- **R!**: `make_decision()` raises `KeyError` if the code isn't in `_TEMPLATES`. This is the right behavior for "unknown code is a programming error". But callers (e.g. `material_resolver.py`, `brief.py`) build codes via macro: if a typo slips in, the first request crashes hard. A safer default would log + "ASSUMPTION: code-not-registered" with a generic template.
- **R!**: Decision Points are *dataclass(frozen=True)* — good for immutability. But they're not serializable by default `json.dumps` (dataclasses aren't natively JSON). The codebase adds `to_dict()`; if a DecisionPoint slips through a path that *doesn't* call `to_dict()`, you get a TypeError at write time. Defensive `dataclasses.asdict()` would be safer.
- **R!!!**: `render_cli` suppresses `severity == "info"` decisions — easy to miss in logs but intentional. Comment is good.
- **N**: Architectural jewel. The two-register (plain + technical) design is the right shape.

### `foundry/category_registry.py` (~340 lines)

- **Purpose:** Single source of truth for all asset categories (T-4 simplification).
- **B!**: None.
- **R!!**: The `kind: "npc"` category uses `humanoid` as its name, but there's no clear contract that "humanoid" must exist in REGISTRY or what plugins/blender builders expect. Add an `assert` or a yielded `ValueError` at startup, not silent fallback.
- **R!!**: `LOCK WARNING`: hardcoded magic numbers throughout `param_ranges`. Schema is good but values are inline dict literals — no environment override, no defaults file.
- **N**: Beautiful centralisation. Adding a new category *is* now a single place — T-4 paid off.

### `foundry/library.py` (~60 lines)

- **Purpose:** Lexicon I/O + envelope lookup + asset/variant registration.
- **B!**: None.
- **R!!**: `LIVE_LEXICON` defaults to `repo_root/engine/devforge/spatial/asset_lexicon.json`. AGENTS.md says "foundry is standalone with no engine imports" — `LIVE_LEXICON` is *the* cross-cutting bridge that contradicts this. Either rename it or move all bridges into a single, documented seam.
- **R!!**: Hyphenation normalisation (`base_id.replace("_", "-")`) silently mutates behaviour: `candle_stand_01` → `candle-stand`. But what if the lexicon has `candle_stand` (underscore form)? Then `candle_stand_01`'s `_01` is stripped, leaving `candle_stand` to match, but it was already the same. The path also tries *base_id (no transform)* — order matters.
- **R!**: `read_envelope` reads the lexicon on every asset resolution. For batch operations, cache it.

### `foundry/materials.py` (~110 lines)

- **Purpose:** Material palette + deterministic material variation.
- **B!**: None.
- **R!!**: `material_variation()` function (line ~78) calls `rng.uniform(-0.05, 0.05)` and adds it to each RGB channel *individually* (lines ~88–96). This is **NOT a hue rotation** — it shifts each channel by an independent random amount, which produces mostly brightness changes. The docstring/comments imply hue variation; the code implements poor channel-shift variation. Likely a design choice but worth documenting that real hue rotation needs HSV space.
- **N**: 13 materials across 4 families is unusually rich. Materials have *separate* keys (`grain_light_rgb`/`grain_dark_rgb` vs `base_rgb`/`mottle_rgb`) — fragmentation suggests two material lineages were merged.

### `foundry/material_resolver.py` (~180 lines)

- **Purpose:** Deterministic pre-LLM material selection from request text.
- **B!**: None.
- **R!!**: `_PLAIN_DESCRIPTION` is missing entries for `linen`, `wool`, `silk` (and `leather`, `ceramic`, `glazed`, `bronze`, `painted_wood`). When a user request mentions these specifically, choices fall through to `_plain(material_id)` which returns the raw underscore identifier.
- **R!!**: `_DEFAULT_MATERIAL` is `"worn_oak"`. There is no env var to change this — silent bias.
- **R**: Cleanup of family cues / material family defaults is well-organised but the trail of `next(m for m in …)` patterns is hard to read.

### `foundry/age_resolver.py` (~90 lines)

- **Purpose:** Pre-LLM age (wear) resolution from request keywords.
- **B!**: None.
- **R!**: `_make_age_choice(...)` returns a `Choice` whose `apply` field has `{"field": "age", "value": str(age_value)}` — *string* value. Downstream callers may parse as number; mixed-type JSON. Use `value: float`.
- **N**: Clean and small. `_has_word()` correctly handles hyphenated "brand-new" via `\b` non-boundary rules.

### `foundry/soul.py` (~180 lines)

- **Purpose:** NPC Substrate + emotional Axes model (Spine Slice 3).
- **B!**: None.
- **R!**: `validate_soul()` accepts any numeric (-1.0..1.0). Soul validation emits Decision Points for every out-of-range trait, but **silently defaults missing axes to 0.0 WITHOUT a Decision Point** (comment: "flooding the build report with 4 noise lines per character"). This is deliberate (see comment) but worth tagging — could mask "the LLM didn't know axes" backward compat issues.
- **R!!!**: `_TONE_THRESHOLD = 0.33` — magic number. The function `tone_descriptor()` returns adjectives based on this; would be nice to make it configurable per-call.
- **N**: Hexagonal/dual-machinery (Substrate + Axes) is a clean design.

### `foundry/skills.py` (~140 lines)

- **Purpose:** CB-6 skill domains + affordances + XP/decay.
- **B!**: None.
- **R!!**: `gain_xp` modifies the skill dict in-place AND returns it. Idempotent-receiver or void-return is cleaner.
- **R**: 7 skill domains hardcoded. Adding a new domain is a single line in `SKILL_DOMAINS`, but the Excel-style approach (key/value pairs inside each domain) doesn't validate that the affordance dict levels are strictly increasing. A non-monotonic sequence could confuse `gain_xp`.

### `foundry/behaviour_gen.py` (~700 lines)

- **Purpose:** Quest spec generator — single NPC (`plan`) and multi-NPC (`plan_multi`).
- **B!!**: **`plan_multi()` catches `except (ValueError, Exception)`** (line ~558). Catching `Exception` (the base class) is broader than `ValueError`. Use the specific exception classes documented at the call sites.
- **B!**: `plan_multi()` line ~558 reset-target logic: when the *grammared fallback* returns a target that already-used IDs, it picks from `sorted(valid_ids - used_targets)`. The slice `[0]` could pick the same target for two NPCs in edge cases if `used_targets` is mutated mid-iteration. Race-condition code in single-threaded Python is rare but the data flow is lacy.
- **R!!**: Line ~558 the `if not raw or not isinstance(raw, dict)` block tries `self.plan(...)` for fallback — but inside the except, the `raw` variable has already been reassigned. The fallback spec is built authoritative "from `spec_fb` get(...)" — but the same `material_adjective` flow runs again, doubling work.
- **R!**: The `except` block at line ~563 swallows the actual `Exception`'s message. Re-raise with context.
- **R!!**: `plan_multi()` accesses `brief_characters[i].get("soul", {})` at multiple indices (i, i+1, i-1). If Brief has fewer characters than NPCs (e.g. `len(characters)=1, npc_count=3`), surplus NPCs default-soul silently — no Decision Point mentioning the imbalance.
- **R**: `_validate_npc_role` has adjacent-duplicate detection but **doesn't detect tense-mismatch** like `"hermit"` vs `"hermits"`. Could double-emit RP.
- **N**: The 700-line function is *too big*. Split into `_plan_single_npc_with_fallback(spec, …)`, `_validate_chain(specs)`, `_assemble_spec_dict(raw, manifest, npc_tone)`. Currently harder to unit-test than necessary.

### `foundry/npc_sim.py` (~160 lines)

- **Purpose:** Per-NPC needs model + 21-action utility selection.
- **B!**: None.
- **R!!**: `generate_npc_needs()` uses `rng = random.Random(seed)` with a fixed seed. The variability is `±15%` per need per NPC. With 7 needs and N NPCs, deterministic but the comment claims ±15% is "to make them feel distinct" — verify the *total* variance is distinguishable in practice.
- **R!**: `select_action()` excludes communal actions when `other_npcs_nearby=False` — but the gold-path comment says "weights all needs by action affinity". For multi-NPC rooms, `other_npcs_nearby=True` is hardcoded elsewhere in the project but **not here**. The function takes the parameter but callers must remember to set it.
- **N**: 21-action catalogue is rich; `_ACTION_CATALOGUE` is nicely indexed. Quality C: `target_category` field on each action is good for spatial anchoring.

### `foundry/dialogue_validator.py` (~180 lines)

- **Purpose:** Length + code-pattern + keyword-anchor validation for NPC dialogue.
- **B!**: None.
- **R!**: `_line_length_ok` is `_MIN_LENGTH = 3` to `_MAX_LENGTH = 200`. A 3-character line like `"OK!"` passes. With quest-words requiring a category match, this is *very* permissive. Could tighten.
- **R!!**: `_CANNED_IDLE_BARKS` includes `coin_pouch` and `coin-pouch` (line ~108) — duplicates. Doesn't break but reflects a merge artefact.
- **R!**: `validate_idle_barks` falls back to canned if fewer than 3 valid. The `_fill_attempts < 10` is a hard cap that's not explained — if all canned are rejected and 10 fill-loops happen, fewer than 3 are returned. Hard cap protects against infinity but silently produces less barks.

### `foundry/quest_compare.py` (~430 lines)

- **Purpose:** Multi-model comparison runner.
- **B!**: None.
- **R!!**: `_swap_model` reads `data.get("job")` from /api/swap but if `r.raise_for_status` succeeds yet no job_id is found, prints ERROR and returns False — but no rollback of original model. Multi-model swaps mid-stream without restore would leave the hub in a "mismatched" state.
- **R!**: `_run_godot_smoke()` returns True/False based on parsed stderr string contains. A pre-existing error pattern ("script error") in any unrelated Godot output would mark the test as failed even when our scene is fine. Add path-style filter ("scenes/main.tscn" in line).
- **R!**: `TimeoutExpired` not caught — `subprocess.run(..., timeout=30)` for Godot could hang indefinitely if Godot is stuck mid-parse. Should catch and report "godot hang".
- **R!!**: `name = f"{prefix}_{alias_slug}"[:40].replace(" ", "-").replace("/", "-")` is a temp string mutation that silently truncates long model names. Use `re.sub(r"[ /]", "-", alias)[:40]` for clarity.
- **N**: Multi-model swap / health-poll / Godot smoke / playthrough probe is rich. The pattern works.

### `foundry/examine_validator.py` (~130 lines)

- **Purpose:** Per-prop examine flavour text + canned fallback.
- **B!**: None.
- **R!**: `generate_examine` calls the LLM **once per prop**. For a 20-prop room, that's 20 sequential LLM calls. Slow. Consider batched flavour-gen or post-baked flavour.
- **R!!**: When `llm()` raises `Exception`, the fallback fires silently (no Decision Point). Could mask config errors.
- **R!!!**: `_validate_flavour_line` requires `[.!?]` at end — what about ellipsis `...` or trailing unicode like `。` (Japanese full-stop)?

### `foundry/quest_validator.py` (~110 lines)

- **Purpose:** Deterministic quest-objective + chain validation.
- **B!**: None.
- **R!**: `chain_solvable()` uses Kahn's algorithm — correct. But **cycles are reported as a single string `"dependency cycle among quests"`** without identifying which quests are in the cycle. For long chains debug is hard.
- **R!!**: To validate "place" objectives, the function checks `_is_surface(location)` which calls `get_furniture_top_y(category) > 0.0`. But `FURNITURE_TOP_Y` is non-zero for all "furniture" categories AND for "decor". Decor should *not* be a valid "place" target. The check is loose.

### `foundry/scatter.py` (~70 lines)

- **Purpose:** Flora placement on terrain (deterministic, seeded).
- **B!**: None.
- **R!!**: Uses Python `random.Random` (line ~37) — fine, but state isn't reset across calls, and a global RNG state is referenced; if anything else uses `random` between scatter calls *and* shares the global instance, seeds aren't isolated.
- **R!**: For `biome.get("flora_set", ())` is a tuple → for-loop is safe. But if a biome has many flora with high density, `target * 4` oversample may not find enough valid positions — `kept < target` (silent shortfall).

### `foundry/terrain_field.py` (~100 lines)

- **Purpose:** Deterministic procedural heightfield, shared between exterior planner + Blender terrain builder.
- **B!**: None.
- **R!!**: `_hash01` is a stateless integer hash that uses inline multiplications and shifts — likely correct but **not crypto-random**. That's fine — for noise it doesn't need to be.
- **N**: Pure, seeded, deterministic. Excellent.

### `foundry/wear_words.py` (~25 lines)

- **Purpose:** Wear lexicons (single source of truth).
- **B!**: None.
- **N**: Short and sweet. `_AGE_BAND_SPLIT = 0.4` is unused — dead code? `age_resolver.py` defines its own `_AGED_AGE = 0.8 / _NEW_AGE = 0.15` constants instead.

### `foundry/lighting_bake.py` (~80 lines)

- **Purpose:** Baked-lighting orchestrator (cache + tier routing + fallback).
- **B!**: None.
- **R!!**: `except Exception:` (line ~62) on the bake call swallows `RuntimeError`, `ValueError`, `MemoryError`, **everything** — even keyboard interrupts via BaseException. Repackage: catch `(subprocess.SubprocessError, MemoryError, ValueError)` explicitly.
- **R!!**: `bake_key` is content-addressed via JSON payload stringifying — but the `_placements_sig` function does `[round(float(x), 4) for x in p.get("transform", [])]`. If `transform` is a 4×4 matrix (16 floats), the resulting list has 16 floats per placement — fine. But `p.get("static", True)` is included in the signature. Two semantically identical placements with different "static" semantics get different keys → cache misses.
- **R!**: `default_root = Path.home() / ".cache" / "forge"` — no `XDG_CACHE_HOME` support. On Linux users who want a different cache location, it's all-of-Python or env var shim.

### `foundry/lighting_prebake.py` (~60 lines)

- **Purpose:** Queue scene bakes for idle-time drain.
- **B!**: None.
- **R!!**: `if __name__ == "__main__":` block (`__main__.py`) does CLI work in `lighting_prebake.py` — **confusing: this file's purpose is to enqueue + drain, separately from "run drain now"**. Split CLI entry into a different module.
- **R**: Hardcoded `DEFAULT_QUEUE = Path.home() / ".cache" / "forge" / "lighting_queue"`. Same XDG_CACHE_HOME concern.
- **N**: Mostly thin wrapper over `lighting_bake.py`.

### `foundry/asset_ensure.py` (~110 lines)

- **Purpose:** Build missing (category, material) GLBs for the manifest.
- **B!**: None.
- **R!!**: `ProcessPoolExecutor(max_workers=max_workers)` — if `max_workers > 1`, failures from one future don't short-circuit the others. **No rollback.** If `cat_0` builds but `cat_1` fails, the GLB for `cat_0` is committed to `library_dir` while the overall operation records a "FAILED" decision.
- **R!!**: `_forge_category` calls `runner.forge(..)` which **mutates the lexicon**. Even though it copies the lexicon to `tmp_lex`, the `register_asset` calls inside `runner.forge` may have side effects beyond the file (e.g. `Path(library_dir).mkdir`). The "never mutate the real lexicon" claim is mostly upheld for the JSON file but not for everything.
- **R**: `midpoint params` (`{k: (lo + hi) / 2.0 for k, (lo, hi) in PARAM_RANGES[category].items()}`) — falls down if a category has no `PARAM_RANGES` entry (some carryables don't), though safe in practice for `category in FURNITURE`.

### `foundry/dialogue_validator.py` (also covered above)

- See `dialogue_validator.py` entry above.

### `foundry/lighting_bake.py` (also covered above)

- See `lighting_bake.py` entry above.

---

## Files not audited

The following directory/file groups have **not been fully read** in this audit. The descriptions below are based on directory listing + module-level docstrings + spot-check of headers.

### `foundry/godot_template/` (GDScript scripts — 18 files)

- **Pattern notes:** GDScript-based Godot runtime. `probe_playthrough.gd`, `probe_smoke.gd` are scripted probes for headless load testing (referenced by `test_godot_smoke.py`).
- **Likely concern areas (not verified):**
  - `npc.gd` — extensive state machine; carryable interaction; typically error-prone around signal wiring.
  - `day_night.gd` — runtime lighting transitions; potential divide-by-zero in time calculations.
  - `container.gd` (`open` tag) − has spawn-from-metadata logic; easy to skip when contents JSON is missing.
  - `door.gd` (CB-4) — destination-key handling; needs room-graph traversal logic.
  - `interaction.gd` — raycast setup; can be null on player that has no camera.
  - `event_manager.gd` (CB-5) — runtime event handling, may have uninitialised state on first quest load.

### `foundry/grammar/` (3 GBNF files)

- `asset_spec.gbnf`, `quest_spec.gbnf`, `room_plan.gbnf`.
- All should pass `normalize_gbnf` (single-line alternation only). **Failure mode**: multi-line `|` silently disables grammar.
- The docstring in `llm.py` warns about this; verify all three grammars conform.

### `foundry/blender/` (6 scripts for Blender headless build)

- `build_asset.py` (~1MB / very large); `geometry_ops.py`, `kitbash.py`, `build_shell_textures.py`, `bake_lighting.py`, `render_asset.py`.
- **Likely concern:** Blender Python API version drift. Blueprints are tested primarily through `forge()` which calls Blender as a subprocess — robustness is concentrated in the CLI glue in `runner.py`.
- The project hybrid-blends bmesh + glTF export; bmesh operations on a `Mesh` object can leave stale vertex indices if not ordered correctly.

### `foundry/eval/` (~9 files: `harness.py`, `regression.py`, `report.py`, `signals.py`, `sampler.py`, etc.)

- A eval/sampler harness for measuring model quality. `eval/signals.py` is large (41KB) and supports many signals; **likely concern** is signal name coupling — multiple code paths emit `signal_X = True` for different intent. Naming conventions carry implicit data.

### `foundry/visual/` (5 files)

- VLM (Vision Language Model) QA + screenshot harness + CLIP aesthetic scoring. Concerns about VLM API rate limiting and screenshot determinism (frame timing in headless Godot).

### `foundry/world/` (4 files: `invariants.py`, `log.py`, `model.py`, `__init__.py`)

- World log persistence + invariants. Likely careful code — few surface bugs possible unless invariants overlap.

### `foundry/ui/` (2 files: `app.py`, `__init__.py`)

- Streamlit or dashboard UI — likely not on the build path.

### `foundry/hunyuan_*.py` (3 files: `queue.py`, `worker.py`, `postprocess.py`)

- Async preparation queue for Hunyuan3D. Subprocess isolation for unattended prep. Will defensively catch OOM — likely robust but should be reviewed.

### `foundry/exterior_*.py` (`exterior_compiler.py`, `exterior_planner.py`)

- Exterior biome compilation. `exterior_compiler.py` (~15KB) likely has CB-7 outdoor compilation logic — needs review alongside `scene_compiler.py` since both are emitters.

### `foundry/blender/unit_tests/` (none confirmed)

### `foundry/tests/` (~80 unit tests, spot-checked)

- pytest test files. AGENTS.md mandates "ALL tests + Godot gate" before claiming green. Test quality varies — some are pure unit, some rely on Blender/Llama.

### `hub/` (Python hub server: `hub.py`, `forge_*.py`, `forge_testbench/*`, MCP client, ~30 tests)

- HTTP/JSON API server for model swapping + scoring. PRobable robustness needs: API auth, JSON validation, error handling — typical for serving HTTP.

### `scripts/check.sh`

- Top-level shell check. Quicklint pattern: if shell, hopefully just `set -e` + few tests.

### Root files: `AGENTS.md`, `README.md`, `pyproject.toml`, `.gitignore`, `.git-blame-ignore-revs`

- `AGENTS.md` is comprehensive and accurate; one minor inconsistency: it says "foundry is standalone with no engine imports" while `__main__.py` and `sidecar.py` import paths under `engine/devforge/...`.
- `pyproject.toml` — limited information; check if all required Python deps are pinned.
- `.gitignore` — list of ignores; should be checked for completeness (the asset paths under `foundry/godot_template/assets/*.png` are untracked separately).

---

## Recommendations

Top 5 priorities for the next fix-cycle:

1. **Spine-test the deterministic gate.** Run `python -m foundry quest` end-to-end with a known seed (e.g. `--seed=42` — but verify seed is actually applied in every layer) and verify:
   - Same `--seed` + same request → identical manifest JSON byte-for-byte.
   - Two simultaneous `--seed=42 --npc-count=2 --camera=third` invocations produce the same `.tscn` (excluding header UID).
   This catches dodgy RNG imports / shared global state.

2. **Refactor `foundry/scene_compiler.py`.** One file, 1,800 lines. Top priorities:
   1. Move `_resolve_prop_overlaps` defaults to accept computed NPC positions (consistency in X5/B!! above).
   2. Fix the `entry = REGISTRY.get(...)` shadowing (B!! above).
   3. Extract `_resolve_atmosphere(...)` and `_resolve_shell(...)` to short helpers.
   4. Add tests for `_build_interior_lights()` cell distribution math (R!! - 8-cell case generates an extra cell).

3. **Fix `foundry/planner.py::resolve_age()` double-call.** Single-line fix: delete either the pre-LLM or post-LLM call. Decide which is correct (the resolver should be authoritative; only one decision emission needed).

4. **Replace `assert` in `foundry/room_graph.py::_wall_between`** with a `ValueError`. Run with `python -O` test once to confirm currently bites.

5. **Auditor: consolidate hardcoded paths.** Move `engine/devforge/asset_lexicon.json` and similar refs to a single `paths.py` module with env-var overrides, so "foundry is standalone" claim matches reality.

After those: open issues for each B/R finding in this doc and triage by impact.

---

## Methodology / scope

This audit was produced from full file reads of the active Foundry spine. Each finding reflects what was *observed in the file itself*, not inferred behaviour from tests or downstream consumers. Severity tags reflect both likelihood of occurrence and potential blast radius:

- **B!** — confirmed bug, will produce wrong outputs or fail in normal use.
- **B!!** — bug that bites only under specific inputs (e.g. empty room, no keywords).
- **R!** — robustness: works but fragile; could fail under environmental changes (Godot path, LLM seed, network).
- **R!!** — robustness: works but fallback or recovery path could fail.
- **R!!!** — robustness: nit; cleanups rather than fixes.
- **N** — design note; not a bug. Useful for future readers.
- **?** — uncertain; would need deeper verification.

A future iteration of this audit should focus on: godot_template scripts (GDScript parse-error footgun), Blender scripts (the build path's biggest surface area), and `foundry/eval/signals.py` (depends on naming conventions across the rest of the codebase, where a vendor-by-mistake swap would silently misclassify).

---

# Round 2 — Blender, grammar, Godot template, eval, visual

**Date:** 2026-06-23 (continued)
**Scope:** Round 1 covered the foundry/ top-level Python spine. Round 2 audits the remaining subpackages: `foundry/blender/`, `foundry/grammar/`, `foundry/godot_template/scripts/`, `foundry/eval/`, `foundry/visual/`. Sampling used for `foundry/blender/build_asset.py` (2535 lines — only entries, headers, two representative sections read end-to-end) and four other large files requiring grep-backed structural reads rather than full line-by-line.

## Cross-cutting concerns (Round 2)

| # | Pattern | Where | Severity |
|---|---------|-------|----------|
| X11 | Identifier list duplicated across GBNF grammars | `asset_spec.gbnf` line 5–6 vs `room_plan.gbnf` line 8 (full category list copy-pasted) | R — adding a category requires editing both |
| X12 | `main()` runs at module load (no `if __name__ == "__main__":` guard) | `blender/render_asset.py`, `blender/build_shell_textures.py`, `blender/bake_lighting.py` | B — importing these as library functions triggers bpy side-effects |
| X13 | Hardcoded endpoint to llama.cpp at `127.0.0.1:8002` | `eval/__main__.py`, `llm.py` (round 1), `visual/vlm.py` | R — paired with the `grammar=None` footgun, callers must remember |
| X14 | Singular Decision-Point dataclass + dict-format branches both exercised | `eval/harness.py:_serialize_decision` lambda fallback for `repr(d)` | R — `decision_codes()` reads `d.get("code", "?")` which on a repr-string is None→"?" for every record |
| X15 | Hardcoded RNG without seeding (`randf_range`, `randi %`) | `godot/container.gd:91` (item impulse jitter); `godot/win_screen.gd` (shake offset) | R — non-reproducible in V-1 visual regression captures |
| X16 | Global `_load_attempted` / lazy-init pattern without locks | `visual/aesthetic.py:25-30` | R — multi-threaded caller races on first-load |
| X17 | Magic numbers in scene_compiler / kitbash / NPC lookups (carryable categories, key roles, theme lists) | `eval/signals.py:_CARRYABLE_CATEGORIES`, `eval/augment.py:_AMBIG_NOUNS`, `audio.gd:CUES`, etc. | R — silent drift if upstream list changes |
| X18 | `set("collision_layer", N)` strings to bypass GDScript static analysis | `godot/pickup.gd:35`, `door.gd:60`, `health.gd:43` | R — Godot's typed setter is bypassed; works at runtime if collision node is a StaticBody/CharacterBody but no compile check |
| X19 | Function-level guard `if OS.has_feature("headless")` for tests | `godot/npc.gd:_wait_for_advance` | N — good pattern (V-1 probe gating), copy elsewhere |
| X20 | Several Godot `_process`/`_physics_process` run raycasts every frame | `godot/interaction.gd:_process` (camera raycast), `godot/day_night.gd:_apply_cycle` (re-emits lerps every frame) | R — scene-complexity-driven perf cliff |

## Per-file findings (Round 2)

### `foundry/grammar/asset_spec.gbnf`

- **Purpose:** Constrains the LLM output of the asset planner to valid JSON: `{asset_id, generator, params}`.
- **B!**: None.
- **R!**: **X11**. The category list (37 alternations) appears verbatim as both `asset-id-val` and `generator-val`. Adding a new generator name requires touching this list and `room_plan.gbnf`'s `category-val` list in lockstep. Extract a single generated source of truth.
- **R!!**: One of the alternations is `"L_bench"` — a Capital-L prefix inconsistent with the rest of the lowercase snake_case categories. Original was likely hand-edited, not generated; if a builder or test name-validates against this list, the case mixing forces dual membership logic. Pick a convention.
- **R!!!**: No comment/note marks what each generator's legal param ranges are — `params-object` accepts any string:number pair without guard. Clamping is done by the planner post-parse.

### `foundry/grammar/quest_spec.gbnf`

- **Purpose:** Quest-dialogue JSON: `{npc_role, target_entity, dialogue, objective}`.
- **B!**: None.
- **R!!**: `objective.type` is hardcoded to `"fetch"` — the grammar enforces the simplest objective type. `deliver`, `place`, `talk` (introduced later, documented in `quest_validator.py` and `quest_manager.gd`) are not grammar-legal. If the LLM tries to emit a `deliver` objective post-fix, it fails the grammar even though downstream accepts it.
- **N**: Short, focused grammar with good use of sub-rules (`dialogue-object`). Single-line alternations only — passes the `normalize_gbnf` invariant.

### `foundry/grammar/room_plan.gbnf`

- **Purpose:** The room plan the legacy `room_planner.py` uses: `{room_size, props}` arrays.
- **B!**: None.
- **R!**: **X11 replica**: duplicates the asset category list (37 alternations) and adds a small material keyword list (6 items). Catalogue drift risk between this and `asset_spec.gbnf`. The 6-material list is also far narrower than `material_resolver.py`'s family set — if generators learn new materials via foundry but not this grammar, the legacy planner will reject them.
- **R!!**: No comment about whether room_plan is still used as primary planner or has been retired in favour of the spine. Check `room_planner.py` callers.

### `foundry/visual/__init__.py`

- **Purpose:** Module docstring header for the visual-eval subpackage.
- **N**: Empty body (0 lines). No public re-exports — `from visual.batch import run_batch` is the explicit path used. Convention; see `foundry/__init__.py` (also empty).

### `foundry/visual/batch.py`

- **Purpose:** Top-level visual-eval batch driver. Catalog scan + scene regression + auto-reroll worklist.
- **B!!**: `reroll_flagged()` (line ~290) treats `if "_" not in prop_id` as the heuristic to skip scene IDs. `scene_id` like `"lab_2"` has an underscore → treated as forgeable prop → forge path called → "lab 2" → likely rejected by AssetPlanner. `prop_id` like `"plate"` with no underscore → skipped incorrectly → no reroll even though it's a real prop. Replace with whitelist prefix or carrying the JSON tag.
- **B!!**: `reroll_flagged()` builds the forge request with `prop_id.replace("_", " ")`. For `"L_bench"` → `"L bench"` (garbage; `L` is not a material prefix but a name suffix), for `"worn_oak_table_3"` → `"worn oak table 3"` (works but the trailing `3` is a per-instance suffix the LLM won't undo). Round-trip with the original request via a stored map.
- **B!!!**: `reroll_flagged()` returns `outcomes` containing "skipped" entries with `rerolls: 0` then continues — `rerolls: 0` is meaningless for skipped entries. The data shape confuses downstream counters.
- **R!**: No upper bound on worklist size — `worklist.json` from a large library (200+ props flagged) means 200+ successive forge calls. Sequential; no concurrency. ~10 minutes wall-clock for full re-render.
- **R!!**: `_run_prop_catalog` swallows every exception from `capture_prop(str(glb), ...)`: `item["checks"] = {"notes": f"capture error: {e}"}; item["error"] = str(e); items.append(item); worklist.append(prop_id)`. A bad GLB floods the worklist, blocking rerolls even when the reroll path also fails. Log + bail-on-N-failures.
- **R!!!**: `_run_scene_regression` filters for `d.is_dir() and (d / "project.godot").exists()` but does NOT verify the directory was actually scaffolded by `foundry.scaffold` (no `_forge_capture` metadata, no `scenes/main.tscn`). Old debug projects left in `builds/` show up.

### `foundry/visual/report.py`

- **Purpose:** Visual report builder + baseline + regression delta.
- **B!**: None.
- **R!!**: `regression_delta()` returns `aesthetic_deltas: dict` with `current=""` / `previous=""` / `delta=None` placeholders when score missing. Markdown doesn't render this; JSON consumers must handle None explicitly. Document schema or drop entries when no data.
- **R!**: `_sort_key` returns `(flag_count, -aesthetic_score)`. When `aesthetic_score` is None for several items with the same flag_count, dict iteration order (Python 3.7+ guaranteed but unstable across runs with reordered kwargs) could shift position; use `id` as final tiebreaker for fully-stable ordering.
- **R!!!**: Markdown `notes` truncated to first 60 chars: `sig.get("notes", "")[:60]`. Truncates in the middle of words. Add `…` suffix or break-word-aware truncation.
- **N**: `_BOOL_KEYS` enumerated for detail blocks — fine. The Markdown + JSON dual output is correct.

### `foundry/visual/vlm.py`

- **Purpose:** Qwen3-VL structured visual check via llama.cpp's `/v1/chat/completions` with `json_schema`.
- **B!**: **X13** — hardcoded endpoint `http://127.0.0.1:8002` (line ~74). Same anti-pattern as `llm.py`.
- **B!!**: Bare `except Exception:` (line ~106) collapses every possible failure into `{**defaults, "_parse_error": True}`. Programming errors (e.g. `requests` not installed) are silently swallowed. Use `except (requests.RequestException, json.JSONDecodeError, Exception) as e:` with a re-raise path for the truly unexpected.
- **R!!**: `requests.HTTPError` (after `raise_for_status()`) is treated identically to `ConnectionError` — no retry on 5xx. For a 30-second VLM image call that's slow on first request (model warmup), failing hard on 500 is unavoidable.
- **R!!**: `_extract_json_from_text` uses non-greedy `\{.*?\}` (line ~204). For multi-object JSON (some models emit reasoning then JSON), picks the FIRST match — not necessarily the intended one. Use `re.findall` and pick last, or prefer a more structured extractor.
- **R!!!**: `_coerce` boolean check `value.strip().lower() in ("true","1","yes")` (line ~228) misses `"y"`, `"on"`, `"affirmative"` — common LLM outputs. Liberalise.
- **N**: Headers and docstring correctly note that `/v1/chat/completions` + `image_url` data URI is the only path libmtmd actually feeds the vision encoder. The legacy `/completion` + `image_data` array is documented as a known-broken alternative.

### `foundry/visual/screenshot.py`

- **Purpose:** Offscreen Godot screenshot harness via SubViewport + EGL surfaceless.
- **B!!**: `_set_capture_config` (line ~140) escapes JSON with `json.dumps(config).replace('"', '\\"')` then writes `_forge_capture="..."`. On second call, the regex matches the already-escaped line and re-escapes — `\\\"` → `\\\\\"` → invalid in Godot's INI-like parser. After ~10 rerun cycles the project.godot is unparseable and the next capture fails to load `_forge_capture`. Track a "first-write" or compare-before-write.
- **B!**: `_run_godot_import` "tolerates non-zero exit" — broken GLB assets (e.g. `_ensure_material` crashes on a corrupt mesh) appear to import OK and only surface during the capture run as cryptic Engine errors. Fail-fast + log specific Godot import errors.
- **R!!**: Default angles `[0.0, 1.5708, 3.1416]` for scene capture cover FRONT, RIGHT, BACK (no left). Comment calls this out — by design, but an "all four cardinal directions" mode would catch more visual bugs.
- **R!**: No concurrency limit on Godot subprocess. `run_batch(catalog=True)` launches serially — a 200-prop library takes 200×120s = 6.7 hours (worst case). For real test/eval schedules, this is the perf bottleneck of the whole visual layer.
- **R!!!**: `_read_manifest` reads `capture_manifest.json` and returns `data.get("paths", [])`. If capture wrote zero PNGs (broken render), the manifest is empty — caller treats it as "no screenshots" → silent reroll trigger. Distinguish "captured 0 due to error" from "captured N".

### `foundry/visual/aesthetic.py`

- **Purpose:** CLIP backbone + tiny aesthetic head (LAION-style); lazy-loaded model cache.
- **B!**: `_load_attempted` (line ~25) is a module-level bool; once True, `FORGE_AESTHETIC_HEAD` env var set AFTER first call is ignored — model never loads. Test with two-stage init.
- **B!!**: Class `_AestheticHead(nn.Module if _HAS_TORCH else object)` (line ~152). When `_HAS_TORCH` is False, `nn` is `None`. The class **body** doesn't error (assigned once at module level), but `__init__` accesses `nn.Linear(embed_dim, 256)` → `None.Linear(...)` → AttributeError at instantiation. Should re-import lazily.
- **R!!**: **X16.** `_load_attempted = True` then `_model_cache = ...` is two statements no atomicity. Two simultaneous first-callers (test fixture + production) race: one loads, one finds `_model_cache is None and _load_attempted is True` → wrong branch.
- **R!**: `weights_only=True` (line ~101) in `torch.load` is the secure default but rejects older checkpoint formats with non-tensor metadata. For legacy LAION heads, this may break loading. Document required `.pth` format.
- **R!!!**: Docstring (line ~12) claims "Architecture mirrors LAION aesthetic predictor V2" — actually `Linear→ReLU→Linear` with hidden 256. Real LAION V2 is `Linear→ReLU→Linear→ReLU→Linear→...` to 1024→128→64→1. Misleading documentation; scores won't be comparable to other LAION-based eval systems.

### `foundry/eval/__init__.py`

- **Purpose:** Header docstring.
- **N**: Empty body. Same pattern as `foundry/__init__.py`.

### `foundry/eval/__main__.py`

- **Purpose:** CLI entry for `python -m foundry.eval` with subcommands run/stability/regression/augment/augment-quest.
- **B!!**: `_cmd_augment_quest` (line ~62) hardcodes a 4-item manifest (`table_0`, `shelf_0`, `cabinet_0`, `table_1`) for `--dry-run` mode. AGENTS.md requires determinism — different test runs producing different stats from a fabricated fixture violates that. Read from a fixture file or accept `manifest=...` argument.
- **B!**: `_stub_llm` (line ~205) defines `def _stub(prompt: str, grammar)` then returns the same `table_spec` for every prompt. **Signature must match the real LLM signature** — if real `FoundryLLM.__call__` ever changes to accept `*args, **kwargs` or extra positional, the stub breaks contract. Mirror via `inspect.signature`.
- **R!!**: 5 subcommands in one 330-line file. Splitting each into its own module + a thin dispatcher would make `python -m foundry.eval augment --help` discoverable.
- **R!**: `print()` everywhere — no `logging` module. Debug via stdout only. When run as a subprocess, output can't be filtered by level.
- **R!!!**: `--seed 0` is valid input but not distinguished from "no `--seed`" — argparse conflates `None` with `0` after `type=int, default=1337`. Test the seed-zero path explicitly.

### `foundry/eval/visual.py`

- **Purpose:** Pure visual signal layer (FLAT booleans from VLM checks + aesthetic score).
- **B!**: None.
- **R!**: `bool_signals` list is hardcoded (line ~70). When the VLM schemas add new fields (PROP_SCHEMA / SCENE_SCHEMA in `vlm.py`), this list must be updated. There's no test that fires when a new field is added — silently drops the signal.
- **R!!!**: `_extract_aesthetic` (line ~94) checks `isinstance(score, (int, float))` — `bool` is a subclass of `int` in Python → if score is `True`, returns `1.0`. Probably fine for the score's range but adds a code-smell (numpy's bool-as-int semantics).
- **N**: Pure-function design is the right pattern; 90 lines, well-tested surface.

### `foundry/eval/sampler.py`

- **Purpose:** Stratified sampler (slice 1 + slice 2 severity-weighted).
- **B!**: None.
- **R!**: `(signals_fn(rec) or set())` (line ~94) handles `None` gracefully but doesn't handle `set()` returning wrong type (e.g. `list`). `Set[str] = set(...)` is the contract; caller breakage is silent.
- **R!!**: When `low_severity_cap > len(low_tier_in_picked)`, `rng.sample(...)` (line ~115) raises `ValueError`. Guarded by `if len(low_tier_in_picked) > low_severity_cap` so it's safe — but the guard relies on the implicit assumption that `low_tier_in_picked` is a `list`, not a `set`. With `set`, ordering is undefined which breaks determinism.
- **N**: 4-step pipeline (compute signals → per-stratum pick → severity tier filter → clean baseline) cleanly separated; easy to test in isolation.

### `foundry/eval/regression.py`

- **Purpose:** Golden-master regression lens.
- **B!!**: `_request_hash` (line ~30) `request.strip().lower()` does NOT nuke whitespace inside — `"the table"` and `"the  table"` (double space) hash differently. Reproducibility footgun if any test data has stray spaces.
- **B!**: `--update` flag re-blesses expectations from CURRENT planner output. **Destructive**: if a regression is real (e.g. qwen produced a bug), running `--update` makes the bug the new ground truth. Require an explicit `--force-update` confirmation or log+back-up the prior expectation file before overwrite.
- **R!**: Per-request `AssetPlanner().plan(request, llm)` (line ~95), no caching. For corpora with 100's of requests, regression takes minutes — repeat invocations re-plan everything. Cache `plan(req, llm) → (spec, decisions)` keyed by `(request, llm_signature)`.
- **R!**: `--update` writes per-request `<hash>.json` files — no rollback, no backup, no audit trail. If multiple devs run with `--update` concurrently, last-write-wins.
- **N**: Per-request `(hard_pass, hard_fail, generator_only_mismatch)` trichotomy is clean; trivial to test.

### `foundry/eval/stability.py`

- **Purpose:** Plan N times per request, measure run-to-run variance.
- **B!!**: `_param_drift` uses `denom = max(abs(a), abs(b), 0.001)` (line ~24). For genuinely zero params, the floor 0.001 prevents div-by-zero — but for two values `a=0.0, b=1.0`, returns 1000.0 (1000x drift), flagged as >15%. False positive when params genuinely differ. The floor should be relative to the param's typical magnitude, not a global 0.001.
- **B!!**: Variation comparison uses `param_keys` set union across captures. If one run's LLM emits an extra param, all OTHER runs (which don't have it) → `valid = [v for v in values if v is not None and isinstance(v, (int, float))]` skips — but the FIRST run has 1 valid, others 0 → `len(valid) < 2` → skipped. Correct behaviour but the per-param "stable" flag may silently mask regressions when schema drifts.
- **R**: Sequential runs (no parallelism). 200 reqs × 5 runs = 1000 sequential planner calls. For batch eval, GPU-lock step.
- **N**: Per-request `runs_info` is useful for debugging — full per-run captures retained.

### `foundry/eval/report.py`

- **Purpose:** Friction report builder + corpus loader.
- **B!**: None.
- **R!**: `_build_digest` (line ~150) renders `Build errors` section even with empty list as `(none)` — markdown headings without content are noise. Conditional section emission.
- **R!!**: Stratum sizes appear as comma-separated `k=v` on one bullet (line ~175). For 50+ strata, the line is unreadable. One-per-line is more grep-friendly.
- **R!!!**: Probe list closing section "Eyeball these N" — when N is 0 (no probes), no section. When N is large, sections render fine but truncated IDs in JSON.
- **N**: `load_corpus` correctly strips `#` comments + blanks — robust corpus loader.

### `foundry/eval/harness.py`

- **Purpose:** `RunRecord` + `QuestRecord` dataclasses + `run_corpus` / `run_quest_corpus` drivers.
- **B!**: **X14.** `_serialize_decision = lambda d: {"repr": repr(d)}` fallback when `decisions` import fails (test env). `repr(d)` produces something like `"DecisionPoint(code='size.mismatch', ...)"`. Downstream `decision_codes(record)` calls `d.get("code", "?")` — returns "?" for every record (none of the repr'd fields have a `code` key). Signal aggregators silently undercount.
- **B!!**: `run_quest_corpus` writes `scene_path = str(Path(scene_output_dir) / f"quest_{idx}.tscn")` (line ~228), but if compile_scene succeeds for `idx=0` and fails for `idx=1`, the spec for `idx=1` is silently lost. Caller has no easy way to retry individual quests.
- **R!**: `tempfile.NamedTemporaryFile(delete=False)` (line ~157) followed by `Path(spec_path).unlink(missing_ok=True)` in `finally`. Process crash between write and unlink → temp spec files pile up in `/tmp`. Implement periodic sweep OR `try/except OSError` unlink.
- **R!!**: `record.error = repr(exc)` (line ~175) — for `KeyError` and `IndexError`, `repr(exc)` includes Python stack-frame detail that can leak internal structure. Capture `type(exc).__name__ + str(exc)` only.
- **N**: `RunRecord` + `QuestRecord` dataclasses are well-designed; JSON-friendly via `asdict`.

### `foundry/eval/signals.py`

- **Purpose:** Objective signal layer — pure functions turn `RunRecord` / `QuestRecord` into sets of tags.
- **B!**: **X17.** Hardcoded `_CARRYABLE_CATEGORIES = {"key", "book", "cup", "gem", "bottle", "scroll", "coin-pouch", "candle", "dagger", "ring"}` (line ~705). When scene_compiler adds a new carryable category (`"keyring"`, `"lockpick"`), this set goes out of sync → `check_target_is_carryable` / `check_multi_item_possible` miss them. Single-source-of-truth violation.
- **B!!**: `SIGNAL_SEVERITY` is a runtime-grown dict: tags added with `SIGNAL_SEVERITY["X"] = "high"` scattered through the file (decor_never_target, headless_not_clean, target_not_carryable, etc., lines ~745-825). New high-severity tags can be added downstream without an explicit import chain — test coverage may miss keys.
- **B!!**: `check_all_npcs_winnable` (line ~880) is a **POSITIVE signal** (fires when quest IS winnable) but classified as `severity = "low"`. Its ABSENCE in a record was intended as a flag but is never inverted. Categorical mismatch — positive signals should NOT be in SIGNAL_SEVERITY maps unless paired with a complementary negative.
- **R!!**: `compute_quest_signals` reads `getattr(record, "quest_specs", None)` then falls back to `getattr(record, "quest_spec", None)` (line ~570). If a record has BOTH (e.g. a partial migration), only the multi-NPC list is used, single-NPC fallback is shadowed. Document the canonical attribute name.
- **R!**: `_material_mismatch` looks for `_MATERIAL_KEYWORDS` (line ~130) — 8 specific keywords. Same list as `material_resolver._SPECIFIC_KW` but duplicated here for testability. If one is updated, the other drifts.
- **R!!!**: `check_soul_tones_vary` returns `"soul_tones_vary"` if `len(specs) >= 2 and len(tones) >= 2`. For 2 NPCs with identical souls (possible bug elsewhere), the function returns None — silent.
- **R!!!**: `compute_room_variety` returns a dict but is never wired into any signal severity or `compute_quest_signals` (lines ~770). Dead-code path. Document or wire.

### `foundry/eval/augment.py`

- **Purpose:** Corpus augmentation via slot-filling + adversarial templates.
- **B!!**: Magic slicing `specific_kws[:4]`, `aged[:3] + new[:3]`, `rng.sample(_SIZE_WORDS, min(6, len(_SIZE_WORDS)))`, `specific_kws[:3]` (lines ~225-235) limits the combinatorial blowout but with no constants — if SPECIFIC_KW grows to 30 entries, still only 4 used. Move to a `MAX_COMBOS_PER_GROUP` constant in the docstring + a test as a guard.
- **B!**: `_adversarial_combos` (line ~250) enumerates a hardcoded `mat_pairs` list with 6 entries — manual list. If `material_resolver._SPECIFIC_KW` is updated, adversarial coverage is missed. Move to `cross_family_pairs(family_a, family_b) -> List[Tuple[str, str]]` driven by the family map.
- **R!!**: `_fires_decision` is called **per-req, post-validation** (line ~290). For target=250, that's 250 additional planner invocations ON TOP OF the 250 from `_is_valid`. Plan-once-per-req caching needed.
- **R!**: `_normalize` regex pattern `[^\w\s]` strips punctuation but treats `_` as word (it's `\w`). So `"a wooden_key"` and `"a wooden key"` are different dedup keys. Edge case but real.
- **R**: dedup keyed on `_normalize(text).hash()` (SHA-256) — first 16 hex chars = 64-bit. Birthday-paradox probability of collision (~10⁻⁹ for 50k requests) is fine but worth noting.
- **N**: Adversarial templates include `an empty {room}` and `a {mood} room with something in it` — good stress tests; this layer is well-designed.

### `foundry/blender/geometry_ops.py`

- **Purpose:** Composable geometry operations (bevel, solidify, array, greeble, parametric_var). Designed for WS-3.3 procedural breadth.
- **B!**: None.
- **R!!**: `_find_object_for_mesh` (line ~226) iterates `bpy.data.objects` linearly — O(N) per op call. For a 5-op pipeline + 50-object scene, 50×5=250 linear scans. Add a `bpy.data.Mesh → bpy.data.Object` cache.
- **R!!**: `solidify`, `array` set `bpy.context.view_layer.objects.active = obj` then `obj.select_set(True)` (line ~85). If a `compose()` had earlier set the active to a different object during a modifier-apply, the order matters. Document the active-then-select invariant.
- **R**: `bevel` clamps `offset = min(width, smallest * 0.4)` — safety for thin geometry. Document magic 0.4.
- **R**: `parametric_variation` twist is `tw * (v.co.z / max(1.0, max(abs(v.co.z), 0.01)))` (line ~193). For negative z, divides by positive — twist direction reverses above/below origin (intentional or bug?). Document.
- **N**: `_HAS_BPY` import-time sentinel is functional; if Blender Python is in a non-Blender Python env, the ops gracefully no-op.

### `foundry/blender/render_asset.py`

- **Purpose:** `blender --background --python render_asset.py -- <glb> <out_png>` heads-eye thumbnail.
- **B!**: **X12.** `main()` runs at module-load (line ~49). Importing this file in any test or library use case triggers `bpy.ops.wm.read_factory_settings`, GLB import, scene setup, and `bpy.ops.render.render`. Add `if __name__ == "__main__": main()`.
- **R!**: No exception handling. bpy errors surface as Python tracebacks — when called via subprocess, the orchestrator must parse stderr to know what went wrong. Wrap in try/except + log.
- **R**: 16 samples for thumbnail is too low for visible banding. For V-1 visual capture, raise to 32+.
- **R**: 640×480 hardcoded output size. No override path.
- **R**: Hardcoded camera `(2.4, -2.4, 1.7)` (line ~37) — frame is "prop at origin, camera 3.5m away looking down 30°". For 4-meter-tall props (wardrobe), camera-too-close; for 5cm props (gem), camera-too-far. Parameterise.

### `foundry/blender/build_shell_textures.py`

- **Purpose:** Bake the E1 room shell textures (floor + wall + ceiling).
- **B!**: **X12.** `main()` runs at module-load (line ~290). Same as `render_asset.py`.
- **B!!**: `sys.path.insert(0, _foundry_dir)` at module level (line ~17) — side-effect on ANY import. If a unit test imports this module without intending to use it (e.g. for a constant lookup), it pollutes `sys.path`. Move into `if __name__ == "__main__":` block.
- **R!!**: `bpy.ops.wm.read_factory_settings(use_empty=True)` called between each material to wipe state — but mid-material cleanup leaves partial heavy state in `bpy.data.images` if exception interrupts. Wrap material setup in try/finally that deletes derived images.
- **R!**: 512×512 baked textures hardcoded. For larger rooms (multi-room WS-7), 1024+ needed. Parameterise.
- **R!**: `margin=16` px on the bake (line ~222) — at 512×512, margin is 3% of size. May bleed on tile seams. Test visually.
- **N**: Floor/wall/ceiling split with progressively lighter base colour (×1.25 / ×1.45) is a smart composer's trick.

### `foundry/blender/bake_lighting.py`

- **Purpose:** Cycles HIP/RT lighting bake with tier routing. Exports `baked.glb` with COLOR_0.
- **B!**: None.
- **B!!**: `bpy.ops.object.bake(...)` (line ~108) is called inside a loop where the previously-set active object is `objs[0]`. But the loops sets `obj.select_set(False)` AFTER each iteration (line ~95). For the final iteration, the active is `objs[0]` but all objects are DESELECTED. The bake call would have nothing to bake. Verify by running with single-object desc.
- **B!**: `json.load(open(path))` (line ~68) — no try/except on bad JSON. Adds `try: json.load(...) except json.JSONDecodeError: sys.exit("bad desc")`.
- **R!!**: `_enable_hip` (line ~21) tries HIP then silently falls back to CPU on `Exception`. For a developer without a GPU, this is the expected path; for a CI box where HIP drivers are misconfigured, this would silently take 10× the expected bake time. Tag bake with device used in a log.
- **R**: `samples` param only honoured if HIP works. Tests with `samples=4` and HIP still set `cycles.samples = int(desc.get('samples', 16))` — but `_enable_hip` was called with `int(desc.get('samples', 16))` too — duplicates the same constant read.
- **N**: Vertex-colour-as-lightmap is a clean deterministic choice; no TextureMap race conditions.

### `foundry/blender/kitbash.py`

- **Purpose:** Composite prop assembly via KitbashLibrary registry + `compose()` orchestrator.
- **B!!**: `compose()` calls `kitbash_library.get(part_name)` (line ~213) which raises `KeyError` for unregistered parts. The exception propagates — no Decision Point or graceful degradation. The exception message says "Kitbash part 'X' not registered" but no map of registered parts is dumped.
- **R!**: 5 built-in parts are registered (line ~141): `leg_turned`, `top_round`, `top_square`, `handle_loop`, `cross_brace`. Adding new scenes requires adding new parts here. No test for "all registered parts are reachable from a kitbash spec".
- **R**: `_add_cylinder` uses `bmesh.ops.create_cone(...)` with `radius1 == radius2` — produces a cylinder by accident. Cone-only specs (e.g. tapered legs) cannot be expressed via kitbash.
- **R**: KitbashLibrary is a module-level singleton (`kitbash_library = KitbashLibrary()`) — multi-process Blender launches each get a fresh singleton, but multi-threaded runs would race.
- **N**: `_add_box` / `_add_cylinder` are duplicated between `kitbash.py` and `geometry_ops.py` (different signatures). Refactor into a single `_blender_geom.py`.

### `foundry/blender/build_asset.py` (sampled — 2535 lines)

- **Purpose:** Procedural geometry builder for every asset category. WS-3.2/3.3 batch.
- **B!**: **X12 confirmed for the whole file family** — module-level `main()` calls in sister files. `build_asset.py` does NOT export a `main()` of its own per the function listing (`_build_table_geometry`...`_build_lectern_geometry`...`build_geometry(spec)`), so it may already be import-safe. Verify.
- **R!!**: 49 builder functions (`_build_table_geometry` ... `_build_lectern_geometry`), each ~10-30 lines following the same shape: validation → bmesh construction → material assignment. **This is the place where AGENTS.md's seed determinism must be enforced** — does each `_build_X_geometry(params)` accept a `seed` (or derive from spec)? Spot-check shows many do NOT take a `seed` parameter — randomness from `bpy` operations is order-dependent. Verify cookie by cookie.
- **R!**: `apply_bevel(mesh_data)` (line ~2061) is ~30 lines of replication vs `geometry_ops.py::bevel` (line ~63). Two implementations of the same operation. **One source of truth needed.**
- **R!!**: `_metal_color_nodes` (line ~122) takes `seed` parameter but only uses it for Material Mapping `Location` offset (line ~133). True randomness for grain/mottle is determined by Voronoi + Noise texture positions, NOT via the seed. Determinism gap.
- **R!!**: `apply_normal_bake` and `apply_roughness_bake` both at ~150 lines each (lines ~2142, ~2234). Heavy node-graph mutation logic. The bake selection of `nodes.active = tex_node` is race-prone (bpy mutates globally, no isolation per-object). Mid-bake errors leave dangling node references.
- **R!!**: `apply_entropy` (line ~2405) — entropy-driven vertex displacement for "wear". The function reads from other modules without obvious sealing — if `_derive_entropy_seed(spec)` is sensitive, calling code may be exposed.
- **N**: 49 categories is a large but manageable list. The structure (one `_build_X_geometry(params)` per category) is clear. Round-trip tests per category would catch drift.

### `godot_template/scripts/audio.gd`

- **Purpose:** AudioStreamGenerator-based procedural audio (footstep, pickup, talk, win) plus theme ambient bed.
- **B!**: None.
- **R!!**: `_process` (line ~210) writes `_ambient_playback.push_frame(...)` every frame but the playback buffer has finite `buffer_length` (0.1s × 44100 = ~4410 frames). If `frames_to_fill` exceeds `get_frames_available()`, the push silently drops samples — no warning. Monitor `_ambient_playback.get_frames_available()` and log when low.
- **R!!**: `_gen_footstep` envelope `exp(-t * decay_rate)` for decay_rate=40 ends sub-audible by t>0.5 (exp(-20)≈2e-9). For a 0.08s cue, only the FIRST ~50ms is audible; the back half is silence. Either shorten duration or raise decay_rate.
- **R!**: CUES dictionary (line ~20) requires `_play_cue` to do `callv(gen_func, [playback, n, rate, duration, extra])`. Adding a new cue means editing CUES + writing `_gen_<name>` + testing callv arg contract. Single source of truth; document.
- **R**: `match surface:` (line ~85) defaults to stone for unknown. If "wood" is added but falls through, footstep plays stone sound on a wood floor — immersive bug.
- **R!!!**: `linear_to_db(volume)` for `volume=0.0` produces -inf. Godot clamps but a `-inf` cache invalidation at runtime can show as "engine error" in logs. Guard `volume > 0`.
- **N**: 12 themes for ambient bed frequencies hardcoded. Comment lists each. Easy to externalise as JSON.

### `godot_template/scripts/door.gd`

- **Purpose:** Locked-door logic with key-check (CB-2) and room traversal signal (CB-4).
- **B!**: None.
- **B!!**: `_travel_to_room` (line ~74) **has no inventory persistence** — comment line 92-95 explicitly says "Persist inventory across room transition via autoload (carried_items should be stored on an autoload singleton or passed as metadata on the next scene load)". **The comment admits this is a TODO and no code implements it.** Loading a new room empties the player's `carried_items`.
- **R!**: `_player_has_key` (line ~39) reads `player.get("carried_items")` via string property access. If `Player` autoload hasn't loaded yet (early scene transition), `get_node_or_null("/root/Root/Player")` is null → returns false → door appears locked with no UI hint why.
- **R!!**: Parts split (`to_room_str.split(",")`) checks `size() != 2` but doesn't validate rx/rz are integers. `"1.5,0"` is silently accepted, `scene_path = "res://scenes/room_1.5_0.tscn"` will fail in `FileAccess.file_exists` → "passage not yet open". Better: log malformed target_room and skip.
- **R**: Hidden door after open: `_is_open=true` and `_target_room != ""` → trigger travel every interaction. Once travelled, the door scene's `_is_open` re-initialised on load — but if scene-change is cancelled (file not found), state is inconsistent.
- **N**: Lock defaulting to `_is_locked = true` (line ~11) is correct security posture.

### `godot_template/scripts/container.gd`

- **Purpose:** Openable chest/cabinet/wardrobe with physics-prop content spawn.
- **B!**: None.
- **B!!**: `_infer_category` (line ~104) — if none of the known keywords found, returns `"book"` as default. **Wrong category inference** means physics BoxShape3D is sized for a book — gem/coin-pouch spawn with book-size collision. Player can't pick up (too big to grab) or visually disproportioned.
- **R!!**: `apply_central_impulse(Vector3(0, 1.5, 0) + Vector3(randf_range(-0.5, 0.5), 0, …))` — non-seeded RNG. **X15.** Contents burst positions are not reproducible in V-1 visual regression.
- **R**: `base_pos = global_position + Vector3(0, 0.3, 0.8)` (line ~70) — fixed offset regardless of container orientation. A cabinet facing north spawns contents behind it.
- **R**: `RigidBody3D` content spawned — physics-active immediately even while player is mid-dialogue. Items may roll out of the container and away.

### `godot_template/scripts/pickup.gd`

- **Purpose:** Item pickup with multi-item inventory, pickup bounce, model reparenting.
- **B!**: None.
- **R!!**: Rollback path (line ~32) re-sets collision `set("collision_layer", 1)` after a failed `add_item`. **`X18`** — static analysis bypass; relies on the underlying node being a `PhysicsBody3D`.
- **R!!**: `player.add_item(name)` (line ~38) called BEFORE `picked_up.emit(name)`. Subscribers receive the signal before the player's inventory was updated. Subscribers that read `player.carried_items` from the signal handler may see stale state.
- **R!**: `model.reparent(carried_parent, false)` (line ~25) — `false` = keep global transform. If the prop was at world (5, 0.5, 3) and reparented, the model stays at world (5, 0.5, 3) but is now under `CarriedItem` (camera-relative). Subsequent `_show_active_model()` positions in camera-space, model snaps back.
- **R**: `name = get_meta("_forge_category", "")` falls back to empty string — `_build_prompt` shows "Press E to pick up" with no specifics. Cosmetic.
- **N**: `_do_pickup_bounce` (line ~55) uses Tween `Vector3(1.2, 1.2, 1.2) → Vector3(1.0, 1.0, 1.0)` — smooth, deterministic.

### `godot_template/scripts/health.gd`

- **Purpose:** HP tracking, damage application, death/respawn.
- **B!**: None.
- **R!!**: `_flash_damage` (line ~83) calls `hud.flash_damage()` — if HUD doesn't implement this method, silent no-op. fragile against renaming.
- **R!**: Respawn sets `current_health = max_health` — if a "permanent debuff" feature ever added this would clobber debuff state. Document respawn semantics OR version-gate.
- **R**: `_respawn_position` recorded only at `_ready()`. If the player teleports (e.g. CB-7 outdoor), respawn returns to origin.
- **N**: 0.5s iframe default is reasonable. Brief 1.0s post-respawn iframe is good design.

### `godot_template/scripts/win_screen.gd`

- **Purpose:** Win overlay with R/Esc handlers and screen-shake.
- **B!**: None.
- **R!!**: `_update_win_message` reads `hud._quests_done` / `hud._quests_total` private fields (line ~62). Underscore-prefix signals intent-private. Tight coupling; refactor HUD to expose `get_quests_done() / get_quests_total()`.
- **R**: `randf_range(-1, 1) × _shake_intensity × decay` (line ~47) — **X15**, non-seeded RNG. Visual QA captures will not reproduce the same shake sequence → diff noise.
- **N**: Shake steps over 10 increments with linear decay — smooth result.

### `godot_template/scripts/combat.gd`

- **Purpose:** Melee swings with skill-aware damage.
- **B!**: None.
- **B!!**: `_swing` (line ~47) uses `PhysicsRayQueryParameters3D.intersect_ray` — single ray, hits first collider. Multi-melee scenarios (3 enemies in cone) require 3 swings. `Area3D` overlap would be fairer/cleaner.
- **R!**: `_swing_cooldown` mutates multiplicatively with skill levels: `0.5 → 0.4 → 0.34`. Multiplied order matters; if a future maintainer adds a 4th speed modifier, the cascade is non-trivial. Use `*=` patterns with explicit comment.
- **R**: `health_node.is_dead` (line ~53) accessed without null check inside the dead-check branch — if `Health` is missing, the swing still happens but no damage. Cosmetic.
- **N**: `_base_damage * _damage_mult` decimal scaling is reasonable.

### `godot_template/scripts/build_report_panel.gd`

- **Purpose:** In-world Build Report card with B-key toggle.
- **B!**: None.
- **R!**: `_load_report` (line ~30) reads `res://build_report.json`. For disposable/scaffolded projects without the file, falls through to "Build Report (not found)" — UX-friendly.
- **R!!**: `_render_section` (line ~56) flattens a Dictionary item `"code"` field but DROPS `context`. For Decision-Point audit, context is the actionable info.
- **R!!!**: `JSON.parse_string` returns null on parse error → `if not report:` catches → "Build Report (parse error)". **But** empty dict `{}` is also falsy in Godot 4 strict sense — actually Godot treats empty dict as truthy. Verify empirically; could mis-route.
- **N**: `@onready var _panel: Panel = $Panel` — implicit coupling to scene tree structure.

### `godot_template/scripts/capture_screenshot.gd`

- **Purpose:** SubViewport-based screenshot driver invoked from `visual.screenshot.py`.
- **B!**: None.
- **B!!**: `ProjectSettings.get_setting("application/_forge_capture", "")` (line ~12) reads config locally. If the python side wrote the config twice (escape bug, see `visual/screenshot.py` B!!), Godot parses the doubled-escaped JSON as a literal string → `JSON.parse_string` returns null → "not valid JSON" printerr + quit 1. Silent capture failure.
- **R!**: `await get_tree().process_frame` + `await RenderingServer.frame_post_draw × 2` (line ~83). Two `frame_post_draw` is heuristic; on complex shaders, may need 3. First-frame capture is famously empty in headless.
- **R!!**: `await get_tree().process_frame` and then `await RenderingServer.frame_post_draw` — if no shaders compile, second await is wasted. Acceptable for now.
- **N**: Scene / prop-aware modes via config — clean.

### `godot_template/scripts/prompt_screen.gd`

- **Purpose:** WS-4 prompt-entry UI + orchestrator polling.
- **B!**: None.
- **B!**: `_poll_build_complete` polls 120 times at 0.5s = 60-second hard timeout (line ~78). **Silent fallback** if build takes >60s → loads "res://generated_scene.tscn" with no error UI. Users see a scene appear with NO indication that generation failed.
- **R!**: `if FileAccess.file_exists(REPORT_FILE): break` (line ~80) — FileAccess polling is fine, but in headless mode the orchestrator MUST write `user://build_report.json` (Godot's user data dir). For builds without user dir setup, poll fails forever.
- **R**: `_input_event` (line ~27) checks `keycode == KEY_ENTER and event.ctrl_pressed` — Ctrl+Enter for "Generate". Not documented in UI.
- **N**: DotsTimer encapsulates UX.

### `godot_template/scripts/hud.gd`

- **Purpose:** HUD with quest log, counter, subtitle scrollback, reticle, tooltip, inventory display.
- **B!**: **None notable**, but several R's.
- **R!!**: `_refresh_quest_log` (line ~74) reads `quest_data.json` EVERY toggle (kbd `J`). Disk I/O bottleneck for long playthroughs. Cache at load.
- **R!**: `_read_quest_targets` (line ~104) opens the JSON file on every refresh (no error handling — file-missing mid-game → silent).
- **R!**: `_collect_all` (line ~177) recurses through scene tree. For deep trees (nesting > 1000) — Python recursion limit hits. Godot recursive function has its own limit (default 1024 stacks).
- **R**: `_subtitle_panel.scroll_to_line(_subtitle_lines.size() - 1)` (line ~119) on RichTextLabel — works but RichTextLabel.docbook scroll API changed across versions. Test 4.x.
- **R**: `_crosshair` is `ColorRect` — `modulate.a = 1.0` not applied (crosshair is solid); only subtitle uses modulate fade.
- **N**: 50-line subtitle cap is sensible. Push subtitle creates a Tween for fade-out.

### `godot_template/scripts/day_night.gd`

- **Purpose:** Runtime day/night cycle with sun + ambient + fog modulation.
- **B!**: None.
- **R!!**: `_apply_cycle` (line ~95) called every frame from `_process`. Computes 8+ lerpf + Color constructions every frame. **X20.** For low-end HW or scenes with shadow casting, this is a measurable perf cliff. Cache when `time_of_day` hasn't changed (e.g. when paused).
- **R!**: `_base_ambient_color` (line ~38) and `_base_ambient` (line ~31) are DUPLICATE fields. One updated in `_ready`, the other in `apply_theme`. Easy to drift; pick one.
- **R**: SDFGI / Glow / SSAO always enabled (line ~149-167). For old GPUs without SDFGI, runtime errors. Fall back to a lightweight environment.
- **R!**: `THEME_PRESETS` (line ~225) is a const-dict — adding a theme requires a code change AND recompile. Move to JSON.
- **N**: 12 themes including `crypt`, `tavern`, `armory`, `workshop`, etc. — sensible theme vocabulary.

### `godot_template/scripts/event_manager.gd`

- **Purpose:** CB-5 emergent events runtime. Reads events from `quest_data.json`, fires consequences.
- **B!**: None.
- **B!**: `_should_fire_now` (line ~66) checks `tick <= _tick_count`. Events with `tick_fired=0` fire on first eligible tick (i.e. always). Mixing ticks (player actions + time-of-day) with single int counter conflates two rates.
- **R!!**: `_fired_events` is an Array, not Set (line ~28). `if eid in _fired_events` is O(N). Long-running games accumulate events; linear scans slow.
- **R!**: `_disable_random_furniture` (line ~144) filters `is_class("StaticBody3D")` — string lookup. If scene emits furniture on `RigidBody3D`, missed.
- **R!**: `_spread_disease` (line ~161) iterates `root.get_children()` for NPCs — first N affected. **`randi() % count` isn't used** — deterministic by enumeration order. If Godot's child order changes, different NPCs get sick.
- **N**: Need-mutations broadcast via `child.apply_need_delta(needs_delta)` — pattern is fine.

### `godot_template/scripts/quest_manager.gd`

- **Purpose:** CB-1 quest completion tracker + chain gating (autoload).
- **B!**: None.
- **B!!**: `try_complete_deliver`, `try_complete_talk`, `try_complete_place` (lines ~92-135) iterate `_quests.keys()` linearly, each calling `is_quest_locked` (which itself does a chain walk). For a multi-NPC room talking once/second, O(N²) per second.
- **R!**: `_carried_item` field (line ~22) is set to "" by default — UNUSED in this file (player.gd doesn't write to it). Dead field. Remove.
- **R!!**: `_player_pos` (line ~25) is also unused — only `place` objective has a surface_id, not a player position check. Dead field.
- **R**: `_load_quests` reads file once at _ready. For multi-NPC scenes, single read is fine. For multi-room multi-NPC… could be a future bottleneck.
- **N**: Kahn-like chain dependency check via `depends_on` is the right shape.

### `godot_template/scripts/enemy.gd`

- **Purpose:** CB-6 enemy entity (golem archetype) with NavAgent3D pathfinding.
- **B!**: None.
- **B!**: `_die()` (line ~134) does `await get_tree().create_timer(2.0).timeout; queue_free()`. During the 2s wait, `_is_dead = true` so subsequent `take_damage` calls return early — but the visual death particles play. If a hit triggers during this window, `apply_need_delta` or other state-change side-effects may quietly miss the player expectation.
- **R!!**: `_read_metadata` reads `_forge_enemy_health`, `_forge_enemy_damage`, etc. from get_meta — **no validation**. If metadata is missing, defaults are used silently. Decision Point would be appropriate for "game designer missing required metadata".
- **R!**: `look_at(global_position + look_dir, Vector3.UP)` (line ~104) — second arg is up vector, correct for CharacterBody3D. But if the enemy is on a slope and the player is at a different Y, the look_dir's `.y = 0` is hardcoded — looking flat when slope should pitch up/down.
- **R**: NavigationAgent3D needs a NavigationRegion3D in the scene — `npc.gd` and `enemy.gd` both create NavAgents but don't bake navmesh. Pathfinding breaks silently.
- **N**: `_spawn_death_particles` uses CPUParticles3D (no shader / GPU required). Portable.

### `godot_template/scripts/interaction.gd`

- **Purpose:** Camera raycast for interaction detection + hover highlight + target glow + place-on-surface.
- **B!**: None.
- **B!!**: `_process` (line ~26) runs camera raycast EVERY frame. **X20.** For scene with 200 colliders, raycast latency stacks.
- **B!**: `_unhandled_input` (line ~74) does TWO raycasts for E-key press (one for place_surface check, one for direct interaction). Could be one.
- **R!!**: `_highlight` (line ~133) checks `if node == _hovered_node: return` but `_clear_highlight` always runs the model overlay reset — wasted calls.
- **R!!**: `_update_target_glow` (line ~177) iterates ALL nodes twice per frame (once for NPC targets, once for prop glow). O(2N) per frame.
- **R!**: `KEY_E` and `KEY_X` consume gesture unconditionally — if the player is typing in a UI prompt (e.g. dev console), they accidentally interact. Use `Input.is_action_just_pressed("interact")` with proper action mapping.
- **N**: `_cached_quest_data` (line ~21) cached in `_ready()` — better than reading on every frame. Pattern.

### `godot_template/scripts/player.gd`

- **Purpose:** First-person CharacterBody3D with WASD, mouse look, sprint, crouch, head-bob, footstep audio, multi-item inventory, throw, use, drop.
- **B!**: None.
- **B!!**: `get_active_item()` (line ~55) — if `active_item_index >= carried_items.size()` (out-of-bounds), crashes with IndexError. Defensive check.
- **R!!**: `_throw_active_item` (line ~327) `await get_tree().create_timer(5.0).timeout; proj.queue_free()` — rigid body still has angular vel from initial impulse; mid-flight collision may bounce it into geometry that's now invisible/orphaned.
- **R!**: `mouse_sensitivity = 0.002` (line ~22) hardcoded. Different DPI / mouse brands require remapping.
- **R!!**: `_surface_ray.target_position = Vector3(0, -2.0, 0)` (line ~36) shoots down 2m — if player is on a 1m-thick floor looking down, ray hits the floor correctly. If on a 5m-thick stone block, ray hits stone; if floating mid-air (CB-7 outdoor), no floor → still returns previous `_floor_surface`. No early-out for "in air".
- **R**: Sprint/Crouch state machine — `_is_sprinting` set false when `_is_crouching` true. Logical but `_base_speed * _crouch_mult` resets on crouch end — no smooth transition (snappy).
- **N**: 8 slot / 10 kg inventory caps baked in — tunable.

### `godot_template/scripts/npc.gd`

- **Purpose:** Talk/give NPC with state machine (IDLE → QUEST_GIVEN → DONE), world-log persistence, navigation, skeletal rig, animation, idle barks.
- **B!**: None.
- **B!**: `_restore_state_from_log` (line ~177) reads ENTIRE log file (JSON lines) on `_ready()`. For long games, log grows; O(N) memory + I/O cost per NPC. The O(N²)-with-many-NPCs problem.
- **B!**: `_append_state_to_log` (line ~199) opens file, seeks to end, writes line. Single-process safe; multi-process race very rare in Godot, but worth a guard if game hosts multiple Godots (e.g. multi-user world).
- **R!!**: `_wait_for_advance` (line ~138) loops `while true: await get_tree().process_frame; if Input.is_key_pressed(KEY_SPACE)...` — busy-wait on frame ticks. If a player presses Space during the next frame's lag spike, missed.
- **R!**: `_load_quest_data` (line ~48) reads `quest_data.json` on every NPC `_ready()`. For 10 NPCs, 10 file reads. Cache project-wide.
- **R**: `_BONE_HIERARCHY` (line ~250) hardcodes 17 bones. Adding bones to scene_compiler requires updating this.
- **R!**: `_pick_wander_target` (line ~430) finds `/root/Root/NavigationRegion3D` for navmesh — if missing, falls back to `global_position` (no wander). Silent degradation.
- **R**: `randi() % 2 == 0` for sway direction sign (line ~507) — non-seeded, **X15**.
- **R**: Spine Slice 3 introduces `_soul` — read from quest_data, applied to idle anim. Clean, but validation is `validate_soul` upstream.

## Recommendations added (Round 2)

Top 5 prios from Round 2 (continuing from Round 1 list):

1. **Fix `visual/batch.py::reroll_flagged` heuristic** — replace underscore check with explicit "is forgeable" flag from the JSON catalog. Prevents missed re-renders.
2. **Add `if __name__ == "__main__":` guards to blender scripts** (already broken — `render_asset.py`, `build_shell_textures.py`) — or split into modules + a thin CLI dispatcher.
3. **Lock down `eval/signals.py:_CARRYABLE_CATEGORIES`** — make it dynamic (read from category_registry.py), single source of truth.
4. **Add `JSON.parse_string` retrier in `godot/capture_screenshot.gd`** when `_forge_capture` config is malformed — currently exits with rc=1 silently, leaves no manifest.
5. **Add headless-mode short-circuit in `godot/day_night.gd::_process`** — the lerpf+Color construction every frame is a perf cliff; gate on `_process(_delta)` only advancing when not paused.

After these, address round-2 R! items in priority of impact:
- `godot/interaction.gd` raycast-per-frame (**X20**) → cache + raycast on movement
- `eval/harness.py` tempfile leak (`tempfile.NamedTemporaryFile(delete=False)`)
- `godot/pickup.gd` signal-vs-update race (`X18` + R!!)
- `visual/aesthetic.py` global-threading (**X16**)

## Files audited (Round 2 summary)

| Path | Lines | Notes |
|------|------:|-------|
| `foundry/grammar/asset_spec.gbnf` | ~28 | read end-to-end |
| `foundry/grammar/quest_spec.gbnf` | ~26 | read end-to-end |
| `foundry/grammar/room_plan.gbnf` | ~21 | read end-to-end |
| `foundry/visual/__init__.py` | 3 | read end-to-end |
| `foundry/visual/batch.py` | ~330 | read end-to-end |
| `foundry/visual/report.py` | ~230 | read end-to-end |
| `foundry/visual/vlm.py` | ~250 | read end-to-end |
| `foundry/visual/screenshot.py` | ~260 | read end-to-end |
| `foundry/visual/aesthetic.py` | ~170 | read end-to-end |
| `foundry/eval/__init__.py` | 5 | read end-to-end |
| `foundry/eval/__main__.py` | ~330 | read end-to-end |
| `foundry/eval/visual.py` | ~110 | read end-to-end |
| `foundry/eval/sampler.py` | ~270 | read end-to-end |
| `foundry/eval/regression.py` | ~180 | read end-to-end |
| `foundry/eval/stability.py` | ~190 | read end-to-end |
| `foundry/eval/report.py` | ~200 | read end-to-end |
| `foundry/eval/harness.py` | ~240 | read end-to-end |
| `foundry/eval/signals.py` | ~1013 | read end-to-end (very large — patterns cataloged) |
| `foundry/eval/augment.py` | ~657 | read end-to-end |
| `foundry/blender/geometry_ops.py` | ~220 | read end-to-end |
| `foundry/blender/render_asset.py` | ~50 | read end-to-end |
| `foundry/blender/build_shell_textures.py` | ~290 | read end-to-end |
| `foundry/blender/bake_lighting.py` | ~150 | read end-to-end |
| `foundry/blender/kitbash.py` | ~255 | read end-to-end |
| `foundry/blender/build_asset.py` | 2535 | sampled (headers + structure + selected sections) |
| `godot_template/scripts/audio.gd` | ~292 | read end-to-end |
| `godot_template/scripts/door.gd` | ~117 | read end-to-end |
| `godot_template/scripts/container.gd` | ~117 | read end-to-end |
| `godot_template/scripts/pickup.gd` | ~73 | read end-to-end |
| `godot_template/scripts/health.gd` | ~101 | read end-to-end |
| `godot_template/scripts/win_screen.gd` | ~67 | read end-to-end |
| `godot_template/scripts/combat.gd` | ~100 | read end-to-end |
| `godot_template/scripts/build_report_panel.gd` | ~78 | read end-to-end |
| `godot_template/scripts/capture_screenshot.gd` | ~123 | read end-to-end |
| `godot_template/scripts/prompt_screen.gd` | ~121 | read end-to-end |
| `godot_template/scripts/hud.gd` | ~252 | read end-to-end |
| `godot_template/scripts/day_night.gd` | ~314 | read end-to-end |
| `godot_template/scripts/event_manager.gd` | ~197 | read end-to-end |
| `godot_template/scripts/quest_manager.gd` | ~183 | read end-to-end |
| `godot_template/scripts/enemy.gd` | ~200 | read end-to-end |
| `godot_template/scripts/interaction.gd` | ~379 | read end-to-end |
| `godot_template/scripts/player.gd` | ~547 | read end-to-end |
| `godot_template/scripts/npc.gd` | ~688 | read end-to-end |

**Total Round 2: 42 files, ~9000+ lines.**
# Round 3 — Re-audit

**Date:** 2026-06-23 (Round 3)
**Scope:** 16 files, ~4500 lines (hunyuan/lighting/exterior/proxy/ui/world/biome/hub/blender/scene_compiler re-audits).

## Cross-cutting concerns (Round 3)

| # | Pattern | Where | Severity |
|---|---------|-------|----------|
| X21 | Module-level  runs at import |  last line is bare  | B!! |
| X22 | Bare  swallowing bugs | ,  | R! |
| X23 | Module-level mutable globals | , ,  | R! |
| X24 | Multi-cat clamp → single DP |  | R!! |
| X25 | Matrix strings duplicated |  in scene_compiler and exterior_compiler | R! |
| X26 | Non-None defaults make theme-fallback DEAD |  | B!! |
| X27 |  called TWICE |  lines ~164 and ~194 | B! |
| X28 | Scale-table drifts from SCALE_BANDS |  | R!! |
| X29 |  not sanitised |  | R!! |
| X30 | Inconsistent argparse in CLI |  mid-function import | R!!! |

## Per-file findings (Round 3 — chosen across hunyuan / lighting / exterior / post-OOM proxy / ui / world / biome / hub / blender / scene_compiler re-audit)

### 
- **Purpose:** Unattended overnight batch; hardcoded 36 hero assets table.
- **B!**: None.
- **R!!**:  runs Blender subprocess (timeout=300). Corrupted  from race leaves Blender failing non-zero;  stderr truncation may miss root cause.
- **R!!**:  table is Python list of dicts. New category → code edit + re-deploy. Move to JSON/YAML.
- **R!**:  runs in-process; trimesh segfault bypasses try/except (hits Python interpreter itself). Docstring says "one-process-per-asset" but  in-process.
- **N**: Decent docstring.

### 
- **R!!**:  uses  cache hit — race-prone under concurrent writers.
- **R!!**:  "extra" field accepts arbitrary strings.  → poison cache.
- **R**:  silently skips malformed JSON. Quarantine dir missing.

### 
- **B!!**:  reads  unvalidated. Empty key →  (corruption).
- **R!!**:  catches broad Exception per job; if callback  reraises, WHOLE drain crashes mid-loop.
- **R!**:  module constant — should be env var.

### 
- **B!!**:  catches bare Exception — fails silently; mesh poly count exceeds downstream budget.
- **R!!**:  mutates passed mesh in-place AND returns it — ambiguous call contract.

### 
- **B!!**:  uses  —  parameter passing JSON payload; parameter naming misleading.
- **R!!**:  catches bare Exception → catches  → silent fallthrough to tier 0.

### 
- **B!!**:  block imports from  — circular potential on refactor.

### 
- **B!!**:   (30 min) too generous.
- **R!!**:  duplicated in . Single source missing.
- **R!**:  ignores palette-resolved material.

### 
- **R!!**:  comment says half-extent () but values are full extent. Build 5x5m cabin instead of 10x10m.
- **R!!**:  from 9 sample points may miss terrain corners.

### 
- **R!!**:  collapses multi-cat clamp failures into single Decision Point — losing per-category visibility.

### 
- **R!**:  shape duplicates biome_recipe; new flora needs update in 4 files.

### 
- **R!!**:  module-level mutable dict; mutable mid-process. Add .
- **R!!**:  imports random inside function — re-import each call.
- **R!!**:  emits  etc. — but  ignores these keys. **Dead semantics**.

###  (post-OOM-fix re-audit)
- **B!!**:  defined at line ~147 — **DEAD CODE**.
- **R!!**:  parameter accepted in  and immediately discarded ().
- **R!**:  for multi-geometry scenes;  silent about lost textures.
- **GOOD**: Incident 2026-06-23 safety bounds correctly added (, , ).

###  (full read — 2,535 lines)
- **B!! CRITICAL**: File ends with bare  — NO  guard. **Importing triggers the full procedural build path.** Fix immediately.
- **B!**:  writes  TWICE — first write wasted.
- **B!!**:  silently returns if both fcurve_ensure and fcurves.new fail — GLB exports WITHOUT idle animation.
- **B!!**:  sets global bpy state without isolation.
- **R!!**: 49 builder functions, NONE accept  parameter — vertex positions not seedable. Material offsets ARE seedable. Determinism gap.
- **N**: 49 similar-shape builders. Long-term refactor: table-driven by .

### 
- **R!!**:  raises bare KeyError — no diagnostic dump.
- **R!**: Module-level singleton races on multi-thread registration.

### 
- **B!!**: , , ,  module-level globals — race-prone.
- **R!!**:   (32-bit collision space — 1 min for 100 RPS).
- **R!!**:  daemon thread without lock on .
- **R!!**:  mode comment misleadingly says it skips LLM but actually calls full plan_fn.
- **R!**:  uses  — O(N). Use deque.

### 
- **R!!**:  total>=2 guard means 0/1 placements silent.
- **R!**:  linear iteration; cache palette set.

### 
- **R!!**:  frozen dataclass but  replaces in-place.
- **R!**:  string match against hardcoded set — no enum.

### 
- **R!!**:  writes without fsync — power loss can lose snapshot.

### 
- **R!!**: 32-bit seed mask drops high bits.  identical to .
- **R!!**: Oversample factor 4. If valid positions scarce, . Silent shortfall.

### 
- **R!!**:   no upper cap —  slow.

###  (re-audit fresh eyes)
- **B! (re-confirmed)**: Loop variable shadowing  (line ~1276).
- **B!! (re-confirmed)**:  defaults  ignore computed NPC positions. **NEW**:  receives  + computes via , but does NOT pass back to overlap pass.
- **B!! NEW**:  initialises  and  (non-None). Outdoor atmosphere  branches are **dead code**. Custom theme overrides silently overridden.
- **R!**:  cell-grid math off-by-one for n_lights=7 (cols=3, rows=3, only 7 of 9 filled; 2 cells with  coords silently dropped).
- **R!!**:  inner loop  — short-circuits; high-index overlaps low-index only moves high-index.

###  (re-confirm)
- **B! (re-confirmed)**:  called TWICE — lines ~164 and ~194. **Identical age.conflict DecisionPoints emitted twice** per ambiguous request.
- **R!!**: Comment at second call site copy-pasted from material comment — incorrect; second call purely accidental.

###  (re-confirm)
- **B!! (re-confirmed)**:  falls into  — . Silent fallback to asset_spec.gbnf.

###  (re-confirm)
- **R!!**:  writes tempfile; if  raises,  cleans temp but  (partial GLB) stays in .

###  (re-confirm)
- **R!**:  calls buggy  (= Round 2 B!!). Foot-gun.
- **R!!**: Hardcoded  default  — user-specific path.

###  (re-read)
- **B!!**:  hardcoded path. Read from env.
- **B!!**:  closed-set hash. New modules don't update BUILD_ID.
- **R!!**:  exact match — IPv6  rejected.

###  (re-read)
- **B!!**:  raises RuntimeError; if  raises (SSE overflow), rollback skipped.  needed.
- **R!!**:  JSONL write — disk full → swap fails reporting. Try/except + stderr fallback.

## Recommendations added (Round 3)

Top 5 prios (continuing from R1+R2):

1. **Add  to ** — single-line fix; importing from any test triggers the entire build pipeline. **Highest blast-radius for one line.**
2. **Fix  double call** — delete second duplicate.
3. **Fix  non-None default overrides** — change  and  to  so theme-fallback branches fire.
4. **Pass NPC positions into  from **.
5. **Validate 's  in ** — fail-fast.

**Total Round 3: 31 files, ~4,500 lines.**

---

## Grand totals (R1 + R2 + R3)

| Metric | R1 | R2 | R3 | Total |
|--------|---:|---:|---:|------:|
| Files audited | 47 | 42 | 31 | ~120 |
| Lines read | ~7,500 | ~9,000 | ~4,500 | ~21,000 |
| Cross-cutting patterns | 10 | 10 | 10 | 30 (X1–X30) |
| Per-file findings | ~80 | ~70 | ~50 | ~200 |

Round 3 redo netted 27 new findings, 20 re-confirmed prior findings, 10 new cross-cutting patterns (X21–X30). Focus surfaces: hunyuan / lighting / exterior / post-OOM proxy / ui / world / biome / hub — files touched by recent commits since Round 1.
