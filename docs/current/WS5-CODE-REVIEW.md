# WS-5 Stability & Robustness Code Review

**Date:** 2026-06-23
**Scope:** `foundry/proxy.py`, `foundry/__main__.py` (visual-eval changes), `foundry/visual/batch.py` (reroll_flagged), `foundry/tests/test_proxy.py`, `foundry/tests/test_ws5_reroll.py`
**Methodology:** Deep review via Gemini thinker agent per file, focusing on crash safety, determinism, edge cases, resource safety, and test quality.

---

## r1: `foundry/proxy.py` — Core Voxelization Logic

### 🔴 Critical Bugs

**1. Anisotropic grid — voxels are not cubic**
`voxel_size` is derived from the max axis only, but `np.linspace(bbox_lo[dim] + voxel_size/2, ..., resolution)` runs per-axis across the full local extent of each dimension. For non-cube meshes (e.g. a flat table, 2×1×0.3 m), the grid points squeeze closer together on short axes, producing **rectangular prisms** rather than cubic voxels. The variable name and docstring claim cubic voxels but the math doesn't deliver.

**2. Reversed/inverted axes on flat meshes**
If a mesh is extremely flat on one axis (extent < `voxel_size`), then `bbox_lo + voxel_size/2 > bbox_hi - voxel_size/2`. `np.linspace(start, stop, ...)` with `start > stop` silently generates **backwards, crossing points**. No error is raised — the output is mathematically garbage.

**3. Incorrect spacing math**
When endpoints are offset by `voxel_size/2` and `resolution` points are distributed across the shortened range, the step size shrinks to `L*(R-2)/(R-1)²` rather than a uniform `voxel_size` step. The grid does **not** uniformly cover the bounding box at the advertised resolution.

**4. Division by zero on `resolution=1`**
```python
voxel_size = (bbox_hi - bbox_lo).max() / (resolution - 1)
```
Passing `resolution=1` triggers an unguarded `ZeroDivisionError`.

### 🟠 Major Robustness Issues

**5. `mesh.bounds` is `None` for empty geometry → `TypeError`**
If the GLB has no vertices, `mesh.bounds` is `None`. `mesh.bounds[0].copy()` in `_compute_grid` crashes with `TypeError: 'NoneType' object is not subscriptable`. No guard exists.

**6. Zero-extent mesh → degenerate grid**
If all axes have zero extent (e.g., a single-point "mesh"), `extent.max() == 0` → `voxel_size = 0` → `linspace(offset/2, -offset/2, ...)` silently produces NaN or empty arrays.

**7. No output directory creation**
`_write_ply` does not call `os.makedirs()`. If the output path's parent directory doesn't exist, the entire `voxelize_glb` call crashes with `FileNotFoundError` **after** expensive mesh loading and containment computation.

**8. Memory bomb at high resolution**
`np.meshgrid` + `.ravel()` + `np.column_stack` materializes the full dense grid. `resolution=512` → 134M points → ~3.2 GB allocation just for the grid array, then `mesh.contains()` raycasts all of them, almost certainly OOM-killing the process. No guard or chunking.

### 🟡 Determinism & Correctness Issues

**9. Non-determinism from dict iteration**
`scene_or_mesh.geometry.values()` iterates in dict insertion order. The GLB parser's insertion order is not guaranteed across trimesh versions or platforms. Should sort by geometry name before `concatenate()`.

**10. Raycasting non-determinism on boundaries**
Points falling exactly on triangle boundaries produce different `contains()` results across OS/CPU architectures (floating-point edge case). This can break the "byte-identical output" guarantee on re-runs.

**11. `seed` parameter is misleading**
Accepts `seed` but body does `_ = seed` (no-op). Should either remove it or document explicitly as "unused; accepted for orchestrator API parity only." Currently says "Reserved" which is opaque.

### 🟢 Minor Issues

**12. No wrapping of `trimesh.load` errors**
Corrupted GLB files produce raw `ValueError`/`struct.error` without context (e.g., which file path failed).

