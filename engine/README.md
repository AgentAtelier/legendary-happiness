# DevForge — Phase-by-Phase Implementation Guides

These `.md` files are ready-to-execute implementation guides for each phase of the DevForge roadmap. Each file references the existing assets from the four source branches and provides specific tasks, code skeletons, and "done when" criteria.

## Source Branches Investigated

| Branch | Zip File | What It Contains |
|--------|----------|-----------------|
| **TerraForge (gen-2)** | `terraforge-master.zip` | 187 Python files: deterministic pipeline, SystemGraph, agents, LLM router, smoke test, fixtures |
| **DevForge (gen-1)** | `DevForge-main.zip` | Compiled `.pyc` only: AST patching, transactions, git governance, headless Godot runner, GraphRAG |
| **ai-lab** | `ai-lab-main.zip` | 7 design docs only: Critic-Manager loop, invariants, ValidationResult contract, validator spec |
| **WorldForge** | `Worldforge-master.zip` | 29 Python files: contracts parser, gates, scope lock, risk scoring, decision log, metrics |

## Phase Guide Index

| Phase | File | Goal | Source Branch | Effort |
|-------|------|------|---------------|--------|
| 1 | [`phase-1-core-pipeline.md`](phase-1-core-pipeline.md) | Clean, tested core pipeline | TerraForge | 1–2 sessions |
| 2 | [`phase-2-godot-mcp.md`](phase-2-godot-mcp.md) | Touch Godot via godot-ai MCP | External (godot-ai) | 1 session |
| 3 | [`phase-3-mcp-server.md`](phase-3-mcp-server.md) | Expose DevForge as MCP server | TerraForge | 1 session |
| 4 | [`phase-4-headless-godot.md`](phase-4-headless-godot.md) | Ground-truth headless validation | DevForge gen-1 | 2 sessions |
| 5 | [`phase-5-transactional-safety.md`](phase-5-transactional-safety.md) | Transactional safety + git | DevForge gen-1 | 2 sessions |
| 6 | [`phase-6-quality-gate.md`](phase-6-quality-gate.md) | Critic-Manager + invariants | ai-lab | 2–3 sessions |
| 7 | [`phase-7-governance-audit.md`](phase-7-governance-audit.md) | Governance & audit layer | WorldForge | 1–2 sessions |
| 8 | [`phase-8-ast-patching.md`](phase-8-ast-patching.md) | AST patching for existing code | DevForge gen-1 | 3 sessions |
| 9 | [`phase-9-blackboard-agents.md`](phase-9-blackboard-agents.md) | Blackboard agents + GraphRAG | TerraForge + gen-1 | 3–4 sessions |
| 10 | [`phase-10-performance.md`](phase-10-performance.md) | Performance + knowledge enrichment | TerraForge | 2 sessions |

## Architecture Overview

```
Odysseus ─MCP→ DevForge MCP server  (apply_spec · build_feature · validate_spec)
  L8 Orchestrate   Coordinator + architect/planner/builder/QA/repair  [Phase 9]
  L2 Plan          grammar-constrained planner · FeatureDecomposer · PlanCache  [Phase 1+10]
  L1 Blackboard    SystemGraph + SceneGraph + code/spec graph + retriever  [Phase 1+9]
  L3 Compile       delta → IR → ops + AST patch (edit existing)  [Phase 1+8]
  L4 Validate      op/scene validity + invariants+critic + contracts/gate/scope-lock  [Phase 6+7]
  L5 Govern        deterministic risk score → human-review gate · decision log · metrics  [Phase 7]
  L6 Apply         checkpoint+fs-snapshot → godot-ai batch_execute → git commit  [Phase 2+3+5]
  L7 Verify        headless Godot run + diagnostic parse + live logs_read → repair loop  [Phase 4]
```

## Build Order Rationale

Phases 1–3 get a working single-step loop fast (immediate value).  
4–8 layer in trustworthiness — ground-truth validation, rollback safety, code quality, and governance — each independently useful even before the agents exist.  
9 unlocks autonomous multi-step features on top of that hardened base.  
10 tunes it.

Every phase ends in a capability you can verify in Godot.

## Standing Rules (Every Task)

- One canonical implementation per concept (delete duplicates on contact)
- A test with every module (port gen-1's test coverage as you reimplement)
- No hardcoded project assumptions (resolve by round-trip, store in config)
- Dogfood the invariants on DevForge's own Python
- Grammar-constrain structured output
- Bound every loop at 3
- Instrument every stage
- Scope-lock every change

## Key Source Files by Phase

### Phase 1 — TerraForge (187 Python files)
- `verify_pipeline.py` — dependency-free smoke test
- `devforge/knowledge/system_graph/system_graph.py` — SystemGraph (171 lines)
- `devforge/compilation/pipeline/validator.py` — OperationValidator
- `devforge/infrastructure/llm/router.py` — LLMRouter singleton
- `devforge/reasoning/ai/planning/feature_decomposer.py` — FeatureDecomposer
- `devforge/reasoning/ai/repair/error_parser.py` — ErrorParser

### Phase 7 — WorldForge (29 Python files, ready to port)
- `tools/orchestrator/contracts/parser.py` — ContractsParser (170 lines)
- `tools/orchestrator/gates/gate1.py` — Gate1Result + run_gate1 (380 lines)
- `tools/orchestrator/scope/scope_lock.py` — ScopeLock + validate (270 lines)
- `tools/orchestrator/reporting/risk_scoring.py` — compute_risk (180 lines)
- `tools/orchestrator/persistence/decision_log.py` — append_entry (270 lines)
- `tools/orchestrator/persistence/metrics_append.py` — append_row (180 lines)

### Phase 6 — ai-lab (7 design docs)
- `docs/validator_design.md` — Complete validate_patch contract + 6 rules
- `docs/invariants.md` — 4 deterministic + 4 semantic invariants
- `docs/architecture.md` — Critic-Manager loop data flow
- `docs/decisions/0001-critic-manager.md` — ADR with consequences

## Deferred (Not Dismissed)

- **WorldForge asset_factory:** AI-assisted asset baking/materials/geometry — future content generation axis
- **Neo4j:** Use the lightweight in-Python graph first; Neo4j only if needed
- **Dual-model 8B/14B swap:** Single model first; the router already supports the swap when needed
