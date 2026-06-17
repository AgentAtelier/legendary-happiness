# DevForge Practicum: Making It Matter

> *The measure of this tool is not whether it works. The measure is whether a below-average game becomes slightly above average because someone used it.*

**Date:** June 11, 2026
**Author:** Buffy (Codebuff)
**Purpose:** Define the concrete path from "interesting learning experience" to "tool that makes a noticeable difference in game quality"

---

## The Honest Starting Point

You said it yourself: DevForge is "practically unusable and only useful for a very limited scope." "Might save an hour over an entire game." That's the baseline.

This document is about changing that baseline. Not by adding more features. Not by chasing AI hype. By understanding what actually makes games better and building the tool that helps with *that*.

---

## Part One: What Makes a Game Below Average?

Before we can make a tool that helps, we need to understand the disease. Below-average games aren't bad because they lack features. They're bad because of **death by a thousand papercuts** — hundreds of small problems that collectively make the experience feel amateur:

| Symptom | Root Cause | Can AI help? |
|---------|-----------|--------------|
| Inconsistent controls | Different nodes have different property values for the same thing (jump height varies, movement speed drifts) | **Yes — batch auditing** |
| Janky physics | Collision shapes don't match their parents, masses are zero, layers are misconfigured | **Yes — rule-based scene audit** |
| Disconnected systems | Health bar exists but nothing updates it. Inventory UI has items but no pickup mechanic. Dialogue system calls a signal nobody emits | **Yes — signal/dependency mapping** |
| Flat difficulty | Enemies all have identical stats. No progression curve. Health never matters because nobody balanced it | **Partially — design analysis** |
| Unpolished feel | Missing particle effects, no screen shake, no sound triggers, no camera easing | **Yes — missing-element detection** |
| Architectural decay | One scene has 200 nodes. Scripts reference nodes by hardcoded paths. Everything breaks when you rename anything | **Yes — structural audit** |
| The "what does this button do?" problem | No consistent UI language. Buttons do different things in different screens. Input mappings differ between scenes | **Partially — naming convention enforcement** |

These are not problems that need a genius programmer. They need a **tireless reviewer** — something that checks every node, every property, every connection, and flags the ones that don't look right. That's what LLMs are good at. That's what DevForge should become.

---

## Part Two: The Five Pillars of a Useful DevForge

I propose rebuilding DevForge around five capabilities. Each one targets a specific class of papercut. Together, they transform the tool from "scaffolding generator" to "development companion."

---

### Pillar 1: The Scene Doctor

**What it does:** Reads your scene and tells you what's wrong.

**How it works:** A set of deterministic rules that traverse the scene graph and flag violations. Phase 1 rules are pure graph-traversal checks (no code parsing needed). Phase 2 rules require script text analysis (parsing GDScript for function calls, signal declarations, variable references) — these are feasible but add implementation complexity. No LLM needed for the checking at any phase — the LLM is used only to *explain* findings in human language.

**Rules to implement (Phase 1 — 5 rules):**

| # | Rule | What it catches | Godot knowledge needed |
|---|------|----------------|----------------------|
| 1 | Every `CollisionShape3D` must be a child of a `CollisionObject3D` descendant | Orphaned collision shapes (silent physics bugs) | Parent class hierarchy |
| 2 | Every `RigidBody3D` must have non-zero `mass` | Physics bodies that won't move | Property existence check |
| 3 | Every `.gd` script referenced by a node must exist as a file | Broken script references (silent failures) | Script path validation |
| 4 | Every `Camera3D` must be `current` if it's the only camera | Scenes with no active camera (black screen) | Property default values |
| 5 | Every `MeshInstance3D` must have a non-null `mesh` | Invisible geometry (common oversight) | Property null check |

**Rules to implement (Phase 2 — 10 rules):**

> ⚠️ **Phase 2 rules marked with (*) require script text parsing** — searching GDScript files for function calls, variable references, or signal declarations. This is more complex than Phase 1's graph traversal but remains deterministic (regex/string matching on script source, not LLM-driven). Budget 2-3 hours per starred rule vs. 1 hour for purely structural rules.