**13. Empty `.ply` on zero interior points**
If `mesh.contains()` returns all `False` (e.g., degenerate surface, wrong orientation), `_write_ply` writes `element vertex 0` — valid PLY but useless. Downstream Hunyuan pipeline silently gets no conditioning.

---

## r2: `foundry/__main__.py` — Visual-Eval CLI & Reroll Integration

### 🔴 Logic Bug

**1. `or` operator masking reports**
```python
report = result.get("catalog_report") or result.get("scene_report")
```
When both catalog and scene scans run (the default), **only the catalog report is printed**. The scene report is completely ignored. The `or` short-circuits. Fix: iterate both explicitly.

### 🟠 Major Robustness Issues

**2. Relative `library_dir` fallback is unsafe**
```python
library_dir=parsed.library_dir or "assets",
```
Falls back to `"assets"` — a **relative path** that assumes CWD contains an `assets/` directory. Breaks if `python -m foundry` is run from outside the repo root. Should require `--library-dir` when `--reroll` is used, or resolve absolutely.

**3. Missing exception safety around `reroll_flagged`**
If `reroll_flagged` raises (LLM timeout, missing lexicon, disk full), the unhandled exception crashes the entire `visual-eval` command **after** all capture/VLM work has been done, destroying the results. Should be wrapped in `try/except` so the report still prints.

**4. Implicit worklist path coupling**
```python
worklist_path = str(Path(parsed.out_dir) / "visual_worklist.json")
```
Assumes `run_batch()` successfully wrote exactly to this path. If the write failed (permissions, disk full), `reroll_flagged` receives a nonexistent path and crashes. Should check `os.path.exists()` or pass the in-memory `wl` list directly.

### 🟡 Minor Issues

**5. No validation of `--max-rerolls`**
Accepts `type=int` without validating `> 0`. `--max-rerolls 0` or negative values are silently accepted and produce undefined behavior.

**6. Lexicon fallback duplicates `_foundry_dir`**
```python
lexicon_path = str(Path(__file__).resolve().parent.parent / "engine" / ...)
```
The file already defines `_foundry_dir` at module level. Could reuse that: `Path(_foundry_dir).parent / "engine" / ...`.

---

## r3: `foundry/visual/batch.py` — Reroll & Worklist Logic

### 🔴 Fragile Heuristic (Data Corruption Risk)

**1. `"_" not in prop_id` is not a reliable scene-vs-prop classifier**
- A prop named `"chair"` (no underscore) is falsely classified as a scene and **silently skipped** — never re-forged.
- A scene named `"boss_room"` (contains underscore) is falsely classified as a prop — triggers a nonsense forge attempt.
- This is **entirely dependent on naming convention**, which is not enforced anywhere. A single badly-named asset breaks the loop silently.

### 🟠 Major Robustness Issues

**2. Unhandled JSON decode errors**
```python
worklist = json.loads(wl_path.read_text())
```
If the worklist file was partially written (crash, disk full), `JSONDecodeError` is unhandled and crashes the caller.

**3. TOCTOU race on worklist file**
```python
if not wl_path.exists():
    return []
worklist = json.loads(wl_path.read_text())
```
File can be deleted between `exists()` and `read_text()`. Should use `try/except FileNotFoundError` instead.

**4. `list(result.gate.reasons)` is fragile**
- If `gate.reasons` is `None` → `TypeError: 'NoneType' object is not iterable`
- If `gate.reasons` is a plain string → produces `['e', 'r', 'r', 'o', 'r']`

**5. Request construction loses original prompt context**
```python
request = prop_id.replace("_", " ")
```
If the original prompt was *"A deteriorated rusty medieval iron broadsword"* but the prop ID was saved as `medieval_sword`, the re-forge prompt becomes *"medieval sword"* — losing all the detail that produced the original asset. Degraded quality on every reroll.

**6. No cleanup of failed forge attempts**
If `forge_from_request` creates intermediate sidecar files or partially-written GLBs on failure, each retry accumulates them. No cleanup between retries.

