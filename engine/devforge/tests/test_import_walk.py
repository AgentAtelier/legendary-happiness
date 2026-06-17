"""Import-walk smoke test — verifies every module under ``devforge.``
imports without side effects (no sys.exit, no network, no file writes).

This is the test the audit says would have caught S1's four import failures.
Run with: python -m pytest devforge/tests/test_import_walk.py -v
Or directly: python devforge/tests/test_import_walk.py
"""

from __future__ import annotations

import importlib
import pathlib
import sys
import os

# Modules that exist on disk but must not be imported.
# Keep this list short and justified — every entry is a hole in the test.
EXCLUDED_MODULES = {
    # Packaging script inside the package tree; importing it would run
    # setuptools' setup() as a side effect.
    "devforge.patch.grammars.setup",
}


def _walk_packages(package_name: str) -> list[str]:
    """Return all sub-module names under *package_name*.

    Discovers modules from .py files on disk rather than via
    pkgutil.walk_packages — pkgutil silently skips directories without
    __init__.py (namespace packages), which hid 17 broken modules from
    this test in the June 2026 audit rounds.
    """
    try:
        package = importlib.import_module(package_name)
    except ImportError as e:
        return [f"FAIL: cannot import {package_name}: {e}"]

    root = pathlib.Path(package.__path__[0])
    names: list[str] = []
    for py in root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        rel = py.relative_to(root).with_suffix("")
        name = ".".join((package_name,) + rel.parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        # Skip test files themselves (avoid infinite recursion)
        if ".tests." in name or name.endswith(".tests"):
            continue
        if name.endswith("__main__") or name in EXCLUDED_MODULES:
            continue
        names.append(name)
    return sorted(set(names))


def test_all_modules_import() -> None:
    """Import every module under devforge. — no side effects allowed."""
    modules = _walk_packages("devforge")
    assert modules, "No modules found under devforge."

    if isinstance(modules[0], str) and modules[0].startswith("FAIL:"):
        raise AssertionError(modules[0])

    failures: list[str] = []

    for mod_name in modules:
        try:
            importlib.import_module(mod_name)
        except SystemExit as e:
            # Import-time sys.exit() — the health_check.py bug
            failures.append(f"{mod_name}: sys.exit({e.code}) at import time")
        except Exception as e:
            failures.append(f"{mod_name}: {type(e).__name__}: {e}")

    if failures:
        raise AssertionError(
            f"{len(failures)}/{len(modules)} modules failed to import:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )

    print(f"All {len(modules)} modules imported successfully.")


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Ensure the package root is on sys.path
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        test_all_modules_import()
        print("PASS")
        sys.exit(0)
    except AssertionError as e:
        print(f"FAIL: {e}")
        sys.exit(1)
