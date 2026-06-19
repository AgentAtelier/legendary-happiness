# Forge Continuation Playbook

**Date:** 2026-06-19. **Purpose:** everything needed to keep the project moving without Claude in the loop — how we work, **how you verify CLI-AI work yourself**, the durable context, and ready-to-run prompts for every item with a real chance of landing cleanly. Written for a competent CLI AI executor and a non-coding architect (you).

---

## 0. How to use this

1. Read §1 (rhythm) and §2 (verification) once — §2 is the part that replaces Claude's "I checked the tree."
2. Do the **Step 0 merge** in §4.
3. Pick a prompt from §5, paste it to your CLI AI, let it work, then **run §2 against the result** before moving on.
4. §6 = items that still need a design conversation before they become prompts. §7 = your own ops decisions.

The two oracles that replace Claude's judgment:
- **The test suite** (`pytest`, green **and** the count went up) = structural correctness.
- **The eval harness friction report** = behavioral correctness (it caught a bug Claude had wrongly called fixed).

---

## 1. The operating rhythm

- **One slice at a time.** Design → one prompt → implement → **verify** → merge. Never stack unverified work.
- **AGENTS.md is law** (repo root). Every prompt references it.
- **TDD.** Every slice ships tests. No tests = not done.
- **Premise: qwen is good enough.** When the LLM step fails, fix it deterministically (a pre-pass, a prompt change, a narrower call) — never "use a bigger model" or an API. That defeats the project.
- **The LLM is a parametric compiler frontend, not a creative engine.** It does semantic routing (which generator, vague phrasing) and fills params. Lexical/simple mappings (material, now age) belong to deterministic code. Geometry/precision is always deterministic.
- **Verify, don't trust.** CLI AIs skip steps and misreport — we caught a skipped merge and outright false reports. Always run §2 yourself.

---

## 2. The verification protocol — run after EVERY delivery

You do not read code. You run these and read the results.

```bash
# 1. Commits exist — are the hashes the report named actually here?
git log --oneline -8

# 2. Tree clean — ONLY anvil-main.zip / forge-main.zip may show as untracked.
git status --short
#    Anything else = out-of-scope file; ask the AI why before continuing.

# 3. Tests green AND grew — must end "N passed", and N must be HIGHER than last time.
cd foundry && .venv/bin/python -m pytest tests/ -q
#    Green with no new tests = the work wasn't really tested. Push back.
```

**4. For anything touching the live pipeline** (planner / resolver / generators / prompts), run the harness **twice** and compare — qwen is stochastic, so a bug can hide in one run (this is exactly how the age bug surfaced):

```bash
cp engine/devforge/spatial/asset_lexicon.json /tmp/lex.json   # throwaway copy; never mutate the real one
foundry/.venv/bin/python -m foundry.eval run foundry/eval/corpus/seed_requests.txt /tmp/lex.json /tmp/run1 --no-build --seed 1337
foundry/.venv/bin/python -m foundry.eval run foundry/eval/corpus/seed_requests.txt /tmp/lex.json /tmp/run2 --no-build --seed 1337
# read /tmp/run1/report.md and /tmp/run2/report.md — did a signal regress? do the two runs agree?
```

**Red flags → stop and push back:** test count went *down*; "no tests needed"; can't show `git log`; a file you didn't ask for; a confident-but-vague report; "merged" without showing `git log` on `main`.

**Merging a verified branch** (all clean fast-forwards so far):
```bash
git checkout main && git merge --no-ff <branch> -m "merge: <what>"
git log --oneline -3 main      # confirm the branch tip is now on main
```
Merges are **local only** — `main` is ahead of `origin` and nothing is pushed (see §7).

---

## 3. Durable context (so this survives even if the memory files are lost)

**What the system is:** a 100% local, free pipeline generating game-ready stylized 3D assets (Valheim/Ori furniture/props) for a Godot RPG from natural-language requests. A small local LLM (qwen ~4B on llama.cpp `:8002`) picks a generator and fills params, grammar-constrained to JSON; deterministic Python+Blender builds geometry, materials, and bakes to GLB; Godot consumes the GLB.