### 🟡 Determinism & Contract Issues

**7. Inconsistent `last_result` schema**
- Success: `{"glb_path": ..., "gate_passed": True, "gate_reasons": [...], "attempt": N}`
- Failure: `{"error": "...", "attempt": N}`
- Skipped: `{"skipped": "not a forgeable prop..."}`
Three different dict shapes for the same key. Downstream consumers must check which keys exist.

**8. Scene IDs pollute the outcome list**
Skipped scene IDs are returned with `rerolls=0` in the outcome list, alongside actual reroll results. The caller must filter them out. Better to silently skip or log them separately.

**9. Worklist overwrite + duplicate risk**
`run_batch()` writes the worklist with non-atomic `write_text()`. Concurrent batch runs clobber each other. Props and scenes with the same ID string produce duplicates in the worklist.

---

## r4: Tests — Coverage & Quality

### 🔴 Test Bugs

**1. Module-level mutation causes parallel test races**
`test_voxelize_no_trimesh_raises` mutates `proxy_mod._HAS_TRIMESH` via `try/finally`. Under `pytest-xdist` or any parallel runner, this **sabotages other tests** running simultaneously. Should use `mock.patch.object()`.

**2. Wrong mock target in reroll tests**
```python
with patch("runner.forge_from_request", ...):
```
`reroll_flagged()` imports `forge_from_request` via `from runner import forge_from_request`. Patching `runner.forge_from_request` does **not** affect the already-imported reference in `visual.batch`. Should patch `"visual.batch.forge_from_request"`.

### 🟠 Missing Coverage

**3. No "eventual success" retry test**
`test_reroll_flagged_retries_on_failure` only tests exhausting all retries (all fail). No test verifies that a **successful retry breaks the loop early**: `Mock(side_effect=[fail_result, pass_result])`.

**4. No edge case tests for proxy.py:**
- `resolution=0`, `resolution=1`, negative resolution
- Non-watertight mesh (warning path)
- `pad=0` (voxels right on the shell boundary)
- Very large `pad` (near-zero useful voxels)
- Multi-part GLB with `Scene` concatenation
- Output path with nonexistent parent directory
- Degenerate mesh (zero area/volume)

**5. Fragile PLY helper**
`_read_ply_ascii` raises bare `StopIteration` if `end_header` is missing, and silently drops lines with < 3 parts instead of surfacing formatting errors. This can cause confusing test failures.

---

## Summary

| File | 🔴 Critical | 🟠 Major | 🟡 Minor |
|------|-----------|---------|---------|
| `proxy.py` | 4 (anisotropic grid, inverted axes, wrong spacing, div-by-zero) | 4 (None bounds, zero extent, missing dir, memory bomb) | 4 (dict order, raycast nondeterminism, misleading seed, empty PLY) |
| `__main__.py` | 1 (`or` masking reports) | 3 (unsafe default, no exception safety, path coupling) | 2 (validation, redundant path) |
| `visual/batch.py` | 1 (fragile ID heuristic) | 6 (JSON, TOCTOU, reasons cast, prompt loss, no cleanup, inconsistent schema) | 3 (pollution, overwrite, duplicates) |
| Tests | 2 (module mutation, wrong mock target) | 3 (missing retry test, missing proxy edge cases, fragile helper) | — |

**Highest priority fixes:**
1. Fix voxel math in `proxy.py` — the grid is not cubic and can silently invert
2. Guard `resolution <= 1` with validation
3. Guard `mesh.bounds is None` and zero-extent meshes
4. Replace `"_" not in prop_id` heuristic with a typed `"type": "prop" | "scene"` field in the worklist
5. Wrap `reroll_flagged` call in try/except so visual-eval reports survive failures
6. Fix mock targets in tests and use `patch.object` for module-level state

---

## r5: `foundry/runner.py` — Core Forge Pipeline

### 🔴 Critical Bugs

