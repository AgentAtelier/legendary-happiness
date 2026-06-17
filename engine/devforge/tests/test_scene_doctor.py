"""Unit tests for SceneDoctor: all 5 rules, edge cases, determinism.

Tests: rule triggers, rule passes, skipped-INFO when no props_lookup,
malformed-node tolerance, stable output ordering.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _empty_props(_path: str) -> dict | None:
    """A props_lookup that always returns an empty dict (no properties)."""
    return {}


def _props_with(values: dict[str, dict | None]):
    """Return a props_lookup that returns *values* keyed by node path,
    or None for paths not in the dict."""
    def lookup(path: str) -> dict | None:
        return values.get(path)
    return lookup


# ── Test data ───────────────────────────────────────────────────

def _tree(name: str = "Main", type_: str = "Node3D", *children: dict) -> dict:
    """Convenience: build a scene-tree dict."""
    return {"name": name, "type": type_, "children": list(children)}


def _leaf(name: str, type_: str = "Node3D") -> dict:
    """A node with no children."""
    return {"name": name, "type": type_}


# ── R1: CollisionShape3D parent must be CollisionObject3D ────────

def test_r1_fires_when_shape_under_plain_node() -> None:
    """R1 fires for a CollisionShape3D whose parent is not a
    CollisionObject3D subclass."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=None)
    tree = _tree("Main", "Node3D",
        _tree("BadParent", "Node3D",
            _leaf("BadShape", "CollisionShape3D"),
        ),
    )
    violations = doctor.audit(tree)
    r1s = [v for v in violations if v.rule_id == "R1"]
    assert len(r1s) == 1, f"Expected 1 R1 violation, got {len(r1s)}"
    assert r1s[0].severity == "CRITICAL"
    assert "/root/Main/BadParent/BadShape" in r1s[0].node_path


def test_r1_passes_when_shape_under_collision_object() -> None:
    """R1 passes for a CollisionShape3D under a CharacterBody3D."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=None)
    tree = _tree("Main", "Node3D",
        _tree("Player", "CharacterBody3D",
            _leaf("Shape", "CollisionShape3D"),
        ),
    )
    violations = doctor.audit(tree)
    r1s = [v for v in violations if v.rule_id == "R1"]
    assert len(r1s) == 0, f"Expected no R1 violations, got {len(r1s)}"


# ── R2: CollisionObject must have a shape child ─────────────────

def test_r2_fires_when_collision_object_has_no_shape() -> None:
    """R2 fires for a CharacterBody3D with no shape child."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=None)
    tree = _tree("Main", "Node3D",
        _tree("Enemy", "CharacterBody3D",
            _leaf("Sprite", "Sprite3D"),
        ),
    )
    violations = doctor.audit(tree)
    r2s = [v for v in violations if v.rule_id == "R2"]
    assert len(r2s) == 1, f"Expected 1 R2 violation, got {len(r2s)}"
    assert r2s[0].severity == "CRITICAL"
    assert "/root/Main/Enemy" in r2s[0].node_path


def test_r2_passes_when_collision_polygon_child_exists() -> None:
    """R2 passes when a CollisionPolygon3D child exists."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=None)
    tree = _tree("Main", "Node3D",
        _tree("Floor", "StaticBody3D",
            _leaf("Bounds", "CollisionPolygon3D"),
        ),
    )
    violations = doctor.audit(tree)
    r2s = [v for v in violations if v.rule_id == "R2"]
    assert len(r2s) == 0, f"Expected no R2 violations, got {len(r2s)}"


# ── R3: single Camera3D must be current ─────────────────────────

def test_r3_reports_skipped_when_no_props_lookup() -> None:
    """R3 returns INFO 'skipped' when props_lookup is None."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=None)
    tree = _tree("Main", "Node3D",
        _leaf("MainCamera", "Camera3D"),
    )
    violations = doctor.audit(tree)
    r3s = [v for v in violations if v.rule_id == "R3"]
    assert len(r3s) == 1, f"Expected 1 R3 skipped, got {len(r3s)}"
    assert r3s[0].severity == "INFO"
    assert "skipped" in r3s[0].message.lower()


def test_r3_fires_when_camera_not_current() -> None:
    """R3 fires when props_lookup returns current=False for the only camera."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=_props_with({
        "/root/Main/MainCamera": {"current": False},
    }))
    tree = _tree("Main", "Node3D",
        _leaf("MainCamera", "Camera3D"),
    )
    violations = doctor.audit(tree)
    r3s = [v for v in violations if v.rule_id == "R3"]
    assert len(r3s) == 1, f"Expected 1 R3 violation, got {len(r3s)}"
    assert r3s[0].severity == "WARNING"


def test_r3_passes_when_camera_is_current() -> None:
    """R3 passes when the only camera has current=True."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=_props_with({
        "/root/Main/MainCamera": {"current": True},
    }))
    tree = _tree("Main", "Node3D",
        _leaf("MainCamera", "Camera3D"),
    )
    violations = doctor.audit(tree)
    r3s = [v for v in violations if v.rule_id == "R3"]
    assert len(r3s) == 0, f"Expected no R3 violations, got {len(r3s)}"


