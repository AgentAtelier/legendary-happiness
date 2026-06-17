"""Completeness checker — auto-injected nodes must use the SAME path
convention as SceneGraph/the validator (/root/<RootName>/...).

Regression: scanning from bare "/root" dropped the scene root's name, so
_find_root picked an arbitrary child (e.g. /root/Camera3D) as the parent for
injected Camera3D/DirectionalLight3D nodes. The validator (correct convention)
then rejected that parent, making apply_spec refuse to execute ANY operation on
any scene missing a light or camera — including the real main.tscn.
"""

from devforge.compilation.pipeline.completeness import CompletenessChecker


# A 3D scene with a camera but NO DirectionalLight3D — the exact shape that
# triggered the bug (root "Main" + Camera3D + Ground, no light).
SCENE = {
    "name": "Main",
    "type": "Node3D",
    "children": [
        {"name": "Camera3D", "type": "Camera3D", "children": []},
        {"name": "Ground", "type": "StaticBody3D", "children": []},
    ],
}


def _injected(scene):
    cc = CompletenessChecker()
    ops = cc.enforce(files=[], operations=[], scene_tree=scene)
    return [o for o in ops if o.get("type") == "add_node"]


def test_collect_nodes_uses_root_main_convention():
    cc = CompletenessChecker()
    idx = cc._collect_nodes(SCENE, [])
    # Root indexed at /root/Main, children one level deeper — matching SceneGraph.
    assert "/root/Main" in idx
    assert "/root/Main/Camera3D" in idx
    assert "/root/Main/Ground" in idx
    # The buggy shallow paths must NOT appear.
    assert "/root/Camera3D" not in idx


def test_injected_light_parents_under_root_main():
    """A 3D scene with no DirectionalLight3D gets one injected — parented to the
    real scene root (/root/Main), never an arbitrary child like /root/Camera3D."""
    injected = _injected(SCENE)
    lights = [o for o in injected if o["node_type"] == "DirectionalLight3D"]
    assert lights, "expected a DirectionalLight3D to be injected"
    for op in injected:
        assert op["parent"] == "/root/Main", (
            f"injected {op['node_type']} parent {op['parent']!r} is not the scene root /root/Main"
        )


def test_find_root_prefers_root_main():
    cc = CompletenessChecker()
    idx = cc._collect_nodes(SCENE, [])
    assert cc._find_root(idx, []) == "/root/Main"


# ── Regression: root-agnostic injection (Main2 cascade fix, 6/14) ──
# When a prior build left the scene root as "Main2" (or any non-"Main"
# name), the completeness checker MUST inject under the real root, not a
# hardcoded "/root/Main". Hardcoding it sent injected camera/light to a
# non-existent path; the bridge then materialized a fresh "Main" and the
# scene cascaded under a rogue root.
SCENE_MAIN2 = {
    "name": "Main2",
    "type": "Node3D",
    "children": [
        {"name": "Ground", "type": "StaticBody3D", "children": []},
    ],
}


def test_find_root_resolves_non_main_root():
    cc = CompletenessChecker()
    idx = cc._collect_nodes(SCENE_MAIN2, [])
    assert "/root/Main2" in idx
    assert cc._find_root(idx, []) == "/root/Main2", "completeness must target the live root, not a hardcoded /root/Main"


def test_injected_nodes_parent_under_live_root_not_main():
    """A scene rooted 'Main2' must get its camera/light injected under
    /root/Main2 — never /root/Main (which would spawn a rogue root)."""
    injected = _injected(SCENE_MAIN2)
    assert injected, "expected camera/light injection on a 3D scene"
    for op in injected:
        assert op["parent"] == "/root/Main2", (
            f"injected {op['node_type']} parent {op['parent']!r} "
            f"should be the live root /root/Main2, not a hardcoded /root/Main"
        )