**1. `forge_from_request` skips `compile_spec()` — raw planner output passed to Blender**
`forge()` calls `compile_spec()` on the loaded spec before passing it to `_build()`. But `forge_from_request()` writes the raw planner spec to the temp file and calls `_build()` directly — **never passes through `compile_spec()`**. This means unvalidated LLM output (missing params, hallucinated fields, wrong types) goes straight to the Blender script. The gate catches geometry issues but parameter validation is completely bypassed.

**2. Error masking via `proc.stderr or proc.stdout`**
```python
raise RuntimeError(f"Blender build failed:\n{proc.stderr or proc.stdout}")
```
The Python `or` operator returns the first truthy value. If `proc.stderr` has a harmless deprecation warning, the **actual fatal error in `proc.stdout` is completely discarded**. Blender frequently dumps fatal traces to stdout rather than stderr.

### 🟠 Major Robustness Issues

**3. Temp file leak on SIGKILL/power loss**
`NamedTemporaryFile(delete=False)` + `os.unlink` in `finally` handles normal exits, but a `SIGKILL`, power failure, or OS crash leaves the temp file permanently in `/tmp`. Eventually fills disk.

**4. `capture_output=True` OOM risk**
If Blender hangs and produces enormous log output, `capture_output=True` buffers it all in Python memory. A looping Blender process could exhaust RAM before the 300s timeout.

**5. Uncaught `subprocess.TimeoutExpired`**
When Blender exceeds 300s, `subprocess.run` raises `TimeoutExpired` — which bypasses the `proc.returncode != 0` check entirely and propagates a raw subprocess exception to the caller.

**6. Half-written GLB on gate failure**
If `_build` succeeds but `gate_asset` raises, the `.glb` file is left in `library_dir` permanently. No cleanup on failure path.

### 🟡 Determinism & Correctness

**7. Duplicate GLB names cause silent overwrites**
`basename = f"{sp['asset_id']}_{sp['material']}"` — two requests producing the same (category, material) pair silently overwrite the same file. No hashing or versioning.

**8. Redundant disk I/O in `forge_from_request`**
Writes `spec` to a temp file, closes it, then immediately calls `sp = load_spec(spec_path)` to read it back. The `spec` dict is already in memory.

**9. No concurrent safety**
Two simultaneous forge calls targeting the same `library_dir` race on GLB writes, sidecar writes, and `register_asset` lexicon mutations. No locking.

### 🟢 Minor

**10. Sidecar decision tracking inconsistency**
`forge()` passes `decisions=decisions` to `build_sidecar()` — but `forge()` never populates `decisions` (it starts as empty). Intentional (explicit-spec path has no planner decisions), but confusing.

---

## r6: `foundry/compiler.py` — Spec Validation

### 🔴 Critical Bugs

**1. Case-sensitive validation will reject valid LLM output**
Generators and materials are checked with strict equality (`gen not in GENERATORS`). LLMs frequently vary casing: `"Table" != "table"`. A completely correct spec will fail validation on casing alone.

**2. Unhandled `KeyError` on `PARAM_RANGES[gen]`**
If `gen` exists in `GENERATORS` but the registry forgot to add it to `PARAM_RANGES`, the lookup raises an unhandled `KeyError`. The source-of-truth split between two dicts makes this a synchronization bug waiting to happen.

### 🟠 Major Robustness Issues

**3. `load_spec` has no error handling**
Raw `open()` with no `FileNotFoundError`, `json.JSONDecodeError`, or `PermissionError` handling. The caller gets raw standard exceptions.

**4. Boolean values bypass numeric type checks**
`isinstance(val, (int, float))` accepts `bool` (which subclasses `int` in Python). `True` becomes `1.0`, `False` becomes `0.0` — silently coercing boolean values through the parameter validation.

**5. NaN/Inf pass type check but fail bounds silently-ish**
`float('nan')` and `float('inf')` pass `isinstance(val, float)`. The bounds check `lo <= val <= hi` returns `False` for both, so they do trigger `SpecError`. Acceptable but the error message is misleading (says "out of range" for NaN).

