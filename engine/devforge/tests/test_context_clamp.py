"""Unit tests for context-budget clamping against the server window.

The configured context_token_budget is a wish; the server's n_ctx is
reality. These verify the math that keeps prompt + generation inside
the window (Round 8 — RX 6800 / ctx-size 12288 tuning).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_clamps_when_budget_exceeds_window() -> None:
    """The user's actual setup: 24000 budget vs n_ctx=12288."""
    from devforge.infrastructure.runtime_config import (
        PROMPT_OVERHEAD_TOKENS,
        effective_context_budget,
    )

    effective = effective_context_budget(n_ctx=12288, llama_max_tokens=4096, configured_budget=24000)
    assert effective == 12288 - 4096 - PROMPT_OVERHEAD_TOKENS
    # Sanity: prompt(budget + overhead) + generation fits the window
    assert effective + PROMPT_OVERHEAD_TOKENS + 4096 <= 12288


def test_no_clamp_when_budget_fits() -> None:
    from devforge.infrastructure.runtime_config import effective_context_budget

    effective = effective_context_budget(n_ctx=32768, llama_max_tokens=4096, configured_budget=24000)
    assert effective == 24000


def test_never_negative() -> None:
    """A tiny window must not produce a negative budget."""
    from devforge.infrastructure.runtime_config import effective_context_budget

    effective = effective_context_budget(n_ctx=2048, llama_max_tokens=4096, configured_budget=24000)
    assert effective == 0


def test_apply_server_limits_mutates_config() -> None:
    """apply_server_limits clamps the config in place from live props."""
    from unittest.mock import MagicMock

    from devforge.infrastructure.llm.llama_client import apply_server_limits
    from devforge.infrastructure.runtime_config import (
        PROMPT_OVERHEAD_TOKENS,
        RuntimeConfig,
    )

    config = RuntimeConfig(context_token_budget=24000, llama_max_tokens=4096)
    client = MagicMock()
    client.server_props.return_value = {
        "n_ctx": 12288,
        "total_slots": 1,
        "model_alias": "gemma-26b",
    }

    apply_server_limits(config, client)
    assert config.context_token_budget == 12288 - 4096 - PROMPT_OVERHEAD_TOKENS


def test_apply_server_limits_keeps_config_when_server_down() -> None:
    from unittest.mock import MagicMock

    from devforge.infrastructure.llm.llama_client import apply_server_limits
    from devforge.infrastructure.runtime_config import RuntimeConfig

    config = RuntimeConfig(context_token_budget=24000)
    client = MagicMock()
    client.server_props.return_value = None

    apply_server_limits(config, client)
    assert config.context_token_budget == 24000


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_clamps_when_budget_exceeds_window,
        test_no_clamp_when_budget_fits,
        test_never_negative,
        test_apply_server_limits_mutates_config,
        test_apply_server_limits_keeps_config_when_server_down,
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
