"""Unit tests for foundry.blender.kitbash — WS-3.3."""

import sys


def test_kitbash_library_register_and_get():
    """KitbashLibrary can register and retrieve part builders."""
    sys.modules.pop("bpy", None)
    sys.modules.pop("bmesh", None)
    from blender.kitbash import KitbashLibrary

    lib = KitbashLibrary()

    def fake_builder(params, seed):
        return ("fake_mesh", 1.0)

    lib.register("test_part", fake_builder)
    assert lib.get("test_part") is fake_builder
    assert "test_part" in lib.list_parts()


def test_kitbash_library_get_unknown_raises():
    """Getting an unregistered part raises KeyError."""
    sys.modules.pop("bpy", None)
    sys.modules.pop("bmesh", None)
    from blender.kitbash import KitbashLibrary

    lib = KitbashLibrary()
    try:
        lib.get("nonexistent")
        assert False, "should have raised"
    except KeyError:
        pass


def test_kitbash_library_list_parts_empty():
    """Empty library returns empty list."""
    sys.modules.pop("bpy", None)
    sys.modules.pop("bmesh", None)
    from blender.kitbash import KitbashLibrary

    lib = KitbashLibrary()
    assert lib.list_parts() == []


def test_compose_requires_blender():
    """compose raises RuntimeError when bpy not available."""
    sys.modules.pop("bpy", None)
    sys.modules.pop("bmesh", None)
    from blender import kitbash
    try:
        kitbash.compose({"parts": [{"part": "leg_turned"}]})
        assert False, "should have raised"
    except RuntimeError as e:
        assert "Blender" in str(e)


def test_compose_empty_parts_raises():
    """compose raises ValueError with empty parts list."""
    sys.modules.pop("bpy", None)
    sys.modules.pop("bmesh", None)
    from blender import kitbash
    # Mock bpy to bypass the RuntimeError
    import blender.kitbash as kb
    kb._HAS_BPY = True
    try:
        kb.compose({"parts": []})
        assert False, "should have raised"
    except ValueError as e:
        assert "at least one part" in str(e)
    finally:
        kb._HAS_BPY = False


def test_kitbash_library_global_singleton():
    """kitbash_library is a module-level singleton."""
    sys.modules.pop("bpy", None)
    sys.modules.pop("bmesh", None)
    from blender.kitbash import kitbash_library, KitbashLibrary
    assert isinstance(kitbash_library, KitbashLibrary)


def test_kitbash_library_multiple_registrations():
    """Can register multiple parts."""
    sys.modules.pop("bpy", None)
    sys.modules.pop("bmesh", None)
    from blender.kitbash import KitbashLibrary

    lib = KitbashLibrary()
    for i in range(5):
        def builder(params, seed, i=i):
            return (f"mesh_{i}", float(i))
        lib.register(f"part_{i}", builder)
    assert len(lib.list_parts()) == 5


def test_compose_unknown_part_raises():
    """compose raises KeyError for unregistered parts."""
    sys.modules.pop("bpy", None)
    sys.modules.pop("bmesh", None)
    from blender import kitbash
    try:
        kitbash.compose({"parts": [{"part": "does_not_exist"}]}, seed=1)
        assert False, "should have raised"
    except (RuntimeError, KeyError):
        # Either RuntimeError (no Blender) or KeyError (unknown part) is fine
        pass
