"""Pytest configuration for forge-hub tests.

Defines the @live marker for integration tests that require the real
forge stack (llama, DevForge, godot-ai) to be running. These are
skipped in the default test run; run with `pytest -m live` to include.
"""

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: integration test that requires the live forge stack running",
    )


def pytest_collection_modifyitems(config, items):
    """Skip @live tests by default — they mutate the running system.
    Pass -m live to include them."""
    if "live" not in config.getoption("-m", ""):
        skip_live = pytest.mark.skip(reason="requires live stack — use -m live")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)
