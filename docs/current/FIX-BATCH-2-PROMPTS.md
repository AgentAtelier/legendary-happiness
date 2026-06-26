# Fix-Batch 2 — Delegation Prompts (suite-green + granite re-tune)

> **For the CLI AI:** small, focused. Spec: this file. One real material fix + a discipline fix
> that caused the last few misses.

## ⚠ STANDING-RULE AMENDMENT (read first — this is why bugs slipped)

The last two batches reported "**133 key tests** pass" — a **subset**. The full suite was actually
**red** (granite roughness drift, plus a test that NameError'd). From now on, **always run the FULL
suite**, not a hand-picked subset:

```
cd foundry && .venv/bin/python -m pytest tests/ -q        # ALL tests, report the real count
cd foundry && .venv/bin/python -m pytest tests/test_godot_smoke.py -q
```

Report the **total** (e.g. "816 passed") and never a subset. A green subset over a red full suite is
how the AO bug, the missing `import struct`, and the granite drift all shipped.

## Global Constraints

- **Testing split:** **[CLI]** runs the FULL fast gates (above) green, then hands off. **[ORCH]** does
  the live/visual verification. Never mutate the real `engine/devforge/spatial/asset_lexicon.json`.
  Never touch `addons/godot_ai`.

---

## Task 1 [CLI] — Granite (stone) roughness back into spec → suite green

**Cause:** `tests/test_slice5_metallic_roughness.py::test_granite_emits_metallic_roughness_texture`
renders the baked `metallicRoughnessTexture` GREEN (roughness) channel and expects ≈ 0.85 (AgX
compresses to ~0.70, ±0.20 band). It now reads **0.525** — E1's new layered **stone** material
(`_stone_color_nodes` / the Voronoi-cell + crack subgraph in `build_asset.py`) drives the average
roughness *down*, so `rough_granite` reads **too glossy** (it should be matte). The roughness baseline
comes from `mat_info["roughness"]` (~L1899) → `apply_roughness_bake(baseline_roughness=...)` (~L2015),
but the stone path is modulating it below the intended band.

**Fix:** keep the stone roughness map's mean within the material's intended band (rough_granite ≈
0.85; spec 0.75–0.90). Whatever the layered stone subgraph does for visual variation (cracks/cells), it
must not pull the *average* roughness down to 0.5 — clamp/raise the stone roughness contribution so the
baked GREEN-channel mean lands in band. Verify with the actual render test (it bakes + renders).

**Acceptance:**
- [ ] `test_slice5_metallic_roughness.py::test_granite_emits_metallic_roughness_texture` passes
  (GREEN mean within ±0.20 of 0.85 after AgX).
- [ ] Other stone-bearing material tests still pass; determinism preserved.
- [ ] **FULL** `pytest tests/ -q` green + `pytest tests/test_godot_smoke.py -q` green — report the total.
- [ ] Commit: `fix(foundry): keep stone roughness in band — rough_granite reads matte (Fix-Batch-2)`.

---

## [ORCH] Verification — orchestrator only

After handoff: orchestrator runs the full suite (confirm green total), generates a granite-bearing build
into a throwaway lib (restoring `asset_lexicon.json` after), and hands a build to the **user** to confirm
granite now reads matte (not glossy/plastic).