| # | Rule | What it catches | Complexity |
|---|------|----------------|-----------|
| 6 | Every `AnimationPlayer` with animations should have an `AnimationTree` or explicit `play()` calls * | Unused animations | Requires scanning scripts for `play()` |
| 7 | `AudioStreamPlayer3D` nodes >50m from the nearest `Camera3D` are flagged as potentially inaudible | Sound placement you can't hear | Distance check against camera positions |
| 8 | Every `Timer` node should be referenced by at least one script * | Unused timers (scapegoat nodes) | Requires scanning scripts for timer name references |
| 9 | Nodes with duplicate `%` unique names in the same scene | Silent node resolution bugs | Pure graph check |
| 10 | `Area3D` nodes without `monitoring` or `monitorable` enabled | Trigger zones that don't trigger | Property check |
| 11 | Signal declarations in scripts with zero `emit()` calls in any script * | Orphaned signals | Requires scanning scripts for `emit()` |
| 12 | Scripts that extend classes not in the `godot_node_types.py` registry | Potential Godot 3 class names | String match against registry |
| 13 | `NavigationRegion3D` without a `NavigationMesh` resource | Pathfinding that doesn't work | Property check |
| 14 | `GPUParticles3D` without a `process_material` | Particles that do nothing | Property check |
| 15 | `Light3D` nodes with `light_energy = 0` or `light_color` ≈ black | Invisible lights | Property check |

**User experience:**
```
> /audit
Found 7 issues in your scene:

🔴 CRITICAL (1):
  - EnemySpawner/Enemy1 (RigidBody3D): mass = 0.000. The body won't
    respond to forces. Set mass to a positive value (default: 1.0).

🟡 WARNING (4):
  - UI/HealthBar: references script "res://scripts/health_bar.gd"
    which doesn't exist. The node will use default Node3D behavior.
  - MainScene: no Camera3D is set as 'current'. The viewport will
    be black when you run the scene.
  - Effects/SmokeParticles (GPUParticles3D): process_material is
    null. No particles will emit.
  - Player (CharacterBody3D): has no CollisionShape3D child.
    The body will fall through the floor.

ℹ️ INFO (2):
  - EnemySpawner/SpawnTimer: no script references this Timer.
    It may be unused.
  - Audio/AmbientWind (AudioStreamPlayer3D): 47m from the camera.
    Audible range is 10m. The sound won't be heard.

Run /fix 1,2,3 to auto-fix the critical and first two warnings.
```

**Why this matters:** A solo developer building a game with 80 nodes and 15 scripts has probably made 5-15 of these mistakes. Finding them manually is 30-60 minutes of tedious inspection. The Scene Doctor finds them in 5 seconds and tells you how to fix them. This alone could save 2-4 hours over a project — already 2-4x the current value proposition.

**Realistic effort:** 8-12 hours for Phase 1 (5 rules, all graph traversal). 20-35 hours for Phase 2 (10 rules, including 3 with script parsing complexity). Total: 30-50 hours for a working Scene Doctor with 15 rules.

**Key insight:** None of these rules need the LLM to be smart. They need *Godot domain knowledge* encoded as predicates. The LLM's job is to take rule violations and write human-readable explanations — a pure text generation task that even Gemma 4B can do well.

---

### Pillar 2: The Batch Operator

**What it does:** Applies operations across filtered selections of nodes. One command replaces 50 clicks.

**How it works:** Extends the existing `batch_execute` pipeline with query-and-filter logic.

**Operations:** (The Batch Operator modifies properties on existing nodes. For creating new node trees from templates, use the Template Forge — Pillar 4.)

| Operation | Example | Manual time | Batch time |
|-----------|---------|-------------|------------|
| Mass property set | "Set all OmniLight3D light_color to warm white (#FFF4E6)" | 5-15 min (20 lights) | 5 seconds |
| Mass child add | "Add a CollisionShape3D to every MeshInstance3D with 'Wall' in the name" | 10-30 min (15 walls) | 5 seconds |
| Mass type conversion | "Convert all SpotLight3D to OmniLight3D" | 15-45 min (10 lights) | 5 seconds |
| Mass delete | "Delete all nodes of type GPUParticles3D" | 5-10 min | 5 seconds |
| Mass rename | "Add prefix 'Old_' to all nodes with 'temp' in the name" | 2-5 min | 5 seconds |

> ⚠️ **Primary technical challenge:** The natural language → structured filter parser. "All OmniLight3Ds" is easy to match with regex patterns. "Every light in the main room" requires LLM parsing (adds 30-120s latency). Recommendation: implement a hybrid — regex for common patterns (type-filter, name-match, parent-scope), fall back to LLM parsing for complex queries. Budget 3-4 hours for the parser alone.

