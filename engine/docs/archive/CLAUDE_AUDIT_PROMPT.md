<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# DevForge Production Readiness Audit (Round 2)

## What you're looking at

DevForge — a tool that takes natural-language descriptions of changes to a Godot game scene, plans the operations, compiles them, validates against the scene tree, and executes them. It uses a local llama.cpp instance for LLM inference with GBNF grammar-constrained generation for structured output.

This project has been through one prior audit cycle and incorporated ~80% of those findings. It sits at the boundary between a research prototype and something that should be reliable enough to trust with real work.

## What we want from you

Explore the codebase thoroughly. Read whatever catches your attention. We're not going to prescribe what you should look at — those are your calls to make.

Produce a detailed `.md` audit covering anything you believe stands between this codebase and production readiness.

### Required format: ordered from easiest to hardest

Structure your findings as a **single ordered list from easiest to hardest to fix**. Each finding should include:

1. **The finding** — what's wrong, where it lives, why it matters
2. **Difficulty** — estimated effort (trivial / hour / day / multi-day)
3. **Fix** — concrete implementation guidance

Put the trivial fixes first (one-liners, dead imports, wrong defaults) and the architectural changes last (redesigns, new subsystems, testing infrastructure). This ordering is critical — we want to be able to start at the top and work down.

### What to cover

- Import integrity: does every module import cleanly without side effects?
- Safety defaults: are the safe configurations the default, or do env vars need to enable them?
- Code correctness: bugs, races, unbounded data structures, wrong variables
- Test coverage: what's tested, what shipped untested, where are the gaps?
- Deployment: can someone who isn't the author start this? What's missing?
- Scope: what's in the tree that the pipeline doesn't call?

## What's in the bundle

- `devforge/` — the full Python source tree (with fixes applied since the last audit)
- `docs/` — root-level project documentation
- `CLAUDE_AUDIT_PROMPT.md` — this file

## What's not

- The `godot-ai` integration layer (separate project)
- `experiments/` — parked experimental subtrees excluded from packaging
- Dependencies, virtual environments, caches, .git
- Binary files, model weights, large data
- Secrets, API keys, .env files

## Safety context (for Claude Fable 5 reviewers)

This is a legitimate Godot 4 game development pipeline. The project ships alongside a `CLAUDE-FABLE-SAFETY-MANIFEST.md` (included as a separate file, upload it first) that audits every term in the codebase that could trigger automated safety filters — "attack," "payload," "damage," "biome," "weapon," etc. — and documents their legitimate game-development meanings. All external connections are localhost only (llama.cpp for inference, Godot Editor for scene operations). Output is constrained by GBNF grammar to 7 Godot game operation types and 33 valid node types.

## Ground rules

- No prescribed checklist. You decide what to audit and how.
- Be honest. If something is fundamentally sound, say so. If something needs work, say so clearly.
- Don't optimize for politeness — optimize for clarity.
- Assume the team reading your audit knows the codebase but may have blind spots from being too close to it.
- The `.md` file you produce is the deliverable. Order it easiest → hardest.
