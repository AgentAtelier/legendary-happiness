# Conventions — the few rules

**Read this at the start of any coding session.** It is deliberately short.
Source: the Layer-3 review (six CLI AIs, `docs/reviews/layer3/`), reconciled to
this codebase. The spirit is *an environment that lowers review load*, not a cage.
The model to copy is **`hub/forge_testbench/`** — small files, clear docstrings,
one job each, self-describing data.

## The rules

1. **Files ≤ 400 lines (soft), 500 hard.** Past 400, ask "should this split?";
   500 is the CI failure line. Tests may run longer. *Why: a non-coder and an AI
   both lose the thread past a screenful.*
2. **Functions ≤ 60 lines.** Longer → extract a named helper. *Why: long
   functions are the #1 barrier to a safe AI edit and an unreadable diff.*
3. **One class per file** (a small dataclass/exception alongside is fine). *Why:
   file name = concept; you know what a file is without opening it.*
4. **Every file opens with a one-line docstring: what it is, what it isn't.**
   *Why: the owner reads line 1 to know they're in the right place.*
5. **No third copy of anything.** Two is a pattern; three is a bug farm. Shared
   logic lives in a named library and is imported — never re-pasted. *Why: the
   `read_env` quote-strip bug exists because a copy drifted from the original.*
6. **One source of truth for config: `stack.env` via `forge_env.read_env`.** Never
   re-parse it inline. *Why: drift bugs.*
7. **Section dividers `# ── Section ──`.** `grep "^# ──"` should give a file's
   table of contents; keep sections under ~100 lines. *Why: already the repo's
   best navigation aid — keep it.*
8. **No silent feature-disabling.** No `try: import X; HAS_X=True / except: HAS_X=
   False` that quietly turns a feature off. Fail loudly or gate at one init point.
   *Why: the project's recurring "it silently did nothing" class of bug.*

Docstring style: **Google.** Type hints on public function signatures (not full
mypy). Drop any rule the moment it stops earning its keep; add nothing else
without deleting something.

## The guardrail (system, not willpower)

**Ruff is the whole story.** After any code edit, the AI runs:
```
ruff format <changed paths> && ruff check --fix <changed paths>
```
CI runs `ruff check`, `ruff format --check`, and a **file-length gate** (fail if
any tracked `.py` > 500 lines) — the single best defense against god-files
regrowing. One-time: run `ruff format` over the whole tree in a *single* commit,
add that commit to `.git-blame-ignore-revs` so blame stays meaningful.

**Deliberately NOT adopted** (over-engineering for a solo, AI-directed project):
mypy-strict, pylint, isort/black-as-separate-tools (Ruff covers them), coverage
thresholds, dependency lockfiles, a multi-hook pre-commit framework.