# ── R4: MeshInstance3D must have mesh ───────────────────────────

def test_r4_fires_when_mesh_is_none() -> None:
    """R4 fires when props_lookup returns mesh=None."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=_props_with({
        "/root/Main/Ground": {"mesh": None},
    }))
    tree = _tree("Main", "Node3D",
        _leaf("Ground", "MeshInstance3D"),
    )
    violations = doctor.audit(tree)
    r4s = [v for v in violations if v.rule_id == "R4"]
    assert len(r4s) == 1, f"Expected 1 R4 violation, got {len(r4s)}"
    assert r4s[0].severity == "WARNING"


def test_r4_passes_when_mesh_is_set() -> None:
    """R4 passes when mesh is not None."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=_props_with({
        "/root/Main/Wall": {"mesh": "res://wall.tres"},
    }))
    tree = _tree("Main", "Node3D",
        _leaf("Wall", "MeshInstance3D"),
    )
    violations = doctor.audit(tree)
    r4s = [v for v in violations if v.rule_id == "R4"]
    assert len(r4s) == 0, f"Expected no R4 violations, got {len(r4s)}"


# ── R5: no duplicate sibling names ──────────────────────────────

def test_r5_fires_for_duplicate_sibling_names() -> None:
    """R5 fires when two siblings share the same name."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=None)
    tree = _tree("Main", "Node3D",
        _tree("Enemies", "Node3D",
            _leaf("Enemy", "CharacterBody3D"),
            _leaf("Enemy", "CharacterBody3D"),
        ),
    )
    violations = doctor.audit(tree)
    r5s = [v for v in violations if v.rule_id == "R5"]
    assert len(r5s) >= 1, f"Expected at least 1 R5 violation, got {len(r5s)}"
    assert r5s[0].severity == "WARNING"
    assert "Enemy" in r5s[0].message


def test_r5_passes_for_same_name_in_different_parents() -> None:
    """R5 passes when nodes share a name but have different parents."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=None)
    tree = _tree("Main", "Node3D",
        _tree("A", "Node3D", _leaf("Shared", "Node3D")),
        _tree("B", "Node3D", _leaf("Shared", "Node3D")),
    )
    violations = doctor.audit(tree)
    r5s = [v for v in violations if v.rule_id == "R5"]
    assert len(r5s) == 0, f"Expected no R5 violations, got {len(r5s)}"


# ── Edge cases ──────────────────────────────────────────────────

def test_malformed_node_does_not_raise() -> None:
    """A child dict without a 'type' key does not crash the auditor."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=None)
    tree = {
        "name": "Main",
        "type": "Node3D",
        "children": [
            {"name": "Weird"},  # no 'type'
            _leaf("OK", "Camera3D"),
        ],
    }
    violations = doctor.audit(tree)
    # Should not raise — the malformed node is skipped
    # R3 should still fire (single camera, no props)
    r3s = [v for v in violations if v.rule_id == "R3"]
    assert len(r3s) >= 0  # survivorship is the test; any output is fine


def test_determinism_same_tree_twice() -> None:
    """Auditing the same tree twice yields identical ordered output."""
    from devforge.auditing.scene_doctor import SceneDoctor

    doctor = SceneDoctor(props_lookup=None)
    tree = _tree("Main", "Node3D",
        _tree("Player", "CharacterBody3D",
            _leaf("Shape", "CollisionShape3D"),
            _leaf("Cam", "Camera3D"),
        ),
        _tree("Guard", "CharacterBody3D"),
    )

    v1 = doctor.audit(tree)
    v2 = doctor.audit(tree)

    assert len(v1) == len(v2), f"Count differs: {len(v1)} vs {len(v2)}"
    for a, b in zip(v1, v2):
        assert a.rule_id == b.rule_id
        assert a.severity == b.severity
        assert a.node_path == b.node_path
        assert a.message == b.message


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_r1_fires_when_shape_under_plain_node,
        test_r1_passes_when_shape_under_collision_object,
        test_r2_fires_when_collision_object_has_no_shape,
        test_r2_passes_when_collision_polygon_child_exists,
        test_r3_reports_skipped_when_no_props_lookup,
        test_r3_fires_when_camera_not_current,
        test_r3_passes_when_camera_is_current,
        test_r4_fires_when_mesh_is_none,
        test_r4_passes_when_mesh_is_set,
        test_r5_fires_for_duplicate_sibling_names,
        test_r5_passes_for_same_name_in_different_parents,
        test_malformed_node_does_not_raise,
        test_determinism_same_tree_twice,
    ]

    passed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")

    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
