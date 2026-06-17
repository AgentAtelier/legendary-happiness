<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# WO-001 — Scene Doctor (Phase A, capability #1)

**Read `00-EXECUTOR-BRIEFING.md` first.**
**Executor:** MiniMax M3. **DeepSeek steps:** none expected. **Est. effort:** 4–8h.
**Goal:** A deterministic scene auditor: rules walk the scene tree and report
violations. No LLM anywhere in this work order (tier 0).

## Deliverables

1. New package `devforge/auditing/` (`__init__.py` with docstring, `rules.py`,
   `scene_doctor.py`)
2. New MCP tool `audit_scene` in `devforge/platform/mcp_server.py`
3. New test suite `devforge/tests/test_scene_doctor.py` (≥ 10 tests),
   registered in `scripts/run_all_tests.sh`

## Data model (`devforge/auditing/scene_doctor.py`)

```python
@dataclass
class Violation:
    rule_id: str          # "R1".."R5"
    severity: str         # "CRITICAL" | "WARNING" | "INFO"
    node_path: str        # "/root/Main/Player"
    message: str          # what is wrong, one sentence, names the node
    suggestion: str       # how to fix it, one sentence, concrete

    def to_dict(self) -> dict: ...

class SceneDoctor:
    def __init__(self, props_lookup: Callable[[str], dict] | None = None):
        """props_lookup(node_path) -> property dict, or None when no live
        editor is available. Rules that need properties return a single
        INFO violation 'R<N> skipped (no property access)' when it's None
        — never crash, never silently skip."""

    def audit(self, scene_tree: dict) -> list[Violation]:
        """Run all rules against a scene-tree dict. Deterministic:
        same tree in, same violations out, stable ordering
        (by rule_id, then node_path)."""
```

Build node paths exactly like `SceneGraph` does (root is
`/root/<root name>`, children append `/<name>`). Reuse `SceneGraph` from
`devforge/knowledge/scene/scene_graph.py` rather than re-walking dicts by
hand — `all_nodes()` gives you `(name, type, path, children)` per node.

## The five rules (`devforge/auditing/rules.py`)

Each rule is a function `(graph: SceneGraph, props_lookup) -> list[Violation]`.
A module-level `ALL_RULES` list registers them.

| ID | Severity | Check | Notes |
|---|---|---|---|
| R1 | CRITICAL | Every node of type `CollisionShape3D` or `CollisionPolygon3D` must have a parent whose type is in `COLLISION_OBJECT_TYPES` | Define `COLLISION_OBJECT_TYPES = {"CharacterBody3D", "RigidBody3D", "StaticBody3D", "AnimatableBody3D", "Area3D", "VehicleBody3D"}` as a module constant with a comment that it mirrors Godot's CollisionObject3D subclasses |
| R2 | CRITICAL | Every node whose type is in `COLLISION_OBJECT_TYPES` must have at least one direct child of type `CollisionShape3D` or `CollisionPolygon3D` | The classic "falls through the floor" bug |
| R3 | WARNING | If the scene contains exactly one `Camera3D`, its `current` property must be truthy | Needs `props_lookup`; if the property is absent from the returned dict, treat as not-current (Godot default is false) |
| R4 | WARNING | Every `MeshInstance3D` must have a non-null `mesh` property | Needs `props_lookup` |
| R5 | WARNING | No two sibling nodes may share the same name | Pure structure; Godot silently renames on instancing, which breaks NodePath references |

Rules must tolerate malformed input (missing `type`, missing `name`,
non-dict children) by skipping the malformed node — never raise.

## MCP tool (in `mcp_server.py`)

```python
@mcp.tool()
def audit_scene() -> Dict[str, Any]:
    """<docstring: follow the validate_spec docstring style — explain when
    to call it, that it is read-only, and show the literal return shape>"""
```

Behavior: `_init()`, then `scene, version = _scene_store.get_or_fetch(_executor)`.
Build `props_lookup` from the executor: a lambda that calls
`_executor.resolve_node_properties(path)` — **this method does not exist;
instead** wire it as `None` for v1 and note in the docstring that
property rules report "skipped" until live property access lands (that is
WO-004, not yours). Return:

```json
{
  "scene_version": 12,
  "counts": {"critical": 1, "warning": 2, "info": 0},
  "violations": [
    {"rule_id": "R2", "severity": "CRITICAL", "node_path": "/root/Main/Player",
     "message": "...", "suggestion": "..."}
  ]
}
```

## Tests (`devforge/tests/test_scene_doctor.py`)

Standalone-script pattern (copy the header/runner from
`test_artifact_store.py`). Synthetic scene dicts only — no live stack, no
LLM, no MCP server import. Minimum cases:

1. R1 fires for a `CollisionShape3D` under a plain `Node3D`
2. R1 passes for a `CollisionShape3D` under `CharacterBody3D`
3. R2 fires for a `CharacterBody3D` with no shape child
4. R2 passes when a `CollisionPolygon3D` child exists
5. R3 reports "skipped" INFO when `props_lookup is None`
6. R3 fires when props_lookup returns `{"current": False}` for the only camera
7. R4 fires when `mesh` is None; passes when set
8. R5 fires for two siblings named "Enemy"; passes for same name in different parents
9. Malformed node (child without `type`) does not raise
10. Determinism: auditing the same tree twice yields identical ordered output

## Acceptance checklist

- [ ] `.venv/bin/python devforge/tests/test_scene_doctor.py` → all pass
- [ ] `scripts/run_all_tests.sh` → "All test suites passed."
- [ ] New suite registered in `scripts/run_all_tests.sh`
- [ ] `audit_scene` docstring shows literal JSON of the return shape
- [ ] WORKLOG.md entry appended
