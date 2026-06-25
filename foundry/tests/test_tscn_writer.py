"""Tests for foundry.tscn_writer — shared .tscn string-builders.

Phase 1.1: every primitive must produce its exact canonical string.
"""

from __future__ import annotations

from tscn_writer import (
    ext_resource,
    fmt_float,
    node_header,
    sub_resource_header,
    transform3d,
)

# ── fmt_float ───────────────────────────────────────────────────

def test_fmt_float_integer_returns_int_str():
    assert fmt_float(0.0) == "0"
    assert fmt_float(1.0) == "1"
    assert fmt_float(-2.0) == "-2"
    assert fmt_float(42.0) == "42"


def test_fmt_float_fraction_keeps_decimals():
    assert fmt_float(0.5) == "0.5"
    assert fmt_float(0.866025) == "0.866025"
    assert fmt_float(-0.433013) == "-0.433013"
    assert fmt_float(3.14159) == "3.14159"


# ── ext_resource ────────────────────────────────────────────────

def test_ext_resource_packed_scene():
    result = ext_resource("PackedScene", "res://assets/table_worn_oak.glb", "1")
    assert result == '[ext_resource type="PackedScene" path="res://assets/table_worn_oak.glb" id="1"]'


def test_ext_resource_script():
    result = ext_resource("Script", "res://scripts/pickup.gd", "s_pickup")
    assert 'type="Script"' in result
    assert 'path="res://scripts/pickup.gd"' in result
    assert 'id="s_pickup"' in result


def test_ext_resource_no_uid():
    """Deterministic output: never emits uid=."""
    result = ext_resource("PackedScene", "res://x.glb", "5")
    assert "uid=" not in result


# ── sub_resource_header ─────────────────────────────────────────

def test_sub_resource_header():
    assert sub_resource_header("BoxShape3D", "sub_1") == '[sub_resource type="BoxShape3D" id="sub_1"]'
    assert sub_resource_header("Environment", "world_env") == '[sub_resource type="Environment" id="world_env"]'


# ── node_header ─────────────────────────────────────────────────

def test_node_header_basic():
    assert node_header("Root", "Node3D") == '[node name="Root" type="Node3D"]'


def test_node_header_with_parent():
    assert node_header("Camera3D", "Camera3D", "Player") == '[node name="Camera3D" type="Camera3D" parent="Player"]'


def test_node_header_instance_no_type():
    """When instance= is given, type= is omitted (Godot 4 convention for
    PackedScene instances on the header line)."""
    result = node_header("table_0_model", parent="table_0", instance="1")
    assert result == '[node name="table_0_model" parent="table_0" instance=ExtResource("1")]'
    assert "type=" not in result, "instance= header should not include type="


def test_node_header_instance_with_type():
    """When both type= and instance= are passed, both appear."""
    result = node_header("Foo", type="Node3D", instance="2")
    assert 'type="Node3D"' in result
    assert 'instance=ExtResource("2")' in result


# ── transform3d ─────────────────────────────────────────────────

def test_transform3d_identity():
    result = transform3d((1, 0, 0, 0, 1, 0, 0, 0, 1), (5, 3, -2))
    assert result == "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 5, 3, -2)"


def test_transform3d_fractional_basis():
    basis = (0.866025, -0.433013, 0.25, 0.0, 0.5, 0.866025, -0.5, -0.75, 0.433013)
    result = transform3d(basis, (0, 8, 0))
    expected = (
        "Transform3D(0.866025, -0.433013, 0.25, 0, 0.5, 0.866025, "
        "-0.5, -0.75, 0.433013, 0, 8, 0)"
    )
    assert result == expected


def test_transform3d_fmt_float_origin():
    """Origin values use fmt_float: 0.0 → 0, -0.5 → -0.5."""
    result = transform3d((1, 0, 0, 0, 1, 0, 0, 0, 1), (0.0, -0.5, 0.0))
    assert result == "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -0.5, 0)"


