# Deferred Claude Opus Recommendations — Status

**Last updated:** June 10, 2026
**Status:** ALL 11 ITEMS IMPLEMENTED ✅

---

## Final Status

| Item | Description | Implemented | By |
|------|------------|-------------|-----|
| P1 | Full escalating retry (context trim + greedy temp=0.0) | ✅ | Fable |
| P2 | Per-stage sampler profiles | ✅ | Us (Phase 6) |
| P3 | Idempotency check in DeterministicPlanner | ✅ | Us (quick wins) |
| P4 | /tokenize-based counting | ✅ | Us (Phase 6) |
| N1 | Node-path grammar rule | ✅ | Us (Phase 6) |
| N2 | Modification + multi-entity prompt examples | ✅ | Fable |
| N3 | Cache warming on startup | ✅ | Us (Phase 6) |
| N4 | Repair convergence detection | ✅ | Us (Phase 6) |
| N5 | Coordinator/preview_api.py retry | ✅ | Us (Phase 6) |
| N6 | Extract max_plan_retries to RuntimeConfig | ✅ | Us (quick wins) |
| N7 | Fix prompt_builder.py placement convention | ✅ | Us (quick wins) |

**Total: 11/11 complete**

---

## Implementation Details

### P1 — Full escalating retry
- **By:** Fable (Claude Fable 5)
- **Files:** `llama_client.py`, `engine.py`, `router.py`
- Attempt 1: full context. Attempt 2+: `assemble(..., minimal=True)` + error feedback. Final: `temperature=0.0` greedy decoding.
- Also fixed critical SyntaxError in `llama_client.py` (orphaned response-parsing code from Phase 5 retry refactor)

### P2 — Per-stage sampler profiles
- **By:** Us (Phase 6)
- **Files:** `runtime_config.py`, `llama_client.py`, `engine.py`
- `RuntimeConfig.sampler_profiles` dict: arch=`0.2/0.9/40`, scripts=`0.4/0.95/64`, ops=`0.2/0.9/40`, decomp=`0.3/0.9/40`
- `LlamaClient.generate()` accepts optional `temperature`, `top_p`, `top_k` overrides
- `engine.py` passes arch profile to LLM calls via `**arch_profile`

### P3 — Idempotency check
- **By:** Us (quick wins)
- **Files:** `architecture_planner.py`
- `DeterministicPlanner.match()` filters entity names against existing `graph.nodes`

### P4 — Tokenize-based counting
- **By:** Us (Phase 6)
- **Files:** `llama_client.py`, `context_assembler.py`
- `LlamaClient.tokenize()` calls `/tokenize` endpoint, returns int or None
- `ContextAssembler._get_token_counter()` lazy-loads the LLM backend
- `assemble()` uses accurate token count when available, falls back to `len//4` heuristic

### N1 — Node-path grammar rule
- **By:** Us (Phase 6)
- **Files:** `planner_grammar.gbnf`
- `node-path` rule enforces `/root/Main/...` prefix
- Wired into all 7 operation rules: `add_node.parent`, `remove_node.node`, `rename_node.node`, `attach_script.node`, `set_property.node`, `connect_signal.source`/`target`, `add_child_scene.parent`
- Hyphens allowed in path components: `[a-zA-Z0-9_-]`

### N2 — Modification + multi-entity examples
- **By:** Fable (Claude Fable 5)
- **Files:** `architecture_planner.py`
- Example B: modifying an existing entity without recreating it
- Example C: multi-entity with connections

### N3 — Cache warming
- **By:** Us (Phase 6)
- **Files:** `lru_cache.py`, `server.py`, `mcp_server.py`
- `warm_from_patterns()` loads pattern JSONs, inserts prompt-only wildcard keys (`{hash}:*:*`)
- Two-tier lookup in `get()`: exact match first, then prompt-only fallback
- Called at startup in both `server.py` and `mcp_server.py`

### N4 — Repair convergence detection
- **By:** Us (Phase 6)
- **Files:** `repair_engine.py`
- Tracks `frozenset` of errors across repair calls
- Returns unchanged after 2 identical error sets
- Resets state after convergence (prevents cross-run leakage)
- Forward-looking: currently repair is single-pass, guard activates when LLM repair loops are added

### N5 — Coordinator path retry
- **By:** Us (Phase 6)
- **Files:** `preview_api.py`
- 3-attempt escalating retry in the generate endpoint
- Uses `RuntimeConfig.max_plan_retries` (not hardcoded)
- Context trimming via `assemble(..., minimal=True)` on attempts 2+
- Narrow exception handling (`RuntimeError`, `ValueError`)

### N6 — Extract max_plan_retries
- **By:** Us (quick wins)
- **Files:** `runtime_config.py`, `engine.py`
- `RuntimeConfig.max_plan_retries: int = 3`
- Engine retry loop uses `self._config.max_plan_retries`

### N7 — Fix prompt_builder.py convention
- **By:** Us (quick wins)
- **Files:** `prompt_builder.py`
- Hardcoded `"Place files in game/"` → `f"Place files in {self.game_root}/"`

---

## Files Changed (cumulative)

| File | Phases | Changes |
|------|--------|---------|
| `llama_client.py` | 0,1,5,P1,P2,P4 | Gemma template, sampling params, grammar self-test, truncation, retry fix, per-call overrides, tokenize() |
| `router.py` | 1,5,P1 | inspect.signature dispatch, grammar on chat(), circuit breaker, truncation |
| `runtime_config.py` | 1,2,P2,N6 | llama_max_tokens, context_token_budget, sampler_profiles, max_plan_retries |
| `engine.py` | 0,1,2,3,4,5,P1,P2,N6 | PlanningError, truncation, dedup, retry escalation, risk_tier, dedupe fix, per-stage profiles, context trimming |
| `context_assembler.py` | 2,P4 | Token budget, relevance ranking, signature extraction, minimal mode, /tokenize support |
| `architecture_planner.py` | 0,3,4,P3,N2 | PlanningError, prompt restructure, DeterministicPlanner, idempotency, multi-example |
| `repair_engine.py` | 4,N4 | Godot 3→4 type table, scripts/ prefix, convergence detection |
| `planner_grammar.gbnf` | 0,N1 | JSON string rule, godot-type enum, node-path rule, wired into operations |
| `planner_prompt.py` | 3,N7 | Operation type alignment, path convention |
| `feature_decomposer.py` | 3 | Grammar loading + wiring |
| `lru_cache.py` | 4,N3 | Prompt normalization, structural hash, disk persistence, two-tier warming |
| `decomposer.gbnf` | 3 | New grammar file |
| `patterns/*.json` | 4 | Triggers + ready deltas |
| `preview_api.py` | 2,N5 | Import update, escalating retry with context trimming |
| `prompt_builder.py` | N7 | Game root path convention |
| `mcp_server.py` | N3 | Cache warming on startup |
| `server.py` | N3 | Cache warming on startup |
| `incremental_context_builder.py` | 2 | Deprecated (absorbed into ContextAssembler) |
| `test_integration.py` | 4 | Fixed prompt path |

**22 files, 6 phases, 3 quick wins, Fable's 3 fixes, Phase 6's 6 remaining items = 37 total changes**