**Filter syntax (natural language → structured query):**

```
User says: "All OmniLight3Ds"
Becomes:   filter(type="OmniLight3D")

User says: "Every node under /root/UI with 'Button' in the name"
Becomes:   filter(parent="/root/UI", name_contains="Button")

User says: "All Area3D nodes that have no script attached"
Becomes:   filter(type="Area3D", script_path=None)
```

**User experience:**
```
> /batch "Make all lights warm"
Found 23 lights (12 OmniLight3D, 8 SpotLight3D, 3 DirectionalLight3D).
Will set:
  - light_color → Color(1.0, 0.96, 0.90) [warm white]
  - light_energy → 0.8

Affected: /root/Main/SunLight, /root/Main/RoomLight, ...
(and 20 more)

Apply? [y/N]: y
Applied. 23 nodes updated.
```

**Why this matters:** The "90% done" trap is real. Your game works but everything looks slightly wrong — lights are too cold, jump heights vary by 0.5 units, cameras clip slightly differently. Fixing each one manually is hours of clicking through the inspector. The Batch Operator turns "spend an afternoon polishing visuals" into "spend 2 minutes issuing commands." This is where DevForge actually saves real time — not in initial creation, but in *iteration and polish*.

**Realistic effort:** 6-10 hours. The `batch_execute` pipeline, `scene_get_hierarchy`, and `_translate_ops_to_commands` already exist. New code: natural language → filter query parser (3-4h, the hardest part), filter → node list resolver (1-2h), `/batch` MCP tool endpoint (1-2h), integration tests (1-2h).

---

### Pillar 3: The Design Companion

**What it does:** Analyzes your game's systems and asks the questions a human design reviewer would ask. Not "here's what to build" but "here's what your design might be missing."

**This is where the LLM earns its keep.** The AI isn't generating code. It's analyzing *structure* — something LLMs are genuinely good at — and applying game design patterns that are well-documented in its training data.

> ⚠️ **Pattern database dependency:** The "200+ analyzed platformers" example illustrates the vision, but the initial pattern database must be seeded manually. Building it from scratch: (a) write 20-30 design patterns based on common game design knowledge (e.g., "platformers have coyote time", "RPGs have healing mechanics"), (b) encode each as a structural check against extracted game state, (c) use the LLM to match extracted state against patterns. The LLM's training data provides *general* genre knowledge — the pattern database provides *structured, queryable* rules. Budget 10-15 hours for the initial 20-pattern database.

**Analysis modes:**

#### Mode A: Completeness Check
```
> /design completeness
Analyzing your scene graph...

Systems detected:
  ✅ Combat (Player.gd: attack(), Enemy.gd: take_damage())
  ✅ Health (Player.gd: health variable, HealthBar.gd: _on_health_changed)
  ❌ Healing — you have health but no way to restore it
  ✅ Movement (Player.gd: _physics_process, CharacterBody3D)

Missing connections:
  • Health system has no death handler. What happens when health reaches 0?
  • Enemy has take_damage() but nothing calls it. How do enemies get hurt?
  • You have 'inventory' in variable names but no inventory system.

Common patterns in this genre (action-adventure):
  • 82% of similar games have a dodge/roll mechanic. You don't.
  • 71% have collectible items with persistent state. You don't.
  • 64% have a stamina system that gates special actions. You don't.
```

#### Mode B: Balance Analysis
```
> /design balance
Analyzing combat stats...

Player:    health=100, damage=25, speed=5.0
Enemy_1:   health=30,  damage=10, speed=3.0
Enemy_2:   health=30,  damage=10, speed=3.0
Enemy_3:   health=30,  damage=10, speed=3.0

⚠️ All 3 enemy types have identical stats. Combat will feel repetitive.
   Consider: one fast/weak, one slow/strong, one ranged.

⚠️ Time-to-kill for a basic enemy: 1.2 seconds (player attacks).
   Time-to-kill for the player (3 enemies attacking): 3.3 seconds.
   The player is overpowered — they can tank 3 enemies simultaneously.
   Consider: increase enemy damage or add enemy variety.
```

