"""Unit 3 e2e — portal→wall-opening geometry + parent-scene kernel."""
import pytest
from world.compose import build_world_tscn, space_openings
from world.operations import apply_op, replay


def _space(sid, origin, size=(8, 4, 8)):
    return {"op": "add_space", "id": sid, "brief": {},
            "footprint": {"origin": list(origin), "size": list(size)}}


def _portal(pid, frm, to, pos, size=(2, 3)):
    return {"op": "add_portal", "id": pid, "from_space": frm, "to_space": to,
            "position": list(pos), "size": list(size)}


def _world():
    # hall at origin; neighbours touching each principal face.
    w = replay([])
    w = apply_op(w, _space("hall", (0, 0, 0)))
    w = apply_op(w, _space("court", (0, 0, -8)))   # north (shares hall's min-z face)
    w = apply_op(w, _space("east", (8, 0, 0)))     # east  (shares hall's max-x face)
    w = apply_op(w, _space("cellar", (0, -4, 0)))  # below (shares hall's min-y face)
    w = apply_op(w, _portal("p_n", "hall", "court", (4, 2, 0)))
    w = apply_op(w, _portal("p_e", "hall", "east", (8, 2, 4)))
    w = apply_op(w, _portal("p_d", "hall", "cellar", (4, 0, 4), size=(2, 2)))
    return w


def test_openings_map_each_portal_to_the_correct_face():
    ops = space_openings(_world(), "hall")
    faces = {o["portal"]: o["face"] for o in ops}
    assert faces == {"p_n": "north", "p_e": "east", "p_d": "down"}


def test_opening_carries_portal_center_and_size():
    ops = {o["portal"]: o for o in space_openings(_world(), "hall")}
    assert ops["p_n"]["center"] == [4, 2, 0] and ops["p_n"]["size"] == [2, 3]
    assert ops["p_d"]["size"] == [2, 2]
    assert ops["p_n"]["to"] == "court"


def test_face_is_relative_to_each_space():
    # From the courtyard's side, the same portal opens its SOUTH face (it shares
    # the courtyard's max-z face with the hall to its south).
    ops = {o["portal"]: o for o in space_openings(_world(), "court")}
    assert ops["p_n"]["face"] == "south"
    assert ops["p_n"]["to"] == "hall"


def test_deterministic_order_by_portal_id():
    ports = [o["portal"] for o in space_openings(_world(), "hall")]
    assert ports == sorted(ports)


def test_space_with_no_portals_has_no_openings():
    w = replay([])
    w = apply_op(w, _space("lone", (0, 0, 0)))
    assert space_openings(w, "lone") == []


def test_missing_space_is_empty():
    assert space_openings(replay([]), "ghost") == []


# ── build_world_tscn (parent-scene kernel) ─────────────────────────────

def _two_space_world():
    w = replay([])
    w = apply_op(w, _space("hall", (0, 0, 0)))    # centre (4,2,4)
    w = apply_op(w, _space("court", (0, 0, -8)))   # centre (4,2,-4)
    return w


_PATHS = {"hall": "res://scenes/hall.tscn", "court": "res://scenes/court.tscn"}


def test_world_tscn_header_and_ext_resources():
    t = build_world_tscn(_two_space_world(), _PATHS)
    assert t.startswith("[gd_scene load_steps=3 format=3]")   # 2 spaces + 1
    # ids follow sorted space order: court (1), hall (2)
    assert '[ext_resource type="PackedScene" path="res://scenes/court.tscn" id="1_court"]' in t
    assert '[ext_resource type="PackedScene" path="res://scenes/hall.tscn" id="2_hall"]' in t


def test_world_tscn_instances_each_space_at_its_footprint_centre():
    t = build_world_tscn(_two_space_world(), _PATHS)
    # instance= INSIDE the brackets (the node_header fix), placed at the centre
    assert '[node name="hall" parent="." instance=ExtResource("2_hall")]' in t
    assert "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 4, 2, 4)" in t       # hall centre
    assert "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 4, 2, -4)" in t      # court centre


def test_world_tscn_has_root_and_spawn():
    t = build_world_tscn(_two_space_world(), _PATHS, spawn_space="court")
    assert '[node name="World" type="Node3D"]' in t
    assert '[node name="PlayerSpawn" type="Marker3D" parent="."]' in t
    # spawn at the court centre (4,2,-4)
    spawn_block = t.split('PlayerSpawn')[1]
    assert "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 4, 2, -4)" in spawn_block


def test_world_tscn_deterministic():
    w = _two_space_world()
    assert build_world_tscn(w, _PATHS) == build_world_tscn(w, _PATHS)


def test_world_tscn_default_spawn_is_first_sorted_space():
    t = build_world_tscn(_two_space_world(), _PATHS)  # no spawn_space → "court" (sorts before "hall")
    spawn_block = t.split('PlayerSpawn')[1]
    assert "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 4, 2, -4)" in spawn_block  # court centre


def test_world_tscn_requires_scene_paths():
    with pytest.raises(ValueError):
        build_world_tscn(_two_space_world(), {})
