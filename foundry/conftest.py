"""Pytest config for the foundry suite.

Registers markers:
- ``blender``: tests that spawn a Blender subprocess (slow).  Apply
  explicitly with ``pytestmark = pytest.mark.blender`` at module level.
  Fast iteration:
      .venv/bin/python -m pytest -m "not blender and not godot_heavy and not live" -q
- ``godot_heavy``: tests that launch Godot headless and are expensive
  or intermittently flaky due to software-rendering timing.
- ``live``: tests that require the live forge stack (llama on :8002,
  hub on :8003) to be running.  Skipped by default; run with
  ``-m live`` to include.

The orchestrator runs the full suite; the fast gate runs
``-m "not blender and not godot_heavy and not live"``.
"""

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "blender: spawns a Blender subprocess (slow). Deselect with -m 'not blender'.",
    )
    config.addinivalue_line(
        "markers",
        "godot_heavy(reason): expensive Godot-headless test, may be intermittent.",
    )
    config.addinivalue_line(
        "markers",
        "live: requires the live forge stack (llama on :8002, hub on :8003).",
    )


def pytest_collection_modifyitems(config, items):
    """Skip @live tests by default — they require the running stack.
    Pass -m live to include them."""
    if "live" not in config.getoption("-m", ""):
        skip_live = pytest.mark.skip(reason="requires live stack — use -m live")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)
