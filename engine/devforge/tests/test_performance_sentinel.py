"""Unit tests for Performance Sentinel: sampling, history, summary stats."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Sample recording ────────────────────────────────────────────


def test_sample_stores_metrics() -> None:
    """Recording a sample stores it in the ring buffer."""
    from devforge.sentinel.sentinel import PerformanceSentinel

    s = PerformanceSentinel(max_samples=10)
    sample = s.sample({"time/fps": 60.0, "rendering/total_draw_calls": 120})

    assert sample is not None
    assert sample.metrics["time/fps"] == 60.0
    assert sample.metrics["rendering/total_draw_calls"] == 120
    assert len(s._samples) == 1


def test_sample_returns_none_for_none_metrics() -> None:
    """Sample(None) returns None and nothing is stored."""
    from devforge.sentinel.sentinel import PerformanceSentinel

    s = PerformanceSentinel()
    sample = s.sample(None)
    assert sample is None
    assert len(s._samples) == 0


# ── History ─────────────────────────────────────────────────────


def test_history_returns_recent_samples() -> None:
    """History returns samples newest first, up to n."""
    from devforge.sentinel.sentinel import PerformanceSentinel

    s = PerformanceSentinel(max_samples=10)
    for i in range(5):
        s.sample({"fps": 60.0 - i})  # 60, 59, 58, 57, 56

    result = s.history(n=3)
    assert len(result["samples"]) == 3
    # Newest first: 56, 57, 58
    assert result["samples"][0]["metrics"]["fps"] == 56.0
    assert result["samples"][2]["metrics"]["fps"] == 58.0
    assert result["total_samples"] == 5


def test_history_empty() -> None:
    """History with no samples returns empty lists and zeros."""
    from devforge.sentinel.sentinel import PerformanceSentinel

    s = PerformanceSentinel()
    result = s.history()
    assert result["samples"] == []
    assert result["summary"] == {}
    assert result["total_samples"] == 0


# ── Summary statistics ──────────────────────────────────────────


def test_summary_computes_stats() -> None:
    """Summary computes min, max, avg across all samples."""
    from devforge.sentinel.sentinel import PerformanceSentinel

    s = PerformanceSentinel()
    s.sample({"fps": 60.0, "draws": 100})
    s.sample({"fps": 50.0, "draws": 200})
    s.sample({"fps": 55.0, "draws": 150})

    result = s.history()
    summary = result["summary"]

    assert "fps" in summary
    assert summary["fps"]["min"] == 50.0
    assert summary["fps"]["max"] == 60.0
    assert summary["fps"]["avg"] == 55.0
    assert summary["fps"]["sample_count"] == 3

    assert "draws" in summary
    assert summary["draws"]["min"] == 100
    assert summary["draws"]["max"] == 200
    assert summary["draws"]["avg"] == 150


def test_summary_skips_non_numeric() -> None:
    """Summary ignores string, bool, and dict metric values."""
    from devforge.sentinel.sentinel import PerformanceSentinel

    s = PerformanceSentinel()
    s.sample({"fps": 60.0, "label": "good", "enabled": True, "config": {}})
    s.sample({"fps": 30.0, "label": "bad", "enabled": False, "config": {}})

    result = s.history()
    summary = result["summary"]

    assert "fps" in summary
    assert "label" not in summary
    assert "enabled" not in summary
    assert "config" not in summary


# ── Ring buffer eviction ────────────────────────────────────────


def test_eviction_on_overflow() -> None:
    """Oldest sample is evicted when max_samples is exceeded."""
    from devforge.sentinel.sentinel import PerformanceSentinel

    s = PerformanceSentinel(max_samples=3)
    s.sample({"i": 1})
    s.sample({"i": 2})
    s.sample({"i": 3})
    s.sample({"i": 4})  # Should evict {i: 1}

    assert len(s._samples) == 3
    assert s._samples[0].metrics["i"] == 2  # oldest remaining
    assert s._samples[-1].metrics["i"] == 4  # newest


# ── Clear ───────────────────────────────────────────────────────


def test_clear_empties_buffer() -> None:
    """Clear() removes all samples."""
    from devforge.sentinel.sentinel import PerformanceSentinel

    s = PerformanceSentinel()
    s.sample({"fps": 60.0})
    s.sample({"fps": 30.0})
    assert len(s._samples) == 2

    s.clear()
    assert len(s._samples) == 0
    result = s.history()
    assert result["total_samples"] == 0


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_sample_stores_metrics,
        test_sample_returns_none_for_none_metrics,
        test_history_returns_recent_samples,
        test_history_empty,
        test_summary_computes_stats,
        test_summary_skips_non_numeric,
        test_eviction_on_overflow,
        test_clear_empties_buffer,
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
