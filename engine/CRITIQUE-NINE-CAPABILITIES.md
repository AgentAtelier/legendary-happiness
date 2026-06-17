# Critique: The Nine-Capability Roadmap for DevForge

**Date:** June 11, 2026
**Author:** Buffy (Codebuff) — strategic analysis against project reality
**Subject:** An AI's proposed feature roadmap claiming 9 capabilities, 8 with time estimates, 4 rated "very high" or "high" value

---

## TL;DR

The AI's roadmap is **directionally insightful but temporally delusional**. It describes capabilities that would be genuinely useful but estimates them as if they'll work on the first try. Our history says otherwise: 38 bugs across 7 hardening rounds just to get *node creation* working. Triple every estimate, discard two capabilities entirely, and you have something actionable.

The AI's biggest blind spot: it never once mentions that the "brain" behind all these capabilities is **Gemma 4B active parameters** — a model that needed 5 phases of grammar constraints, deterministic post-filters, and retry logic just to emit parseable JSON.

---

## The Project Reality (What the AI Didn't See)

Before evaluating individual proposals, understand the actual constraints:

| Constraint | Reality |
|-----------|---------|
| **LLM quality** | Gemma 4B active (MoE, 26B total). It hallucinates Godot 3 types, emits empty deltas as valid answers, and needs grammar-constrained output to produce parseable JSON. |
| **LLM latency** | 30–120 seconds per call on local llama.cpp. A "tight feedback loop" is physically impossible. |
| **Pipeline architecture** | One LLM call per request. Deterministic compiler after that. No multi-turn, no conversation, no observation loop. |
| **Bug rate** | 38 bugs found across 7 rounds. Every new MCP capability will introduce 5–10 integration bugs, each taking hours to diagnose. |
| **The user's own words** | "Practically unusable and only useful for a very limited scope." "Might save an hour over an entire game." |
| **What actually works** | Create nodes, set properties, attach scripts, rename/delete nodes. All via batch_execute. Scene hierarchy reads work. That's it. |

---

## Capability #1: Live Debugging

**AI's claim:** "Read Godot's error console, fix scripts." ~5 hours. "Very high" value.

### ✅ AGREED — on direction and value

This IS the highest-value capability on the list. The AI is right that the MCP bridge already gives us access to Godot's output — godot-ai has `logs_read` on its 40-tool list. The core insight is correct: piping errors back to the LLM and asking it to suggest fixes is a natural extension of what already works.

> ⚠️ **Caveat:** `logs_read` was confirmed present on the 40-tool godot-ai inventory during the investigation session, but its *output format* was never examined. It may return raw text, structured JSON, or a streaming log buffer. Parsing logic may be needed before the tool is usable in a pipeline. This is precisely the kind of integration assumption the document criticizes — verify before building on it.

### ❌ DISAGREED — on the estimate (by 3–4×)

Five hours assumes you can just "pipe Godot's error console back to the agent and add a 'fix errors' tool" and everything works. Here's what actually needs to happen:

1. **Error format parsing.** Godot's error output includes stack traces with line numbers, file paths, and error types. The LLM needs these parsed into structured context — not just dumped as raw text that eats the 24K token budget.

2. **File-to-error matching.** An error at `player.gd:42` means the LLM needs *that exact file's contents at that exact line* in context. The ContextAssembler currently ranks files by keyword relevance, not by error location. New assembly logic needed.

3. **Fix injection.** The AI says "fix it." But fixing a GDScript error means *editing* an existing file, not creating a new one. DevForge's pipeline creates files — surgical editing is capability #4 on this same list, rated at ~8 hours. So live debugging *depends on* surgical editing, which means the ~5 hour estimate is already wrong by at least the cost of that dependency.

4. **Error categorization.** Not all errors are fixable by an LLM. "Invalid call to function 'move_and_slide'" might be a missing `super._physics_process()` call — but it might also be a type mismatch, a missing node reference, a scene configuration issue, or a Godot engine bug. The LLM needs to know which errors it can fix and which it should report as "needs human attention."