**Key components (all under `foundry/`):**
- `planner.py` — `AssetPlanner.plan(request, llm) -> (spec, decisions)`. qwen picks generator + params (material and soon age are NOT qwen's job).
- `material_resolver.py` — deterministic `resolve_material(request) -> (material, [DecisionPoint])`; `material_cues(request)` returns all matched cues. Material is regex, not LLM.
- `compiler.py` — `compile_spec`, `GENERATORS` (table/chair/shelf/cabinet), `PARAM_RANGES`, validates `age ∈ [0.15,1.0]`.
- `grammar/asset_spec.gbnf` — single-line `root` rule; qwen emits asset_id/generator/age/params (material already removed).
- `blender/build_asset.py` — bmesh generators + family-dispatched shaders (`_COLOR_BUILDERS` by material `family`: wood/stone/metal) → shared AO×albedo→EMIT bake + normal + metallicRoughness bake; `apply_entropy` (seeded age-scaled deformation).
- `materials.py` — 5 materials across 3 families.
- `gate.py` — deterministic admit/reject (watertight, poly budget, bounds).
- `decisions.py` — `DecisionPoint`/`Choice` dataclasses, `make_decision`, template registry (dual-register technical+plain), `render_cli`, `to_dict`. The explainable-failure layer.
- `sidecar.py` — per-asset metadata sidecar; validates against `engine/devforge/governance/schemas/asset_metadata_sidecar_schema.json` (we added an optional `decisions` property).
- `runner.py` — `forge`, `forge_from_request`, `ForgeResult` (gate + `decisions`).
- `eval/` — autonomous harness: `harness.py` (run_corpus + RunRecord), `signals.py` (objective signals incl. `AGED_WORDS`/`NEW_WORDS`, `material_conflict`, `age_mismatch`, `SIGNAL_SEVERITY`), `sampler.py` (severity-weighted stratified sampling + clean baseline + `estimate_clean_rate`), `report.py` + `__main__.py` (friction report + CLI), `corpus/seed_requests.txt`.

**Hard-won facts:**
- The age few-shot "fix" is **unreliable** — qwen's age output swings wildly run-to-run (run1 bimodal, run2 all-0.15). The real fix is the **age pre-pass** (Prompt 1). This is *the* lesson: a single manual run cannot validate a stochastic model.
- Material is rock-solid *because* it's deterministic (not qwen). Apply the same to age.
- Shader *aesthetics* (wood/stone/metal look) are **the user's hand-authoring**, NOT to be blind-delegated — the plumbing is correct, only the node recipes need an artist's eye.
- `python -m foundry...` runs from the **repo root**; foundry has its own venv (`foundry/.venv`).
- Never mutate the real `asset_lexicon.json` (forge a `/tmp` copy). Never commit the two `.zip` reference archives or `foundry/.venv`.

**Test command:** `cd foundry && .venv/bin/python -m pytest tests/ -q` (currently 266 on the eval-slice-2 branch).

---

## 4. Sequencing

**Step 0 (do first):** the eval-slice-2 branch (`feat/foundry-eval-quality-heuristics`, tip `af9cb58`, 266 green) is verified but **not merged**. Merge it: `git checkout main && git merge --no-ff feat/foundry-eval-quality-heuristics -m "merge: eval harness slice 2 (quality heuristics)"`. Then every prompt below branches off the new `main`.

**Dependency graph (not all independent):**
- **Prompt 1 (age pre-pass) first** — it's the highest-value fix and several others assume age is deterministic.
- Prompts 2, 3 are small and independent — do anytime.
- Prompts 4–6 (stability / regression / corpus) build on the harness; do after 1 (so stability *confirms* the age fix and regression can assert age).
- **Prompt 8 (world-model) is foundational** for future coherence/editing and for a real journey lens — but it's ahead of immediate need; schedule by appetite.
- **Prompt 7 (UI MVP) is the largest/most-open** — do it when you want a face on the system; it depends on nothing but benefits from 1–2 being done.

Recommended order: **0 → 1 → 4 → 2 → 5 → 6 → 7 → 8.**

---

## 5. Ready-to-run prompts

Each is self-contained. The standard preamble (read it as given for every one):

> Read AGENTS.md at the repo root and follow it (TDD, scope discipline, commit-proof reporting, foundry venv/determinism, single-line GBNF). Read `docs/CONTINUATION-PLAYBOOK.md` §3 for system context. Create the named branch off the latest `main`. Do NOT touch `anvil-main.zip`/`forge-main.zip`. Tests run from repo root: `cd foundry && .venv/bin/python -m pytest tests/ -q`. End by reporting commit hashes, `git log --oneline -N`, `git status --short`, and the full pytest output. Do NOT merge and do NOT run the live harness — the user does that.

### Prompt 1 — Age pre-pass (deterministic wear→age) — branch `feat/foundry-age-prepass`

```
Mirror the material resolver, for age. qwen's age output is provably unreliable run-to-run; remove
age from qwen entirely and resolve it deterministically from wear words.

- Create foundry/age_resolver.py: resolve_age(request) -> tuple[float, list[DecisionPoint]].
  Reuse the wear lexicons already in foundry/eval/signals.py (AGED_WORDS / NEW_WORDS) — move them
  to a shared module (e.g. foundry/wear_words.py) imported by both signals.py and age_resolver.py
  (do NOT duplicate the lists; update signals.py to import them).
  Rules: an AGED word -> 0.8 ; a NEW word -> 0.15 ; neither -> 0.15 (floor).
  Emit a DecisionPoint (via decisions.make_decision) when: no wear word was present (age.unspecified_defaulted,
  severity assumption), or when both AGED and NEW words appear (age.conflict, severity ambiguous), with
  the alternative as a Choice. Confident single-class -> no DecisionPoint.
- Remove age from qwen: drop the "age" field from grammar/asset_spec.gbnf root (single-line edit) and
  the age guidance from planner.py's prompt; in plan(), call resolve_age(request) first, set spec["age"]
  from it, and merge its decisions into the returned decisions list (alongside material's).
- compiler.py still validates age in [0.15,1.0]; keep that.

Tests (synthetic + fake-LLM planner): "an old chair"->0.8; "a new table"->0.15; "a vintage cabinet"->0.8
(vintage is AGED); neutral "a plain table"->0.15 + one age.unspecified_defaulted; "an old new thing"->
age.conflict; determinism (same request->same age); plan() with a fake LLM whose JSON has NO age field
still yields a valid spec whose age came from the resolver; grammar root no longer contains "age".
```

### Prompt 2 — Conflict → recoverable Decision Point — branch `feat/foundry-conflict-decision-point`

```
material_conflict is currently only detected in the eval harness. Promote it into the live resolver so
users get a recoverable choice.

- In foundry/material_resolver.py resolve_material(): after resolving the winning material, call
  material_cues(request); if the cues span MORE THAN ONE distinct family, also emit a DecisionPoint
  (code material.conflict, severity "ambiguous") whose choices are one Choice per competing family's
  default material (apply {"field":"material","value":<id>}), with context naming the competing cues and
  the resolved winner. Still return the deterministic winner (specific keyword wins, else first family).
- Add the material.conflict template to decisions.py's registry (plain + technical).

Tests: "a stone-look wooden cabinet" -> resolves to a winner AND emits one material.conflict with choices
covering wood and stone; "an oak walnut table" (same family) -> NO conflict; a single-cue request -> no
conflict. Existing material_resolver / planner tests stay green.
```

### Prompt 3 — Run the devforge suite (verification, not a feature) — no branch unless a fix is needed

```
We merged an additive change to a SHARED schema (engine/devforge/governance/schemas/
asset_metadata_sidecar_schema.json — added an optional "decisions" property) but only ran the foundry
suite. Confirm devforge's own tests still pass.

Discover how the devforge/engine tests run (check root pyproject.toml, engine/ test dirs, engine/.venv or
the root .venv) and run the full engine/devforge test suite. Report the exact command used and the full
output. If there are failures, report them and say whether each is plausibly caused by the schema change
(touches sidecar validation) or pre-existing/unrelated. Do NOT fix anything unless a failure is directly
caused by the schema change AND the fix is one obvious line — in which case branch
feat/devforge-schema-fix, fix, test, report.
```

### Prompt 4 — Stability lens — branch `feat/foundry-eval-stability`

```
Add a stability lens to the eval harness: run each request N times and measure run-to-run variance of
qwen's choices. This is the tool that validates whether the age pre-pass actually made age deterministic.

- New foundry/eval/stability.py + a CLI subcommand: python -m foundry.eval stability <corpus> <lexicon>
  <out_dir> [--runs 5] [--seed 1337]. For each request, run AssetPlanner().plan() N times (planner only,
  no build), capture (generator, material, age, params) each run.
  Unstable if across the N runs: generator differs, material differs (should be 0 — regression guard),
  age differs (post-age-prepass should be 0 — this is the validation of Prompt 1), or any param drifts
  >15% relative. Output per-request {stable: bool, varied: [...]}, an overall stability score
  (% of requests stable), as report.md + report.json.
- Keep it pure/injectable: a FAKE llm makes it deterministic in tests.

Tests on synthetic/fake-LLM: a fake whose output is identical across runs -> all stable; a fake that
flips generator on run 2 -> that request unstable with varied=["generator"]; a fake that drifts a param
>15% -> unstable; score computed correctly; deterministic given a seed.
```

### Prompt 5 — Regression lens — branch `feat/foundry-eval-regression`

```
Add a golden-master regression lens to the eval harness.

- New foundry/eval/regression.py + CLI: python -m foundry.eval regression <corpus> <lexicon> <out_dir>
  [--update]. Each corpus request has a paired expectation (JSON) capturing expected generator, material,
  age. Run each request once, compare:
    material + age -> HARD assertions (deterministic via the resolvers; a mismatch is a real failure).
    generator -> tracked assertion (a mismatch may reflect residual qwen variance; report it but weight
    it separately in the score).
  --update rewrites the expectation files from current output (re-bless after approved changes).
  Output a pass/fail report with per-field diffs + an aggregate score; persist expectations as JSON files
  paired with the corpus (e.g. an expectations/ dir keyed by a hash of the request).

Tests: an output matching the golden -> pass; a changed material -> fail with a diff; --update rewrites the
expectation so the next run passes; aggregate score correct.
```

### Prompt 6 — qwen-augmented corpus — branch `feat/foundry-corpus-augment`

```
Grow the eval corpus from ~60 to ~250 via lexicon-driven slot-filling — NOT by asking qwen to invent
freely (it would hallucinate materials the resolver can't parse).

- New foundry/eval/augment.py + CLI: python -m foundry.eval augment <out_file> [--target 250] [--dry-run].
  Build requests from templates whose slots are filled from OUR real lexicons: generator nouns
  (table/chair/shelf/cabinet + synonyms), material keywords (from material_resolver), wear words (from the
  shared wear lexicon). Use qwen ONLY to paraphrase a slot-combo into natural phrasing (grammar-free is
  fine here; it's corpus text, not a spec). Also include a fixed set of adversarial templates: conflicting
  material cues, no-material, ambiguous nouns.
  Dedup: hash-normalized (lowercase, strip punctuation/whitespace, hash; drop collisions).
  Validity: keep a request only if it plans + compiles without a hard error. KEEP requests that fire
  Decision Points (conflicts/defaults are the valuable edge cases — do not drop them).
  --dry-run prints stats (counts per template/family, dedup rate) without writing.

Tests (fake LLM for paraphrase): dedup removes a normalized duplicate; the validity filter keeps a
Decision-Point-firing request; output size is bounded by --target; slot-filling covers all four generators.
```

### Prompt 7 — UI MVP (local web app) — branch `feat/foundry-ui-mvp`

```
Build a minimal LOCAL web app that surfaces the system. MVP scope only — resist scope creep.

- New foundry/ui/ : a FastAPI app (foundry/.venv has or can add fastapi+uvicorn; add to requirements).
  Endpoints: POST /forge {request} -> starts plan+forge in a background thread, returns a job id;
  GET /jobs/{id} -> status + result (glb path, spec, decisions); GET /decisions -> recent Decision Points;
  GET /report -> latest harness report.json if present. Wrap the existing foundry (planner/runner); inject
  them so tests don't need llama/Blender.
- A single static index.html (HTMX or Alpine.js — NO build step) with three areas:
  (1) a request box that POSTs /forge and polls /jobs;
  (2) a Decision Point INBOX — cards showing the plain message, a collapsed technical line, and the choices
      as buttons; resolving a choice writes a spec override and re-runs. NON-BLOCKING: never a modal.
  (3) a JSON spec editor with a "re-run at layer" selector: material-only / params / full-prompt
      (full-prompt re-runs the LLM; the others bypass it — this is the cheap-edit superpower).
  Show a "copy GLB path" button for opening in Godot. Do NOT build a web 3D viewer, WebSockets, or a
  database — those are post-MVP.

Tests: the FastAPI endpoints return the expected shapes with an injected fake foundry (no llama/Blender);
POST /forge then GET /jobs reaches a done state; /decisions renders injected Decision Points. Use FastAPI's
TestClient. If implementation pressure mounts, ship areas (1)+(2)+(3) and defer polish — say so in the report.
```

### Prompt 8 — World-model slice 1 (coherence foundation) — branch `feat/foundry-world-model`

```
Build the smallest piece of the coherence/editing architecture: a deterministic, validate-before-commit
world model with an append-only log. STANDALONE — do not wire it into the live pipeline yet.

- New foundry/world/ : 
  World (dataclass): a list of Placement{id, asset_hash, attrs: dict (e.g. material, generator, zone)}.
  Geometry is referenced by asset_hash, NEVER stored in the model (geometry is derived).
  An append-only event log (JSONL): each accepted change is one event.
  propose(world, intent) -> ProposeResult, where intent is a WHOLE small object (add or replace one
  placement — never a diff). It applies the intent to a STAGED copy and runs tiered invariants:
    HARD (block): referential integrity (a placement's material/asset is known) and a simple budget
      (e.g. max placements per zone). On violation -> reject + a DecisionPoint (reuse decisions.py),
      no event appended.
    SOFT (warn): a style rule example -> emit a DecisionPoint but allow the append.
  On accept: append the event, return the new World. Provide replay(log) -> World (state = fold over
  events) and a snapshot/restore.

Tests: a valid add appends one event and yields the new state; a referential-integrity violation ->
DecisionPoint and NO event; a budget violation -> DecisionPoint; replay(log) reconstructs the same state;
determinism. Do NOT feed any LLM the whole world; do NOT store geometry; check semantics only.
```

---

## 6. Design briefs (not prompt-ready — need a conversation first)

These have a clear direction (from the external-AI survey, critically filtered) but a real decision remains. Restart from here.

**Perceptual judge.** Direction: tiered, all-local, **informational only — never a gate**. Tier 0 = deterministic render heuristics (material-color sanity, missing/black-texture detection via Laplacian variance, silhouette/proportion). Tier 1 = image-to-image distance to a *curated reference bank* (per category; novelty ≠ failure). Optional Tier 2 = a tiny VLM (Moondream-class) as a **cross-checker** of the deterministic material/category choice (disagreement → Decision Point), NOT a scorer. **Why it's not a prompt yet:** the high-value tiers need a reference bank you don't have, and the right first move (per the survey's own advice) is to log human "reject" reasons for a while and only build the neural layers if "style mismatch" is actually common. CLIP text-image scoring and LAION aesthetic predictors are traps (photoreal bias). Aligns with our founding "no VLM taste-judge" stance.

**Organic assets.** Direction: hybrid with a **LOD/scale seam, ~80% Geometry Nodes**. GeoNodes (ratio-parametric, LLM fills ratios not coords) for flora/rocks/food — non-negotiable for instancing + the chunky look. Local-LRM ingest (Hunyuan3D/TripoSR, never cloud) only for **hero static** organics, **Decision-Point-gated** ("static, unriggable; accept/regen/fallback"), and **never decimated** (it melts the silhouette — voxel-remesh or normal-bake onto a low-poly proxy). The Rust `forge_assets` blueprint = the ingest validator. Kitbash-DB banked as the creature alternative. **Why it's not a prompt yet:** authoring GeoNodes generators is taste-heavy technical-art work (your domain, like the shaders), and the ingest path is a method commitment. Decide GeoNodes-first scope with you before delegating.

**Journey lens.** Direction: deterministic ledger backbone (procedural/templated) → verbalize to NL; oracle = intended-vs-actual ledger diff + differential-vs-one-shot + **negative-control probes** (prove the pipeline actually *responds* to input — a pipeline that ignores everything is "perfectly coherent"); reuse Decision-Point co-occurrence as the context-loss signal. **Why it's not a prompt yet:** the genuinely valuable property (true iterative editing) is **untestable until the world model exists (Prompt 8)** — today you can only test "attribute non-regression under restatement," which overlaps with the stability lens. Revisit after Prompt 8.

**Coherence & editing — beyond slice 1.** Prompt 8 is the converged smallest slice (everyone landed on: Python-first, event-sourced, validate-before-commit, **Decision Points become staged intents validated against global state**). Banked upgrades, only when Python hurts: SQLite + savepoints; a content-addressed (git-like) DAG for branching/instant-revert; Z3/SMT for "unsat-core" razor-sharp failure messages; or wrapping the abandoned Rust impl via IPC (NOT FFI). **Hard NOs everyone agreed on:** CRDTs (you want hard rejects, not merges), porting Rust now, feeding the LLM the whole world (give it the local neighborhood + query results), validating geometry instead of semantics (check coherence on the JSON *before* Blender bakes), letting the LLM write invariants or do diff-arithmetic.

---

## 7. Your ops & decisions (not CLI-AI work)

- **Push to origin?** `main` is local-only, ~50+ commits ahead of `origin/main`. Decide if/when to `git push`. Nothing is pushed automatically.
- **LAN security (unresolved).** Ports 8000/8001/8002 are on `0.0.0.0` with no firewall — a real exposure. Needs your sudo (e.g. `ufw`). Flagged in earlier audits.
- **Branch cleanup.** The old foundry feature branches are all merged into `main` and are deletable.
- **Shader authoring (yours).** Wood/stone/metal first-pass shaders + the multi-channel-bake *content* are your hand-authoring (taste, not delegation). The pipeline already carries normal + roughness; enrich the recipes in `blender/build_asset.py`'s family color builders.

---

*If you regain access to Claude: paste the latest `git log --oneline -15` on `main` plus any harness `report.md`, and it can pick the thread back up.*
