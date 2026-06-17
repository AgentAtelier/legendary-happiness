# Archived dead modules (June 2026 round-1 cleanup)

These modules could never import — they reference packages that do not
exist in this tree (`devforge.core`, `devforge.state`, `devforge.knowledge.state`,
`devforge.knowledge.specs`, `devforge.reasoning.ai.context`) — and nothing
in the live codebase imports them. They are leftovers from an earlier
project layout (pre-DevForge / TerraForge era).

Original locations:

- `platform-server/preview_api.py`      ← devforge/platform/server/preview_api.py
- `reasoning-ai-planning/plan_cache.py`        ← devforge/reasoning/ai/planning/
- `reasoning-ai-planning/plan_generator.py`    ← devforge/reasoning/ai/planning/
- `reasoning-ai-planning/planner_interfaces.py` ← devforge/reasoning/ai/planning/
- `reasoning-ai-planning/prompt_builder.py`    ← devforge/reasoning/ai/planning/

Note: `LRUPlanCache` (the live plan cache) lives in
`devforge/reasoning/ai/planning/lru_cache.py` and was NOT archived.
