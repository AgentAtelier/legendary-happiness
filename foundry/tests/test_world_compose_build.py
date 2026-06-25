"""Unit 3 e2e — compose_world orchestration (stack-free).

Drives the multi-space build wiring without Blender/Godot: ensure_assets,
the per-space shell, compile_scene, asset-copy and pre-import are all
monkeypatched, so the test asserts ORCHESTRATION (each space compiled into
its own scene, world.tscn references them all, main_scene points at it).
The real build (with assets + Godot) is run by the orchestrator.
"""
from __future__ import annotations

from pathlib import Path

import world.compose as compose
from world.compose import compose_world
from world.operations import apply_op, replay


def _space(sid, origin, size=(8, 4, 8)):
    return {"op": "add_space", "id": sid, "brief": {"theme": "study"},
            "footprint": {"origin": list(origin), "size": list(size)}}


def _entity(sid, eid, cat, mat, pos):
    return {"op": "add_entity", "space": sid,
            "entity": {"id": eid, "type": cat, "pos": list(pos),
                       "properties": {"material": mat}}}


def _two_space_world():
    w = replay([])
    w = apply_op(w, _space("hall", (0, 0, 0)))
    w = apply_op(w, _space("court", (0, 0, -8)))
    w = apply_op(w, _entity("hall", "t1", "table", "worn_oak", (3, 0, 3)))
    w = apply_op(w, _entity("court", "sh1", "shelf", "rough_granite", (2, 0, -6)))
    return w


def _fake_stack(monkeypatch, calls):
    monkeypatch.setattr(compose.asset_ensure, "ensure_assets",
                        lambda m, lib, lex, **k: calls["ensured"].append(len(m)) or [])
    monkeypatch.setattr(compose.room_shell, "ensure_room_shell",
                        lambda *a, **k: (None, {}))

    def fake_compile(specs, manifest, scene_path, **kw):
        Path(scene_path).write_text("[gd_scene format=3]\n")
        calls["compiled"].append(Path(scene_path).name)

    monkeypatch.setattr(compose.scene_compiler, "compile_scene", fake_compile)
    monkeypatch.setattr(compose.publish, "copy_asset_family", lambda *a, **k: [])
    monkeypatch.setattr(compose.scaffold, "_pre_import",
                        lambda *a, **k: calls.__setitem__("preimport", calls["preimport"] + 1))
    monkeypatch.setattr(compose.scaffold, "_find_godot", lambda: "godot")


def _template(tmp_path):
    template = tmp_path / "template"
    (template / "scenes").mkdir(parents=True)
    (template / "project.godot").write_text("[application]\n")
    return template


def test_compose_world_compiles_each_space(tmp_path, monkeypatch):
    calls = {"compiled": [], "ensured": [], "preimport": 0}
    _fake_stack(monkeypatch, calls)
    out = compose_world(_two_space_world(), tmp_path / "build",
                        library_dir="lib", lexicon="lex.json",
                        template_dir=str(_template(tmp_path)))
    assert sorted(calls["compiled"]) == ["court.tscn", "hall.tscn"]
    assert (out / "scenes" / "court.tscn").exists()
    assert (out / "scenes" / "hall.tscn").exists()


def test_compose_world_writes_world_tscn_referencing_all_spaces(tmp_path, monkeypatch):
    calls = {"compiled": [], "ensured": [], "preimport": 0}
    _fake_stack(monkeypatch, calls)
    out = compose_world(_two_space_world(), tmp_path / "build",
                        library_dir="lib", lexicon="lex.json",
                        template_dir=str(_template(tmp_path)))
    world_tscn = (out / "scenes" / "world.tscn").read_text()
    assert "res://scenes/hall.tscn" in world_tscn
    assert "res://scenes/court.tscn" in world_tscn


def test_compose_world_sets_world_tscn_as_main(tmp_path, monkeypatch):
    calls = {"compiled": [], "ensured": [], "preimport": 0}
    _fake_stack(monkeypatch, calls)
    out = compose_world(_two_space_world(), tmp_path / "build",
                        library_dir="lib", lexicon="lex.json",
                        template_dir=str(_template(tmp_path)))
    pg = (out / "project.godot").read_text()
    assert 'run/main_scene="res://scenes/world.tscn"' in pg


def test_compose_world_ensures_assets_and_preimports_once(tmp_path, monkeypatch):
    calls = {"compiled": [], "ensured": [], "preimport": 0}
    _fake_stack(monkeypatch, calls)
    compose_world(_two_space_world(), tmp_path / "build",
                  library_dir="lib", lexicon="lex.json",
                  template_dir=str(_template(tmp_path)))
    assert len(calls["ensured"]) == 2          # one ensure_assets per space
    assert calls["preimport"] == 1             # single import pass at the end


def test_compose_world_spawn_space_threads_to_world_tscn(tmp_path, monkeypatch):
    calls = {"compiled": [], "ensured": [], "preimport": 0}
    _fake_stack(monkeypatch, calls)
    out = compose_world(_two_space_world(), tmp_path / "build",
                        library_dir="lib", lexicon="lex.json",
                        template_dir=str(_template(tmp_path)), spawn_space="hall")
    world_tscn = (out / "scenes" / "world.tscn").read_text()
    spawn_block = world_tscn.split("PlayerSpawn")[1]
    # hall centre is (4, 2, 4)
    assert "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 4, 2, 4)" in spawn_block
