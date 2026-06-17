"""DevForge Pipeline Verification — runs without pytest/fastapi.

Tests the entire pipeline from prompt → operations using a mock LLM.
Imports are lazy — no tests execute at import time.

Run with::

    python -m devforge.verify_pipeline
"""

import json
import sys
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

PASS = 0
FAIL = 0
_registry: list = []


def test(name, section=None):
    """Decorator for test functions — defers execution so tests never
    run at import time.  All registered tests execute under
    ``if __name__ == \"__main__\"`` only."""

    def decorator(fn):
        _registry.append((section, name, fn))
        return fn

    return decorator


# ═══════════════════════════════════════════════════════════════
# Test definitions (registered, not executed)
# ═══════════════════════════════════════════════════════════════

# ── 1. Module Imports ──


@test("Logger imports", section="Module Imports")
def _():
    from devforge.infrastructure.logger import logger


@test("LLM Router imports", section="Module Imports")
def _():
    from devforge.infrastructure.llm.router import LLMRouter


@test("System Graph imports", section="Module Imports")
def _():
    from devforge.knowledge.system_graph.system_graph import SystemGraph


@test("Scene Graph imports", section="Module Imports")
def _():
    from devforge.knowledge.scene.scene_graph import SceneGraph


@test("IR Plan imports", section="Module Imports")
def _():
    from devforge.compilation.ir.plan import DevForgePlan, CreateEntityStep


@test("Architecture Planner imports", section="Module Imports")
def _():
    from devforge.compilation.pipeline.architecture_planner import ArchitecturePlanner


@test("Architecture Compiler imports", section="Module Imports")
def _():
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler


@test("Validator imports", section="Module Imports")
def _():
    from devforge.compilation.pipeline.validator import OperationValidator


@test("Completeness Checker imports", section="Module Imports")
def _():
    from devforge.compilation.pipeline.completeness import CompletenessChecker


@test("Repair Engine imports", section="Module Imports")
def _():
    from devforge.compilation.pipeline.repair_engine import RepairEngine


@test("Context Assembler imports", section="Module Imports")
def _():
    from devforge.compilation.pipeline.context_assembler import ContextAssembler


@test("Monitor imports", section="Module Imports")
def _():
    from devforge.platform.monitor.monitor import Monitor


@test("Runtime Config imports", section="Module Imports")
def _():
    from devforge.infrastructure.runtime_config import RuntimeConfig


# ── 2. Scene Graph ──


@test("Parse empty scene", section="Scene Graph")
def _():
    from devforge.knowledge.scene.scene_graph import SceneGraph

    sg = SceneGraph({"name": "Main", "type": "Node3D", "children": []})
    assert sg.root.name == "Main"
    assert sg.has_path("/root")


@test("Parse scene with children", section="Scene Graph")
def _():
    from devforge.knowledge.scene.scene_graph import SceneGraph

    sg = SceneGraph(
        {"name": "Main", "type": "Node3D", "children": [{"name": "Player", "type": "CharacterBody3D", "children": []}]}
    )
    assert sg.has_path("/root/Main/Player")
    assert sg.find_by_path("/root/Main/Player").type == "CharacterBody3D"


@test("Validate Godot types", section="Scene Graph")
def _():
    from devforge.knowledge.scene.scene_graph import SceneGraph

    assert SceneGraph.is_valid_godot_type("CharacterBody3D")
    assert SceneGraph.is_valid_godot_type("Camera3D")
    assert not SceneGraph.is_valid_godot_type("FakeNode")


# ── 3. System Graph ──


@test("Add and query nodes", section="System Graph")
def _():
    from devforge.knowledge.system_graph.system_graph import SystemGraph, NodeType

    sg = SystemGraph()
    sg.add_node("player", "Player", NodeType.ENTITY)
    assert sg.has_node("player")
    assert sg.get_node("player").name == "Player"


@test("Build context", section="System Graph")
def _():
    from devforge.knowledge.system_graph.system_graph import SystemGraph, NodeType

    sg = SystemGraph()
    sg.add_node("movement", "Movement", NodeType.SYSTEM)
    ctx = sg.build_context()
    assert "Movement" in ctx


# ── 4. Architecture Planner ──


@test("Parse valid JSON response", section="Architecture Planner")
def _():
    from devforge.compilation.pipeline.architecture_planner import ArchitecturePlanner

    p = ArchitecturePlanner()
    r = p._parse_response('{"systems":[],"entities":[{"name":"Player","type":"CharacterBody3D"}],"connections":[]}')
    assert len(r["entities"]) == 1
    assert r["entities"][0]["name"] == "Player"


@test("Parse JSON with markdown fences", section="Architecture Planner")
def _():
    from devforge.compilation.pipeline.architecture_planner import ArchitecturePlanner

    p = ArchitecturePlanner()
    r = p._parse_response('```json\n{"systems":[],"entities":[],"connections":[]}\n```')
    assert r["systems"] == []