#### Mode C: Genre Expectation Check
```
> /design genre platformer
Comparing your scene to platformer conventions...

✅ Present:
  • CharacterBody3D player with jump
  • Moving platforms (MovePlatform.gd)
  • Collectibles (Coin.gd)

❌ Missing (based on 200+ analyzed platformers):
  • Coyote time (grace period after walking off ledge) — 89% have this
  • Jump buffering (press jump slightly before landing) — 76% have this
  • Variable jump height (hold button = higher jump) — 94% have this
  • Camera smoothing/lerp — 82% have this
  • Checkpoint/respawn system — 91% have this

The 3 most impactful additions for your game:
  1. Variable jump height (~30 lines of code, massive feel improvement)
  2. Camera smoothing (~15 lines, professional feel)
  3. Coyote time (~20 lines, forgives player mistakes)
```

**Why this matters:** A below-average game becomes above-average through *design iteration*, not just bug fixes. A solo developer has no design reviewer. The Design Companion fills that role — not with creative genius, but with *pattern recognition across hundreds of analyzed games*. "You're missing coyote time" is not a brilliant insight — it's a pattern match. But it's a pattern match the solo developer didn't think to make.

**The LLM's role here is perfect:** It doesn't need to understand GDScript logic. It needs to read a *structural description* of the game (node types, property names, script function signatures, signal declarations) and compare it against common patterns. This is a classification and pattern-matching task — exactly what LLMs excel at.

**Realistic effort:** 30-45 hours. Breakdown: structural game description extractor (8-12h), genre pattern database with 20-30 seeded patterns (10-15h), LLM prompt engineering for design analysis modes (6-8h), `/design` MCP tool endpoint (3-5h), integration tests (3-5h). Most of the work is in the extractor and pattern database, not in pipeline code.

---

### Pillar 4: The Template Forge

**What it does:** Generates complete, working scene templates from natural language descriptions. Not "create a Player node" but "create a complete first-person character controller with sprint, crouch, head bob, and footstep sounds."

**This is what DevForge was originally built to do — generalized and made reliable.**

The current pipeline creates individual nodes from LLM plans. The Template Forge would create *complete systems* from a library of pre-built, tested, deterministic templates. The LLM's job is to select and customize the right template, not to generate code from scratch.

**Template library (Phase 1 — 10 templates):**

| Template | What it creates | Nodes | Scripts |
|----------|----------------|-------|---------|
| `fps_controller` | First-person character with sprint, crouch, head bob | Camera3D, CharacterBody3D, CollisionShape3D, 3 RayCasts | player.gd (~150 lines) |
| `tps_controller` | Third-person character with orbit camera | SpringArm3D, Camera3D, CharacterBody3D, CollisionShape3D, MeshInstance3D | player.gd (~120 lines), camera.gd (~60 lines) |
| `health_system` | Health, damage, healing, UI bar, death handler | Node3D (marker) | health.gd (~80 lines), health_bar.gd (~40 lines) |
| `inventory_system` | Item pickup, inventory array, UI grid, equip/use | Node3D (marker), GridContainer | inventory.gd (~120 lines), inventory_ui.gd (~80 lines) |
| `enemy_patrol` | Patrol route, detection radius, chase, attack, return | Path3D, PathFollow3D, Area3D, CharacterBody3D, CollisionShape3D | enemy_patrol.gd (~100 lines) |
| `dialog_system` | Dialog tree, branching choices, speaker portraits, typewriter effect | Control, Label, VBoxContainer, 9SliceRect | dialog_manager.gd (~150 lines), dialog_ui.gd (~80 lines) |
| `save_system` | JSON save/load, autosave timer, save slot management | Node (marker) | save_manager.gd (~100 lines) |
| `quest_system` | Quest states, objectives, rewards, quest log UI | Node (marker), VBoxContainer | quest_manager.gd (~150 lines), quest_ui.gd (~60 lines) |
| `checkpoint_system` | Checkpoint placement, respawn, death screen, retry | Area3D (checkpoint marker), Timer | checkpoint.gd (~60 lines) |
| `day_night_cycle` | Directional light rotation, sky color interpolation, ambient changes | DirectionalLight3D, WorldEnvironment | day_night.gd (~50 lines) |

**How it works:**
```
User: "/template inventory_system"
→ LLM recognizes "inventory system" as a known template
→ Template has slots: [items, max_slots, ui_position, hotkey]
→ LLM asks (or uses defaults): "Max inventory slots? [20] Hotkey? [Tab]"
→ Template instantiates:
    - Creates inventory manager node
    - Creates inventory_ui.gd at res://scripts/
    - Creates inventory.gd at res://scripts/
    - Connects to existing player via signal (asks for player path)
    - Sets default properties
→ Done. Working inventory in 30 seconds.
```

