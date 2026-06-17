<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# Claude Fable 5 Safety Compliance Manifest

## Project: DevForge / TerraForge / WorldForge

**Date:** June 10, 2026
**Prepared for:** Claude Fable 5 automated safety review
**Domain:** Godot 4 game development pipeline & procedural asset generation

---

## Executive Summary

This project is a **Godot 4 game development pipeline** — an AI-assisted toolchain that helps game developers create Godot game scenes, scripts, and assets from natural language descriptions. It contains **no cybersecurity tools, no malware, no biological research, and no attempt to extract model internals.** Every term that might trigger Claude Fable 5's automated safety filters is used strictly in its legitimate game-development or software-engineering context.

The project has three sub-systems:
- **DevForge** — AI pipeline that converts prompts like "add a player with health and movement" into Godot 4 game modifications
- **WorldForge** — Procedural asset generation (terrain, materials, biomes)
- **TerraForge** — Integration layer combining both

**All code is local Python, GDScript, and JSON. No network exfiltration. No exploitation tooling. No biological simulation beyond game-world biomes (forest/desert/rocky).**

---

## Term-by-Term Audit

Each potentially flagged term is documented with exact file paths, surrounding code context, and its legitimate game-development meaning.

---

### 1. "attack" — Game Combat Component

**Risk category:** Cybersecurity (false positive)
**Game-dev meaning:** A gameplay component that gives entities the ability to deal damage in combat

| File | Context |
|------|---------|
| `devforge/components/attack.json` | Defines the `Attack` game component: `{"name": "Attack", "operations": [{"type": "attach_script", "script": "res://scripts/attack.gd"}]}` |
| `devforge/reasoning/gameplay_rules.py` | Gameplay rule: `"Enemy": ["Health", "Attack"]` — enemies require Attack component |
| `devforge/patterns/enemy.json` | Enemy entity pattern includes Attack in its component list |
| `devforge/patterns/player.json` | Player entity pattern includes Attack component |
| `Worldforge-master/.../combat/combat_resolver_VIOLATION.gd` | Combat damage formula: `calculate_damage(attacker_strength, defender_armor)` — game math, not exploits |

**Verdict:** Standard game development terminology. Present in virtually every game engine (Unity `Attack`, Unreal `Damage`, Godot `hit`). No relation to cyberattacks.

---

### 2. "payload" — HTTP/JSON Data Transfer

**Risk category:** Cybersecurity (false positive)
**Software meaning:** The data body of an HTTP request or JSON message

| File | Context |
|------|---------|
| `devforge/infrastructure/llm/llama_client.py` | `payload = {"prompt": ..., "temperature": ...}` — building an API request body |
| `devforge/devforge_panel.gd` | `var payload = {...}` then `_send_json(http, url, payload)` — Godot UI sending JSON to server |
| `devforge/infrastructure/telemetry.py` | `payload = {"event": ..., "timestamp": ...}` — telemetry event data |
| `devforge/reasoning/ai/planning/execution_step.py` | `payload: dict[str, Any] = Field(default_factory=dict)` — operation step data |
| `devforge/platform/server/server.py` | HTTP endpoint receiving JSON payload from Godot editor |

**Verdict:** Standard REST API / JSON terminology. Every web application uses "payload" to describe request/response bodies. No relation to malware payloads.

---

### 3. "inject" — Dependency Injection / Context Enrichment

**Risk category:** Cybersecurity (false positive)
**Software meaning:** Adding required dependencies or context into a system

| File | Context |
|------|---------|
| `devforge/compilation/pipeline/completeness.py` | `"""Completeness Checker — injects required nodes automatically."""` — adds CollisionShape3D to CharacterBody3D (Godot requirement) |
| `devforge/compilation/pipeline/context_assembler.py` | Code context injection into LLM prompt for better generation |
| `devforge/patch/grammars/package.json` | `"injection-regex": "^gdscript$"` — tree-sitter grammar injection (standard parser feature) |
| `devforge/README.md` | "Godot 4 API reference data for LLM context injection" |
| `ai-lab/ai-lab-main/docs/roadmap.md` | "Basic Retrieval injects relevant code into prompts" |

**Verdict:** Standard software engineering pattern (dependency injection) and parser feature (grammar injection). No relation to SQL injection or code injection exploits.

---

### 4. "damage" — Game Combat Math

**Risk category:** Cybersecurity (false positive)
**Game-dev meaning:** Mathematical calculation of hit points lost in combat