@test("Parse JSON with thinking tags", section="Architecture Planner")
def _():
    from devforge.compilation.pipeline.architecture_planner import ArchitecturePlanner

    p = ArchitecturePlanner()
    r = p._parse_response('<think>reasoning</think>{"systems":[],"entities":[],"connections":[]}')
    assert r["entities"] == []


@test("Plan with mock LLM", section="Architecture Planner")
def _():
    from devforge.compilation.pipeline.architecture_planner import ArchitecturePlanner

    p = ArchitecturePlanner()
    mock = lambda prompt: '{"systems":[],"entities":[{"name":"Enemy","type":"CharacterBody3D"}],"connections":[]}'
    r = p.plan(context="empty", prompt="add enemy", llm_fn=mock)
    assert len(r["entities"]) == 1


# ── 5. Architecture Compiler ──


@test("Compile entities to plan steps", section="Architecture Compiler")
def _():
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler

    c = ArchitectureCompiler()
    plan = c.compile(
        {
            "systems": [{"name": "Movement", "description": "Player movement"}],
            "entities": [{"name": "Player", "type": "CharacterBody3D"}],
            "connections": [],
        }
    )
    assert len(plan.steps) > 0


@test("Reject invalid Godot types", section="Architecture Compiler")
def _():
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler

    c = ArchitectureCompiler()
    plan = c.compile({"systems": [], "entities": [{"name": "Foo", "type": "NotReal"}], "connections": []})
    ops = plan.compile_all()
    for op in ops["operations"]:
        if op["type"] == "add_node":
            assert op["node_type"] == "Node3D", f"Expected Node3D fallback, got {op['node_type']}"


@test("Skip existing entities", section="Architecture Compiler")
def _():
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler
    from devforge.knowledge.scene.scene_graph import SceneGraph

    c = ArchitectureCompiler()
    scene = SceneGraph(
        {"name": "Main", "type": "Node3D", "children": [{"name": "Player", "type": "CharacterBody3D", "children": []}]}
    )
    plan = c.compile(
        {"systems": [], "entities": [{"name": "Player", "type": "CharacterBody3D"}], "connections": []}, scene=scene
    )
    ops = plan.compile_all()
    add_ops = [o for o in ops["operations"] if o["type"] == "add_node" and o["name"] == "Player"]
    assert len(add_ops) == 0


# ── 6. IR Plan ──


@test("Plan compile produces files and operations", section="IR Plan")
def _():
    from devforge.compilation.ir.plan import DevForgePlan, CreateEntityStep, CreateScriptStep, AttachScriptStep

    plan = DevForgePlan(
        goal="test",
        steps=[
            CreateEntityStep(name="Player", node_type="CharacterBody3D"),
            CreateScriptStep(path="scripts/player.gd", content="extends CharacterBody3D"),
            AttachScriptStep(node="/root/Main/Player", script="scripts/player.gd"),
        ],
    )
    r = plan.compile_all()
    assert len(r["files"]) == 1
    assert len(r["operations"]) == 2


@test("Plan validation catches empty names", section="IR Plan")
def _():
    from devforge.compilation.ir.plan import DevForgePlan, CreateEntityStep

    plan = DevForgePlan(steps=[CreateEntityStep(name="")])
    errors = plan.validate()
    assert len(errors) > 0


# ── 7. Operation Validator ──

_SCENE = {"name": "Main", "type": "Node3D", "children": []}


@test("Accept valid add_node", section="Operation Validator")
def _():
    from devforge.compilation.pipeline.validator import OperationValidator

    v = OperationValidator()
    ops = [{"type": "add_node", "parent": "/root", "node_type": "CharacterBody3D", "name": "Player"}]
    valid, errors = v.validate(ops, _SCENE, [])
    assert len(valid) == 1 and len(errors) == 0


@test("Reject invalid parent", section="Operation Validator")
def _():
    from devforge.compilation.pipeline.validator import OperationValidator

    v = OperationValidator()
    ops = [{"type": "add_node", "parent": "/root/NonExistent", "node_type": "Node3D", "name": "X"}]
    valid, errors = v.validate(ops, _SCENE, [])
    assert len(valid) == 0 and len(errors) == 1


@test("Reject invalid Godot type", section="Operation Validator")
def _():
    from devforge.compilation.pipeline.validator import OperationValidator

    v = OperationValidator()
    ops = [{"type": "add_node", "parent": "/root", "node_type": "FakeType", "name": "X"}]
    valid, _ = v.validate(ops, _SCENE, [])
    assert len(valid) == 0


@test("Accept chained add_node + attach_script", section="Operation Validator")
def _():
    from devforge.compilation.pipeline.validator import OperationValidator

    v = OperationValidator()
    ops = [
        {"type": "add_node", "parent": "/root", "node_type": "CharacterBody3D", "name": "Player"},
        {"type": "attach_script", "node": "/root/Player", "script": "scripts/player.gd"},
    ]
    files = [{"path": "scripts/player.gd", "content": "extends CharacterBody3D"}]
    valid, errors = v.validate(ops, _SCENE, files)
    assert len(valid) == 2, f"Expected 2 valid ops, got {len(valid)} (errors: {errors})"