5. **The re-run cycle.** After the fix is applied, someone (or something) needs to re-run the scene and check if the error is gone. The AI imagines an automatic loop. In practice: 30–120 seconds for the LLM call + 15 seconds for Godot to recompile + however long it takes to trigger the error condition again. A single debug cycle is 2–5 minutes minimum. Five errors = 15–25 minutes of waiting.

**Realistic estimate: 15–20 hours.** And "fix errors" will work for ~40% of common error patterns. The other 60% will need a human.

---

## Capability #2: Consistency Auditing

**AI's claim:** "Scan scene tree for problems like orphaned nodes, missing scripts." ~3 hours. "High" value.

### ✅ AGREED — on concept and feasibility

This is genuinely achievable and useful. The scene tree is already accessible via `scene_get_hierarchy`. Rule checking is deterministic pattern matching — exactly what LLMs are good at and exactly what can be done without an LLM at all.

### ✅ AGREED — on the estimate (approximately)

Three hours is reasonable *if* you implement this with hardcoded rules (not LLM-driven analysis). The alternative — asking the LLM "are there any problems?" — is a token-budget disaster (the scene tree alone could be 5K+ tokens) and unreliable (the LLM will flag false positives and miss real problems).

### ❌ DISAGREED — on one key assumption

The AI says "collision shapes without siblings, orphaned nodes, missing scripts that are referenced, signals declared but never connected, physics bodies with zero mass." These are NOT free rules — each one requires encoding Godot-specific domain knowledge:

- **Collision shapes without siblings:** Need to know that `CollisionShape3D` must be a child of a `CollisionObject3D` (or descendant class). This is a Godot convention, not a generic graph property.
- **Signals declared but never connected:** Need to parse GDScript `signal` declarations AND `.tscn` connection data. This is non-trivial parsing.
- **Physics bodies with zero mass:** Need to know which node types have a `mass` property and what the dangerous range is.

Each rule is a small project. The AI's ~3 hours assumes these rules are already written. In reality: 1–2 hours per rule × 5–10 useful rules = 5–20 hours for a useful rule set.

**Realistic estimate: 8–12 hours** for a useful first pass with 5–8 well-chosen rules. But the core idea is correct: this doesn't need LLM intelligence, just graph traversal with Godot-specific predicates.

---

## Capability #3: Batch Property Editing

**AI's claim:** "Make all OmniLight3Ds use warm colors." ~2 hours. "Medium" value.

### ✅ FULLY AGREED

This is the one capability on the list that is genuinely low-hanging fruit. It maps directly to the existing `batch_execute` pipeline:

1. Query `scene_get_hierarchy` → get all nodes
2. Filter by type (`OmniLight3D`)
3. Generate `set_property` commands for each
4. Send via `batch_execute`

This is what DevForge was *built* to do. The translation layer (`_translate_ops_to_commands`) already handles `set_property`. The scene hierarchy is already readable. The only new code is the filter-and-batch-loop logic.

**Realistic estimate: 2–4 hours.** This should be the *first* thing built after live-stack verification.

### 💡 WORTH MORE THAN "MEDIUM"

The AI undervalues this. Batch property editing is a workflow multiplier. One command replaces 5–20 minutes of clicking through nodes in the Godot editor. Over a project, this saves real time. Upgrade to "high" value.

---

## Capability #4: Surgical Script Editing

**AI's claim:** "Add coyote time to the existing player.gd." ~8 hours. "Very high" value.

### ❌ STRONGLY DISAGREED — on feasibility, estimate, and premise

This is where the AI's optimism becomes actively misleading. Let me be blunt: **surgical GDScript editing with a 4B active parameter model will not work reliably.**

Here's why the AI is wrong at every level:

**Wrong about the problem.** The AI says "The LLM just needs to be prompted differently and given the current file contents as context." This frames surgical editing as a *prompting problem*. It is not. It is a **code understanding problem**. Inserting coyote time into player.gd means:

