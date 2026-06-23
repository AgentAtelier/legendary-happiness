from pathlib import Path
import room_shell


def test_cache_hit_skips_blender(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(room_shell, "_run_blender", lambda *a, **k: calls.append(a) or True)
    # pre-create the cached glb so it's a hit
    key_dir = room_shell._cache_dir(8, 6, 3, "study", 0, tmp_path)
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "shell.glb").write_bytes(b"GLB")
    p = room_shell.ensure_room_shell(8, 6, 3, "study", 0, cache_root=tmp_path)
    assert p and p.exists() and calls == []   # no blender call on hit


def test_cache_miss_calls_blender(tmp_path, monkeypatch):
    def fake(out_glb, *a, **k):
        Path(out_glb).parent.mkdir(parents=True, exist_ok=True)
        Path(out_glb).write_bytes(b"GLB"); return True
    monkeypatch.setattr(room_shell, "_run_blender", fake)
    p = room_shell.ensure_room_shell(8, 6, 3, "study", 0, cache_root=tmp_path)
    assert p and p.exists()


def test_blender_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(room_shell.shutil, "which", lambda _: None)
    assert room_shell.ensure_room_shell(8, 6, 3, "study", 0, cache_root=tmp_path) is None


def test_generation_failure_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(room_shell, "_run_blender", lambda *a, **k: False)
    assert room_shell.ensure_room_shell(8, 6, 3, "study", 0, cache_root=tmp_path) is None


def test_key_stable_and_version_sensitive(tmp_path):
    a = room_shell._cache_dir(8, 6, 3, "study", 0, tmp_path)
    b = room_shell._cache_dir(8.0, 6.0, 3.0, "study", 0, tmp_path)
    assert a == b
    c = room_shell._cache_dir(8, 6, 3, "tavern", 0, tmp_path)
    assert a != c
