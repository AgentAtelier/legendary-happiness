# ADR 001 — Single monorepo + `engine` rename

**Date:** 2026-06-17
**Status:** Accepted

## Context
The project lived in a ~387 MB folder that was not under version control at the
top level, while one sub-folder (`devforge_review_package`) carried its own
nested `.git` with only 2 commits of history — and those commits already tracked
~5.7 MB of PDFs. Documentation, code, a 169 MB `legacy/` archive, two
virtualenvs, and research PDFs were all mixed together.

We surveyed four external AIs on version-control strategy. All four recommended a
single monorepo and `git subtree` to preserve the engine's history.

## Decision
1. **One monorepo** at the project root (`AgentAtelier/legendary-happiness`).
2. **Start the history fresh** rather than `git subtree`-importing the engine.
   The engine's nested repo had only 2 commits and they carried PDF bloat;
   preserving them wasn't worth dragging binaries into permanent history. The old
   `.git` was saved as a backup bundle (`~/engine-history-*.bundle`).
3. **Rename `devforge_review_package` → `engine`.** The old name was a fossil
   that misled every reader (human and AI) about what the folder is.
4. **`.gitignore` written before the first `git add`** — excludes venvs, caches,
   databases, `*.gguf`, Godot caches, the PDFs, and `legacy/`. Result: `.git` is
   ~2 MB for a 387 MB working tree.

## Consequences
- All references to the old path were updated: 3 live code paths, 7 docstrings,
  and the critical `~/.config/forge-stack/stack.env` `DEVFORGE_DIR`.
- The engine's pre-import history is archaeology only, recoverable from the
  backup bundle.
- `legacy/` and the PDFs stay on disk but out of git; back them up separately.
