# Next-Phase Direction + Survey — Visual Evaluation & the Reliability Loop

**Date:** 2026-06-17 · Status: direction agreed in brainstorming; gathering
outside input before a design spec.

## The direction (one loop, not four ideas)

The next vertical slice gives the system **eyes**, and folds the reliability
concerns into one coherent loop:

> **Condition well (A) → generate → rate it visually (VLM) → gate on quality,
> retry/escalate if it collapsed (B).**

- **Keystone — Visual evaluation.** A local **vision model (VLM)** rates a
  generated scene from a screenshot (richness / coherence / "does it match the
  request", 0–100). This is the missing half of the project: everything we built
  *generates*; nothing *judges the visual result*. First use: finish the richness
  verdict (which stalled because we couldn't capture/evaluate visuals). Then: a
  standing visual quality gate, and the seed of the future **asset-pipeline**
  evaluator.
- **A — System owns the conditioning.** The richness/quality framing ("be
  ambitious, varied, coherent") lives in the system's **planner prompts**, not the
  user's. Audit every planner/system prompt so a plain, task-only request from the
  non-coder owner reliably gets the best output — **no magic words required.**
  *(Born from: a neutral prompt → thin output; only an added "be rich" instruction
  unlocked 3–4× more. The owner should never have to know the incantation.)*
- **B — Collapse / quality gate.** Detect when a generation degrades (engine-
  variety collapse, low VLM rating, incoherence) and **signal / retry / escalate**
  (e.g., to a bigger model). The VLM rater is the visual **sensor** for this gate.
  *(Born from: the 4B "collapsed" under a demanding instruction while the 27B
  stayed consistent; the owner wants the system to detect-and-signal, not silently
  ship degraded output.)*
- **Principle (4).** Prefer **integrating existing tools** (a local VLM; Odysseus's
  RAG) over building from scratch. RAG's real home is later (asset selection, the
  teacher mode), not now.

**The central risk to interrogate:** this adds *another stochastic model* (the
VLM judge) to a system already worried about model brittleness. The defense is
that *judging is a safer use of a model than generating*, and a judge can be
**calibrated** (tested against known-good/known-bad scenes + human spot-checks).
The survey below stress-tests that.

---

## Survey A — Chat AIs (concept) · 2 prompts, run through 4 chat AIs each

Paste the **Shared Context** first, then one prompt. Prepend a **lens** per chat
to get varied answers. They're adversarial on purpose.

### Shared Context (paste above either prompt)
> I'm the non-programmer owner of a local, self-hosted toolchain that turns
> natural-language prompts into Godot 3D game scenes. Architecture bet:
> deterministic code owns anything with a single correct answer (geometry,
> wiring, physics) and is model-independent; the LLM only authors an open-ended
> "brief" that a deterministic engine turns into the scene. Everything runs
> locally on a 16 GB GPU with quantized open-weight models (qwen 4B–27B); I direct
> AI assistants who write the code. Recent finding: a *neutral* planner prompt
> produced thin output from both 4B and 27B; adding one instruction — "be
> ambitious, use many regions and a variety of engines" — tripled the richness for
> both, and the small model became erratic (sometimes rich, sometimes collapsed)
> while the big one stayed consistent. This unsettled me: output quality depends
> heavily on prompt phrasing, which is fragile for a tool. Think from scratch and
> tell me where I'm wrong.

### Prompt A1 — The VLM-as-judge
> I want to add a **local vision model** that looks at a screenshot of a generated
> 3D scene and rates it (richness, coherence, "does it match the request") — both
> to evaluate output automatically and, later, to judge generated assets. Make the
> strongest case **against** this. In particular: am I just adding a second
> unreliable model to judge the first ("two stochastic things rating each other")?
> Is judging genuinely more reliable than generating, or is that wishful? How
> would I **calibrate** a local VLM judge so its scores are trustworthy and stable,
> on a 16 GB GPU where it can't run alongside the text model? What failure modes
> make this worse than no automated visual eval at all? Give a ranked pre-mortem
> (it's two years later and this judge misled the project — why?), and end with the
> single change that would make it trustworthy. No hedging.

### Prompt A2 — The reliability loop (conditioning + collapse detection)
> Two related ideas I want attacked. **(A)** Since output depends on prompt
> phrasing, I want the *system* to own the good phrasing — bake the "be rich,
> varied, coherent" framing into the system's planner prompts so a plain
> task-only request from me always gets the best output, no magic words. **(B)** I
> want the system to **detect when a generation collapsed/degraded** (e.g. a small
> model that followed part of an instruction and dropped the rest) and signal /
> retry / escalate to a bigger model, rather than silently shipping the bad
> result. My naive wish was "the AI should always give its best"; I now understand
> there's no hidden effort dial — but I want the *tool* to behave as if there is.
> Is this the right goal, and is it achievable? What's the strongest objection?
> How do real systems handle prompt-brittleness and quality-gating of stochastic
> generators? What am I not seeing? Ranked pre-mortem + the single highest-value
> change. No hedging.

### Lenses (prepend one per chat, to diverge the answers)
- *"You are an ML/eval researcher who studies LLM-as-judge and its failure modes."*
- *"You are a solo indie dev who ships on tiny local hardware and hates added complexity."*
- *"You are a production ML engineer who has built model-quality gates and fallbacks."*
- *"You are a technical artist who judges 3D scene quality for a living."*

---

## Survey B — CLI AIs (codebase-grounded) · 1 prompt, run through 3 CLI AIs

These read the real repo. **Read-only on the code; the only write is each one's
own report file** (the scheme that finally worked in Layer 3).

### How to run (the one thing YOU do)
Before pasting into each CLI AI, change `codex` in the OUTPUT FILE line to that
AI's name (`gemini`, `claude`, `cursor`…). You set the filename — never the AI.

```
============================ COPY FROM HERE ============================
READ-ONLY CODE REVIEW — ONE PERMITTED WRITE: your report file.

You are reviewing a repository to recommend HOW to build a feature. This is
READ-ONLY on the code. The ONLY change you may make is writing your report to:

    OUTPUT FILE:  docs/reviews/visual-eval/response-codex.md

Hard rules: do NOT edit/create/move/delete any file except that OUTPUT FILE; do
NOT open/read/list any OTHER file in docs/reviews/ (other reviewers' reports are
off-limits); do NOT run the app/tests or any state-changing git command; do NOT
install anything. You MAY read any source/config file. Put ALL findings in the
OUTPUT FILE; chat reply = one line (the path).

READ FIRST: docs/decisions/003-approach-survey-and-world-state-gap.md,
docs/current/NEXT-PHASE-VISUAL-EVAL-SURVEY.md (this file — the direction),
docs/current/CONVENTIONS.md, docs/reviews/world-state-richness/RESULT.md.

CONTEXT: a hub (FastAPI, port 8003) orchestrates a DevForge engine
(engine/devforge/) over MCP; the engine builds Godot scenes via a godot-ai MCP
bridge (port 8000) and uses a local llama.cpp model (port 8002, 16 GB GPU). A
unified test chassis lives in hub/forge_testbench/. We want to add VISUAL
EVALUATION (a local vision model rates a scene screenshot) plus a reliability loop
(A: system-owned planner prompts; B: a collapse/quality gate). Recommend HOW,
grounded in THIS code. Reference real files as path:line.

DELIVER (ranked, concrete, smallest-viable-first):
1. SCREENSHOT CAPTURE — today, editor_screenshot source=viewport returns an EMPTY
   editor view (the world builds — 1000s of ops — but the editor camera isn't
   framed on it). Find where this should be fixed (executor / godot-ai tools like
   camera_manage/game_manage) and how to get a framed, repeatable shot of the
   built scene.
2. LOCAL VLM INTEGRATION — how to add a local vision model under 16 GB VRAM
   alongside the text model (swap vs separate pass), reusing the existing model-
   swap machinery (hub/forge_ops.py swap_model) and config (stack.env).
3. TESTBENCH WIRING — how a visual rating plugs into hub/forge_testbench/ as a
   typed Metric / a new Test category (see metric.py, test.py, runner.py).
4. A — where system-owned conditioning belongs (the planner prompts, e.g.
   engine/devforge/spatial/world_planner.py) and how to keep it from one place.
5. B — where a collapse/quality gate hooks into the apply_spec pipeline
   (engine/devforge/platform/mcp_server.py, .../compilation/pipeline/engine.py) to
   detect a degraded generation and retry/escalate.
End with: what am I not asking that I should be?

Write the report to the OUTPUT FILE with one section per item 1–5 plus the final
question. Reply in chat with only the file path.
============================= TO HERE ==================================
```

---

## How to use the answers
Chat answers + the 3 CLI reports come back here; I reconcile them against the real
code (some will over-engineer), keep the gold, and turn it into a design spec for
the visual-evaluation slice + the A/B reliability loop — owner-approved before any
code moves.
