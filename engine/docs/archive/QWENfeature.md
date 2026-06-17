<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

You're absolutely right, and your instinct is spot-on. Let me be blunt about why:

## The Gimmick Test

"Add a Camera3D named MainCamera" is the **Hello World of AI demos**. It looks magical for 30 seconds, then it falls apart because:

1. **Clicking is faster than typing.** A Godot dev can add a node in 2 seconds. Prompting, waiting for prefill, reviewing the plan, confirming, watching it apply — that's 15+ seconds.
2. **LLMs are bad at spatial reasoning.** "Put the enemy spawn behind the pillar where the player can't see it" — the model has no concept of sight lines.
3. **It's the wrong abstraction layer.** Godot's editor IS the DSL for scene building. Replacing a visual tool with text is a step backward.
4. **It solves a problem nobody has.** Nobody sits at their desk thinking, "Ugh, if only I had an AI to add Node3Ds for me."

You built a **Ferrari engine** (LLM Gateway, SceneStore, ArtifactStore, GBNF grammars, budget controls) and bolted it to a **golf cart** (scene mutation). The infrastructure is begging for a problem worthy of it.

---

## What LLM Agents Are Actually Good At in Game Dev

The sweet spot is: **tedious for humans, rule-bound, text-heavy, and benefits from cross-referencing large codebases.** Not spatial. Not visual. Not clicky.

Here are five directions that would actually make game devs pay attention, ranked by how well they fit the infrastructure you've built:

### 1. 🧪 The Test Autopilot *(highest leverage, best fit)*
Read every `.gd` file in the project. Generate comprehensive **GdUnit4** tests. Run them. Read the failures. Fix the tests or the code. Iterate until green.

- **Why it's not a gimmick:** Writing tests is the #1 thing devs skip because it's boring. A test suite that writes itself is genuinely transformative.
- **Why your stack fits:** Long-running (Gateway budget), needs state awareness (SceneStore for scene-dependent tests), multi-step reasoning (DevForge planner), artifact storage (test reports).
- **Moat:** Nobody else has a persistent Godot bridge that can actually *run* the tests it writes.

### 2. 🔮 Shader & VFX Studio
Text-to-shader with live Godot preview. *"Make this material look wet when it rains"*, *"Add a dissolve effect triggered by damage"*, *"Create a holographic UI shader"*.

- **Why it's not a gimmick:** Godot's shader language is hard. Visual Shader is clunky. Artists genuinely need this.
- **Why your stack fits:** Grammar-constrained generation (GBNF for shader syntax is perfect), iterative refinement (DevForge's validate→repair loop), live preview via MCP.
- **Moat:** Tight integration with the editor's material inspector — change a parameter, see it live.

### 3. 🕵️ The Game Doctor (Autonomous Debugger)
Watch the game run. Read `logs_read` output. Detect anomalies (frame drops, null refs, physics glitches). Form a hypothesis. Instrument the code. Reproduce. Fix. Verify.

- **Why it's not a gimmick:** Debugging is the #1 time sink. An agent that can reproduce and fix bugs *while you sleep* is worth its weight in gold.
- **Why your stack fits:** Requires everything — persistent state, long budget, tool orchestration, scene awareness, log analysis.
- **Moat:** The SceneStore + versioned snapshots means the agent can *revert* its failed attempts safely.

### 4. 📜 Narrative & Dialogue Engine
Generate branching dialogue (ink/Yarn format), quest chains, item lore, NPC schedules. Cross-reference against world state so dialogue stays consistent.

- **Why it's not a gimmick:** Writing 50,000 words of branching dialogue is soul-crushing. LLMs are genuinely good at prose with constraints.
- **Why your stack fits:** SceneStore tracks which NPCs exist and what the player has done — so the agent can generate *contextually consistent* dialogue.
- **Moat:** Most narrative tools have no awareness of game state. Yours does.

### 5. ⚖️ Balance Simulator
Read your CSVs (items, enemies, abilities, economy). Run Monte Carlo simulations. Answer questions like: *"Can a level 10 player afford the endgame sword after 5 hours of farming?"* or *"Is the fire-elemental boss trivialized by the ice ring?"*

- **Why it's not a gimmick:** Every indie game ships with broken balance because playtesting is expensive.
- **Why your stack fits:** Data ingestion (MCP tools to read CSVs), computation (Python sandbox), reporting (ArtifactStore for simulation reports).
- **Moat:** Connects directly to live game data, not a stale spreadsheet.

---

## My honest recommendation

**Start with #1 (Test Autopilot).** Here's why:

- It's the fastest path to *proving* your stack is more than a demo. A 5-minute video of "I pointed DevForge at my project and it wrote 200 passing tests" will get more attention than every scene-building demo combined.
- It uses every piece of infrastructure you built, so nothing was wasted.
- It has a clear, measurable success metric (test coverage %).
- It's something you can use on *your own* Forge project immediately — dogfooding is the best filter for gimmicks.

**Then pivot to #2 (Shaders)** as the viral feature. Shaders are visual, shareable, and make for incredible demos that *aren't* gimmicks because the output is genuinely useful.

---

## The deeper question

Here's what I'd actually push back on: **maybe the problem isn't "what can it do" but "who is it for?"**

Right now, DevForge feels like a tool for *you*, the power user, to talk to your own game. That's always going to feel gimmicky because you know Godot too well — you don't need an intermediary.

The tools above become non-gimmicky the moment they're solving a problem for someone who *isn't* you:
- A **narrative designer** who can't code but wants to write branching dialogue
- A **junior dev** who's scared to write tests
- An **artist** who wants custom shaders but can't learn GLSL
- A **solo dev** who's drowning in bug reports

Which of those people do you actually want to build for? That answer will make the "what should it do" question almost answer itself.