### 🟡 Minor

**6. Silent age default masks missing data**
`spec.get("age", 0.15)` — missing age in the LLM output silently defaults to `0.15` rather than flagging the omission.

**7. Extra spec keys silently dropped**
The return dict is a strict whitelist filter. Other keys the LLM emitted are silently discarded — this is intentional for LLM pipelines but could mask upstream bugs.

---

## r7: `foundry/gate.py` — Deterministic Guardrail

### 🔴 Critical Bugs

**1. Corrupt GLB crashes with unhandled exception**
`trimesh.load(glb_path, force="mesh")` is called with no `try/except`. Corrupt files, unsupported GLTF extensions, or malformed binary data throw raw `ValueError`/`GLTFDecodeError`/`IndexError` — bypassing the entire gate and crashing the caller.

### 🟠 Major Robustness Issues

**2. Non-mesh GLB types cause `AttributeError`**
If `force="mesh"` returns a `PointCloud` or `Path3D` (possible with certain GLB content), the object has no `.faces` attribute. `mesh.faces.shape[0]` raises `AttributeError`.

**3. Degenerate threshold over-penalizes thin props**
`value < 0.01` hardcoded. A rug (height ~0.005), coin, playing card, or piece of paper will predictably fail the degenerate check on their thinnest axis.

**4. Footprint dict missing keys → `KeyError`**
`width > footprint["width"]` — if the footprint dict is missing keys, unhandled `KeyError`.

### 🟡 Minor

**5. Duplicate `topo` reconstruction**
`mesh.merge_vertices()` is called on line 36, then a new `trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)` is created and `merge_vertices()` called again on line 61. Intentional (strips UV seams for watertight check) but the first merge makes the second mostly redundant.

**6. Watertight check false negatives**
Props placed on the ground (e.g., a boulder with no bottom face) will fail watertight — intentional geometry optimization is penalized.

**7. Watertight check false positives**
Intersecting closed meshes (two overlapping spheres) pass `is_watertight` since every edge has exactly two faces, but the geometry has internal intersections.

---

## r8: `foundry/scene_compiler.py` — Godot Scene Assembly

### 🔴 Critical Bugs

**1. Resource count mismatch breaks Godot loading**
`total_load_steps` is manually computed and can be wrong. If the manifest has duplicate IDs, `len(interactable_ids)` (a set) is smaller than the number of times `sub_res_idx` increments in the loop body. Godot rejects the `.tscn` with a parse error on incorrect `load_steps`.

**2. `_init_world_log` append mode corrupts on recompile**
The world log is opened with mode `"a"` (append). Recompiling a scene for the same build directory appends duplicate NPC initial states to the `.jsonl` file. Each recompile grows the log, and the Godot runtime replays all entries on load — stacking NPCs.

**3. `_guard_player_spawn` can re-overlap resolved props**
Applied **after** `_resolve_prop_overlaps`, `_guard_player_spawn` can push two previously separated props back into each other, or push a prop through a wall.

### 🟠 Major Robustness Issues

**4. Duplicate node names cause Godot auto-rename**
If a prop and an NPC share the same ID (e.g., both named `"chest"`), Godot silently auto-renames the second to `"@chest@2"`. Metadata lookups and script path assumptions break.

**5. `collision_info["NPC"]` overwritten by prop named "NPC"**
If a prop has `id="NPC"`, its collision info is written during the manifest loop, then immediately overwritten by the hardcoded `collision_info["NPC"] = ...` line. The prop gets a humanoid-sized collider.

**6. Quest JSON uses unseparated manifest positions**
The `enemies` block and `examine` block in the quest data JSON read from the **original** `manifest`, but the `.tscn` uses `separated_manifest`. Enemy positions in the JSON won't match their actual positions in the scene.

**7. Exterior atmosphere `IndexError` on short tuples**
```python
fog_color_override = tuple(fc) if len(fc) >= 3 else (fc[0], fc[1], fc[2])
```
If `len(fc) < 3`, the `else` branch tries to index `fc[2]` — which doesn't exist — and raises `IndexError`.

