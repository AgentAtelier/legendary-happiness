# Layer 1 Survey — Neutral Prompts for Outside AIs

**Purpose:** get fresh, independent input on how to set up the project workspace
(version control, structure, docs, IDE, orientation) *before* we reorganize.
Paste the **Shared Context** block first, then **one** focused prompt. Keep each
conversation to a single subject. The prompts are written to invite disagreement —
if there's a better approach than we're assuming, we want to hear it.

---

## Shared Context (paste this above any prompt below)

> I'm the owner of a local, self-hosted toolchain that turns LLM prompts into
> Godot game scenes — I direct AI assistants who write the code; I am **not** a
> programmer myself. The project grew organically and now lives in one ~387 MB
> folder on a Linux machine. Its parts:
> - a web **hub** (Python/FastAPI) that orchestrates everything (also holds ~9
>   one-off benchmark/test scripts mixed in with the app);
> - a generation **engine** (Python, currently in a folder confusingly named
>   `devforge_review_package`, ~151 MB, carrying ~18 MB of PDF research reports
>   and its own virtualenv);
> - a local **LLM server** (llama.cpp) and **Godot** integration;
> - a **`legacy/`** archive (~169 MB, ~half the folder);
> - **~34 markdown docs** scattered across three directories (stage handoffs,
>   plans, audits, roadmaps), with no separation of current vs. historical;
> - two Python virtualenvs, build caches, and a small database file.
>
> Version control is half-set-up: the top level is **not** a git repo, but the
> engine sub-folder has **its own nested `.git`**.
>
> My goals: (a) use version control properly, (b) open the project in an IDE
> (PyCharm) and actually understand and navigate it, (c) keep it maintainable as
> it keeps growing. Please think from scratch — if you'd set this up
> fundamentally differently than I'm assuming, say so.

---

## Prompt 1 — Version control strategy

> Given the setup above, how should I structure version control? The top level
> isn't a repo yet, and one sub-folder (the engine) already has its own `.git`.
> Should this be a single repository or multiple? How do I handle the existing
> nested repo without losing its history? What belongs in `.gitignore`
> (virtualenvs, caches, the ~18 MB of PDFs, the 169 MB `legacy/` archive, a
> database file)? What branching/commit habits make sense for a solo,
> non-programmer owner who directs AI coders? What would you recommend, what are
> the tradeoffs, and what am I not asking that I should be?

## Prompt 2 — Directory structure & project layout

> Given the setup above, how should the folders be organized so the project is
> navigable and maintainable? Specifically: where should the live app, the
> engine, shared utilities, tests, one-off benchmark scripts, generated data, and
> the `legacy/` archive each live? How should I handle a top-level folder that is
> badly named (`devforge_review_package` is actually the live engine)? Is a
> conventional Python project layout (e.g. a `src/` layout, separate packages)
> appropriate here, or is there something better for a multi-service local
> toolchain? What would you recommend, what are the tradeoffs, and what am I not
> asking that I should be?

## Prompt 3 — Documentation organization

> The project has ~34 markdown documents scattered across three directories:
> stage handoffs, design plans, audits, roadmaps, test results — with no
> separation between what's current and what's historical. As a non-programmer
> owner, I need to be able to find the current state of things and not drown in
> superseded docs. How should I organize, name, and prune project documentation
> so it stays useful as the project moves quickly? Should there be a single index,
> an archive convention, status markers, or something else? What would you
> recommend, what are the tradeoffs, and what am I not asking that I should be?

## Prompt 4 — IDE setup for a non-coding owner

> I want to open this multi-service Python project (multiple virtualenvs, a web
> hub, an engine, tests) in an IDE — PyCharm — not to write code, but to **see
> and understand** what's there, navigate it, and observe what my AI assistants
> change. I'm not looking for a plugin shopping list; I want to know the right way
> to set up the IDE so a non-programmer can stay oriented: how to handle multiple
> virtualenvs/interpreters, how to keep the project view clean (hiding caches and
> archives), how to find my way around unfamiliar code, and how to run/observe the
> services. Is an IDE even the best tool for that goal, or is there something
> better? What would you recommend, what are the tradeoffs, and what am I not
> asking that I should be?

## Prompt 5 — Staying oriented as the project moves

> I'm a non-programmer owner directing AI assistants on a fast-moving project, and
> I keep losing the thread of how it all fits together. What is the best **durable
> artifact or practice** for keeping a person like me oriented — an architecture
> map, a maintained README index, a glossary of the key files and their jobs, a
> regular "state of the project" summary, or something else entirely? How do I
> keep it from going stale, given the code changes faster than docs usually do?
> What would you recommend, what are the tradeoffs, and what am I not asking that
> I should be?

---

## How to use the answers
Bring the responses back here. I'll reconcile them against what I can see in the
actual folder, flag where they agree/disagree, and fold the good ideas into the
reorganization proposal — which you approve before any files move.
