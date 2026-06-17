# Layer 3 Survey — Code Health & Maintainability (for CLI AIs)

**Purpose:** get independent, concrete recommendations for making this codebase
easier to **review** (by a non-programmer owner) and easier to **navigate** (by AI
assistants). Three prompts, each run through up to four CLI AIs. Each CLI AI can
read the real repository, so the advice should be specific to *this* code — and
each writes its findings into its **own report file** (CLI agents are terse in
chat; the substance must land in a file).

---

## ⛔ READ-ONLY ON THE CODE — ONE PERMITTED WRITE: YOUR REPORT FILE

> Paste this banner at the TOP of every prompt.
>
> **This is a READ-ONLY review of the code. The ONLY thing you may write is your
> own report file.**
> - Do **not** edit, create, move, or delete any file in the project **except** the
>   single response file described under "Where to write your answer" below.
> - Do **not** run the application or any build/test command. Do **not** run any
>   state-changing `git` command (no add / commit / checkout / push / restore).
>   Do **not** install packages or change configuration.
> - You **may read any file.** You **must** put your findings **in your report
>   file, not in chat** — your chat reply can be a single line pointing to the
>   file. Be thorough in the file; sparse chat output is not collected.
> - Treat all code as a museum exhibit behind glass. The report file is the only
>   thing you touch.

## Where to write your answer

> Copy the template `docs/reviews/layer3/_TEMPLATE.md` to a new file named with
> **your** name:
>
> ```
> docs/reviews/layer3/RESPONSE-<your-name>.md
> ```
> e.g. `RESPONSE-codex.md`, `RESPONSE-gemini.md`, `RESPONSE-claude.md`,
> `RESPONSE-cursor.md`. Fill in only the prompts you were asked. Reference real
> code as `path/to/file.py:line`. **This file is the only file you may create or
> write.**

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
>
> **→ Write your full answer into the "Prompt 1" section of
> `docs/reviews/layer3/RESPONSE-<your-name>.md`. Keep your chat reply to one line.**

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
>
> **→ Write your full answer into the "Prompt 2" section of
> `docs/reviews/layer3/RESPONSE-<your-name>.md`. Keep your chat reply to one line.**

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
>
> **→ Write your full answer into the "Prompt 3" section of
> `docs/reviews/layer3/RESPONSE-<your-name>.md`. Keep your chat reply to one line.**

---

## How to use the answers
Each reviewer's file lands in `docs/reviews/layer3/`. The responses will be
reconciled against the real codebase (some CLI AIs will over-engineer for a solo
project), and the good parts folded into a short conventions doc + an architecture
ADR + a god-file split plan — handed to the implementing AI, owner-approved before
any code moves.
