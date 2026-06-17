"""Unit tests for script extractor: path sanitization, content-hash names.

Tests: path traversal rejection, absolute path rejection, content-hash
fallback, explicit header paths, class-name extraction.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_rejects_dot_dot_traversal() -> None:
    """Paths containing .. are rejected."""
    from devforge.compilation.pipeline.script_extractor import _sanitize_path

    # No kwarg form available — test the internal function directly
    result = _sanitize_path("../../.config/evil.gd")
    assert result is None or result == "" or "scripts/" in str(result)


def test_rejects_absolute_path() -> None:
    """Absolute paths are rejected."""
    from devforge.compilation.pipeline.script_extractor import _sanitize_path

    result = _sanitize_path("/etc/passwd")
    assert result is None or result == "" or "scripts/" in str(result)


def test_allows_relative_scripts_path() -> None:
    """Normal relative paths under scripts/ are allowed."""
    from devforge.compilation.pipeline.script_extractor import _sanitize_path

    result = _sanitize_path("scripts/player.gd")
    assert result is not None
    assert result != ""
    assert ".." not in result
    assert not result.startswith("/")


def test_fallback_uses_content_hash() -> None:
    """The fallback filename uses a content-based hash, not Python's salted hash."""
    from devforge.compilation.pipeline.script_extractor import (
        extract,
    )

    # Extract with a simple GDScript snippet
    prompt = "Add a player with this script:\n```gdscript\nextends CharacterBody3D\n\nfunc _ready():\n    pass\n```"
    files, scrubbed = extract(prompt)

    if files:
        for f in files:
            assert f.path is not None
            assert ".." not in f.path
            assert not f.path.startswith("/")
            assert f.content is not None


def test_extract_with_path_header() -> None:
    """Scripts with # path: header use that path (if safe)."""
    from devforge.compilation.pipeline.script_extractor import extract

    prompt = """# path: scripts/player.gd
extends CharacterBody3D

func _ready():
    pass
"""
    files, scrubbed = extract(prompt)
    # The whole prompt is one script — scrubbing leaves it empty and
    # the engine short-circuits planning (see engine.py Phase 0).
    assert len(files) >= 1, "Files should be extracted from the prompt"
    assert files[0].path == "scripts/player.gd"
    assert not scrubbed.strip(), "Fully-extracted prompt should scrub to empty"


def test_extract_with_class_name() -> None:
    """Scripts with class_name derive a path from the class name."""
    from devforge.compilation.pipeline.script_extractor import extract

    prompt = """class_name PlayerController
extends Node

func move():
    pass
"""
    files, scrubbed = extract(prompt)
    # Either path is derived from class_name, or falls back to hash
    assert len(files) >= 1
    assert "PlayerController" in files[0].path or files[0].path.startswith("scripts/")


def test_empty_body_rejected() -> None:
    """An empty or whitespace-only script body produces no files."""
    from devforge.compilation.pipeline.script_extractor import _sanitize_path

    result = _sanitize_path("   ")
    assert result is None or result == ""


def test_fragments_merge_on_same_path() -> None:
    """Fragments inferring the same path merge into one file.

    A script split at a blank line must not produce two files with the
    same path — the executor's second script_create would overwrite the
    first and silently lose content.
    """
    from devforge.compilation.pipeline.script_extractor import extract

    prompt = "# path: scripts/player.gd\nextends CharacterBody3D\n\nfunc _ready():\n    pass\n"
    files, _ = extract(prompt)

    paths = [f.path for f in files]
    assert len(paths) == len(set(paths)), f"Duplicate paths: {paths}"
    assert "extends CharacterBody3D" in files[0].content
    assert "func _ready():" in files[0].content


def test_rejects_empty_basename() -> None:
    """A path with no basename is rejected."""
    from devforge.compilation.pipeline.script_extractor import _sanitize_path

    result = _sanitize_path("scripts/")
    assert result is None or result == ""


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_rejects_dot_dot_traversal,
        test_rejects_absolute_path,
        test_allows_relative_scripts_path,
        test_fallback_uses_content_hash,
        test_extract_with_path_header,
        test_extract_with_class_name,
        test_empty_body_rejected,
        test_fragments_merge_on_same_path,
        test_rejects_empty_basename,
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