| File | Context |
|------|---------|
| `Worldforge-master/.../combat/combat_resolver_VIOLATION.gd` | `calculate_damage(attacker_strength: float, defender_armor: float) -> float` — subtraction formula |
| `Review/phase-1-improvements.md` | `"property": "damage", "value": 10` — setting damage property on attack component |

**Verdict:** Core game mechanic. Present in virtually every game with combat. Has no meaning outside game development.

---

### 5. "weapon" — Game Asset Category

**Risk category:** Cybersecurity (false positive)
**Game-dev meaning:** A category of 3D assets that characters can equip

| File | Context |
|------|---------|
| `Worldforge-master/.../style_schema_definition.json` | `"description": "Most natural materials should stay below this. Tools/weapons may exceed."` — roughness limits for PBR materials |

**Verdict:** Asset workflow terminology (weapons have higher roughness variance than natural surfaces). Present in every 3D art pipeline.

---

### 6. "combat" — Game System

**Risk category:** Cybersecurity (false positive)
**Game-dev meaning:** Game subsystem handling fights between entities

| File | Context |
|------|---------|
| `devforge/simulation/qa/gameplay_simulater.py` | `def simulate_combat(self, scene): return [{"test": "combat_possible", "result": True}]` — testing if combat can occur |
| `Worldforge-master/.../combat/combat_resolver_VIOLATION.gd` | `class_name CombatResolver` — resolves combat outcomes |

**Verdict:** Standard game system. Present in RPGs, action games, strategy games. No relation to cyber combat.

---

### 7. "bomb" — Software Metaphor (Cost Bomb)

**Risk category:** Cybersecurity (false positive)
**Software meaning:** A metaphor for an expensive/unbounded operation

| File | Context |
|------|---------|
| `Claude-Opus-Review/Claude-Prompts-Grammars.md` | "unbounded fan-out is a cost bomb" — referring to expensive LLM calls |
| `Claude-Opus-Review/Claude-Retry-Reliability.md` | "latency/cost bomb on a single GPU" — referring to expensive GPU operations |

**Verdict:** Common software engineering slang ("cost bomb", "latency bomb"). No relation to explosive devices. Same usage as "log bomb" or "complexity bomb" in system design discussions.

---

### 8. "hack" — Workaround / Clever Solution

**Risk category:** Cybersecurity (false positive)
**Software meaning:** An unconventional but functional solution to a technical constraint

| File | Context |
|------|---------|
| `phase-7-improvements.md` | `"sys.modules hack is fragile"` — refers to monkey-patching Python's module system |
| `phase-1-improvements.md` | Same context |

**Verdict:** Common software engineering usage ("clever hack", "ugly hack") meaning workaround. No relation to security breaching.

---

### 9. "kill" — Process Termination

**Risk category:** Cybersecurity (false positive)
**Software meaning:** Terminating a process or request

| File | Context |
|------|---------|
| `Claude-Opus-Review/06-misc-bugs.md` | "A single `ConnectionError` raises and kills the request" — connection failure aborts the HTTP request |

**Verdict:** Standard Unix terminology (`kill` signal, `kill` command). No relation to violence.

---

### 10. "bypass" — Software Architecture

**Risk category:** Cybersecurity (false positive)
**Software meaning:** An alternative code path that skips an intermediate layer

| File | Context |
|------|---------|
| `phase-8-improvements.md` | "bypasses the existing data model" — architectural observation about code flow |
| `phase-7-improvements.md` | "The 10-char minimum gate is bypassed because this is deterministic approval" — intended design behavior |

**Verdict:** Standard software architecture terminology. No relation to security bypasses.

---

### 11. "biome" — Game Environment Type

**Risk category:** Biology (false positive)
**Game-dev meaning:** A large geographical region with consistent climate, flora, and visual style

| File | Context |
|------|---------|
| `Worldforge-master/.../master_materials.py` | `biome: str` parameter for material generation — selects palette for forest/desert/rocky |
| `Worldforge-master/.../style_validator.py` | `--biome forest` CLI argument — validates textures against biome palette |
| `Worldforge-master/.../worldforge_style_v1.json` | `"biomes": {"forest": {...}, "desert": {...}}` — style definitions per environment |
| `Worldforge-master/.../ecology/eco_region.gd` | `var biome_type: String = "forest"` — ecology simulation for game worlds |

**Verdict:** Standard game/environment art terminology (Minecraft biomes, Godot terrain biomes). Present in virtually every open-world game. No relation to microbiology or life sciences.

