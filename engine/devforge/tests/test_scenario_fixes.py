"""Unit tests for scenario score fixes (Bug 1 + Bug 2, 2026-06-14).

Bug 1: Invalid set_property ops on wrong node types are dropped by validator.
Bug 2: Deterministic delete/rename intent pre-pass injects _remove/_rename.
"""

from __future__ import annotations

import pytest


# ── Test scenes ─────────────────────────────────────────────────

SCENE_WITH_LIGHT = {
    "name": "Main",
    "type": "Node3D",
    "children": [
        {"name": "TestSun", "type": "DirectionalLight3D", "children": []},
    ],
}

SCENE_SIMPLE = {
    "name": "Main",
    "type": "Node3D",
    "children": [],
}


# ── Bug 1: Property-vs-type validation ─────────────────────────


def test_validator_drops_material_override_on_light():
    """material_override on a DirectionalLight3D is dropped by the validator."""
    from devforge.compilation.pipeline.validator import OperationValidator

    ops = [
        {"type": "add_node", "parent": "/root/Main", "name": "TestSun", "node_type": "DirectionalLight3D"},
        {
            "type": "set_property",
            "node": "/root/Main/TestSun",
            "property": "material_override",
            "value": {"__class__": "StandardMaterial3D"},
        },
        {
            "type": "set_property",
            "node": "/root/Main/TestSun",
            "property": "position",
            "value": {"x": 0, "y": 10, "z": 0},
        },
    ]
    valid, errors = OperationValidator().validate(ops, SCENE_WITH_LIGHT, files=[])

    # material_override should be dropped (invalid on DirectionalLight3D)
    # position should still be valid
    assert len(valid) == 2, f"Expected 2 valid ops (add_node + position), got {len(valid)}: {valid}"
    valid_props = [o.get("property") for o in valid if o["type"] == "set_property"]
    assert "material_override" not in valid_props
    assert "position" in valid_props
    assert len(errors) == 1
    assert "material_override" in errors[0]
    assert "DirectionalLight3D" in errors[0]


def test_validator_drops_mesh_on_light():
    """mesh on a DirectionalLight3D is dropped by the validator."""
    from devforge.compilation.pipeline.validator import OperationValidator

    ops = [
        {"type": "set_property", "node": "/root/Main/TestSun", "property": "mesh", "value": {"__class__": "BoxMesh"}},
    ]
    valid, errors = OperationValidator().validate(ops, SCENE_WITH_LIGHT, files=[])
    assert len(valid) == 0, f"Expected mesh on light to be dropped, got {valid}"
    assert len(errors) == 1
    assert "mesh" in errors[0]


def test_validator_allows_mesh_on_meshinstance():
    """mesh on a MeshInstance3D passes validation."""
    from devforge.compilation.pipeline.validator import OperationValidator

    scene = {
        "name": "Main",
        "type": "Node3D",
        "children": [
            {"name": "TestCube", "type": "MeshInstance3D", "children": []},
        ],
    }
    ops = [
        {"type": "set_property", "node": "/root/Main/TestCube", "property": "mesh", "value": {"__class__": "BoxMesh"}},
    ]
    valid, errors = OperationValidator().validate(ops, scene, files=[])
    assert len(valid) == 1, f"Expected mesh on MeshInstance3D to pass, got errors: {errors}"
    assert len(errors) == 0


def test_validator_drops_shape_on_light():
    """shape on a DirectionalLight3D is dropped."""
    from devforge.compilation.pipeline.validator import OperationValidator

    ops = [
        {
            "type": "set_property",
            "node": "/root/Main/TestSun",
            "property": "shape",
            "value": {"__class__": "BoxShape3D"},
        },
    ]
    valid, errors = OperationValidator().validate(ops, SCENE_WITH_LIGHT, files=[])
    assert len(valid) == 0
    assert len(errors) == 1
    assert "shape" in errors[0]


def test_validator_allows_shape_on_collisionshape():
    """shape on a CollisionShape3D passes validation."""
    from devforge.compilation.pipeline.validator import OperationValidator

    scene = {
        "name": "Main",
        "type": "Node3D",
        "children": [
            {"name": "ColShape", "type": "CollisionShape3D", "children": []},
        ],
    }
    ops = [
        {
            "type": "set_property",
            "node": "/root/Main/ColShape",
            "property": "shape",
            "value": {"__class__": "BoxShape3D"},
        },
    ]
    valid, errors = OperationValidator().validate(ops, scene, files=[])
    assert len(valid) == 1
    assert len(errors) == 0


def test_validator_allows_unknown_property():
    """A property not in the allowlist passes through (avoids over-blocking)."""
    from devforge.compilation.pipeline.validator import OperationValidator

    ops = [
        {"type": "set_property", "node": "/root/Main/TestSun", "property": "light_energy", "value": 0.8},
    ]
    valid, errors = OperationValidator().validate(ops, SCENE_WITH_LIGHT, files=[])
    # light_energy IS in the allowlist and DirectionalLight3D is allowed
    assert len(valid) == 1
    assert len(errors) == 0