**Why this matters:** The most painful part of game development is rebuilding the same systems for every project. Every game needs health. Every game needs a save system. Every game needs dialogue. These are solved problems with known-good implementations. The Template Forge eliminates the boilerplate tax — the hours spent implementing the same thing for the 5th time.

**The difference from current DevForge:** The current pipeline uses the LLM to *plan* what to create, then generates operations. The Template Forge uses deterministic, pre-written templates. The LLM only selects and customizes. This is 100% reliable (no grammar constraints needed, no retry logic) and produces working code (because the templates were written and tested by a human).

**Realistic effort:** 50-80 hours for Phase 1 (10 templates + engine). Each template takes 4-6 hours: design the GDScript (1-2h), implement and test in Godot (2-3h), encode as DevForge IR + script files (1h). The template engine (slot system, question flow, instantiation, parameter customization) is 10-15 hours. These are human-written, tested scripts — not LLM-generated — so they actually work. Unlike the current pipeline, template instantiation is 100% reliable (no grammar constraints, no retry logic).

---

### Pillar 5: The Progress Journal

**What it does:** Tracks your project over time and shows you what's changed, what's growing, and what needs attention. A git log for your scene graph that understands Godot semantics.

**This is the meta-tool — it makes all other tools more useful by giving them history.**

**Features:**

#### Change Tracking
```
> /journal today
Changes since your last session (June 10, 2026):

  Nodes: +12 (95 → 107)
    + 3 enemies (Enemy_Soldier, Enemy_Sniper, Enemy_Heavy)
    + 2 weapons (Rifle, SniperRifle)
    + 1 UI element (AmmoCounter)
    + 6 collision shapes (for new enemies and weapons)

  Scripts: +3 (18 → 21)
    + scripts/enemy_soldier.gd (142 lines)
    + scripts/enemy_sniper.gd (98 lines)
    + scripts/ammo_counter.gd (45 lines)
    ~ scripts/player.gd (+12 lines: added ammo tracking)

  Properties changed: 47
    - 23 light adjustments
    - 12 collision layer changes
    - 8 mass value updates
    - 4 script re-attachments

  Scene complexity: 107 nodes is within healthy range (<200).
```

#### Growth Warnings
```
> /journal health
📊 Project health over 30 days:

  Nodes: 12 → 107 (↑ 95)
  Scripts: 3 → 21 (↑ 18)
  Avg script length: 45 → 112 lines (↑ 67)
  
  ⚠️ MainScene has 107 nodes. Consider extracting:
      - Enemy group (20 nodes) → enemies.tscn
      - UI group (15 nodes) → ui.tscn
      - Weapons group (8 nodes) → weapons.tscn
  
  ⚠️ player.gd has grown from 50 to 230 lines in 5 days.
      Consider splitting into: player_movement.gd, player_combat.gd,
      player_inventory.gd.
  
  ⚠️ 8 scripts have no associated test file.
```

#### Design Drift Detection
```
> /journal drift
Comparing current scene to your initial architecture plan (June 1, 2026):

  Planned systems (8):
    ✅ Player controller
    ✅ Enemy AI
    ✅ Combat
    ✅ Health
    ✅ Inventory
    ✅ Quest system
    ❌ Crafting system — planned but never built
    ❌ Dialogue system — planned but never built
  
  Unplanned additions (3):
    • Day/night cycle (not in initial plan)
    • Weather system (not in initial plan)
    • Photo mode (not in initial plan)
  
  You're drifting from your original design. Either:
    - Update your plan to include the new systems
    - Remove the unplanned systems if they're scope creep
```

**Why this matters:** The "I forgot what I was doing" problem kills solo projects. You take a week off, come back, and don't remember what you changed, what was half-finished, or why you made certain decisions. The Progress Journal is institutional memory for your project. It turns "staring at the scene trying to remember what's different" into a 5-second command.

**Realistic effort:** 15-25 hours. Requires: scene snapshot storage (new, but lightweight — JSON diffs), journal entry generation (new), health metric calculation (new), drift detection against stored plans (new), and the `/journal` MCP tool endpoint. Most of the code is deterministic data processing — no LLM needed.

---

## Part Three: The Honest Priority Stack

If you build nothing else, build these, in this order:

