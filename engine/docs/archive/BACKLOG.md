<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# Work Order Backlog

Sequenced from `CAPABILITY-ROADMAP.md` (the strategy document — read it for
the why; work orders carry the how). **Claude writes work orders; executors
do not start backlog items without one.** Items become work orders only
after the previous phase's handbacks are reviewed.

## Ready (work orders exist)

| WO | Capability | Executor | Status |
|---|---|---|---|
| WO-001 | Scene Doctor (5 rules, tier 0) | MiniMax | Ready |
| WO-002 | Batch Operator (preview/apply) | MiniMax (+DeepSeek review) | Ready — after WO-001 |
| WO-003 | Error Triage (knowledge table) | MiniMax (+DeepSeek review) | Ready — after WO-002 |
| WO-023 | Configurable prompt template (gemma/chatml/raw) | DeepSeek | Ready |

## Queued (Claude will spec after Phase A review)

| Future WO | Capability | Blocking question Claude must resolve first |
|---|---|---|
| WO-004 | Live property access for the executor (`node_get_properties` plumbing) — unlocks Scene Doctor rules R3/R4 live | param shape of godot-ai `get_node_properties` |
| WO-005 | Template Forge engine (slot system, no templates yet) | template IR format decision |
| WO-006 | First templates: `save_system`, `interaction_system`, `fps_controller` | must be extracted from the user's actual game code |
| WO-007 | Progress Journal v1 (scene snapshot diffs, session brief) | snapshot storage location/retention |
| WO-008 | Lorekeeper v1 (item/NPC/quest schemas + integrity checks) | schema design needs the user's content model |
| WO-009 | Quest Graph Validator | depends on WO-008 schemas |
| WO-010 | Performance Sentinel | needs live-stack verification of `get_performance_monitors` |

## Rules

- One work order in flight at a time.
- `scripts/run_all_tests.sh` green is the entry AND exit condition for every WO.
- DeepSeek v4 Pro budget is 5 hours TOTAL across all work orders — the
  running total lives in WORKLOG entries. When in doubt, use MiniMax.