def test_validator_allows_light_property_on_light():
    """light_energy on DirectionalLight3D passes (in allowlist)."""
    from devforge.compilation.pipeline.validator import OperationValidator

    ops = [
        {"type": "set_property", "node": "/root/Main/TestSun", "property": "light_energy", "value": 0.8},
    ]
    valid, errors = OperationValidator().validate(ops, SCENE_WITH_LIGHT, files=[])
    assert len(valid) == 1
    assert len(errors) == 0


def test_validator_pending_node_type_used():
    """Property validation works for nodes that haven't been created yet (in pending)."""
    from devforge.compilation.pipeline.validator import OperationValidator

    # Scene doesn't have TestSun — it's about to be created by add_node
    ops = [
        {"type": "add_node", "parent": "/root/Main", "name": "TestSun", "node_type": "DirectionalLight3D"},
        {
            "type": "set_property",
            "node": "/root/Main/TestSun",
            "property": "material_override",
            "value": {"__class__": "StandardMaterial3D"},
        },
    ]
    valid, errors = OperationValidator().validate(ops, SCENE_SIMPLE, files=[])

    # add_node should pass (parent /root/Main is pending from scene root)
    # material_override should be dropped (invalid on DirectionalLight3D)
    assert len(valid) == 1, f"Expected only add_node, got {len(valid)}: {valid}"
    assert valid[0]["type"] == "add_node"
    assert len(errors) == 1
    assert "material_override" in errors[0]


# ── Bug 2: Deterministic intent pre-pass ────────────────────────


def test_engine_injects_remove_for_delete_intent():
    """'Create X, then delete it' → engine injects _remove marker."""
    from devforge.compilation.pipeline import engine as eng

    m = eng._DELETE_INTENT_RE.search("Create a MeshInstance3D called ToDelete at 0,0,0, then delete it.")
    assert m is not None, "_DELETE_INTENT_RE should match 'then delete it'"


def test_engine_injects_rename_for_rename_intent():
    """'Create X, then rename OldName to NewName' → engine injects _rename marker."""
    from devforge.compilation.pipeline import engine as eng

    m = eng._RENAME_TO_RE.search("Create a MeshInstance3D called OldName at 0,0,0, then rename OldName to NewName.")
    assert m is not None, "_RENAME_TO_RE should match 'rename OldName to NewName'"
    assert m.group(1).strip() == "OldName"
    assert m.group(2).strip() == "NewName"


def test_engine_rename_re_matches_rename_it():
    """'rename it to NewName' is also matched."""
    from devforge.compilation.pipeline import engine as eng

    m = eng._RENAME_TO_RE.search("Create OldName, then rename it to NewName.")
    assert m is not None
    assert m.group(2).strip() == "NewName"


# ── Bug 1: invalid props on a light are rejected by property validation ──
# NOTE (2026-06-16): Slice 4 moved this guarantee from the COMPILER (which used
# to silently skip the prop) to the VALIDATOR (compiler now emits; validator
# drops via _property_matches_type — the "dual-validation" design). These tests
# assert the validator rule that now protects lights. `position` stays valid on
# a light (it IS a Node3D), so it must NOT be rejected.


def test_validation_rejects_mesh_on_light():
    """mesh on a DirectionalLight3D is rejected; position is kept."""
    from devforge.knowledge.scene.godot_node_types import _property_matches_type

    assert _property_matches_type("mesh", "DirectionalLight3D") is False
    # position is a Vector3 transform prop and a light IS a Node3D → allowed.
    assert _property_matches_type("position", "DirectionalLight3D") is not False


def test_validation_rejects_color_on_light():
    """color (→ material_override) on a DirectionalLight3D is rejected."""
    from devforge.knowledge.scene.godot_node_types import _property_matches_type

    assert _property_matches_type("material_override", "DirectionalLight3D") is False


def test_validation_rejects_shape_on_light():
    """shape on a DirectionalLight3D is rejected."""
    from devforge.knowledge.scene.godot_node_types import _property_matches_type

    assert _property_matches_type("shape", "DirectionalLight3D") is False


# ── Slice D (2026-06-16): position is a denylist, validated in one place ──


def test_position_rejected_on_transformless_nodes():
    """Vector3 transform props are dropped on nodes with no transform."""
    from devforge.knowledge.scene.godot_node_types import _property_matches_type

    for nt in ("Timer", "Label", "Control", "AudioStreamPlayer", "AnimationPlayer"):
        assert _property_matches_type("position", nt) is False, nt
    assert _property_matches_type("scale", "Timer") is False
    assert _property_matches_type("rotation_degrees", "Label") is False


def test_position_allowed_on_spatial_nodes():
    """Transform props pass through on Node3D and spatial subclasses."""
    from devforge.knowledge.scene.godot_node_types import _property_matches_type

    for nt in ("Node3D", "MeshInstance3D", "Camera3D", "Area3D", "CharacterBody3D"):
        assert _property_matches_type("position", nt) is not False, nt


