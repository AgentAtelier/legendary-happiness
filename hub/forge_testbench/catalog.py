"""Catalog — the test registry. Every Test self-registers.

The UI reads the catalog for {id, category, title, description} —
test descriptions are a property of the test, not hard-coded HTML.
Suites are named lists of test ids.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .test import Test

CATALOG: list[type[Test]] = []

DEFAULT_SUITES: dict[str, list[str]] = {
    "everything": [],  # populated from all registered tests
    "fast": [],  # tests that run in < 5s (declared in test metadata)
    "llama-layer": [
        "probe.llama.throughput",
        "probe.llama.context",
        "probe.llama.grammar",
        "probe.llama.thinking",
        "probe.llama.tools",
    ],
    "devforge-layer": [
        "probe.devforge.plan",
        "probe.devforge.compile",
        "probe.devforge.execute",
        "probe.devforge.completeness",
        "probe.devforge.validate",
        "probe.devforge.roundtrip",
    ],
    "godotai-layer": [
        "probe.godotai.latency",
        "probe.godotai.fidelity",
    ],
    "runtime-layer": [
        "probe.runtime.launch",
    ],
    "odysseus-layer": [
        "probe.odysseus.persona",
        "probe.odysseus.retrieval",
    ],
    "chain-health": [
        "probe.devforge.plan",
        "probe.devforge.compile",
        "probe.devforge.execute",
        "probe.devforge.completeness",
        "probe.devforge.validate",
    ],
    "scenarios-v1": [],  # populated from scenario tests
    "diagnostics-v1": [],  # populated from variety tests
    "capability-v1": [],
    "spatial-v1": [],
    "building-v1": [],
    "garden-v1": [],
    "ssp-v1": [],
    "wfc-v1": [],
    "voronoi-v1": [],
}


def register(test_cls: type[Test]) -> type[Test]:
    """Register a test class in the global catalog.

    Usage as a decorator:
        @register
        class ProbeLlamaThroughput(Test):
            ...

    Auto-adds the test to every suite listed in the class's suites attribute
    that also appears in DEFAULT_SUITES.  This means suite definitions
    declared on the Test class flow into get_suites() automatically.
    """
    CATALOG.append(test_cls)
    for suite in test_cls.suites:
        if suite in DEFAULT_SUITES and test_cls.id not in DEFAULT_SUITES[suite]:
            DEFAULT_SUITES[suite].append(test_cls.id)
    return test_cls


def get_suites() -> dict[str, list[str]]:
    """Return the current suite → test_id mapping.

    Loads user overrides from data/testbench/suites.json if present,
    merging with defaults. User additions win; user removals are honored.
    """
    suites = dict(DEFAULT_SUITES)

    # Load user overrides
    user_path = Path(__file__).parent.parent / "data" / "testbench" / "suites.json"
    if user_path.exists():
        try:
            user = json.loads(user_path.read_text())
            # User definitions fully replace defaults for the same key
            for k, v in user.items():
                suites[k] = v
        except Exception:
            pass

    return suites


def save_suites(suites: dict[str, list[str]]) -> None:
    """Persist user-defined suite definitions."""
    user_path = Path(__file__).parent.parent / "data" / "testbench" / "suites.json"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    # Only save suites that differ from defaults or don't exist in defaults
    to_save = {}
    for k, v in suites.items():
        default = DEFAULT_SUITES.get(k)
        if default != v or k not in DEFAULT_SUITES:
            to_save[k] = v
    user_path.write_text(json.dumps(to_save, indent=2))


def catalog_entries() -> list[dict]:
    """Return all registered tests as catalog entries for UI consumption."""
    return [t.to_catalog_entry() for t in CATALOG]
