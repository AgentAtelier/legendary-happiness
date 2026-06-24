"""Pytest config for the foundry suite.

Registers markers:
- ``blender``: tests that spawn a Blender subprocess (slow).  Apply
  explicitly with ``pytestmark = pytest.mark.blender`` at module level.
  Fast iteration:
      .venv/bin/python -m pytest -m "not blender" -q
- ``godot_heavy``: tests that launch Godot headless and are expensive
  or intermittently flaky due to software-rendering timing.

The orchestrator runs the full suite; the CLI AI runs ``-m "not blender"``
to stay inside its time budget.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "blender: spawns a Blender subprocess (slow). Deselect with -m 'not blender'.",
    )
    config.addinivalue_line(
        "markers",
        "godot_heavy(reason): expensive Godot-headless test, may be intermittent.",
    )
