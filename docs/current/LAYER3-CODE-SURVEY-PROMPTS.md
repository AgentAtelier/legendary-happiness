# Layer 3 Survey — Code Health & Maintainability (for CLI AIs)

**Purpose:** get independent, concrete recommendations for making this codebase
easier to **review** (by a non-programmer owner) and easier to **navigate** (by AI
assistants). Three prompts, each run through up to four CLI AIs. Each CLI AI can
read the real repository, so the advice should be specific to *this* code.

---

## ⛔ READ-ONLY — paste this banner at the TOP of every prompt

> **THIS IS A STRICTLY READ-ONLY TASK. DO NOT MODIFY ANYTHING.**
> Do **not** edit, create, move, or delete any file. Do **not** run the
> application or any build/test command. Do **not** run any `git` command that
> changes state (no add/commit/checkout/push). Do **not** install packages or
> change configuration. You may **only read files** and produce a **written
> report** in your reply. If you are tempted to "just fix it," stop — output the
> recommendation as text instead. Treat the repository as a museum exhibit behind
> glass.

## Shared context (paste under the banner)

> This repository is a local, self-hosted toolchain that turns natural-language
> prompts into Godot game scenes. Roughly: a **`hub/`** (FastAPI ops panel) that
> orchestrates everything; an **`engine/`** (the "DevForge" generation engine)
> that the hub talks to over an **MCP / subprocess boundary** (they do *not*
> import each other); a local LLM server (llama.cpp); and a test system (an older
> set of runners in `hub/` plus a newer `hub/forge_testbench/`). The owner is a
> **non-programmer** who directs AI assistants to write all the code; the owner
> reviews changes but cannot read code deeply. **Maintainability and reviewability
> by that owner are first-class goals**, not afterthoughts.
>
> Important: several large files in `hub/` (`bench.py`, `shootout.py`,
> `scenarios.py`, `gauntlet.py`, `multi_model_bench.py`, `comprehensive_bench.py`)
> are **legacy test runners scheduled for deletion** in an in-progress migration
> to `hub/forge_testbench/`. Do **not** recommend investing in them.
>
> The owner's stated wants: keep Python files short; use functions to reduce
> duplication; adopt a **few loose conventions** (not a rigid cage); settle on
> **one architecture pattern** and stay close to it; a naming convention. The
> spirit is **an environment/system that lowers review load and eases navigation
> — not a straitjacket.**

---

## Prompt 1 — One architecture + splitting the god files

> Read this repository (read-only) and recommend **one simple, coherent
> architecture / layering** that fits the project *as it actually is* (hub
> orchestrator, engine behind an MCP boundary, a test system, supporting scripts).
> Describe it in a few sentences a non-programmer can hold in their head, and show
> where the current code already follows it versus where it muddies it.
>
> Then tackle the **god files**. The largest long-lived ones are
> `engine/devforge/platform/mcp_server.py` (~2150 lines), `hub/hub.py` (~1940),
> `engine/devforge/compilation/pipeline/engine.py` (~1440), and
> `engine/devforge/execution/godot_ai_mcp.py` (~1080). For each, propose
> concretely **how to split it along the architecture's natural seams** — what the
> resulting modules would be, each module's single responsibility, and a **safe
> order** to do the splits in (lowest risk first). Skip the legacy test runners
> noted above.
>
> Optimize for the smallest set of boundaries that buys the most clarity for a
> non-coder owner directing AI. What am I not asking that I should be?

## Prompt 2 — A short conventions guide (files, functions, naming, the few rules)

> Read this repository (read-only) and propose a **SHORT conventions guide — a
> handful of rules, not a style bible** — tuned for code that is reviewed by a
> non-programmer and maintained by AI assistants. Cover:
> 1. **File & function length:** a sensible maximum, and *where the code already
>    exceeds it* (name files/functions with line counts).
> 2. **Duplication → functions:** the most valuable repeated logic to collapse
>    into shared helpers — point at **real examples** in the code.
> 3. **Naming convention** for files, functions, and modules — and where current
>    names mislead or are fossils (call them out specifically).
> 4. **The minimal set of "loose rules"** actually worth standardizing.
>
> For each rule give a **one-line rationale**. The goal is the *fewest* rules that
> most reduce cognitive load — explicitly **not** a rigid cage; if a rule wouldn't
> earn its keep for a solo non-coder project, leave it out. What am I not asking
> that I should be?

## Prompt 3 — The review & navigation "environment" (system, not willpower)

> Read this repository (read-only). The owner is a non-programmer who reviews
> AI-written changes and needs the codebase to be **(1) easy to review** and
> **(2) easy for AI assistants to navigate**. Recommend the **lightweight system**
> — not discipline, not a cage — that delivers this. Consider:
> - **Structural signals** that make a file's purpose obvious at a glance (module
>   docstrings, consistent entry points, a top-level architecture map / index,
>   predictable file placement).
> - **Reviewability:** what makes a diff understandable to someone who can't read
>   code deeply (commit size/shape, what to summarize, what to surface).
> - **Automated guardrails** that *enforce the few conventions so humans don't have
>   to police them* — e.g., a formatter, a linter, simple checks — chosen for the
>   **most relief per unit of setup and ongoing burden** (this owner can't babysit
>   tooling).
>
> Prioritize concretely and point at real files. Recommend only what a non-coder,
> AI-directed project will actually sustain. What am I not asking that I should be?

---

## How to use the answers
Bring the responses back. They'll be reconciled against the real codebase (some
CLI AIs will over-engineer for a solo project), and the good parts folded into a
short conventions doc + an architecture ADR + a god-file split plan — handed to
the implementing AI, owner-approved before any code moves.