# ── 8. Completeness Checker ──


@test("Adds CollisionShape3D for CharacterBody3D", section="Completeness Checker")
def _():
    from devforge.compilation.pipeline.completeness import CompletenessChecker

    cc = CompletenessChecker()
    ops = [{"type": "add_node", "parent": "/root", "node_type": "CharacterBody3D", "name": "Player"}]
    result = cc.enforce([], ops, _SCENE)
    collision = [o for o in result if o.get("name") == "CollisionShape3D"]
    assert len(collision) == 1


@test("Adds Camera3D for 3D scenes", section="Completeness Checker")
def _():
    from devforge.compilation.pipeline.completeness import CompletenessChecker

    cc = CompletenessChecker()
    ops = [{"type": "add_node", "parent": "/root", "node_type": "Node3D", "name": "Thing"}]
    result = cc.enforce([], ops, _SCENE)
    names = [o.get("name") for o in result]
    assert "MainCamera" in names


# ── 9. Repair Engine ──


@test("Fixes missing /root prefix", section="Repair Engine")
def _():
    from devforge.compilation.pipeline.repair_engine import RepairEngine

    r = RepairEngine()
    ops = [{"type": "add_node", "parent": "Main", "node_type": "Node3D", "name": "Foo"}]
    result = r.repair(ops, [], _SCENE, [])
    assert result[0]["parent"].startswith("/root")


# ── 10. LLM Router ──


@test("Mock backend works", section="LLM Router")
def _():
    from devforge.infrastructure.llm.router import LLMRouter

    r = LLMRouter()
    r.configure_mock(lambda p: "hello")
    assert r.generate("test") == "hello"


@test("Unconfigured raises error", section="LLM Router")
def _():
    from devforge.infrastructure.llm.router import LLMRouter

    r = LLMRouter()
    try:
        r.generate("test")
        assert False, "Should have raised"
    except RuntimeError:
        pass


# ── 11. Full Pipeline (end-to-end) ──


@test("Complete pipeline: prompt → operations", section="Full Pipeline (end-to-end)")
def _():
    from devforge.compilation.pipeline.architecture_planner import ArchitecturePlanner
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler
    from devforge.compilation.pipeline.completeness import CompletenessChecker
    from devforge.compilation.pipeline.validator import OperationValidator
    from devforge.compilation.pipeline.context_assembler import ContextAssembler
    from devforge.knowledge.system_graph.system_graph import SystemGraph

    scene = {"name": "Main", "type": "Node3D", "children": []}

    def mock_llm(prompt):
        return json.dumps(
            {
                "systems": [{"name": "Movement", "description": "Player movement"}],
                "entities": [{"name": "Player", "type": "CharacterBody3D"}],
                "connections": [],
            }
        )

    graph = SystemGraph()
    assembler = ContextAssembler(Path("."), graph)
    context = assembler.assemble(scene, "create a player")
    planner = ArchitecturePlanner()
    delta = planner.plan(context=context, prompt="create a player", llm_fn=mock_llm)
    assert len(delta["entities"]) == 1
    compiler = ArchitectureCompiler()
    plan = compiler.compile(delta)
    result = plan.compile_all()
    files = result["files"]
    operations = result["operations"]
    checker = CompletenessChecker()
    operations = checker.enforce(files, operations, scene)
    validator = OperationValidator()
    valid_ops, errors = validator.validate(operations, scene, files)
    add_ops = [o for o in valid_ops if o["type"] == "add_node"]
    assert any(o["name"] == "Player" for o in add_ops), f"Expected Player, got {add_ops}"
    assert len(files) > 0, "Expected at least one script file"


# ── 12. Monitor ──


@test("Trace lifecycle", section="Monitor")
def _():
    from devforge.platform.monitor.monitor import Monitor

    m = Monitor()
    t = m.begin_trace("test")
    assert t.status == "running"
    m.log_step(t, "step1")
    m.end_trace(t, status="complete")
    assert t.status == "complete"


# ═══════════════════════════════════════════════════════════════
# Test runner (only runs under __main__)
# ═══════════════════════════════════════════════════════════════


def _run_tests() -> int:
    global PASS, FAIL

    print("\n" + "=" * 60)
    print("DEVFORGE YEAR 1 — PIPELINE VERIFICATION")
    print("=" * 60)

    current_section = None
    for section, name, fn in _registry:
        if section is not None and section != current_section:
            current_section = section
            print(f"\n{section}\n")

        try:
            fn()
            print(f"  PASS  {name}")
            PASS += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            traceback.print_exc()
            FAIL += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)

    if FAIL > 0:
        print("\nSome tests failed. Fix issues before deploying.\n")
        return 1
    else:
        print("\nAll tests passed! Pipeline is stable.\n")
        return 0


if __name__ == "__main__":
    sys.exit(_run_tests())
