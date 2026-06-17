from devforge.governance.quality_gate import assess_quality


def test_healthy_scene_has_no_warnings():
    ops = [{"type": "add_node"}, {"type": "set_property"}, {"type": "add_node"}]
    delta = {"entities": [{"type": "MeshInstance3D"}, {"type": "Camera3D"}], "systems": []}
    assert assess_quality(ops, delta, "a small village") == []


def test_variety_collapse():
    ops = [{"type": "add_node"}, {"type": "set_property"}]
    delta = {"entities": [{"type": "Tree"}, {"type": "Tree"}, {"type": "Tree"}], "systems": []}
    assert any("variety_collapse" in w for w in assess_quality(ops, delta, "a forest"))


def test_operation_monoculture():
    ops = [{"type": "add_node"}, {"type": "add_node"}, {"type": "add_node"}]
    delta = {"entities": [{"type": "A"}, {"type": "B"}], "systems": []}
    assert any("operation_monoculture" in w for w in assess_quality(ops, delta, "x y z a b c d"))


def test_thin_generation():
    w = assess_quality(
        [{"type": "add_node"}], {"entities": [], "systems": []}, "build a sprawling medieval castle with many towers"
    )
    assert any("thin_generation" in x for x in w)


def test_missing_systems():
    ops = [{"type": "add_node"}, {"type": "set_property"}]
    delta = {"entities": [{"type": "CharacterBody3D"}], "systems": []}
    w = assess_quality(ops, delta, "an npc that can patrol and attack the player")
    assert any("missing_systems" in x for x in w)


def test_no_false_positive_on_simple_request():
    ops = [{"type": "add_node"}, {"type": "set_property"}]
    delta = {"entities": [{"type": "MeshInstance3D"}], "systems": []}
    assert assess_quality(ops, delta, "add a red cube") == []
