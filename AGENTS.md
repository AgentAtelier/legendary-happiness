# AGENTS.md — Standing rules for delegated implementation work

These are the **always-on** rules for any AI implementer working in this repo. A per-task prompt
adds *what* to build; this file is the *how*, and it does not get repeated in every prompt. If a task
prompt contradicts this file, the task prompt wins — but call out the conflict before proceeding.

## Architecture orientation (read `docs/current/PROJECT-STATE.md` first)

- Generation flows through a **spine**: `prompt → Interpreter (LLM) → Brief (shared structured intent)
  → generators (room/quest/assets) → Godot scene + a Build Report`. New capabilities ride the Brief
  (add a Brief section + a generator that consumes it + Decision Points + report lines), not bespoke
  wiring. See `SPINE-DESIGN.md`.
- **Structured LLM output uses llama.cpp `json_schema`** (pass a schema), NEVER `grammar=None` —
  `None` applies the default *asset* grammar and silently mangles output. Free-form = `grammar=""`.
- **Python builds, Godot lives:** decide everything at build time in Python and bake it; Godot
  renders/loops. Assets are Blender-baked PBR GLBs (albedo/roughness/metallic/normal/AO).
- **Visual QA** lives in `foundry/visual/` (V): screenshot harness + Qwen3-VL checks + CLIP aesthetic +
  batch (`python -m foundry visual-eval`). The VLM/Claude never replaces the human as final visual judge.

## Lint gate (Phase 0.9 — recurrence-preventer)

Run **before** every commit that touches Python under `foundry/` or `hub/`:

```bash
scripts/lint.sh                # ruff check only
scripts/lint.sh --fix          # apply safe auto-fixes first, then re-check
```

The linter is `ruff` (installed via `foundry/requirements-dev.txt`); rule selection is
`E + F + I + UP + B` (with project-specific ignores enumerated in `docs/current/ACCEPTED.md`).
**Safe auto-fixes only** — `UP006`/`UP007`/`UP024` are deferred to the Phase 1.4
`scene_compiler.py` decompose (see `AUDIT-03 Q12`).  Distinct from `scripts/check.sh`,
which adds `ruff format --check` + the 500-line file-length gate.

## 🔴 Always run the FULL test suite — never a subset

**Every** implementation turn must end with BOTH commands, and you must **paste the literal final
result line of EACH** into your report:

```
cd foundry && .venv/bin/python -m pytest tests/ -q                     # ALL unit tests
cd foundry && .venv/bin/python -m pytest tests/test_godot_smoke.py -q  # THE Godot-in-the-loop gate
```

Report the **total** count (e.g. "816 passed") — never a hand-picked subset like "133 key tests
pass".  A green subset over a red full suite is how bugs (AO not wired, missing imports, material
drift) ship undetected.

### 🛑 The Godot gate is non-negotiable (this has been a recurring false-green)

`pytest tests/ -q` reporting "0 failed" is **NOT** sufficient and is **NOT** "done". The Godot-in-the-
loop tests (`test_godot_smoke.py`) are THE gate, and **the last three delegated bundles each reported
"0 failed" while these were RED** — GDScript parse errors that pass every Python unit test but load
*nothing* in Godot, and a multi-NPC regression. You MUST:

- **Paste the literal `test_godot_smoke.py -q` result line** (e.g. `8 passed in 31s`). A report without
  it is rejected, regardless of the unit count.
- Treat **"skipped" / "no tests ran" / `TimeoutExpired`** as a **FAILURE** — if Godot isn't found, or a
  probe hangs, the gate did NOT pass and you may not claim green. (A GDScript parse error makes the
  probe hang → timeout; that is a red gate, not a slow machine.)
- After any change under `foundry/godot_template/` or to `scene_compiler.py`: also do a plain headless
  launch and grep stderr for `SCRIPT ERROR|Parse Error|Failed to load` = **0**, and **regenerate
  builds** (old builds keep old scripts).

If you cannot run Godot in your environment, say so explicitly and hand the Godot gate to the
orchestrator — do **not** report "0 failed / done".

## Working discipline

- **TDD, in small slices.** Write the failing test, watch it fail, write the minimal code, watch it
  pass, commit. One logical change per commit.
- **Stay in scope.** Touch only the files the task names. No "while I'm here" refactors, no reformatting
  untouched code, no opportunistic renames. If you find an unrelated problem, report it — do not fix it.
- **Do not trust prior "already fixed" claims** (including your own). Verify against the actual tree
  before building on top of anything.

## Reporting contract (non-negotiable)

- **Prove your commits.** End every unit of work by pasting the literal output of `git log --oneline -N`
  and `git status --short`. "I committed it" without that output is not acceptable — two previous
  implementers misreported (one claimed "no code changed" while editing core files; one left work
  uncommitted). The tree is the source of truth.
- **Report failures honestly.** If tests fail, paste the failing output and say so. If you skipped a
  step, say so. Never describe unverified work as done.
- **Never commit:** `foundry/.venv`, `*.zip` reference archives in the repo root (e.g. `anvil-main.zip`,
  `forge-main.zip`), or generated build artifacts.

## Foundry specifics (`foundry/`)

- The foundry is a **standalone package with its own venv** and no `devforge` import.
- **Run `python -m foundry` from the repo root**, never from inside `foundry/`.
- **Test command:** `cd foundry && .venv/bin/python -m pytest tests/ -q`. Live build/render tests also
  need llama on `:8002` and Blender (installed).
- **Determinism is required** in the build path: seed all randomness from the spec. Two identical specs
  must produce byte-identical output. No wall-clock or unseeded RNG.
- The deterministic **gate** (`foundry/gate.py`) is the guardrail — assets must stay watertight (on
  position-welded topology), within the poly budget, and inside the lexicon bounds envelope. Any change
  that risks these must keep them green.
- **GBNF grammars:** single-line alternations only. Multi-line `|` silently disables the grammar;
  `normalize_gbnf` guards this — do not work around it.
- **Never mutate the real `asset_lexicon.json` in tests.** Use fixtures/temp copies.

## Upstream / fork policy

- **Never patch `godot-ai` or `Odysseus` source.** Adapt DevForge or use the provided config/extension
  mechanisms instead. The same applies to any vendored upstream.
