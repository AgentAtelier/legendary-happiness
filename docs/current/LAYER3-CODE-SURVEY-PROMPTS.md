# Layer 3 Survey — Code Health & Maintainability (for CLI AIs)

**Purpose:** independent, concrete recommendations for making this codebase easier
to **review** (by a non-programmer owner) and easier to **navigate** (by AI
assistants). One self-contained prompt block, run through up to four CLI AIs. Each
AI reads the real repo and writes its findings into its **own** report file.

---

## How to run this (the one thing YOU do)

1. Open the **PROMPT BLOCK** below.
2. Find the single line `OUTPUT FILE: docs/reviews/layer3/response-codex.md` and
   change `codex` to the AI you're about to use — `gemini`, `claude`, `cursor`,
   etc. **You set the filename; never rely on the AI to name its own file.** Give
   each AI a *different* name.
3. Paste the whole block into that CLI AI. It will read the repo, write that one
   file, and reply with a single line (the path).
4. Repeat for each AI, changing the filename each time.

That's it. The block is self-contained — the report structure is inlined, so the
AI never needs to open this folder or any template, which is what stops them from
overwriting each other's reports.

---

## PROMPT BLOCK — paste everything between the lines

```
============================ COPY FROM HERE ============================
READ-ONLY CODE REVIEW — ONE PERMITTED WRITE.

You are reviewing a code repository. This task is READ-ONLY. The ONLY change you
may make anywhere is writing your report to ONE file:

    OUTPUT FILE:  docs/reviews/layer3/response-codex.md

Create that exact file and write your report into it. Hard rules:
- Do NOT edit, create, move, rename, or delete ANY file except the OUTPUT FILE.
- Do NOT open, read, or list any OTHER file inside docs/reviews/. Other
  reviewers' reports live there; they are OFF-LIMITS — never touch them. You do
  not need anything from that folder.
- Do NOT run the app or any build/test command. Do NOT run any state-changing
  git command (no add/commit/checkout/restore/push). Do NOT install anything.
- You MAY read any source/code/config file elsewhere in the repo. Put ALL your
  findings IN THE OUTPUT FILE, not in chat. Your chat reply must be a single
  line: the path you wrote. Sparse chat output is not collected — be thorough in
  the file.

CONTEXT:
This repository is a local, self-hosted toolchain that turns natural-language
prompts into Godot game scenes. Roughly: a `hub/` (FastAPI ops panel) that
orchestrates everything; an `engine/` (the "DevForge" generation engine) that the
hub talks to over an MCP / subprocess boundary (they do NOT import each other); a
local LLM server (llama.cpp); and a test system (older runners in `hub/` plus a
newer `hub/forge_testbench/`). The owner is a NON-PROGRAMMER who directs AI
assistants to write all the code and reviews changes but cannot read code deeply.
Maintainability and reviewability by that owner are first-class goals.

NOTE: several large files in `hub/` (`bench.py`, `shootout.py`, `scenarios.py`,
`gauntlet.py`, `multi_model_bench.py`, `comprehensive_bench.py`) are LEGACY test
runners scheduled for deletion in an in-progress migration to
`hub/forge_testbench/`. Do NOT recommend investing in them.

The owner wants: short Python files; functions to cut duplication; a FEW loose
conventions (not a rigid cage); ONE architecture pattern to stay close to; a
naming convention. The spirit is an environment that lowers review load and eases
navigation — NOT a straitjacket. Recommend only what a solo, non-coder,
AI-directed project will actually sustain; flag over-engineering.

DO ALL THREE TASKS. Reference real code as path/to/file.py:line.

TASK 1 — One architecture + god-file splits.
Recommend ONE simple, coherent architecture/layering that fits the project AS IT
ACTUALLY IS (hub orchestrator, engine behind an MCP boundary, a test system,
supporting scripts), described in a few sentences a non-programmer can hold in
their head. Show where the code follows it vs. muddies it. Then, for each of the
long-lived god files — engine/devforge/platform/mcp_server.py (~2150 lines),
hub/hub.py (~1940), engine/devforge/compilation/pipeline/engine.py (~1440),
engine/devforge/execution/godot_ai_mcp.py (~1080) — propose concretely how to
split it along the architecture's seams: the resulting modules, each module's
single responsibility, and a SAFE order (lowest risk first). Skip the legacy
runners above. End with: what am I not asking that I should be?

TASK 2 — A short conventions guide.
Propose a SHORT conventions guide (a handful of rules, not a style bible) for code
reviewed by a non-programmer and maintained by AI. Cover: (a) sensible file &
function length limits, plus where the code already exceeds them (name
files/functions with line counts); (b) the most valuable duplication to collapse
into shared functions (point at real examples, path:line); (c) a naming
convention for files/functions/modules, and any misleading or fossil names to
fix; (d) the minimal set of "loose rules" worth standardizing. One-line rationale
per rule; drop any rule that wouldn't earn its keep for a solo non-coder project.
End with: what am I not asking that I should be?

TASK 3 — The review & navigation "environment" (system, not willpower).
Recommend the lightweight SYSTEM that makes the codebase (1) easy to review for a
non-coder and (2) easy for AI assistants to navigate. Consider: structural
signals that make a file's purpose obvious at a glance (module docstrings,
consistent entry points, a top-level architecture map/index, predictable file
placement); what makes a diff understandable to someone who can't read code
deeply; and automated guardrails (formatter, linter, simple checks) that ENFORCE
the few conventions so humans don't police them — chosen for the most relief per
unit of setup and ongoing burden (this owner can't babysit tooling). Point at
real files. End with: what am I not asking that I should be?

WRITE THE OUTPUT FILE WITH EXACTLY THIS STRUCTURE:

    # Layer-3 Code-Health Review — <name of the AI you are>
    (date, and which tasks you answered)

    ## Task 1 — Architecture + god-file splits
    ### Recommended architecture
    ### Where the code follows it vs. muddies it
    ### God-file split plan (per file: target modules, responsibility, risk order)
    ### What you're not asking that you should be

    ## Task 2 — Conventions guide
    ### File & function length (+ offenders with line counts)
    ### Duplication to collapse (real path:line examples)
    ### Naming convention (+ fossil names to fix)
    ### Minimal loose rules (each + one-line rationale)
    ### What you're not asking that you should be

    ## Task 3 — Review & navigation environment
    ### Structural signals
    ### Reviewable diffs for a non-coder
    ### Automated guardrails (most relief per setup)
    ### What you're not asking that you should be

    ## Cross-cutting / anything else

After writing the file, reply in chat with ONLY the file path. Nothing else.
============================= TO HERE ==================================
```

---

## How to use the answers
Each reviewer's file lands in `docs/reviews/layer3/`. The responses get reconciled
against the real codebase (some CLI AIs over-engineer for a solo project), and the
good parts folded into a short conventions doc + an architecture ADR + a god-file
split plan — handed to the implementing AI, owner-approved before any code moves.