**8. `_find_open_npc_positions` inserts invalid positions**
The fallback loop runs up to 50 attempts, then **always appends `(x, z)`** regardless of whether `_valid_npc_spot` ever returned `True`. NPCs can spawn inside props or walls.

### 🟡 Minor

**9. Asymmetrical interior light grid for partial rows**
`n_lights` = 18 with a 4×5 grid (20 cells) runs `range(18)`, producing lights at columns 0-1 on the last row only. The top half of the room is asymmetrically lit.

---

## r9: `foundry/behaviour_gen.py` — Quest Generation

### 🔴 Critical Bugs

**1. Target deduplication causes dialogue misalignment**
When `plan_multi` falls back to per-NPC `plan()` calls and the returned target was already used by another NPC, the code reassigns `raw["target_entity"] = available[0]` but **does not regenerate the dialogue**. The NPC speaks dialogue written for the original target (e.g., "Find my brass key!"), while the actual quest target is silently swapped to a different item. The objective `target` field is correct, but the dialogue is hallucinated.

**2. Module-level grammar loading crashes on import**
`_GRAMMAR = _load_grammar(_GRAMMAR_PATH)` executes at module import time. If the `.gbnf` file is missing or malformed, **every import of `behaviour_gen`** (including indirect imports) raises `FileNotFoundError`, crashing the entire foundry.

### 🟠 Major Robustness Issues

**3. Unclosed `<think>` tags poison JSON parsing**
The regex `re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)` uses the non-greedy `.*?` which only matches if the closing `</think>` tag exists. If the LLM output is truncated before the closing tag, the entire `<think>` block passes through to the JSON parser, which fails.

**4. Catastrophic fallback latency (O(N) LLM calls)**
If the multi-NPC JSON call fails, the loop falls back to calling `self.plan()` sequentially for each NPC. For 5-10 NPCs, this is **5-10 blocking LLM generations** with grammar constraints — completely defeating the purpose of the single multi-call and spiking latency/cost massively.

### 🟡 Minor

**5. Punctuation bypasses duplicate role validation**
`_validate_npc_role` splits on whitespace and compares `lower()` — so `"Blacksmith, blacksmith"` is not detected as a duplicate because `"blacksmith," != "blacksmith"`.

---

## Overall Summary

| Segment | File(s) | 🔴 Critical | 🟠 Major | 🟡 Minor |
|---------|---------|------------|---------|---------|
| r1 | `proxy.py` | 4 | 4 | 4 |
| r2 | `__main__.py` | 1 | 3 | 2 |
| r3 | `visual/batch.py` | 1 | 6 | 3 |
| r4 | Tests | 2 | 3 | — |
| r5 | `runner.py` | 2 | 4 | 3 |
| r6 | `compiler.py` | 2 | 3 | 2 |
| r7 | `gate.py` | 1 | 3 | 3 |
| r8 | `scene_compiler.py` | 3 | 5 | 1 |
| r9 | `behaviour_gen.py` | 2 | 2 | 1 |
| **Total** | | **18** | **33** | **19** |

### Cross-Cutting Themes

1. **Missing error handling on I/O boundaries**: `trimesh.load` (gate, proxy), `json.loads` (batch, behaviour_gen), file opens (compiler) — all lack try/except wrappers.
2. **Silent data corruption**: wrong positions in JSON vs scene (scene_compiler), dialogue misalignment on target dedup (behaviour_gen), resource count mismatch (scene_compiler).
3. **Fragile string heuristics**: case-sensitive validation (compiler), underscore-in-ID check (batch), whitespace-only duplicate detection (behaviour_gen).
4. **No concurrent safety anywhere**: duplicate GLB names (runner), worklist overwrites (batch), lexicon mutations (runner), world log append (scene_compiler).
5. **Module-level I/O that crashes on import**: grammar loading (behaviour_gen) is the worst offender.
