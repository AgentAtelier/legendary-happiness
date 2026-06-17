"""Unit tests for Polish Pass: game-feel audit rules and auto-fix operations."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _make_scene(**overrides) -> dict:
    scene = {
        "name": "Main",
        "type": "Node3D",
        "children": [],
    }
    scene.update(overrides)
    return scene


def _make_node(name: str, ntype: str, **props) -> dict:
    node: dict = {"name": name, "type": ntype, "children": []}
    node.update(props)
    return node


# ── P1: Camera3D without smoothing ──────────────────────────────


def test_p1_camera_without_smoothing() -> None:
    """Camera3D with smoothing disabled is flagged as P1."""
    from devforge.polish.polish_pass import PolishPass

    scene = _make_scene(
        children=[
            _make_node("Camera3D", "Camera3D"),
        ]
    )
    # Mock props_lookup: smoothing disabled
    pp = PolishPass(props_lookup=lambda p: {"position_smoothing/enabled": False})
    findings = pp.audit(scene)
    assert any(f.rule_id == "P1" for f in findings)


def test_p1_camera_smoothing_enabled_no_flag() -> None:
    """Camera3D with smoothing enabled is NOT flagged."""
    from devforge.polish.polish_pass import PolishPass

    scene = _make_scene(
        children=[
            _make_node("Camera3D", "Camera3D"),
        ]
    )
    pp = PolishPass(props_lookup=lambda p: {"position_smoothing/enabled": True})
    findings = pp.audit(scene)
    assert not any(f.rule_id == "P1" for f in findings)


# ── P2: Camera3D without screen shake ──────────────────────────


def test_p2_camera_shake() -> None:
    """Camera3D without screen shake is flagged as P2."""
    from devforge.polish.polish_pass import PolishPass

    scene = _make_scene(
        children=[
            _make_node("Camera3D", "Camera3D"),
        ]
    )
    pp = PolishPass()
    findings = pp.audit(scene)
    assert any(f.rule_id == "P2" for f in findings)


# ── P3: Light with zero energy ──────────────────────────────────


def test_p3_light_zero_energy() -> None:
    """Light with zero energy is flagged as P3."""
    from devforge.polish.polish_pass import PolishPass

    scene = _make_scene(
        children=[
            _make_node("Sun", "DirectionalLight3D", light_energy=0),
        ]
    )
    pp = PolishPass()
    findings = pp.audit(scene)
    assert any(f.rule_id == "P3" for f in findings)


def test_p3_light_nonzero_energy_no_flag() -> None:
    """Light with nonzero energy is NOT flagged."""
    from devforge.polish.polish_pass import PolishPass

    scene = _make_scene(
        children=[
            _make_node("Sun", "DirectionalLight3D", light_energy=1.0),
        ]
    )
    pp = PolishPass()
    findings = pp.audit(scene)
    assert not any(f.rule_id == "P3" for f in findings)


# ── P4: MeshInstance3D without mesh ─────────────────────────────


def test_p4_mesh_missing() -> None:
    """MeshInstance3D without a mesh is flagged as P4 (ERROR)."""
    from devforge.polish.polish_pass import PolishPass

    scene = _make_scene(
        children=[
            _make_node("Rock", "MeshInstance3D", mesh=None),
        ]
    )
    pp = PolishPass()
    findings = pp.audit(scene)
    assert any(f.rule_id == "P4" for f in findings)
    p4 = next(f for f in findings if f.rule_id == "P4")
    assert p4.severity == "ERROR"


# ── P5: UI with small font size ────────────────────────────────


def test_p5_label_small_font() -> None:
    """Label with font size < 14 is flagged as P5."""
    from devforge.polish.polish_pass import PolishPass

    scene = _make_scene(
        children=[
            _make_node("Prompt", "Label"),
        ]
    )
    pp = PolishPass(props_lookup=lambda p: {"theme_override_font_sizes/font_size": 10})
    findings = pp.audit(scene)
    assert any(f.rule_id == "P5" for f in findings)


def test_p5_label_large_font_no_flag() -> None:
    """Label with font size >= 14 is NOT flagged."""
    from devforge.polish.polish_pass import PolishPass

    scene = _make_scene(
        children=[
            _make_node("Prompt", "Label"),
        ]
    )
    pp = PolishPass(props_lookup=lambda p: {"theme_override_font_sizes/font_size": 18})
    findings = pp.audit(scene)
    assert not any(f.rule_id == "P5" for f in findings)


# ── Fix operations ──────────────────────────────────────────────


def test_fix_camera_smoothing() -> None:
    """P1 fix sets position_smoothing/enabled."""
    from devforge.polish.polish_pass import PolishPass, PolishFinding

    pp = PolishPass()
    finding = PolishFinding(
        rule_id="P1",
        severity="WARNING",
        node_path="/root/Main/Camera3D",
        message="No smoothing",
    )
    op = pp.apply_fix(finding)
    assert op is not None
    assert op["type"] == "set_property"
    assert op["property"] == "position_smoothing/enabled"
    assert op["value"] is True


def test_fix_light_energy() -> None:
    """P3 fix sets light_energy to 1.0."""
    from devforge.polish.polish_pass import PolishPass, PolishFinding

    pp = PolishPass()
    finding = PolishFinding(
        rule_id="P3",
        severity="WARNING",
        node_path="/root/Main/Sun",
        message="Zero energy",
    )
    op = pp.apply_fix(finding)
    assert op is not None
    assert op["property"] == "light_energy"
    assert op["value"] == 1.0


def test_no_fix_for_info() -> None:
    """INFO findings have no fix."""
    from devforge.polish.polish_pass import PolishPass, PolishFinding

    pp = PolishPass()
    finding = PolishFinding(
        rule_id="P4",
        severity="ERROR",
        node_path="/root/Main/Rock",
        message="No mesh",
    )
    op = pp.apply_fix(finding)
    assert op is None  # P4 (missing mesh) can't be auto-fixed


# ── run_polish_pass with fixes ──────────────────────────────────


def test_run_polish_pass_no_fixes() -> None:
    """run_polish_pass without apply_fixes returns findings only."""
    from devforge.polish.polish_pass import run_polish_pass

    scene = _make_scene(
        children=[
            _make_node("Camera3D", "Camera3D"),
            _make_node("Sun", "DirectionalLight3D", light_energy=0),
        ]
    )
    props = {"light_energy": 0}
    result = run_polish_pass(scene, apply_fixes=False, props_lookup=lambda p: props)
    assert result["finding_count"] >= 2  # P2, P3 (P1 not flagged — smoothing defaults to enabled)
    assert result["fixes_applied"] == 0
    assert result["fix_operations"] == []


def test_run_polish_pass_with_fixes() -> None:
    """run_polish_pass with apply_fixes returns fix operations."""
    from devforge.polish.polish_pass import run_polish_pass

    scene = _make_scene(
        children=[
            _make_node("Camera3D", "Camera3D"),
        ]
    )
    props = {"position_smoothing/enabled": False}
    result = run_polish_pass(scene, apply_fixes=True, props_lookup=lambda p: props)
    assert result["finding_count"] >= 2  # P1 + P2
    assert result["fixes_applied"] >= 1
    # Fix operations should be set_property ops
    for op in result["fix_operations"]:
        assert op["type"] == "set_property"


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_p1_camera_without_smoothing,
        test_p1_camera_smoothing_enabled_no_flag,
        test_p2_camera_shake,
        test_p3_light_zero_energy,
        test_p3_light_nonzero_energy_no_flag,
        test_p4_mesh_missing,
        test_p5_label_small_font,
        test_p5_label_large_font_no_flag,
        test_fix_camera_smoothing,
        test_fix_light_energy,
        test_no_fix_for_info,
        test_run_polish_pass_no_fixes,
        test_run_polish_pass_with_fixes,
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
