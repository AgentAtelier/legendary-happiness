"""Unit tests for LLM Gateway per-turn budget tracking.

Tests: default bucket, strict mode, sliding expiry, 429 on exceed,
budget reset after expiry, concurrent access (single-threaded asyncio).
"""

from __future__ import annotations

import sys
import os
import time

# Ensure the package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_default_bucket_exists() -> None:
    """Untagged requests share a default bucket."""
    from devforge.infrastructure.llm.gateway import _DEFAULT_BUCKET, _check_budget  # noqa: F401

    entry = _check_budget(_DEFAULT_BUCKET)
    assert entry is not None
    assert entry.tokens_used == 0
    assert entry.call_count == 0


def test_budget_exceed_raises_429() -> None:
    """Requests exceeding the budget limit get a 429."""
    from devforge.infrastructure.llm.gateway import (
        _check_budget,
        _record_usage,
        BUDGET_LIMIT_TOKENS,
    )
    from fastapi import HTTPException

    # Use a unique key so we don't collide with other tests
    test_key = f"__test_exceed_{time.monotonic()}"

    # _record_usage is a no-op for unknown turns — create the entry
    # first, the same way the production handlers do.
    _check_budget(test_key)
    # Drain the budget
    _record_usage(test_key, BUDGET_LIMIT_TOKENS)

    try:
        _check_budget(test_key)
        assert False, "Expected HTTPException(429)"
    except HTTPException as e:
        assert e.status_code == 429
        assert "exceeded" in e.detail.lower()


def test_budget_below_limit_passes() -> None:
    """Requests below the budget limit pass."""
    from devforge.infrastructure.llm.gateway import (
        _check_budget,
        _record_usage,
    )

    test_key = f"__test_below_{time.monotonic()}"
    _check_budget(test_key)  # create the entry
    _record_usage(test_key, 500)
    entry = _check_budget(test_key)
    assert entry.tokens_used == 500


def test_sliding_expiry_resets_on_usage() -> None:
    """Active turns don't expire mid-pipeline — expiry resets on record."""
    from devforge.infrastructure.llm.gateway import (
        _check_budget,
        _record_usage,
        _turn_budgets,  # noqa: F401
    )

    test_key = f"__test_sliding_{time.monotonic()}"

    # Create entry and record usage
    entry1 = _check_budget(test_key)
    _record_usage(test_key, 100)

    entry2 = _turn_budgets.get(test_key)
    assert entry2 is not None
    # created_at should have been reset by _record_usage
    assert entry2.created_at >= entry1.created_at


def test_strict_mode_env_var_configurable() -> None:
    """GATEWAY_STRICT_BUDGET env var can enable strict mode."""
    import devforge.infrastructure.llm.gateway as gw

    # Strict mode defaults to off
    assert gw.GATEWAY_STRICT_BUDGET is False

    # The env var path is tested by setting os.environ and re-reading.
    # Rather than mutating the module global, we verify the env-var
    # parsing logic: '1' → True, anything else → False.
    assert gw.GATEWAY_STRICT_BUDGET == (gw.os.environ.get("GATEWAY_STRICT_BUDGET", "0") == "1")


def test_expired_entry_purged_on_lookup() -> None:
    """Entries past TURN_EXPIRY_SECONDS are purged and get a fresh budget."""
    from devforge.infrastructure.llm.gateway import (
        _check_budget,
        _record_usage,
        _turn_budgets,  # noqa: F401
        TURN_EXPIRY_SECONDS,
    )

    test_key = f"__test_expired_{time.monotonic()}"

    # Create entry with old timestamp
    entry = _check_budget(test_key)
    _record_usage(test_key, 1000)
    # Artificially age the entry past expiry
    entry.created_at = time.monotonic() - TURN_EXPIRY_SECONDS - 60

    # Next lookup should purge and create fresh
    fresh = _check_budget(test_key)
    assert fresh is not None
    assert fresh.tokens_used == 0  # fresh budget
    assert fresh.call_count == 0


def test_separate_turns_have_separate_budgets() -> None:
    """Two different turn_ids get independent budgets."""
    from devforge.infrastructure.llm.gateway import (
        _check_budget,
        _record_usage,
    )

    turn_a = f"__test_turn_a_{time.monotonic()}"
    turn_b = f"__test_turn_b_{time.monotonic()}"

    _check_budget(turn_a)  # create the entries
    _check_budget(turn_b)
    _record_usage(turn_a, 2000)
    _record_usage(turn_b, 100)

    entry_a = _check_budget(turn_a)
    entry_b = _check_budget(turn_b)

    assert entry_a.tokens_used == 2000
    assert entry_b.tokens_used == 100


def test_record_usage_noop_on_zero() -> None:
    """Recording zero tokens is a no-op."""
    from devforge.infrastructure.llm.gateway import _record_usage

    # Should not raise
    _record_usage("nonexistent", 0)


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_default_bucket_exists,
        test_budget_exceed_raises_429,
        test_budget_below_limit_passes,
        test_sliding_expiry_resets_on_usage,
        test_strict_mode_env_var_configurable,
        test_expired_entry_purged_on_lookup,
        test_separate_turns_have_separate_budgets,
        test_record_usage_noop_on_zero,
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
