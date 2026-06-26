import pytest

pytest.importorskip("shapely")
pytest.importorskip("mapbox_earcut")

from navmesh import carve_walkable, point_in_polygons


def test_empty_obstacles_walkable_center():
    verts, polys = carve_walkable(8.0, 6.0, [])
    assert verts and polys
    # center of the room is walkable
    assert point_in_polygons(0.0, 0.0, verts, polys)
    # a point outside the inset (near the wall) is NOT walkable
    assert not point_in_polygons(0.0, 2.9, verts, polys)  # d/2=3, margin 1.2 -> edge ~1.8


def test_obstacle_carves_hole():
    # one 1x1 obstacle at the center, inflated by agent_radius -> center blocked
    obs = [(0.0, 0.0, 0.5, 0.5)]
    verts, polys = carve_walkable(8.0, 6.0, obs)
    assert not point_in_polygons(0.0, 0.0, verts, polys)   # inside the prop -> blocked
    assert point_in_polygons(2.5, 0.0, verts, polys)        # clear floor -> walkable


def test_determinism():
    obs = [(1.0, 0.5, 0.4, 0.4), (-1.5, -1.0, 0.3, 0.6)]
    a = carve_walkable(8.0, 6.0, obs)
    b = carve_walkable(8.0, 6.0, list(reversed(obs)))
    assert a == b  # sorted internally -> order-independent, identical output


def test_over_furnished_returns_empty():
    # one obstacle larger than the whole inset region -> nothing walkable
    obs = [(0.0, 0.0, 50.0, 50.0)]
    verts, polys = carve_walkable(8.0, 6.0, obs)
    assert verts == [] and polys == []