1. Understanding the existing movement logic (what variables control jump timing? is there already a `coyote_timer`? does the code use `_physics_process` or `_process`?)
2. Finding the right insertion point (after variable declarations, inside the jump logic, before the `move_and_slide` call)
3. Writing valid GDScript that doesn't break indentation, doesn't shadow variables, doesn't introduce type errors
4. Not breaking any OTHER code in the file

These are semantic reasoning tasks. Gemma 4B active cannot do them reliably. We have 38 bugs proving it can barely emit parseable JSON with grammar constraints. Asking it to understand GDScript control flow is like asking a calculator to write poetry.

**Wrong about the mechanism.** The AI says godot-ai "has script editing tools." Even if true, the tool is almost certainly line-based (`insert_line_at`, `replace_lines`) or file-based (`set_script`). Neither helps with *semantic* insertion points. You'd need the LLM to output specific line numbers, which is extremely fragile (line numbers change if any other edit happens first).

**Wrong about the dependency chain.** Surgical editing is a dependency for live debugging (capability #1) and test generation (capability #8). If it doesn't work, those capabilities collapse. The AI's roadmap has a single point of failure it doesn't acknowledge.

**Wrong about value.** The AI rates this "very high." But a surgical editor that works 60% of the time and introduces bugs 20% of the time is *negative value* — it wastes more time than it saves because you have to review every change and fix the ones it breaks.

### What COULD work instead

A much more modest version: **code template insertion.** Instead of "add coyote time to the existing player.gd," limit scope to "insert this known code pattern at a specified marker comment":

```gdscript
# Player.gd
func _physics_process(delta):
    # @devforge:movement_logic
    velocity.y -= gravity * delta
    move_and_slide()
```

The agent inserts code at `# @devforge:movement_logic` markers. This is mechanical, not semantic. It eliminates the "understand the code" problem entirely. It's less ambitious but actually achievable.

**Realistic estimate for marker-based insertion: 10–15 hours.**
**Realistic estimate for truly semantic surgical editing: not achievable with current model quality.**

---

## Capability #5: Signal/Dependency Mapping

**AI's claim:** "Read full scene tree and all scripts, produce a map of signals and connections." ~12 hours. "High" value.

### ✅ AGREED — on value

The AI is right that this is uniquely valuable and that Godot's signal system becomes a mess in real projects with no good tooling for it. The output — a map of what emits what and who listens — would be genuinely useful.

### ❌ DISAGREED — on the estimate (by 3–5×)

The AI describes this as "essentially a static analyzer." Static analysis of dynamically-typed GDScript connected through a GUI editor's drag-and-drop system is NOT a 12-hour project.

Here's what's actually involved:

1. **Parsing GDScript for signal declarations.** `signal health_changed` is straightforward. But `signal health_changed(new_health: int)` with typed parameters, or signals declared through `@warning_ignore` annotations, or signals in inner classes — edge cases multiply.

2. **Parsing GDScript for `emit_signal()` calls.** These can be dynamic: `emit_signal(signal_name)` where `signal_name` is a variable. The LLM cannot resolve these statically. You'd need a runtime trace or you'd need to mark them as "dynamic — unresolvable."

3. **Parsing GDScript for `.connect()` calls.** Same problem: `node.connect(signal_name, callable)` with variables.

4. **Parsing `.tscn` files for editor-made connections.** Godot stores signal connections in `.tscn` files as `[connection signal="health_changed" from="Player" to="HealthBar" method="_on_health_changed"]`. These are parseable, but the format differs between Godot versions, and you need to walk the entire scene dependency tree.

5. **Resolving node paths.** A connection from `"../Player"` to `"HealthBar"` in `UI.tscn` means different things depending on which scene instances which. Path resolution across `.tscn` boundaries is non-trivial.

6. **Presenting the results.** The output needs to be readable: "Player.gd emits `health_changed` (line 12). HealthBar.gd receives it via `_on_health_changed` (line 34, connected in UI.tscn). Nothing listens to `died` (line 15) — orphaned signal."

This is weeks of work, not hours. Each of the 6 steps above is 1–3 days.

**Realistic estimate: 30–50 hours** for a useful first version that handles the common cases and gracefully reports unresolvable ones. And that's WITH the LLM — most of this is deterministic parsing, not AI.

---

## Capability #6: Scene Refactoring

**AI's claim:** "Extract the campfire into its own scene so I can instance it multiple times." ~15 hours. "Medium-high" value.

### ⚠️ PARTIALLY AGREED — on value, not on estimate

The AI is right that scene refactoring is painful to do by hand and that the scene graph manipulation tools exist. And yes, "create .tscn, move nodes, replace with instance, update script references" is the correct sequence of operations.

### ❌ DISAGREED — on the estimate (by 2–3×)

The AI severely underestimates the edge cases:

1. **Script reference updating.** When you extract `Campfire` into its own scene, every script that references `$Campfire/Particles` needs to update to `$Campfire/Particles` (which is now an instanced scene path, not a direct child). Some references use `get_node()`, some use `$`, some use `%` (unique names), some use relative paths. You need to find and update ALL of them.

2. **Signal reconnection.** If `Campfire.gd` emits `warmed_up` and `Player.gd` connects to it, the connection survives extraction (it's on the instance). But if `Campfire.gd` connects to signals from its *former siblings*, those break because the sibling relationship changes.

3. **Nested instancing.** What if the extracted `Campfire` contains another instanced scene? You need to preserve the instance chain, not flatten everything into one `.tscn`.

4. **Resource sharing.** Materials, meshes, and textures might be shared between the extracted nodes and nodes that stay behind. You need to decide whether to copy or reference.

5. **Undo safety.** Scene refactoring is destructive. If the agent gets it wrong, the user's scene is corrupted. You need either a .tscn backup mechanism or a dry-run preview before applying.

6. **Unique name conflicts.** If two nodes in the extracted group both have `%` unique names, and the parent scene already has nodes with those unique names, you have a collision.

Each of these edge cases is a 1–2 day investigation and implementation.

**Realistic estimate: 30–50 hours** for a version that handles 80% of cases and has a safe preview mode. The remaining 20% of cases (nested instancing, resource sharing conflicts, complex signal topologies) are multi-day problems each.

---

## Capability #7: Runtime Observation

**AI's claim:** "Run the game, watch the output log, capture screenshots, form hypotheses about bugs." ~25 hours. "Potentially very high" value.

### ❌ STRONGLY DISAGREED — on feasibility, mechanism, value, and estimate

This is the most over-claimed capability on the list. Let me count the things that don't exist:

1. **Godot runtime instrumentation.** There is no MCP tool to "inspect live node properties during play mode." godot-ai's 40 tools operate on the *editor* scene, not the *running* game. The AI imagines an API that doesn't exist.

2. **Screenshot capture + interpretation.** The AI says "maybe captures screenshots." Even if you could capture frames (you can't via MCP), interpreting gameplay screenshots is a computer vision problem. Gemma 4B is a text model. It cannot see.

3. **Frame-level physics diagnosis.** The AI's example: "The player falls through the floor on frame 3 — I see `velocity.y` is -980 but `is_on_floor()` returns false." This requires *frame-by-frame physics state inspection*, which Godot does not expose through any API. Even if it did, 30–120 seconds per LLM call means you're looking at one diagnosis every 2–5 minutes while the game runs at 60fps.

4. **Hypothesis formation is causal reasoning.** The AI imagines the LLM can form meaningful bug diagnoses from log output. But log output is verbose, unstructured, and often misleading (the real bug is 3 seconds before the visible symptom). The AI's own example demonstrates the gap: deducing that `is_on_floor()` returns false because `move_and_slide()` wasn't called first is a **multi-step causal chain** — you must reason about *why* a state exists, not just observe it. Causal reasoning from log output is an open research problem for frontier models (GPT-4, Claude). Gemma 4B cannot get near it. The LLM will generate plausible-sounding but incorrect diagnoses — exactly the worst kind of AI assistance because it *looks* right.

5. **The closed-loop fallacy.** The AI's opening argument is that DevForge uniquely enables a "closed loop — the LLM can see the actual state of the project and act on it." This is true for the *editor scene graph*, which is static. It is completely false for the *running game*, which is dynamic, high-frequency, and inaccessible through existing MCP tools.

### What COULD work instead

A much more modest version: **error log triage.** After the user runs the game and it crashes, the agent reads `logs_read` output, categorizes the errors, and suggests the 2–3 most likely fixes. This is a *post-hoc* analysis, not real-time observation. It doesn't require new Godot instrumentation. It's essentially capability #1 (live debugging) scoped to crash analysis.

**Realistic estimate for error log triage: 10–15 hours.**
**Realistic estimate for the AI's full vision: not achievable without a complete rewrite of the godot-ai MCP bridge to support runtime instrumentation — 80–120+ hours, and even then unreliable.**

---

## Capability #8: Test Generation

**AI's claim:** "Read scripts, understand the logic, produce GDScript unit tests." ~10 hours. "Medium" value.

### ❌ STRONGLY DISAGREED — on feasibility

The AI says "the agent reads the scripts, understands the logic, and produces test files." This is pure LLM hype. Let me be absolutely clear: **Gemma 4B active parameters cannot understand GDScript logic well enough to produce meaningful tests.**

We know this because we have evidence:

- The model needed a **33-entry type enum** in the grammar to stop hallucinating Godot 3 types (Phase 0.5)
- The model needed **grammar constraints** to produce parseable JSON at all (Phase 0)
- The model needed **deterministic post-filters** to stop creating duplicate entities (Phase 3.2)
- The model needed **retry escalation** (3 attempts) to produce correct plans (Phase 4.3)
- After ALL of this, the model still produces plans that need repair (Phase 4 repair engine)

This is not a model that "understands logic." This is a model that, with extensive scaffolding, can produce *structurally valid scene descriptions*. Test generation is an order of magnitude harder — it requires reasoning about *behavior*, not structure.

The AI's example: "Write a test that verifies the player takes cold damage when not near fire." To generate this test, the LLM would need to:

1. Understand the cold damage mechanic (how is it calculated? what triggers it?)
2. Understand the fire proximity mechanic (how is "near fire" determined?)
3. Generate a test that sets up the correct game state (player NOT near fire)
4. Assert the correct outcome (player takes cold damage)
5. Handle edge cases (what if the player is near TWO fires? what if there are no fires in the scene at all?)

These are reasoning tasks that challenge human developers. A 4B active parameter model cannot do them.

### What the model CAN do

Generate *structural* tests: "Verify player.gd has a `health` variable." "Verify enemy.gd emits a `died` signal." "Verify all `.gd` files extend a valid Godot class." These are pattern-matching, not logic-understanding. They're useful (they catch typos and regressions) but they're not the "unit tests" the AI imagines.

**Realistic estimate for structural test generation: 8–12 hours.**
**Realistic estimate for behavioral test generation: not achievable with current model.**

---

## Capability #9: Iteration Tuning

**AI's claim:** "Make the jump feel snappier → adjust values → run → observe → adjust again." No estimate given.

### ❌ STRONGLY DISAGREED — on the entire premise

The AI left this one without a time estimate, and for good reason: the estimate would have exposed the fundamental absurdity of the idea.

**Game feel is perceptual.** "Snappier" does not mean "gravity > 20" or "jump_velocity > 500." It means "when I press jump, the character responds in a way that feels satisfying to my human brain." An LLM has no body, no thumbs, no experience of pressing a button and seeing a character jump. It cannot evaluate game feel.

**The feedback loop is impossibly slow.** Even if you could quantify "snappiness" as a number, the cycle is:

1. LLM proposes new values (30–120 seconds)
2. Apply values to the scene (~5 seconds)
3. Run the game (10–30 seconds to launch + navigate to the right state)
4. "Observe" — but the LLM can't observe. You'd need the human to describe what felt wrong, which adds another 30–60 seconds.
5. Back to step 1.

Each cycle: 2–4 minutes. Tuning a jump feel takes 10–20 iterations for a human playtesting live. That's 20–80 minutes for an LLM-assisted version vs. 5–10 minutes for a human just tweaking values in the editor. **The LLM makes it slower, not faster.**

### What the AI is actually describing

The AI is describing a **human-in-the-loop parameter optimization** system. The LLM proposes changes, the human evaluates them, the LLM adjusts based on human feedback. This could work for parameters that have clear numerical targets (e.g., "the player should jump exactly 3 meters high"). It cannot work for perceptual targets ("the jump should feel good").

**Realistic estimate: not worth building. The human is faster alone.**

---

## What the AI Got Right (Credit Where Due)

Despite the critiques above, the AI made several genuinely insightful observations:

1. **The closed loop is the unique advantage.** The AI correctly identified that DevForge's connection to the *live scene graph* is what distinguishes it from "chatting with an LLM in another window." This is the right strategic insight, even if the AI overestimates what the loop can do.

2. **Live error handling is the natural next step.** Of all 9 capabilities, piping Godot's error output through the pipeline is the most obvious extension of what already works, and the most likely to produce real value.

3. **Batch property editing is genuinely low-hanging fruit.** This maps directly to the existing `batch_execute` pipeline. It should have been in the initial scope.

4. **Consistency auditing with deterministic rules.** The AI correctly identified that rule-based scene checking doesn't need LLM intelligence — it needs Godot domain knowledge encoded as predicates.

5. **The AI correctly identified the unique advantage of scene graph access.** The AI's insight that batch editing, rule-based auditing, and error triage exploit the existing MCP bridge without requiring new capabilities is the right framing. However, the AI's top-ranked capability (live debugging at #1 with "very high" value) is actually Tier 2 — it depends on code editing capabilities that don't work with Gemma 4B. Our Tier 1 (build now) reorders to: batch editing first, then consistency auditing, then error triage. The AI got the *set* of valuable capabilities right but ranked them by ambition rather than achievability.

---

## What the AI Got Wrong (The Big Picture)

### 1. The Model Quality Blind Spot

The AI never once mentions that the "intelligence" behind all 9 capabilities is Gemma 4B active. Every capability that requires understanding code semantics (surgical editing, test generation, runtime diagnosis) assumes a model quality that doesn't exist.

This isn't a small oversight — it's a category error. You cannot estimate implementation time for an LLM-powered feature without accounting for the LLM's capabilities. A capability that takes ~8 hours with GPT-4 might be *impossible* with Gemma 4B, not just slower.

### 2. The "First Try" Fallacy

Every estimate assumes things work on the first implementation attempt. Our history:

- 5 bugs just to connect DevForge to godot-ai (transport protocol, parameter names, tool names, response format, grammar syntax)
- 4 more bugs in the godot-ai contract audit (command names, parameter keys, path formats)
- 38 total bugs across 7 rounds of hardening

Triple every estimate. Minimum.

### 3. The Dependency Chain

The AI presents 9 independent capabilities, but they're not independent:

```
Live Debugging ──depends on──▶ Error Format Parsing (new ContextAssembler logic)
Live Debugging ──depends on──▶ Surgical Script Editing (or marker-based insertion)
Test Generation ──depends on──▶ Surgical Script Editing
Iteration Tuning ──depends on──▶ Runtime Observation
Runtime Observation ──depends on──▶ (API that doesn't exist)
```

Surgical editing is a dependency for 2 of the 3 "very high" value capabilities. If it doesn't work (and with Gemma 4B, it won't reliably), those capabilities collapse.

### 4. The Latency Elephant in the Room

The AI imagines "tight loops" and "continuous observation." The pipeline makes ONE LLM call per request. Each call takes 30–120 seconds. A "closed loop" debugging session would mean:

- Send error to LLM (30–120s)
- LLM proposes fix (included in the above)
- Apply fix via batch_execute (~5s)
- Re-run scene to check (~15s)
- Still broken? Repeat from step 1.

That's 2–5 minutes per cycle. A human reading the error, fixing it in their editor, and re-running takes 1–2 minutes. **The AI assistance is slower than the human.**

Until the LLM can produce correct fixes in *one shot*, the latency penalty of the pipeline makes it a net negative for debugging workflows.

---

## What's Actually Achievable (The Honest Roadmap)

Given the constraints, here's what I'd actually recommend building:

### Tier 1: Build Now (these actually work with current architecture)

| # | Capability | Real Hours | Why |
|---|-----------|-----------|-----|
| 1 | **Batch property editing** | 2–4 | Maps to existing batch_execute. Low risk. Actually saves time. |
| 2 | **Deterministic consistency auditing** | 8–12 | Hardcoded rules, not LLM-driven. Scene tree already readable. |
| 3 | **Error log triage** (post-hoc, not real-time) | 10–15 | Uses existing `logs_read`. Categorizes errors, suggests fixes. Does NOT auto-apply. |

### Tier 2: Build If Model Improves (need better LLM or accept low reliability)

| # | Capability | Real Hours | Caveat |
|---|-----------|-----------|--------|
| 4 | **Marker-based code insertion** | 10–15 | Only works with `# @devforge` markers in code. Not semantic. Mechanically inserts code at known anchor points — avoids the script "understanding" problem entirely. |
| 5 | **Live debugging** (manual review mode) | 15–20 | LLM proposes fixes; human reviews before applying. NOT automatic. Requires error format parsing + file-to-error matching in ContextAssembler. |
| 6 | **Signal/dependency mapping** (GDScript only) | 15–25 | Parse `.gd` files for signal declarations and `.connect()` calls. Skip `.tscn` connections for v1. |

### Tier 3: Do Not Build (current model cannot do these reliably)

| # | Capability | Why Not |
|---|-----------|--------|
| 7 | Surgical script editing (semantic) | Gemma 4B can't understand GDScript control flow. Would introduce more bugs than it fixes. |
| 8 | Test generation (behavioral) | Requires understanding game logic. Model can barely produce valid JSON. |
| 9 | Runtime observation | Requires Godot runtime instrumentation that doesn't exist. 80–120+ hours to build, still unreliable. |
| 10 | Iteration tuning | Game feel is perceptual. LLMs can't feel. Human is faster alone. |

### Tier 0: Finish What's Already Broken

Before ANY new capability, finish the live-stack verification:

1. Restart the DevForge MCP server (the running instance predates Rounds 5–6)
2. Run the live smoke test
3. Verify `attach_script`, `set_property`, `connect_signal` work end-to-end
4. Verify rename/delete work end-to-end
5. Run `scripts/run_all_tests.sh` and verify all pass

**Estimated time: 2–4 hours.** This is the actual next step, not any of the 9 capabilities.

---

## The Bottom Line

The AI's roadmap is a **research vision dressed as an implementation plan.** It describes capabilities that would be genuinely useful in a world where:

- The LLM was GPT-4 class instead of Gemma 4B
- The pipeline supported multi-turn continuous interaction
- Godot had runtime instrumentation APIs
- Every integration worked on the first try
- Game feel was a quantifiable metric

None of these are true.

The *one capability* that could actually ship this week is batch property editing, because it's just a filter-and-loop over the existing `batch_execute` pipeline. Everything else on the list needs either a better model, new Godot APIs, or a fundamental architectural shift from "one-shot pipeline" to "continuous assistant."

The AI's best insight — and the one to actually pursue — is that **the closed loop to the live scene graph** is the unique advantage. Batch property editing, deterministic rule checking, and error log triage are the three capabilities that exploit this advantage without requiring capabilities the system doesn't have.

Build those. Skip the rest. The gap between "what an AI can describe" and "what Gemma 4B can actually do" is the gap between a compelling vision and a working tool.