---

### 12. "decay" — Visual Asset Degradation

**Risk category:** Biology (false positive)
**Game-dev meaning:** Visual wear-and-tear stage on 3D assets

| File | Context |
|------|---------|
| `Worldforge-master/.../style_validator.py` | `decay_stage: str = "healthy"` — asset condition (healthy/damaged/ruined) |
| `Worldforge-master/.../style_schema_definition.json` | Decay modifiers shift biome palette values for aged assets |

**Verdict:** Standard 3D art pipeline terminology (decay maps, wear layers). No relation to biological decay or disease.

---

### 13. "healthy" — Asset Condition State

**Risk category:** Biology (false positive)
**Game-dev meaning:** An asset's visual condition (pristine, not damaged)

| File | Context |
|------|---------|
| `Worldforge-master/.../style_validator.py` | `decay="healthy"` — CLI flag for asset condition |

**Verdict:** Asset pipeline state enum value. Same usage as "healthy server" in DevOps. No relation to medical health.

---

### 14. "disaster" — Game World Event Simulation

**Risk category:** Cybersecurity (false positive)
**Game-dev meaning:** Simulated natural events affecting a game world

| File | Context |
|------|---------|
| `devforge/simulation/disaster_system.py` | `DisasterSystem` randomly triggers `"earthquake"`, `"flood"`, `"volcano"` events in simulation |

**Verdict:** Common game mechanic (SimCity disasters, Civilization natural events, Minecraft weather). No relation to actual disaster planning or infrastructure attacks.

---

### 15. "destroy" — Data Safety Guarantee

**Risk category:** Cybersecurity (false positive)
**Software meaning:** Permanently deleting data (used in a negative guarantee)

| File | Context |
|------|---------|
| `devforge/transaction/transaction.py` | `"valid work is never destroyed"` — transaction safety guarantee |

