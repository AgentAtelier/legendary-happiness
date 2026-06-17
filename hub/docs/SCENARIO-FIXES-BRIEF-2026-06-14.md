# Scenario Score — Implementation Brief (raise 58% → high) (2026-06-14)

**Audience:** a fresh AI implementing the fixes. **Goal:** fix the 5 remaining scenario failures
on qwen3-14b so the suite moves well past its stable 58% baseline.

**Read first:** `hub/docs/AUDIT-BRIEF-2026-06-14.md` (full context + hard constraints). The
Main→Main2 corruption is ALREADY FIXED (§5d/5e) — do not re-touch root resolution. This brief is
ONLY about the remaining build-quality + editing-op failures, which are **separate** bugs.

## Hard constraints (unchanged)
- **Odysseus + godot-ai stay VANILLA.** All fixes here are DevForge-side
  (`devforge_review_package/devforge/...`). godot-ai `batch_execute` is **atomic** and cannot be
  changed — work WITH that, don't try to make it per-op.
- `stack.env`/`forge-model` single source of truth; hub loopback-only.
- Use **qwen3-14b** for build work (⚒Build mode). Verify with evidence — run the suite.

## How to run / verify
```bash
cd /home/mrg/dev/games/Forge/hub
# (ensure ⚒Build / qwen3-14b is loaded — see /api/mode; editor open on a scene)
.venv/bin/python -c "
import asyncio, scenarios
ids=[s.id for s in scenarios.SCENARIOS]
r=asyncio.run(scenarios.run_suite(ids, print))
print(r['summary'])"
# DevForge unit tests:
cd /home/mrg/dev/games/Forge/devforge_review_package && .venv/bin/python -m pytest devforge/tests/ -q
# After editing DevForge: systemctl --user restart forge-devforge   (loads the code)
```
Restart `forge-devforge` after ANY DevForge code change or the running server won't see it.

## Current state (qwen3-14b, stable): 58% (7/12), 0 errors
PASS: cube_create, sphere_create, camera_create, batch_three, property_edit, player_movement,
no_dup_camera. FAIL: light_create, script_attach, small_room, node_delete, node_rename.

---

## BUG 1 — invalid `set_property` ops cause ATOMIC ROLLBACK (fixes light_create, small_room, script_attach)

### Evidence (captured planner→executor ops, 2026-06-14)
`light_create` (prompt: *"Place a DirectionalLight3D called TestSun … light_energy 0.8"*):
```
add_node      TestSun  DirectionalLight3D  /root/Main     ← correct, the node IS planned
set_property  position
set_property  material_override            ← INVALID: DirectionalLight3D has no material_override
add_node      MainCamera Camera3D
```
`small_room` (30 ops) — `RoomLight` is a `DirectionalLight3D` yet gets:
```
set_property  material_override   ← invalid on a light
set_property  shape               ← invalid on a light
set_property  mesh                ← invalid on a light
```
Result: godot-ai `batch_execute` is **atomic** → one invalid op rolls back the ENTIRE batch →
**nothing builds** (scene ends as `['/Main']` + completeness scaffold). This is NOT planner
under-production — the requested nodes ARE planned; an invalid sibling op nukes them.

### Root cause
`devforge/compilation/validator/operation_validator.py` `_validate_set_property` (line 107-120)
validates ONLY that the node exists — it does **not** check that the property is valid for the
node's type. So `material_override`/`mesh`/`shape` on a light pass validation, reach the atomic
batch, and roll everything back.

### Fix (DevForge-side, two layers — do both)
1. **Property-vs-type validation** in `_validate_set_property`: drop a `set_property` op whose
   property is not valid for the target node's Godot type. Pull the node type from the live
   scene (`self.scene.find_by_path(node).type`) AND from add_node ops earlier in the same batch
   (nodes created this turn). Add a pragmatic property→allowed-types map, e.g.:
   ```
   material_override, material_overlay : MeshInstance3D, GeometryInstance3D, CSG*, Sprite3D
   mesh                                : MeshInstance3D
   shape                               : CollisionShape3D, CollisionShape2D
   light_energy, light_color, shadow_enabled : *Light3D (Directional/Omni/Spot)
   (anything not in the map → allow, to avoid over-blocking)
   ```
   Dropping an invalid op (rather than failing the build) means the valid ops still execute.
   There is a node-type knowledge module at `devforge/knowledge/scene/godot_node_types.py` —
   extend it with the property allowlist and reference it here.
