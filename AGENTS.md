# AGENTS.md — Standing rules for delegated implementation work

These are the **always-on** rules for any AI implementer working in this repo. A per-task prompt
adds *what* to build; this file is the *how*, and it does not get repeated in every prompt. If a task
prompt contradicts this file, the task prompt wins — but call out the conflict before proceeding.

## 🔴 Always run the FULL test suite — never a subset

**Every** implementation turn must end with:

```
cd foundry && .venv/bin/python -m pytest tests/ -q        # ALL tests
cd foundry && .venv/bin/python -m pytest tests/test_godot_smoke.py -q
```

Report the **total** count (e.g. "816 passed") — never a hand-picked subset like "133 key tests
pass".  A green subset over a red full suite is how bugs (AO not wired, missing imports, material
drift) ship undetected.  If a specific file group is worth checking mid-stride, that is fine — but
the **final** report MUST include the full `pytest tests/` output.

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
