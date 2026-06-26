# Forge — Prompt Queue (2026-06-26)

**Purpose:** self-contained prompts for implementing the planned work while orchestrator (Opus)
is unavailable. Written so a cold CLI agent (DeepSeek V4 Pro or equivalent) can pick up any
section and make real progress without needing a live design conversation.

**Read first (every session):**
- `AGENTS.md` — always-on rules (gates, delegation model, lint, testing split)
- `docs/current/PROJECT-STATE.md` — live status + gotchas
- `docs/current/WORLD-ENGINE.md` — current north star and build order

**Gate command (fast, stack-free):**
```bash
cd foundry && .venv/bin/python -m pytest -m "not blender and not godot_heavy and not live" -q
```
**Full suite (required at end of every bundle):**
```bash
cd foundry && .venv/bin/python -m pytest tests/ -q
cd foundry && .venv/bin/python -m pytest tests/test_godot_smoke.py -q
```

---

## STANDING HEADER — paste at the top of every session

> Read `AGENTS.md` and `docs/current/PROJECT-STATE.md` first — these are the always-on
> rules and live status. **Dedicated worktree (preferred):** `git worktree add
> ../forge-wip -b feat/<short-name>`. VERIFY-FIRST: before writing code, grep/read
> the actual files mentioned. TDD red→green. Run the FULL suite at the end — paste
> the literal total line. Ruff gate: `cd foundry && .venv/bin/ruff check .` must exit 0.
> After any change under `foundry/godot_template/` or `scene_compiler.py`: scaffold a
> build, `godot --headless --path <build> --quit`, grep stderr for
> `SCRIPT ERROR|Parse Error|Failed to load` = 0. Never mutate the real
> `asset_lexicon.json` in tests. Never touch `addons/godot_ai`.

---

# SECTION 1 — IMMEDIATE: commit the in-progress work on `feat/exterior-and-props`

**Context:** The branch `feat/exterior-and-props` has ~584 lines of uncommitted changes across
`foundry/blender/`, `foundry/placement.py`, `foundry/scaffold.py`, `foundry/scene_compiler.py`,
`foundry/sidecar.py`, `foundry/world/compose.py`, four test files, and three new PNG texture
assets (shell_roof/wall rename). Four untracked new files are also present:
`foundry/manifest_to_world.py`, `foundry/tests/test_manifest_to_world.py`,
`foundry/tests/test_world_compose_build.py`, `foundry/tests/test_world_integration.py`.

These are the World Engine unit 3 e2e (build_world_tscn parent-scene kernel + portal-opening
geometry) and unit 5 (manifest→world bridge). They appear to be nearly complete based on the
commit messages; the task is to verify gates pass and commit cleanly.

## PROMPT 1-A · Commit the current in-progress World Engine work

> You are on branch `feat/exterior-and-props`. There are uncommitted changes and untracked
> files that implement World Engine unit 3 e2e (compose_world orchestration, build_world_tscn,
> portal-opening geometry) and unit 5 (manifest_to_world bridge). Your job:
>
> 1. **VERIFY:** Run `cd foundry && .venv/bin/python -m pytest -m "not blender and not
>    godot_heavy and not live" -q`. All tests must pass. If any fail, fix them before committing
>    (do NOT skip failing tests or loosen assertions — diagnose and fix the root cause).
> 2. Run `cd foundry && .venv/bin/ruff check .` — fix any lint violations.
> 3. Review the four untracked files (`manifest_to_world.py` + the three test files) plus the
>    diffs in `world/compose.py`, `scene_compiler.py`, `placement.py`, `scaffold.py`,
>    `sidecar.py`, and the blender scripts. Understand what each piece does before committing.
> 4. Stage and commit in logical units (at minimum: one commit for shell texture renames +
>    material fixes, one for compose_world/build_world_tscn, one for manifest_to_world bridge).
>    Use `feat(world):` / `fix(shell):` prefixes per the existing commit style.
> 5. Run the FULL suite (`pytest tests/ -q` AND `pytest tests/test_godot_smoke.py -q`) and
>    paste the literal total lines in your report.
> 6. Update `docs/current/WORLD-ENGINE.md` §7 to mark any newly completed units as ✅ and
>    update the "what remains" sentence.