def test_compiler_shares_canonical_transformless_set():
    """The compiler's _NON_3D_TYPES is the single source of truth in the
    knowledge layer (no divergent local copy)."""
    from devforge.compilation.pipeline import architecture_compiler as ac
    from devforge.knowledge.scene.godot_node_types import NODES_WITHOUT_VECTOR3_TRANSFORM

    assert ac._NON_3D_TYPES is NODES_WITHOUT_VECTOR3_TRANSFORM


def test_reverse_host_node_stub_generation():
    """Slice B: a known signal yields a correctly-typed handler stub; an
    unknown signal yields None (safe drop)."""
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler

    c = ArchitectureCompiler()
    s = c._generate_signal_stub("Node3D", "_on_SpawnTimer_timeout", "timeout")
    assert s and "func _on_SpawnTimer_timeout() -> void:" in s and "extends Node3D" in s
    s2 = c._generate_signal_stub("Area3D", "_on_body_entered", "body_entered")
    assert "func _on_body_entered(body: Node3D) -> void:" in s2
    assert c._generate_signal_stub("Node3D", "_on_x", "not_a_signal") is None


# ── Bug 2: DeterministicPlanner mid-prompt patterns ─────────────


def test_planner_mid_rename_does_not_return_delta():
    """Mid-prompt rename must fall through to LLM, not return deterministic delta."""
    from devforge.compilation.pipeline.architecture_planner import DeterministicPlanner

    # "Create OldName, then rename OldName to NewName" — the deterministic
    # planner should NOT return a delta. The engine handles this post-LLM.
    result = DeterministicPlanner().match(
        "Create a MeshInstance3D called OldName at 0,0,0, then rename OldName to NewName."
    )
    # Should fall through (return None) — the LLM creates OldName,
    # and engine._run_arch_path injects _rename afterward.
    assert result is None, (
        "Mid-prompt rename should NOT return a deterministic delta — the LLM must still create the entity"
    )


def test_planner_still_handles_full_prompt_rename():
    """Full-prompt 'rename X to Y' still works (start-anchored)."""
    from devforge.compilation.pipeline.architecture_planner import DeterministicPlanner

    result = DeterministicPlanner().match("rename Player to Hero")
    assert result is not None
    assert result["_rename"] == {"from": "Player", "to": "Hero"}


def test_planner_still_handles_full_prompt_delete():
    """Full-prompt 'delete node X' still works (start-anchored)."""
    from devforge.compilation.pipeline.architecture_planner import DeterministicPlanner

    result = DeterministicPlanner().match("delete node Enemy")
    assert result is not None
    assert result["_remove"] == "Enemy"


# ── Property allowlist correctness ──────────────────────────────


def test_property_matches_type_known_good():
    """mesh on MeshInstance3D → True."""
    from devforge.knowledge.scene.godot_node_types import _property_matches_type

    assert _property_matches_type("mesh", "MeshInstance3D") is True


def test_property_matches_type_known_bad():
    """mesh on DirectionalLight3D → False."""
    from devforge.knowledge.scene.godot_node_types import _property_matches_type

    assert _property_matches_type("mesh", "DirectionalLight3D") is False


def test_property_matches_type_unknown():
    """An unknown property → None (allow)."""
    from devforge.knowledge.scene.godot_node_types import _property_matches_type

    assert _property_matches_type("position", "Node3D") is None


def test_property_matches_type_light_energy():
    """light_energy on DirectionalLight3D → True."""
    from devforge.knowledge.scene.godot_node_types import _property_matches_type

    assert _property_matches_type("light_energy", "DirectionalLight3D") is True
    assert _property_matches_type("light_energy", "MeshInstance3D") is False


def test_compiler_drops_connection_to_phantom_node():
    """A connection whose endpoint was never created (LLM hallucination, e.g.
    'ScoreLabel' from a collectible-game pattern) must be DROPPED — not emitted
    as a connect_signal to a fabricated '/root/Main/ScoreLabel' path, which
    atomic-rolls-back the WHOLE build (G4_children: 0 nodes from 3 phantom
    signals)."""
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler

    delta = {
        "systems": [],
        "entities": [{"name": "Pickup", "type": "Area3D", "props": {"position": [0, 0, 0]}}],
        "connections": [{"from": "Pickup", "to": "ScoreLabel", "type": "signal", "signal": "body_entered"}],
    }
    ops = ArchitectureCompiler().compile(delta).compile_all()["operations"]
    op_types = [o["type"] for o in ops]
    assert "add_node" in op_types, "the real Pickup node must still build"
    assert "connect_signal" not in op_types, f"phantom connection to ScoreLabel must be dropped, got: {op_types}"


def test_compiler_keeps_connection_between_real_entities():
    """The drop only targets UNRESOLVABLE endpoints — a connection between two
    entities created in the same delta must still emit a connect_signal."""
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler

    delta = {
        "systems": [],
        "entities": [{"name": "SpawnTimer", "type": "Timer"}, {"name": "Spawner", "type": "Node3D"}],
        "connections": [{"from": "SpawnTimer", "to": "Spawner", "type": "signal", "signal": "timeout"}],
    }
    ops = ArchitectureCompiler().compile(delta).compile_all()["operations"]
    assert "connect_signal" in [o["type"] for o in ops], (
        "a connection between two real same-delta entities must be kept"
    )
