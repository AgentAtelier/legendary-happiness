<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

Good question. Let me think about what your architecture — local LLM + MCP bridge + live Godot connection — uniquely enables that you *can't* do by just chatting with an LLM in another window.

The key difference is the **closed loop**. The LLM can see the actual state of the project and act on it. Not just files — the live scene graph, the error console, the running game.

Here's what that enables, grouped by how much new work they'd require:

---

**Built on what you already have (MCP bridge + scene graph access):**

**Live debugging.** Run the scene, read Godot's error output, fix the script, re-run. Right now when a script fails, you read the error, switch to your editor, fix it, switch back. The agent could do: "I see `Invalid call to function 'move_and_slide'` — your CharacterBody3D script isn't calling `super._physics_process()`. Fix it?" This is the single most useful thing beyond scaffolding and it's almost free — godot-ai already has access to the output console.

**Consistency auditing.** "Check my scene for problems." The agent reads the full scene tree and flags: collision shapes without siblings, orphaned nodes, missing scripts that are referenced, signals declared but never connected, physics bodies with zero mass. This is tedious work humans skip and LLMs are good at — it's pattern matching against rules.

**Batch property editing.** "Make all OmniLight3Ds use warm colors." "Set every CollisionShape3D's debug color to red." "Double all enemy health values." Trivial for the agent, agonizing for a human clicking through 40 nodes.

---

**Requires moderate new work (new MCP tools or deeper Godot integration):**

**Surgical script editing.** Not "generate player.gd from scratch" but "add coyote time to the existing player.gd." This requires reading the current script, understanding its structure, and inserting code at the right point instead of replacing the whole file. Your pipeline currently creates files — it doesn't edit them. But godot-ai has script editing tools. The LLM just needs to be prompted differently and given the current file contents as context.

**Signal and dependency mapping.** Read the full scene tree and all attached scripts, then produce a map: "Player.gd emits `health_changed`, HealthBar.gd receives it — but nothing listens to `died`, and Campfire.gd calls `set_near_fire` which doesn't exist on Cabin." This is essentially a static analyzer that understands Godot conventions. Uniquely valuable because Godot's signal system becomes a spaghetti mess in real projects and there's no good tooling for it.

**Scene refactoring.** "Extract the campfire into its own scene so I can instance it multiple times." This means: create a new .tscn, move the right nodes into it, replace the original with an instance, update any script references. Deeply Godot-specific, genuinely painful to do by hand, and requires the scene graph manipulation you already have.

---

**Requires significant new work (new capabilities):**

**Runtime observation.** The agent runs the game, watches the output log, maybe captures screenshots, and forms hypotheses about bugs. "The player falls through the floor on frame 3 — I see `velocity.y` is -980 but `is_on_floor()` returns false. You probably need to call `move_and_slide()` before checking floor state." This requires Godot to expose its runtime console and ideally a way to inspect live node properties during play mode.

**Test generation.** Given a scene and scripts, generate GDScript unit tests (Godot 4 has a test framework). "Write a test that verifies the player takes cold damage when not near fire." The agent reads the scripts, understands the logic, and produces test files. This is pure code generation but scoped to the actual project.

**Iteration tuning.** The tight loop I mentioned before — "make the jump feel snappier" → adjust values → run → observe → adjust again. This needs runtime observation plus a way to modify properties without full scene reloads. Godot's `set()` through the editor bridge might already support this.

---

Here's the honest ranking by **value per hour of development time:**

| Capability | Hours to build | Value |
|-----------|---------------|-------|
| Live debugging (read console errors, fix scripts) | ~5 | Very high |
| Consistency auditing | ~3 | High |
| Batch property editing | ~2 | Medium |
| Surgical script editing | ~8 | Very high |
| Signal/dependency mapping | ~12 | High |
| Scene refactoring | ~15 | Medium-high |
| Runtime observation | ~25 | Potentially very high |
| Test generation | ~10 | Medium |

The live debugging one is the sleeper hit. You already have 90% of it — the MCP bridge, the script creation, the LLM. You just need to pipe Godot's error console back to the agent and add a "fix errors" tool. That transforms DevForge from "scaffolding that runs once" to "a pair programmer that watches your back continuously."

Want me to scope out what the live debugging capability would actually look like in terms of code changes?
