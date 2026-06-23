"""Pytest config for the foundry suite.

Registers a ``blender`` marker and auto-applies it to every test module that
gates on a Blender binary (these spawn real Blender subprocesses and are slow —
minutes for the whole group). Fast iteration:

    .venv/bin/python -m pytest -m "not blender" -q     # everything except Blender bakes
    .venv/bin/python -m pytest -m blender -q           # only the Blender-gated tests

The orchestrator runs the full suite (including ``-m blender``); the CLI AI runs
``-m "not blender"`` to stay inside its time budget.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "blender: spawns a Blender subprocess (slow). Deselect with -m 'not blender'.",
    )


def pytest_collection_modifyitems(config, items):
    import functools
    import pytest

    @functools.lru_cache(maxsize=None)
    def _spawns_blender(path: str) -> bool:
        try:
            src = open(path, encoding="utf-8").read()
        except OSError:
            return False
        return "blender" in src.lower() and any(
            tok in src for tok in ("subprocess", "--background", "--python")
        )

    for item in items:
        path = getattr(getattr(item, "module", None), "__file__", None)
        if path and _spawns_blender(path):
            item.add_marker(pytest.mark.blender)
