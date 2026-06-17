"""Unit tests for Smoke Runner: POI visits, report generation, callback mocking.

Tests: SmokeRunner with mock callbacks, SmokeReport aggregation, build_poi, edge cases.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Helpers ─────────────────────────────────────────────────────


def _mock_callbacks():
    """Return mock callbacks for SmokeRunner testing."""
    screenshots: list[str] = []
    logs: list[str] = []
    perf_samples: list[dict] = []

    def run_project():
        return {"status": "running"}

    def stop_project():
        return {"status": "stopped"}

    def game_eval(expr):
        return f"OK: {expr[:50]}"

    def take_screenshot():
        path = f"/tmp/smoke/screenshot_{len(screenshots)}.png"
        screenshots.append(path)
        return path

    def get_logs():
        log_text = "\n".join(logs) if logs else ""
        return log_text

    def get_perf():
        metrics = {"time/fps": 60.0, "rendering/total_draw_calls": 100}
        perf_samples.append(metrics)
        return metrics

    return {
        "run_project": run_project,
        "stop_project": stop_project,
        "game_eval": game_eval,
        "take_screenshot": take_screenshot,
        "get_logs": get_logs,
        "get_perf": get_perf,
    }, screenshots


# ── SmokeRunner tests ────────────────────────────────────────────


def test_smoke_runner_visits_all_pois() -> None:
    """SmokeRunner visits all POIs in order."""
    from devforge.runner.smoke_runner import POIStop, SmokeRunner

    cb, ss = _mock_callbacks()
    runner = SmokeRunner(
        run_project_fn=cb["run_project"],
        stop_project_fn=cb["stop_project"],
        game_eval_fn=cb["game_eval"],
        take_screenshot_fn=cb["take_screenshot"],
        get_logs_fn=cb["get_logs"],
        get_perf_fn=cb["get_perf"],
    )

    pois = [
        POIStop(name="Town", teleport_expr="teleport(0,0,0)", wait_seconds=0.1),
        POIStop(name="Forest", teleport_expr="teleport(100,0,200)", wait_seconds=0.1),
        POIStop(name="Dungeon", teleport_expr="teleport(-50,0,-100)", wait_seconds=0.1),
    ]

    report = runner.run(pois)
    assert report.total_pois == 3
    assert report.pois_visited == 3
    assert report.total_screenshots == 3
    assert report.avg_fps == 60.0
    assert report.min_fps == 60.0
    assert len(report.stops) == 3
    assert report.stops[0].poi.name == "Town"
    assert report.stops[1].poi.name == "Forest"
    assert report.stops[2].poi.name == "Dungeon"


def test_smoke_runner_handles_launch_failure() -> None:
    """When project fails to launch, report includes error and no stops."""
    from devforge.runner.smoke_runner import POIStop, SmokeRunner

    runner = SmokeRunner(
        run_project_fn=lambda: None,  # launch fails
        stop_project_fn=lambda: None,
        game_eval_fn=lambda e: str(e),
        take_screenshot_fn=lambda: "/tmp/fake.png",
        get_logs_fn=lambda: "",
        get_perf_fn=lambda: {"time/fps": 60},
    )

    pois = [POIStop(name="Town", teleport_expr="tp()")]
    report = runner.run(pois)
    assert len(report.errors) == 1
    assert "Failed to launch" in report.errors[0]
    assert len(report.stops) == 0


def test_stop_result_records_error() -> None:
    """StopResult records errors when teleport fails."""
    from devforge.runner.smoke_runner import POIStop, SmokeRunner

    runner = SmokeRunner(
        run_project_fn=lambda: {"ok": True},
        stop_project_fn=lambda: None,
        game_eval_fn=lambda e: None,  # teleport fails
        take_screenshot_fn=lambda: "/tmp/fake.png",
        get_logs_fn=lambda: "",
        get_perf_fn=lambda: {"time/fps": 30},
    )

    pois = [POIStop(name="BrokenPOI", teleport_expr="bad_expr()")]
    report = runner.run(pois)
    assert report.stops[0].error == "Teleport eval failed"
    assert report.pois_visited == 0


# ── build_poi tests ─────────────────────────────────────────────


def test_build_poi_generates_correct_teleport() -> None:
    """build_poi creates a POI with correct GDScript teleport expression."""
    from devforge.runner.smoke_runner import build_poi

    poi = build_poi("Test", {"x": 10, "y": 5, "z": -20}, wait=1.0, description="Testing")
    assert poi.name == "Test"
    assert "Vector3" in poi.teleport_expr
    assert "10" in poi.teleport_expr
    assert "5" in poi.teleport_expr
    assert "-20" in poi.teleport_expr
    assert poi.wait_seconds == 1.0
    assert poi.description == "Testing"


# ── SmokeReport tests ────────────────────────────────────────────


def test_smoke_report_summary_text() -> None:
    """SmokeReport.summary_text includes all key stats."""
    from devforge.runner.smoke_runner import SmokeReport

    report = SmokeReport(
        timestamp=1718000000,
        total_pois=5,
        pois_visited=4,
        total_errors_logged=3,
        total_screenshots=4,
        avg_fps=55.5,
        min_fps=45.0,
        errors=["Failed to teleport to Dungeon"],
    )
    text = report.summary_text()
    assert "5" in text  # total POIs
    assert "4" in text  # visited
    assert "55.5" in text  # avg FPS
    assert "45.0" in text  # min FPS


def test_run_smoke_test_convenience() -> None:
    """run_smoke_test wraps POI dicts and returns report dict."""
    from devforge.runner.smoke_runner import run_smoke_test

    result = run_smoke_test(
        pois_data=[
            {"name": "Spawn", "position": {"x": 0, "y": 0, "z": 0}, "wait_seconds": 0.1},
            {"name": "Market", "position": {"x": 50, "y": 0, "z": 30}, "wait_seconds": 0.1},
        ],
        callbacks={
            "run_project": lambda: {"ok": True},
            "stop_project": lambda: None,
            "game_eval": lambda e: "OK",
            "take_screenshot": lambda: "/tmp/ss.png",
            "get_logs": lambda: "error: something broke\nerror: another thing\ninfo: all good",
            "get_perf": lambda: {"time/fps": 60.0},
        },
    )

    assert result["total_pois"] == 2
    assert result["pois_visited"] == 2
    assert result["total_screenshots"] == 2
    assert result["total_errors_logged"] > 0  # log contains "error" lines
    assert result["avg_fps"] == 60.0
    assert result["min_fps"] == 60.0
    assert "summary" in result


def test_smoke_runner_error_log_count() -> None:
    """Error log counting detects 'error' keywords in log lines."""
    from devforge.runner.smoke_runner import POIStop, SmokeRunner

    runner = SmokeRunner(
        run_project_fn=lambda: {"ok": True},
        stop_project_fn=lambda: None,
        game_eval_fn=lambda e: "OK",
        take_screenshot_fn=lambda: "/tmp/ss.png",
        get_logs_fn=lambda: "ERROR: null reference\nWarning: low fps\nerror: timeout",
        get_perf_fn=lambda: {"time/fps": 45},
    )

    report = runner.run([POIStop(name="Test", teleport_expr="tp()", wait_seconds=0.01)])
    # "ERROR" (case-insensitive) and "error" both count
    assert report.total_errors_logged == 2


# ── Main ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_smoke_runner_visits_all_pois,
        test_smoke_runner_handles_launch_failure,
        test_stop_result_records_error,
        test_build_poi_generates_correct_teleport,
        test_smoke_report_summary_text,
        test_run_smoke_test_convenience,
        test_smoke_runner_error_log_count,
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