2. **Stop emitting `material_override` on non-mesh nodes at the source.** Trace where the default
   material gets attached — `devforge/knowledge/scene/resource_templates.py:36-45` ("Material
   template … Default red material used as a scaffold fallback") and the completeness mesh-inject
   (`completeness.py:90-114`). Whatever injects a default material must gate on
   `node_type in {MeshInstance3D, GeometryInstance3D, …}`. (Layer 1 is the safety net; layer 2
   removes the cause.)

### Acceptance
- `light_create` PASS (`/Main/TestSun` exists as DirectionalLight3D).
- `small_room` PASS (all four walls + RoomLight built; the light has no mesh/shape/material).
- `script_attach` PASS (capture its ops first — likely the same invalid-prop rollback; if not,
  it's the script-attach path: confirm `attach_script` targets the just-created node).
- Add a DevForge unit test: a batch with one invalid `set_property` (material_override on
  DirectionalLight3D) → validator drops THAT op, keeps the rest.

---

## BUG 2 — "create then delete/rename" intent dropped (fixes node_delete, node_rename)

### Evidence (captured ops)
`node_delete` (prompt: *"Create a MeshInstance3D … called ToDelete …, then delete it."*):
```
add_node ToDelete MeshInstance3D ; set mesh ; set position ; attach_script ; MainCamera ; DirectionalLight
```
→ **No delete op at all.** ToDelete is created and never removed (+ a stray `attach_script`).

`node_rename` (prompt: *"… called OldName …, then rename it to NewName."*):
```
add_node OldName ; set mesh ; set position ; add_node NewName ; set mesh ; set position ; attach_script renamesystem.gd ; …
```
→ The planner creates a **second node** `NewName` instead of renaming `OldName` → `OldName`
persists, assertion `node_not_exists(/Main/OldName)` fails.

### Root cause
The deterministic markers `_remove` and `_rename` are **fully supported downstream** — the
arch compiler consumes them (`architecture_compiler.py:122 _rename`→`RenameNodeStep`,
`:130 _remove`→`RemoveNodeStep`) and the operation validator validates them
(`operation_validator.py:_validate_remove_node:63`, `_validate_rename_node:77`). The PLANNER
just never emits them — it treats "delete/rename" as "create another node."

### Fix (DevForge-side)
Make the planner produce `_remove` / `_rename` markers for delete/rename intents. Two options
(prefer the deterministic pre-pass — robust, no model dependence):
1. **Deterministic intent pre-pass** (recommended): before/after architecture planning, scan the
   prompt for patterns like *"delete/remove <Name>"* and *"rename <Old> to <New>"* and inject
   `delta["_remove"] = {"target": Name}` / `delta["_rename"] = {"from": Old, "to": New}`. Wire it
   in `engine._run_arch_path` (after `self._planner.plan(...)`, near the dedup at engine.py:650+).
   This is the same "deterministic marker" philosophy already used elsewhere.
2. **Planner-prompt/grammar** (`devforge/reasoning/architecture_planner.py` + its GBNF): teach the
   planner that "rename/delete" → emit `_rename`/`_remove`, not a new `add_node`. Higher variance
   (LLM-dependent); only do this in addition to (1) if needed.

Also drop the spurious `attach_script` the planner adds to these simple prompts (it's inventing a
"system"). If T2 `infer_systems` is over-firing on "delete/rename" prompts, gate it so a pure
create-then-edit prompt doesn't get a script.

### Acceptance
- `node_delete` PASS (`/Main/ToDelete` does NOT exist after the build).
- `node_rename` PASS (`/Main/NewName` exists, `/Main/OldName` does not).
- DevForge unit test: a delta from a "rename X to Y" / "delete X" prompt contains the
  `_rename`/`_remove` marker (not a duplicate add_node).

---

## ISSUE 3 — per-scenario isolation tradeoff (test-harness, hub-side)

`hub/scenarios.py` `run_suite` currently does a suite-start probe reset + per-scenario cleanup
(the Round-2 per-scenario `_probe_scene_reset()` was REVERTED — it left bare scenes via the no-op
`scene_open`). Consequence: completeness-injected `MainCamera`/`DirectionalLight` ACCUMULATE
across the suite, which can make the planner skip a same-category node in a later scenario.
**Proper fix:** a per-scenario reset that genuinely reloads the probe baseline between scenarios
WITHOUT the no-op-`scene_open` limitation — e.g. explicitly delete ALL non-root children (incl.
accumulated MainCamera/DirectionalLight) and re-add the baseline, or force a real disk reload.
Validate via the suite (must not regress the bare-scene failures). This is hub code, not DevForge.

---

## Suggested order & overall acceptance
1. Bug 1 (covers 3 scenarios, single highest-leverage) → re-run suite.
2. Bug 2 (covers 2 scenarios) → re-run suite.
3. Issue 3 (isolation) → re-run suite, confirm no accumulation regressions.

**Overall acceptance:** full scenario suite on qwen3-14b ≥ ~90% (ideally 12/12) with 0 errors and
every node under the real `/Main` root; DevForge `pytest devforge/tests/` green (add the 3 unit
tests above); `main.tscn` never touched (runs stay in `res://probe.tscn`).

## Pointers (verified file:line, 2026-06-14)
- `compilation/validator/operation_validator.py:107` — `_validate_set_property` (Bug 1 layer 1).
- `compilation/pipeline/completeness.py:90-114` + `knowledge/scene/resource_templates.py:36-45` —
  default-material/mesh injection (Bug 1 layer 2).
- `knowledge/scene/godot_node_types.py` — node-type knowledge to extend with the property allowlist.
- `compilation/pipeline/architecture_compiler.py:122,130` — `_rename`/`_remove` consumers (already work).
- `compilation/pipeline/engine.py:650+` (`_run_arch_path`) — where to add the deterministic
  delete/rename intent pre-pass (Bug 2 option 1).
- `reasoning/architecture_planner.py` (+ its GBNF) — planner prompt (Bug 2 option 2 / drop stray script).
- Capture any scenario's real ops with: `_devforge_call('apply_spec',{'prompt':...})` →
  `read_artifact` → `operations` (see how this brief's evidence was gathered).