---

# SECTION 2 — WORLD ENGINE sub-project (a): remaining pieces

**Context:** The pure-Python machinery of sub-project (a) is complete (units 1–4 done, 151+
world tests green). Unit 3 e2e (Godot+assets) and unit 1.5 (human-patch CLI) remain.
`WORLD-ENGINE.md` §7 is the authoritative status tracker. The goal of (a) is: a human writes
JSON-patch operations → the engine assembles a deterministic Godot scene → the validation gate
rejects impossible patches. NO LLM yet.

## PROMPT 2-A · Unit 1.5 — human-patch CLI (`forge world`)

> **Verify first:** grep `foundry/` for `"forge world"` and `"world apply"` — the CLI may
> already be partially wired. Read `foundry/__main__.py` (or the entry-point for `forge`
> commands) to understand how existing subcommands are registered.
>
> Implement `forge world apply <world_file> <patch_file>` — a CLI command that:
> - Loads a world from `<world_file>` (JSON, via `world.persistence.load_world`).
> - Reads one or more JSON-patch operations from `<patch_file>` (a JSON array of ops).
> - Applies each op via `world.validation.apply_op_checked` (which runs the W3 AABB gate).
> - On success: saves the updated world back to `<world_file>` and prints a one-line summary
>   ("Applied N ops. Spaces: X. Portals: Y.").
> - On `WorldValidationError`: prints the structured violation to stderr and exits non-zero —
>   do NOT silently skip the error; surface it so a human or LLM can correct the patch.
>
> Also add `forge world show <world_file>` — prints `world.query.world_index(world)` as
> formatted JSON (compact LLM-consumable map of the current world state).
>
> TDD: write tests in `foundry/tests/test_world_cli.py` covering: apply happy path, apply with
> overlap rejection, apply with unknown op (should raise cleanly), `show` output is valid JSON.
>
> Godot gate: n/a (pure Python). Run full suite + lint at end. Paste totals.

## PROMPT 2-B · Unit 3 e2e — full Godot-in-the-loop build of a 2-space world

> **Context:** `world/compose.py::compose_world` assembles a multi-space world into a parent
> Godot scene (`world.tscn` that instances per-space `.tscn` files). The unit tests mock
> Blender/Godot. This prompt proves it works for real.
>
> **This task is ORCHESTRATOR-OWNED for the Godot/Blender verification step.** What you
> (CLI agent) must deliver:
>
> 1. A runnable build script at `scripts/build_world_test.sh` (or a `forge world build`
>    subcommand) that:
>    - Creates a minimal 2-space world via `forge world apply` (a hall + a courtyard connected
>      by a portal, each 8×4×8 m).
>    - Calls `compose_world(world, build_dir, ...)` to assemble the Godot project.
>    - Runs `godot --headless --path <build_dir> --quit` and greps stderr for 0 SCRIPT ERRORs.
> 2. A test stub `foundry/tests/test_world_e2e.py` marked `@pytest.mark.godot_heavy` that
>    asserts the script exits 0 and the stderr grep passes. (Mark it `godot_heavy` — the
>    orchestrator runs it live; the CLI gate skips it.)
> 3. Ensure `compose_world` properly handles the case where a space has no entities yet
>    (empty manifest → shell-only room). The shell should still generate and load clean.
>
> After delivering this, **flag in your report:** "ORCH: run `scripts/build_world_test.sh`
> and visually confirm `world.tscn` loads in real Godot with 2 rooms accessible."
>
> Run full suite (fast gate) + lint. Paste totals.

---

# SECTION 3 — WORLD ENGINE sub-project (b): NL → patch

**Context:** Sub-project (a) proves the machinery with HUMAN-authored patches. Sub-project (b)
plugs the LLM in as the patch generator. It adds W2 semantic grounding — a `query_world` tool
the LLM can call to resolve references ("the throne near the window") before proposing an edit.
Design is in `WORLD-ENGINE.md` §5 (W2) and §6.