### 🥇 Priority 1: The Batch Operator (Pillar 2)
**Time: 4-8 hours. Impact: Immediate, visible, measurable.**

This is the one thing you can build this week that someone would use *today* and say "that saved me time." Everything needed already exists — the `batch_execute` pipeline, scene hierarchy reading, operation translation. The Batch Operator is just a query layer on top.

### 🥈 Priority 2: The Scene Doctor (Pillar 1)
**Time: 8-12 hours (Phase 1, 5 rules). Impact: Catches silent bugs before they become hours of debugging.**

This is the tool that makes a below-average game feel more polished because it catches the invisible mistakes. Every rule is a small project, but each rule prevents a class of bugs that would otherwise survive until playtesting.

### 🥉 Priority 3: The Template Forge (Pillar 4)
**Time: 50-80 hours (Phase 1, 10 templates). Impact: Eliminates the boilerplate tax.**

This is the big one — the thing that makes DevForge feel like magic. "Give me an inventory system" → 30 seconds → working inventory. The templates are human-written and tested, so they actually work. The LLM just picks which one and customizes parameters.

> **Why Template Forge before Design Companion?** The templates are content, not code — once written, they work forever (barring Godot API changes). The Design Companion requires ongoing prompt engineering and pattern database maintenance as the LLM evolves. Templates are a **one-time investment with permanent payoff.** The Design Companion is a **living system that needs care.** Build the thing that stays built first.

### Priority 4: The Design Companion (Pillar 3)
**Time: 30-45 hours. Impact: Makes the difference between "functional" and "designed."**

This is what makes a below-average game above-average. It's the design reviewer that solo developers never have. But it depends on having good game state extraction and a solid pattern database, so build it after the infrastructure (Scene Doctor, Batch Operator) and content (Template Forge) are solid.

### Priority 5: The Progress Journal (Pillar 5)
**Time: 15-25 hours. Impact: Prevents project abandonment.**

This is the long-term play. It's most valuable after weeks of development, when the project is complex enough to need tracking. Build it last, but build it.

---

## Part Four: What NOT to Build

Equally important: the things that would consume months of effort for negligible impact with current technology.

| Don't build | Why |
|-------------|-----|
| Real-time runtime debugging | Godot doesn't expose runtime state through MCP. 80-120+ hours to add, still unreliable. |
| Semantic code editing | Gemma 4B cannot understand GDScript control flow. Would introduce more bugs than it fixes. |
| Behavioral test generation | Requires understanding game logic. Model can barely produce parseable JSON. |
| Iteration/tuning loops | Game feel is perceptual. LLMs can't feel. Human is faster alone. |
| Multi-turn planning | Requires pipeline architecture change. Low value until continuous-use mode is proven. |
| GUI-based workflow | The MCP/CLI interface IS the advantage. A GUI adds maintenance burden without new capability. |
| Cloud LLM integration | Kills the local-only advantage. Network dependency, cost, privacy concerns. |

---

## Part Five: The Architecture Principles

As you build these five pillars, adhere to these principles:

### 1. The LLM is a Classifier, Not a Creator

The LLM should be used to recognize patterns, classify situations, and explain findings. It should NOT be used to generate code or make creative decisions. The templates, audit rules, and property filters are human-written and tested. The LLM selects, customizes, and explains.

### 2. Deterministic Where Possible, LLM Where Necessary

Every tool should have a deterministic core with an LLM wrapper. The Scene Doctor's rules are deterministic — the LLM just writes the explanations. The Batch Operator's filters are deterministic — the LLM just parses the natural language query. The Template Forge's templates are deterministic — the LLM just picks which one.

### 3. One Tool, One Responsibility

Each pillar is a separate MCP tool with a clear, single purpose:
- `/audit` — find problems
- `/batch` — apply mass changes
- `/template` — instantiate known patterns
- `/design` — analyze game design
- `/journal` — track changes

No tool does two things. No capability is hidden behind another tool's interface.

### 4. Explain Everything

Every action produces human-readable output that explains what happened, why, and what the developer should do next. No silent successes. No mysterious failures. The output IS the product.

### 5. Safe by Default

- `/batch` always shows a preview and asks for confirmation
- `/template` never overwrites existing files without asking
- `/audit` never auto-fixes without explicit `/fix` command
- `/journal` never stores data outside the project directory

---

## Part Six: The Success Metric

The current metric: "might save an hour over an entire game."

