"""Unit 4 — the W2 read-only world query layer."""
from world.operations import apply_op, replay
from world.query import (
    direction,
    find_entities,
    neighbors,
    space_summary,
    world_index,
)


def _add_space(sid, origin, size=(4, 3, 4), theme=None):
    return {"op": "add_space", "id": sid, "brief": ({"theme": theme} if theme else {}),
            "footprint": {"origin": list(origin), "size": list(size)}}


def _world():
    # A at origin; B to the east; C to the north (Godot -Z); portal A<->B.
    w = replay([])
    w = apply_op(w, _add_space("a", (0, 0, 0), theme="hall"))
    w = apply_op(w, _add_space("b", (4, 0, 0), theme="armory"))   # east of a
    w = apply_op(w, _add_space("c", (0, 0, -4)))                  # north of a
    w = apply_op(w, _add_space("up", (0, 3, 0)))                  # above a
    w = apply_op(w, {"op": "add_portal", "id": "p_ab", "from_space": "a",
                     "to_space": "b", "position": [4, 1.5, 2], "size": [1.5, 2]})
    w = apply_op(w, {"op": "add_entity", "space": "a",
                     "entity": {"id": "throne", "type": "throne", "pos": [2, 0, 2]}})
    w = apply_op(w, {"op": "add_entity", "space": "b",
                     "entity": {"id": "anvil", "type": "anvil", "pos": [6, 0, 2]}})
    return w


# ── neighbors ──────────────────────────────────────────────────────────

def test_neighbors_follows_portals_both_directions():
    w = _world()
    assert neighbors(w, "a") == [("p_ab", "b")]
    assert neighbors(w, "b") == [("p_ab", "a")]   # bidirectional
    assert neighbors(w, "c") == []                 # unconnected


# ── direction (the convention) ─────────────────────────────────────────

def test_direction_cardinals_and_vertical():
    w = _world()
    assert direction(w, "a", "b") == "east"    # +x
    assert direction(w, "b", "a") == "west"    # -x
    assert direction(w, "a", "c") == "north"   # -z
    assert direction(w, "c", "a") == "south"   # +z
    assert direction(w, "a", "up") == "up"     # +y


def test_direction_here_and_unknown():
    w = _world()
    assert direction(w, "a", "a") == "here"
    assert direction(w, "a", "ghost") == "unknown"


# ── find_entities (reference resolution) ───────────────────────────────

def test_find_entities_by_type_and_space():
    w = _world()
    by_type = find_entities(w, type="throne")
    assert by_type == [("a", w.nodes["a"].entities[0])]
    by_space = find_entities(w, space="b")
    assert len(by_space) == 1 and by_space[0][1].id == "anvil"
    assert find_entities(w, type="anvil", space="a") == []  # anvil is in b, not a
    assert len(find_entities(w)) == 2                        # all


# ── world_index (the LLM-consumable map) ───────────────────────────────

def test_space_summary_shape():
    w = _world()
    s = space_summary(w, "a")
    assert s["id"] == "a" and s["theme"] == "hall"
    assert s["centre"] == [2.0, 1.5, 2.0]
    assert {"id": "throne", "type": "throne"} in s["entities"]
    assert s["neighbors"] == [{"portal": "p_ab", "to": "b", "direction": "east"}]


def test_world_index_lists_all_spaces_and_portal_count():
    w = _world()
    idx = world_index(w)
    assert idx["portal_count"] == 1
    assert [s["id"] for s in idx["spaces"]] == ["a", "b", "c", "up"]  # sorted
    a = next(s for s in idx["spaces"] if s["id"] == "a")
    assert a["neighbors"][0]["direction"] == "east"


def test_queries_do_not_mutate():
    w = _world()
    before = len(w.op_log)
    world_index(w); neighbors(w, "a"); direction(w, "a", "b"); find_entities(w)
    assert len(w.op_log) == before  # read-only