## PROMPT 3-A · Design-first spec for sub-project (b)
> ✅ **DONE** — landed on Forge `feat/exterior-and-props` commit `bf06ccd`<br>> (`docs(world-engine): sub-project (b) NL->patch spec`).  Pure spec, no code per queue.<br>> Lands at `docs/current/WORLD-ENGINE-B-SPEC.md` (~470 lines): 6 sections per queue<br>> NL→patch loop · `query_world` tool · `WorldInterpreter` extension · W2 entity-ID grounding<br>> · module boundaries (no addons/godot_ai, no scene_compiler / interpreter / behaviour_gen edits)<br>> · test strategy (6 MockLLM-stubbed unit tests + 1 `@pytest.mark.live` integration).<br>> Closed with a 6-task TDD-red→green impl plan; ready for PROMPT 3-B (implementation) on review.

> **This is a spec-writing task, not an implementation task.** Read `WORLD-ENGINE.md` §4–6
> and `foundry/world/query.py` (the existing W2 query layer). Write a spec document at
> `docs/current/WORLD-ENGINE-B-SPEC.md` covering:
>
> 1. **The NL→patch loop:** how a natural-language edit ("add a courtyard to the north",
>    "make the hall darker") becomes a JSON-patch op. Include the prompt template the LLM
>    receives (world_index + available ops vocabulary + the user's NL request) and the
>    output format (JSON array of ops).
> 2. **The `query_world` tool:** how the LLM can ask "what's north of hall?" before
>    generating a patch. Map this onto `world.query.direction` / `world.query.find_entities`.
>    Define the tool call signature and response format.
> 3. **The interpreter extension:** how the existing `Interpreter` (or a new
>    `WorldInterpreter`) calls the LLM with the world context, validates the returned ops
>    via `apply_op_checked`, and falls back with a Decision Point on `WorldValidationError`.
> 4. **W2 entity ID grounding:** the strategy for resolving "the throne" → `throne_001` (use
>    the stable entity IDs in the Brief / Read-State written after generation).
> 5. **Module boundaries:** new files to create (e.g., `foundry/world/interpreter.py`) and
>    what they import. Nothing touches `addons/godot_ai`.
> 6. **Test strategy:** unit tests with stub LLM; live test flagged for orchestrator.
>
> End the spec with a numbered task list (≤6 tasks) so the implementation can be delegated.
> Do NOT write any implementation code in this task.

## PROMPT 3-B · Implement the NL → patch interpreter (after 3-A is reviewed)

> Read `docs/current/WORLD-ENGINE-B-SPEC.md` (written and reviewed in 3-A). Implement it
> TDD, one task at a time. Create `foundry/world/interpreter.py` and extend the `forge world`
> CLI with `forge world edit <world_file> "<NL prompt>"`.
>
> Standing rules from AGENTS.md apply. Structured LLM output via `json_schema`, never
> `grammar=None`. After each task: fast gate green. After all tasks: full suite + smoke + lint,
> paste totals. Flag for orchestrator: "ORCH: live run `forge world edit world.json 'add a
> dark crypt to the south'` against the running LLM stack and confirm the patch is valid and
> the resulting scene loads in Godot."

---

# SECTION 4 — WORLD ENGINE sub-project (c): Cohesion Contract

**Context:** The Cohesion Contract is the W4 defense — enforcing style/scale/connectivity
coherence as hard mechanical constraints, not prompt text. Spec:
`docs/superpowers/specs/2026-06-24-cohesion-contract-design.md`.

## PROMPT 4-A · Implement the Cohesion Contract validator suite

> Read `docs/superpowers/specs/2026-06-24-cohesion-contract-design.md` in full.
> Read `foundry/world/validation.py` (existing W3 AABB gate).
>
> Extend the validation layer with the Cohesion Contract. Implement as a new module
> `foundry/world/cohesion.py`. It must enforce (at minimum, per the spec):
> - **Palette lock:** every space's material references must be within the World Bible's
>   locked palette. Violations → `Violation(rule="palette_violation", ...)`.
> - **Scale constraints:** space dimensions and entity sizes within defined bands.
> - **Connectivity:** no orphan spaces (every space must be reachable from the root via portals).
> - **Throne-room invariant** (example): a space tagged `theme: throne_room` must contain
>   ≥1 entity of type `throne`. Generalize this into a configurable "required contents" rule.
>
> `validate_cohesion(world, bible) -> list[Violation]` is the public API. A `WorldBible`
> dataclass (palette, scale_bands, required_contents) is loaded from a JSON file alongside
> the world file. Implement `apply_op_checked_with_cohesion` that wraps the existing gate
> and adds the cohesion check after each op.
>
> TDD: tests in `foundry/tests/test_cohesion.py`. Full suite + lint at end. Paste totals.
>
> Flag for orchestrator: "ORCH: build a 3-space world that violates the palette constraint
> and confirm the gate rejects it with a clear human-readable error."

---

# SECTION 5 — REMAINING M1 ITEMS

These are the three open M1 items from `ROADMAP.md` that were not blocking the epoch shift.

## PROMPT 5-A · M1.2.2 — batch Blender spawns (orchestrator-owned design, CLI implements)

> **Verify first:** read `foundry/blender/build_asset.py` and grep for `subprocess` calls
> to understand the current one-Blender-per-asset pattern. Read `ROADMAP.md` §Phase 2 item
> 2.2 for the design intent. Check `ACCEPTED.md` to confirm 2.2 is not already landed.
>
> The goal: replace ~31 individual Blender subprocess spawns (one per asset) with a single
> Blender invocation per build batch, dramatically cutting per-build latency.
>
> **Design note (orchestrator-supplied):** run Blender with `--background --python
> foundry/blender/build_batch.py` and pass the asset list via stdin or a temp JSON file.
> `build_batch.py` loops over the asset specs inside one Blender process, writing GLBs.
> The existing `build_asset.py` function becomes a fallback for single-asset calls (tests,
> dev). Determinism must be preserved: byte-identical output for identical specs.
>
> Implement TDD. The Blender tests are marked `@pytest.mark.blender` — keep them. The fast
> gate skips them; the full suite runs them (orchestrator verifies the real bakes).
> After implementation: run full suite (not just fast gate). Paste totals.
>
> Flag for orchestrator: "ORCH: verify bake output is byte-identical between single and batch
> modes for 3 assets (wood table, granite shelf, iron lantern)."

## PROMPT 5-B · M1.0.5b — headless interaction ray-aim (`godot_heavy` fix)

> **Context:** 3 tests are marked `@pytest.mark.godot_heavy` and skipped in the fast gate.
> They test `interact_under_crosshair()` in `interaction.gd` but fail headless because the
> camera ray misses the prop collider (likely player self-hit or aim-at-base misses the
> collider). `ROADMAP.md` §0.5b describes the fix: `query.exclude=[player_rid]` + aim at
> collider centre. These 3 tests should become green headless.
>
> Read `foundry/godot_template/scripts/interaction.gd` and the 3 failing test stubs
> (find them: `grep -r godot_heavy foundry/tests/`). Fix the raycast in `interaction.gd`:
> exclude the player's own RID, aim at the centroid of the prop's AABB (not its origin).
> Verify the 3 tests pass with `godot --headless`.
>
> After the fix: run `cd foundry && .venv/bin/python -m pytest tests/test_godot_smoke.py
> tests/test_godot_heavy.py -q` (or whichever file holds the 3 tests). They must be green.
> Full suite + lint. Paste totals.
>
> If after investigation the fix is more complex than the 1-line estimate, document exactly
> what the blocker is and leave the tests marked `godot_heavy` — do NOT loosen or delete them.

---

# SECTION 6 — MATURITY LEAP: easy wins

From `MATURITY-LEAP-BACKLOG.md` §1 (Visuals) and §2 (Worldbuilding). These are independent
of the World Engine and can be done any time.

## PROMPT 6-A · Enable SDFGI + per-instance material variation (EASY visual leap)
> 🟡 **IN-PROGRESS** — SDFGI half ✅ DONE on Forge `feat/exterior-and-props` commit `2a1be8d`<br>> (`feat(scene): PROMPT 6-A.A -- bake SDFGI into WorldEnvironment`).<br>> 2 module-level constants in `foundry/scene_compiler.py`: `_SDFGI_MIN_CELL_SIZE=0.2`, `_SDFGI_CASCADE0_DISTANCE=12.0`.<br>> 4 properties baked into Environment sub_resource between glow + fog blocks:<br>> `sdfgi_enabled`, `sdfgi_use_occlusion`, `sdfgi_min_cell_size`, `sdfgi_cascade0_distance`.<br>> Tests: helper `_forge_environment_block` + 3 tests (enabled + tuning + use_occlusion);<br>> full `pytest tests/` 1764 passed, ruff exit 0.  Forward+ renderer already configured in `project.godot`<br>> (`config/features=PackedStringArray("4.7", "Forward Plus")`); day_night.gd now writes-to-same-value<br>> at runtime (`sdfgi_bounce_feedback` still modulated for the day/night cycle).<br>> <br>> ⏳ **NEXT** — per-instance HSV material variation in `foundry/blender/build_asset.py`<br>> (`@pytest.mark.blender` tests).  Seed derivation: `jitter_seed = hash(entity_id + material_name)`<br>> → HSV jitter (deterministic for a fixed seed + name; varies across different entity_ids).<br>> Being picked up in the next cycle.

> **Verify first:** grep `scene_compiler.py` and `lighting_resolve.py` for `sdfgi` and
> `WorldEnvironment`. Check if SDFGI is already wired. Check `MATURITY-LEAP-BACKLOG.md`
> §1 EASY items to confirm this is still open.
>
> Two independent improvements (implement together, commit separately):
>
> **A. SDFGI toggle:** In `scene_compiler.py` / `lighting_resolve.py`, enable SDFGI in the
> generated `WorldEnvironment` node (`Environment.sdfgi_enabled = true`, with
> `sdfgi_min_cell_size` and `sdfgi_max_distance` tuned for interior room scale ~4–12 m).
> This is a one-toggle cheap win for bounce lighting. Verify headless-loads clean
> (no parse errors). Flag for orchestrator: "ORCH: eyeball a room with SDFGI — confirm
> bounce light is visible and no performance regression."
>
> **B. Per-instance seeded material variation:** In `build_asset.py`, after baking the base
> material, apply a seed-driven per-instance HSV micro-jitter (hue ±5°, saturation ±10%,
> value ±8%) so two chairs of the same material look slightly different. The jitter seed =
> `hash(entity_id + material_name)`. Add an eval signal `"material_per_instance_variation"`
> that confirms adjacent same-material props differ by ≥ε in hue.
>
> TDD for the seed-jitter. Blender tests marked `@pytest.mark.blender`. Full suite + lint.
> Paste totals.

## PROMPT 6-B · More material families + more theme table entries (EASY content leap)

> **Verify first:** read `foundry/room_control.py` (`THEME_TABLE` + `SHELL_THEME_INDEX`).
> Read `docs/current/MATURITY-LEAP-BACKLOG.md` §1 EASY and §2 EASY. Check `shell_materials.py`
> and `materials.py` for existing families. Confirm which items below are not already present.
>
> **A. New material families** (add to `materials.py` and emit via `shell_materials.py` where
> appropriate): `ceramic` (matte, slight sheen, cool tones), `leather` (dark warm, slight
> specular, seam bump), `painted_wood` (wood grain with a painted color overlay using HSV
> tint). Each new family: base params + `_build_*_material_nodes` function + lexicon envelope
> entry + test coverage. Add fabric (`linen`/`wool`) to the `tavern` and `study` theme palettes
> (T-3 ticket fix from `BACKLOG-PROMPTS-READY.md`).
>
> **B. New theme table entries:** add to `THEME_TABLE` in `room_control.py`:
> `crypt` (stone/bone, dense, urns/pillars/sarcophagi), `armory` (metal bias, weapon-racks/
> shields/chests), `workshop` (mixed wood/metal, bench/anvil/barrel), `kitchen` (ceramic/
> wood, pots/shelves/fireplace). Per entry: required props, allowed_palette, density_band,
> must_include. Use existing generators only (verify with `category_registry` what's available).
>
> Eval signal: "theme_content_matches_table" — for each theme, assert required props appear
> in generated rooms. TDD. Full suite + lint. Paste totals.

---

# SECTION 7 — V VISUAL EVAL HARDENING (CB-8)

From `docs/current/CLI-FULL-BACKLOG-PROMPTS.md` §CB-8.

## PROMPT 7-A · Fix the V harness capture issues

> **Verify first:** read `foundry/visual/` — find `capture.tscn`, `vlm.py`, `aesthetic.py`.
> Read `CLI-FULL-BACKLOG-PROMPTS.md` §CB-8 in full. Check the open items listed there.
>
> Fix the following V harness issues (implement in order, commit each):
>
> **1. Camera fits to prop AABB:** `book_worn_oak` renders blank because the turntable
> camera is at a fixed radius that misses small props. Fix the capture harness to compute
> the prop's AABB from its GLB and set the camera distance to `max_dimension * 2.0`.
>
> **2. Raise import/capture timeout:** `humanoid_rough_granite` + `key_worn_oak` fail with
> Godot subprocess timeout under load. Raise the timeout from the current value to 120 s.
>
> **3. Player-eye scene framing:** the orbit-at-radius-8 for full-scene capture sees through
> walls. Replace with a player-eye framing: camera at the player spawn position, looking at
> the scene centroid.
>
> **4. Document the CLIP aesthetic head situation** (no code change needed): add a comment
> in `aesthetic.py` explaining that `_AestheticHead` is currently disabled (weights mismatch)
> and what is needed to re-enable it (LAION-V2 MLP + ViT-L/14 public weights). Do NOT
> attempt to fix this without the orchestrator — it requires a model swap.
>
> **5. EB-6 examine wiring:** verify `examine_validator.py` + the `examine` verb in
> `interaction.gd` are wired end-to-end (grep for `examine` in both). If the wiring is
> already live, confirm with a test; if not, wire it — `examine` on a prop calls the LLM
> for flavor text and displays it in the HUD.
>
> TDD where testable. Full suite + lint. Paste totals.
> Flag for orchestrator: "ORCH: run `python -m foundry visual-eval` against the prop
> catalog after Qwen3-VL + mmproj are serving. CB-8 is the pre-condition."

---

# SECTION 8 — AUDIT / MAINTENANCE PROMPTS

Use these to keep the project healthy without a live orchestrator. Run them whenever you've
done a large batch of work, or when something smells wrong.

## AUDIT-A · Full gate green check

> Run the complete test suite and report honestly. No subsets. No skipping.
>
> ```bash
> cd foundry
> .venv/bin/ruff check .
> .venv/bin/python -m pytest tests/ -q
> .venv/bin/python -m pytest tests/test_godot_smoke.py -q
> ```
>
> For every failure: identify root cause. If a test is failing because the feature it tests
> is genuinely broken, fix it. If a test is a false positive (testing something that no
> longer exists), remove the test ONLY after confirming the feature was intentionally removed
> — document the removal in `docs/current/ACCEPTED.md`. Do NOT comment out or skip tests
> to make the count green.
>
> Paste the literal final line of each command in your report. If the total is lower than the
> last known total (which was ~1400+ on the fast gate), investigate before proceeding.

## AUDIT-B · Architecture drift check

> Read `docs/current/AUDIT-00-SYNTHESIS.md` (the 5-round audit synthesis). For each root
> pattern listed there, grep the current tree to verify the fix was applied and has not
> regressed. Specifically check:
>
> 1. **Single source of truth for categories:** `foundry/category_registry.py` (or wherever
>    it landed) — confirm grammar, compiler, lexicon, blender builders, room_layout all
>    derive from it and there are no hardcoded category lists elsewhere.
> 2. **`json_schema` everywhere:** grep `grammar=None` in `foundry/` — should be zero hits.
>    Every LLM call must use `json_schema=` or `grammar=""` (free-form only).
> 3. **No silent fallbacks:** grep `except` blocks in the generation pipeline — confirm every
>    catch emits a Decision Point before falling back.
> 4. **No print() in library code:** grep `print(` in `foundry/` (not tests) — all must be
>    `logging.*` since the 0.9b conversion.
> 5. **Determinism:** run the same build twice with the same seed and confirm output is
>    byte-identical (compare GLB file hashes).
>
> Report any regressions as new tickets in `docs/current/BACKLOG.md` (add to the existing
> open items, don't overwrite).

## AUDIT-C · Godot template health check

> After any session that touched `foundry/godot_template/` scripts, run this audit:
>
> 1. Scaffold a fresh build: `cd foundry && .venv/bin/python -m forge quest
>    --prompt "a blacksmith's forge" --model stub 2>&1 | tail -5` (use a stub model to avoid
>    LLM dependency). Note the build path.
> 2. Load headless: `godot --headless --path <build_path> --quit 2>&1 | grep -E
>    "SCRIPT ERROR|Parse Error|Failed to load"`. Expect 0 matches.
> 3. Check for regressions in `test_godot_smoke.py`: `cd foundry && .venv/bin/python -m
>    pytest tests/test_godot_smoke.py -v`. All smoke tests must be green.
>
> If any GDScript error appears: read the referenced script line directly (grep for the
> function name or line content) and fix the parse error. Do NOT regenerate the template
> file from scratch — make a targeted edit.

## AUDIT-D · World Engine consistency check

> After any session that touched `foundry/world/`:
>
> 1. Run world-specific tests: `cd foundry && .venv/bin/python -m pytest tests/ -k world -v`
>    — all 151+ world tests must pass.
> 2. Verify the hashing invariant: two identical op sequences produce the same world hash.
>    (There is a test for this — confirm it is not accidentally skipped.)
> 3. Check round-trip: `save_world(load_world(path))` produces an identical JSON file.
> 4. Verify `apply_op_checked` rejects: overlapping spaces (W3), portals between nonexistent
>    spaces, entities placed outside their space's footprint. Each must raise
>    `WorldValidationError`, not return silently.
>
> Any breakage here is a P0 fix — the World Engine machinery being flawed undermines every
> upstream feature.

## AUDIT-E · Documentation freshness check

> Check that the key doc files reflect actual code state (not aspirational state):
>
> 1. Open `docs/current/PROJECT-STATE.md` and `docs/current/WORLD-ENGINE.md` §7.
>    For each unit marked ✅, verify the code actually exists and its tests pass.
>    For each unit marked as "not started," verify there is no partial implementation.
> 2. Open `docs/current/CAPABILITIES.md`. Pick 5 listed capabilities at random.
>    For each: find the implementation in `foundry/` and confirm it matches the description.
>    If a capability is listed but the code is missing or broken, add a ⚠ annotation.
> 3. Open `docs/current/BACKLOG-PROMPTS-READY.md` and `CLI-FULL-BACKLOG-PROMPTS.md`.
>    Items marked ✅ DONE — verify the implementing commit exists in `git log --oneline`.
>    Items NOT marked done — verify they haven't been silently implemented without the
>    doc being updated.
>
> Do not rewrite the docs — just add ⚠ markers where you find drift, so the orchestrator
> can reconcile them in the next live session.

---

# SECTION 9 — MEDIUM-TERM: Maturity Leap (after World Engine (a)+(b) are stable)

These are significant scope expansions from `MATURITY-LEAP-BACKLOG.md`. Do NOT start these
until World Engine (a) (machinery) and (b) (NL→patch) are verified working in real Godot.

## PROMPT 9-A · MEDIUM: second-gen geometry (composable Blender ops)

> **Context:** `MATURITY-LEAP-BACKLOG.md` §1 MEDIUM. The 37 fixed generators are all
> box-primitive (no bevel/boolean/array/greeble). This prompt extends them with composable
> ops.
>
> **Design-first:** before touching code, write a spec at `docs/current/GEOMETRY-OPS-SPEC.md`
> covering: (a) which Blender operations to expose (bevel, solidify, array, basic greeble/
> surface-detail); (b) how they compose (a generator can request a list of ops; the Blender
> script applies them in order); (c) the `json_schema` that lets the LLM request ops vs. the
> deterministic fallback; (d) backward compatibility (existing generators unaffected).
> Get the spec reviewed before implementing. Implementation: one op at a time, TDD, one
> commit per op. After each: fast gate green. After all: full suite + visual flag for
> orchestrator.

## PROMPT 9-B · HARD (research): procedural character + rig

> **Context:** `MATURITY-LEAP-BACKLOG.md` §1 HARD. This is the single biggest anti-slop move
> but also the riskiest. Do NOT start until second-gen geometry (9-A) is shipped and verified.
>
> **Design-first:** write a spec at `docs/current/CHARACTER-RIG-SPEC.md` covering the
> pure-generative approach: parametric humanoid mesh (box/cylinder primitives, seeded size
> parameters for height/build/proportions) → procedural `Skeleton3D` (joint positions
> derived from mesh dimensions) → skinning weights (proximity-based) → a small procedural
> animation set (idle bob, walk cycle via sinusoidal joint offsets — no authored keyframes).
> The spec must include an explicit off-ramp: if procedural skinning proves intractable in
> the available time, document the wall and fall back to a rigged GLB from a known-good
> simple base mesh. Get spec reviewed. Implementation is a multi-week effort; the spec is
> the deliverable for this prompt.

---

# SECTION 10 — UX / FORGE HUB REDESIGN (parked, do last)

**Context:** Parked in `FUTURELOG.md`. Needs the World Engine working first (the hub is the
shell over the world-editor experience). Approach notes are in `FUTURELOG.md` — read them
before starting. This is a design-first thread, NOT an engineering-survey thread.

## PROMPT 10-A · UX research brief + Claude-design handoff

> Read `docs/current/FUTURELOG.md` §"UX / Forge Hub redesign — approach notes." This is NOT
> an engineering survey. Do NOT fan out to multiple AIs for opinions.
>
> Deliverable: a UX brief document at `docs/current/UX-BRIEF.md` covering:
> 1. **Who the user is** (the maker/creator, 7-beat journey from FUTURELOG.md).
> 2. **Anti-slop constraints** (what must NOT look like "typical AI tool UI").
> 3. **Reference products to study** (name 3–5 tools that nail "creative builder" UX — e.g.
>    Notion, Miro, Figma, Linear — and extract ONE principle each that applies here).
> 4. **Information architecture** (world map / prompt bar / preview / library — rough
>    content inventory for each panel).
> 5. **Open design decisions** for the Claude-web mockup session (color palette approach,
>    typography direction, interaction patterns to prototype first).
>
> This brief feeds the Claude-web design feature for actual mockups. Do not implement any
> code. Do not write an HTML prototype. The brief IS the deliverable.

---

# VERIFICATION CHECKLIST — before claiming any section done

Copy and paste this into your session report when you finish a section:

```
[ ] Fast gate green: `pytest -m "not blender and not godot_heavy and not live" -q` → __ passed
[ ] Full suite green: `pytest tests/ -q` → __ passed
[ ] Godot smoke green: `pytest tests/test_godot_smoke.py -q` → __ passed
[ ] Ruff exit 0: `ruff check .` → 0 violations
[ ] VERIFY-FIRST done: read the actual files before writing code
[ ] No silent fallbacks added without a Decision Point
[ ] No `grammar=None` added
[ ] `asset_lexicon.json` not mutated in tests
[ ] Docs updated (WORLD-ENGINE.md §7 or PROJECT-STATE.md) if a unit is complete
[ ] ORCH flags listed (what needs live/visual/Blender verification)
```

---

*Authored 2026-06-26 by the orchestrator (Opus) as a low-context-budget handoff.*
*When resuming with the orchestrator: share the report from whichever section was last
completed, and the orchestrator will handle ORCH-flagged verification steps.*