The target metric: **"A developer who uses DevForge produces a game that is measurably more polished, more consistent, and better-designed than the same developer would produce without it."**

**How we measure it:** The Scene Doctor provides the measurement framework. A game with:
- **0 critical violations** (orphaned collision shapes, broken script refs, missing required children)
- **<3 warnings** (unused nodes, missing optional elements, scripts needing attention)
- **<5 info items** (style suggestions, optimization opportunities)

...is measurably more polished than a game with 5+ criticals and 15+ warnings. Every `/audit` produces a score. The developer's goal is zero.

This is not about time saved. It's about quality gained.
- Zero orphaned collision shapes (The Scene Doctor)
- Consistent lighting and property values (The Batch Operator)
- No missing core systems like health or save (The Template Forge)
- Genre-appropriate mechanics like coyote time and camera smoothing (The Design Companion)
- No lost context after breaks (The Progress Journal)

...is a game that feels professional, not amateur. It's the difference between "I made this in a weekend" and "I can sell this."

The tool doesn't need to make every game great. It needs to catch the mistakes that make a game feel unfinished. It needs to remind the developer of the features that make a game feel complete. It needs to eliminate the busywork that steals time from creative work.

Do those three things, and DevForge becomes the reason a below-average game becomes slightly above average.

---

## Part Seven: The First Week

Here's what you build in the first week after live-stack verification:

**Day 1: Live Stack Verification**
- Restart the DevForge MCP server on port 8001
- Run `test_smoke.py`
- Verify `attach_script`, `set_property`, `connect_signal`, rename, delete all work end-to-end
- Run `scripts/run_all_tests.sh` — all must pass

**Day 2-3: The Batch Operator**
- Implement filter query parser (natural language → structured filter)
- Implement filter → node list resolver (using existing `scene_get_hierarchy`)
- Implement the `/batch` MCP tool endpoint
- Write 3 integration tests

**Day 4-5: The Scene Doctor (Phase 1)**
- Implement 5 audit rules as individual predicate functions
- Implement rule runner (applies all rules, collects violations)
- Implement LLM explanation generator (violation → human-readable text)
- Implement the `/audit` MCP tool endpoint
- Write 5 unit tests (one per rule)

**Day 6-7: The Scene Doctor (Phase 1 continued) + Template Forge engine start**
- Implement 3 more audit rules (total: 5 rules for Phase 1)
- Begin template engine (slot system, question flow) — engine work only, no templates yet
- Write 5 unit tests (one per rule)

**Week 2: Template Forge content**
- Day 1-2: Write and test `health_system` template in Godot → encode as DevForge IR
- Day 3-4: Write and test `save_system` template → encode
- Day 5: Write and test `checkpoint_system` template → encode
- Day 6-7: Template engine completion, `/template` endpoint, integration tests

**What you have after two weeks:**
- A tool that can find 5 types of scene problems in 5 seconds
- A tool that can apply mass property changes across filtered node selections
- A tool that can instantiate 3 complete game systems from tested, working templates
- All running on the existing MCP bridge with the existing LLM

**Week 3-4: Expand (if the first two weeks prove the concept)**
- Scene Doctor Phase 2 (10 more rules, including script-parsing rules)
- Template Forge Phase 1 completion (7 more templates: fps_controller, tps_controller, inventory_system, enemy_patrol, dialog_system, quest_system, day_night_cycle)
- Design Companion prototype (structural extractor + first 10 design patterns)

---

## Epilogue: Why This Matters

You said DevForge is "only useful for a very limited scope." You're right — today. The current scope is: "describe a scene, get nodes created." That's a demo, not a tool.

But the architecture you've built — the MCP bridge, the grammar-constrained pipeline, the operation translation layer, the scene graph access — is the right architecture for something much bigger. The 38 bugs you fixed weren't wasted effort. They were the necessary work of making the foundation solid.

Now build on it. Not with more LLM calls. Not with fancier prompts. With deterministic tools that use the LLM where it's strong (pattern recognition, explanation, classification) and deterministic code where the LLM is weak (generation, reasoning, precision).

The five pillars are not a roadmap. They're a rescue plan. They take DevForge from "interesting experiment" to "tool that makes games better." They don't require a better model, a bigger budget, or a new architecture. They require focus — building the things that actually help, and having the discipline to not build the things that don't.

The difference between abandoned and above-average is not a thousand features. It's five. Build them.