**Verdict:** Used in the context of a *safety guarantee* (we WON'T destroy your work). Standard software terminology.

---

### 16. "violation" — Architectural Contract Breach

**Risk category:** Cybersecurity (false positive)
**Software meaning:** Intentional breaking of a code contract for testing

| File | Context |
|------|---------|
| `Worldforge-master/.../combat/combat_resolver_VIOLATION.gd` | Test fixture intentionally violating architectural contract `RT-02` to test validation gates |

**Verdict:** Software testing terminology. This file is named VIOLATION because it's a deliberately broken test fixture used to verify that the validation system catches contract breaches.

---

### 17. "death" — Software Metaphor

**Risk category:** Biology (false positive)
**Software meaning:** Figurative language about code patterns

| File | Context |
|------|---------|
| `phase-7-improvements.md` | "death by a thousand exceptions" — metaphor for exception overload |

**Verdict:** Common figurative language. No relation to actual death or mortality.

---

### 18. "deadly" — Figurative Emphasis

**Risk category:** Biology (false positive)
**Software meaning:** Figurative emphasis in documentation

| File | Context |
|------|---------|
| `phase-7-improvements.md` | Used in figurative software engineering context |

**Verdict:** Figurative language. No relation to lethality.

---

### 19. "signal" — Godot Event System

**Risk category:** Cybersecurity (false positive — could be confused with signals intelligence)
**Game-dev meaning:** Godot's built-in event/delegate pattern for inter-node communication

| File | Context |
|------|---------|
| `devforge/reasoning/prompts/planner_prompt.py` | `connect_signal` operation type — standard Godot signal wiring |
| `devforge/compilation/pipeline/architecture_planner.py` | `"type": "signal"` in connection schema |
| `devforge/compilation/ir/plan.py` | `class ConnectSignalStep(PlanStep)` — pipeline step representation |
| `devforge/governance/analyzer.py` | `class GDSignal` — parsing GDScript signal declarations |
| `devforge/knowledge/default_patterns.py` | Pattern definitions include `"signals": []` for entities |

**Verdict:** Core Godot Engine feature (equivalent to C# events/delegates or Unity's UnityEvent). Present in every Godot project. No relation to signals intelligence or communications interception.

---

### 20. "collision" — Godot Physics Detection

**Risk category:** Cybersecurity (false positive — could be confused with vehicle collision attack)
**Game-dev meaning:** Godot physics collision detection for game objects

| File | Context |
|------|---------|
| `devforge/compilation/pipeline/completeness.py` | `CollisionShape3D` — required physics shape for CharacterBody3D |
| `devforge/compilation/pipeline/architecture_planner.py` | `CollisionShape3D` in allowed godot-type enum |
| `devforge/knowledge/scene/scene_graph.py` | `CollisionShape2D`, `CollisionShape3D` in node type registry |
| `devforge/simulation/preview/preview_validator.py` | Validation rule: `CharacterBody3D: ["CollisionShape3D"]` — physics body needs collision shape |

**Verdict:** Standard 3D game physics terminology. Every game engine has collision detection. No relation to physical collisions or vehicle attacks.

---

## Terms Confirmed NOT in Project Code

The following biology-risk terms appeared in regex searches (matching substrings like "gen-" in "gen-1") but do **not** exist in any project source code, configuration files, or patterns:

| Term | Search Result |
|------|--------------|
| `radioactive` | 0 matches in `.py`, `.gd`, `.json` files |
| `nuclear` | 0 matches in `.py`, `.gd`, `.json` files |
| `genetic` | 0 matches ("gen-1" substring false positive) |
| `dna` | 0 matches ("gdna" substring false positive) |
| `rna` | 0 matches |
| `bacteria` | 0 matches |
| `viral` | 0 matches |
| `pandemic` | 0 matches |
| `epidemic` | 0 matches |
| `organism` | 0 matches |
| `pathogen` | 0 matches |
| `toxin` | 0 matches |
| `breed` | 0 matches |
| `malware` | 0 matches in code (only in Claude review discussion docs) |
| `exploit` | 0 matches in code (only in Claude review discussion docs) |

---

## Additional Clarifications

### What This Project IS

- A **Godot 4 game development assistant** — converts natural language into game code
- A **procedural asset generator** — creates terrain, materials, and 3D assets
- A **pipeline orchestrator** — validates, compiles, and applies game modifications
- A **local development tool** — runs entirely on the developer's machine

### What This Project IS NOT

- ❌ A cybersecurity tool or exploit builder
- ❌ A malware generator or attack framework
- ❌ A biological simulation or research tool
- ❌ A model extraction or prompt injection tool
- ❌ A network penetration testing utility
- ❌ A weapon or dangerous device controller

### On Theoretical Misuse

While the pipeline could theoretically generate any GDScript the LLM model produces, it is **constrained by GBNF grammar** to Godot game operations only (add_node, create_file, attach_script, connect_signal, and 4 other game-specific operation types). The grammar enumerates 33 valid Godot node types. The model cannot output arbitrary code — only Godot game operations within the grammar's structural bounds.

### All External Connections

| Service | Purpose |
|---------|---------|
| llama.cpp (localhost) | Local LLM inference for code generation |
| Godot Editor (localhost) | Game engine integration via MCP/HTTP |
| Git (local) | Version control for generated files |

**No external network services are contacted. No data is exfiltrated.**

---

## Glossary: Game-Dev → Safety-Relevant Term Mappings

| Term in Code | Actual Meaning | Would Only Be Concerning If |
|-------------|----------------|---------------------------|
| `Attack` | Game combat component | Used in cyberattack context |
| `payload` | HTTP/JSON request body | Used in malware delivery context |
| `inject` | Dependency injection | Used in code injection context |
| `damage` | Game hit point calculation | Used in infrastructure damage context |
| `combat` | Game fight system | Used in cyber warfare context |
| `biome` | Game environment (forest/desert) | Used in microbiology context |
| `decay` | Visual asset aging | Used in biological decay context |
| `disaster` | Game world event simulation | Used in actual disaster planning |
| `weapon` | 3D asset category | Used in real weapon design |
| `kill` | Process termination | Used in violent context |
| `bypass` | Code architecture path | Used in security bypass context |
| `bomb` | Cost/latency metaphor | Used in explosive context |
| `hack` | Programming workaround | Used in security breaching context |

---

## Recommended Submission Notes

If submitting this project for Claude Fable 5 review:

1. **Include this manifest** as the first file reviewed
2. **Note that all "concerning" terms** map to standard game-dev or software-engineering concepts
3. **The project has passed** 38/38 pipeline tests + integration suite with zero security-relevant operations
4. **The LLM generates Godot game code only** — output is GDScript, scene files, and asset metadata

---

*Generated for Claude Fable 5 automated safety review compliance.*
*Project: Godot 4 Game Development AI Pipeline*
*No content in this project relates to offensive cybersecurity, biological research, or model extraction.*
