"""Smoke Runner / Dailies — scripted auto-playtest with morning report.

Deterministic core (tier 0): no LLM calls. Launches the game, teleports
through POIs, captures screenshots + logs + perf samples at each stop,
and produces a structured report — the game-dev equivalent of watching
yesterday's dailies footage.

Every primitive exists in godot-ai (run_project, game_eval, take_screenshot,
get_logs, get_performance_monitors). The work is orchestration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from devforge.infrastructure.logger import logger


# ── Data model ───────────────────────────────────────────────────


@dataclass
class POIStop:
    """A point of interest to visit during the smoke run."""

    name: str                          # "Town Square"
    teleport_expr: str                 # GDScript expression to move there
    wait_seconds: float = 2.0          # seconds to wait after teleport
    description: str = ""              # what to look for at this POI

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "teleport_expr": self.teleport_expr,
            "wait_seconds": self.wait_seconds,
            "description": self.description,
        }


@dataclass
class StopResult:
    """Data captured at one POI stop."""

    poi: POIStop
    screenshot_path: str = ""
    log_text: str = ""
    perf_metrics: dict = field(default_factory=dict)
    eval_result: str = ""
    elapsed_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "poi": self.poi.name,
            "screenshot": self.screenshot_path or None,
            "log_lines": len(self.log_text.splitlines()) if self.log_text else 0,
            "perf_metrics": self.perf_metrics,
            "eval_result": self.eval_result[:200] if self.eval_result else "",
            "elapsed_ms": self.elapsed_ms,
            "error": self.error or None,
        }


@dataclass
class SmokeReport:
    """The morning report generated after a smoke run."""

    timestamp: float = 0.0
    total_pois: int = 0
    pois_visited: int = 0
    total_errors_logged: int = 0
    total_screenshots: int = 0
    avg_fps: float = 0.0
    min_fps: float = 0.0
    stops: list[StopResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_pois": self.total_pois,
            "pois_visited": self.pois_visited,
            "total_errors_logged": self.total_errors_logged,
            "total_screenshots": self.total_screenshots,
            "avg_fps": round(self.avg_fps, 1),
            "min_fps": round(self.min_fps, 1),
            "stops": [s.to_dict() for s in self.stops],
            "errors": self.errors,
            "summary": self.summary_text(),
        }

    def summary_text(self) -> str:
        lines = [
            f"Smoke Run — {time.strftime('%Y-%m-%d %H:%M', time.localtime(self.timestamp))}",
            f"  POIs: {self.pois_visited}/{self.total_pois} visited",
            f"  Screenshots: {self.total_screenshots}",
            f"  Errors logged: {self.total_errors_logged}",
            f"  Avg FPS: {self.avg_fps:.1f} (min {self.min_fps:.1f})",
        ]
        if self.errors:
            lines.append(f"  Runner errors: {len(self.errors)}")
            for e in self.errors[:5]:
                lines.append(f"    - {e}")
        return "\n".join(lines)


# ── Smoke Runner orchestrator ───────────────────────────────────


class SmokeRunner:
    """Orchestrates a smoke run through a list of POIs.

    Usage::

        runner = SmokeRunner(
            run_project_fn=executor.run_project,
            stop_project_fn=executor.stop_project,
            game_eval_fn=executor.game_eval,
            take_screenshot_fn=executor.take_screenshot,
            get_logs_fn=executor.read_logs,
            get_perf_fn=executor.get_performance_monitors,
        )
        report = runner.run(pois, output_dir="/tmp/smoke")
    """

    def __init__(
        self,
        *,
        run_project_fn: Callable[[], dict | None] | None = None,
        stop_project_fn: Callable[[], dict | None] | None = None,
        game_eval_fn: Callable[[str], str | None] | None = None,
        take_screenshot_fn: Callable[[], str | None] | None = None,
        get_logs_fn: Callable[[], str | None] | None = None,
        get_perf_fn: Callable[[], dict | None] | None = None,
    ):
        self._run_project = run_project_fn or (lambda: None)
        self._stop_project = stop_project_fn or (lambda: None)
        self._game_eval = game_eval_fn or (lambda e: f"[mock] {e}")
        self._take_screenshot = take_screenshot_fn or (lambda: "/tmp/smoke.png")
        self._get_logs = get_logs_fn or (lambda: "")
        self._get_perf = get_perf_fn or (lambda: {})

    def run(
        self,
        pois: list[POIStop],
        output_dir: str = "/tmp/smoke",
    ) -> SmokeReport:
        """Execute a full smoke run through all POIs.

        Returns a SmokeReport with per-stop data and aggregate stats.
        """
        report = SmokeReport(
            timestamp=time.time(),
            total_pois=len(pois),
        )
        _launched = False

        # 1. Launch the game
        logger.info("smoke_runner", "Launching project")
        start_result = self._run_project()
        if start_result is None:
            report.errors.append("Failed to launch project")
            return report
        _launched = True

        try:
            # 2. Visit each POI
            for poi in pois:
                stop_result = self._visit_poi(poi, output_dir)
                report.stops.append(stop_result)
                if stop_result.error:
                    report.errors.append(f"{poi.name}: {stop_result.error}")

            # 3. Aggregate stats
            fps_values = []
            for s in report.stops:
                if s.screenshot_path:
                    report.total_screenshots += 1
                if s.perf_metrics:
                    fps = s.perf_metrics.get("time/fps", 0)
                    if fps > 0:
                        fps_values.append(fps)
                if s.log_text:
                    # Quick error count — just count lines with "error" or "Error"
                    for line in s.log_text.splitlines():
                        if "error" in line.lower():
                            report.total_errors_logged += 1

            if fps_values:
                report.avg_fps = sum(fps_values) / len(fps_values)
                report.min_fps = min(fps_values)

            report.pois_visited = len([s for s in report.stops if not s.error])

        finally:
            # 4. Stop the game (only if it was launched)
            if _launched:
                logger.info("smoke_runner", "Stopping project")
                try:
                    self._stop_project()
                except Exception:
                    pass

        logger.info("smoke_runner", report.summary_text())
        return report

    def _visit_poi(self, poi: POIStop, output_dir: str) -> StopResult:
        """Visit one POI: teleport, wait, capture."""
        t0 = time.time()
        result = StopResult(poi=poi)

        # Teleport
        eval_result = self._game_eval(poi.teleport_expr)
        if eval_result is not None:
            result.eval_result = str(eval_result)
        else:
            result.error = "Teleport eval failed"

        # Wait for scene to settle
        if poi.wait_seconds > 0:
            time.sleep(poi.wait_seconds)

        # Capture screenshot
        ss = self._take_screenshot()
        if ss:
            result.screenshot_path = str(ss)
        else:
            result.error = result.error or "Screenshot failed"

        # Capture logs
        logs = self._get_logs()
        if logs:
            result.log_text = str(logs)

        # Capture perf
        perf = self._get_perf()
        if perf:
            result.perf_metrics = perf

        result.elapsed_ms = int((time.time() - t0) * 1000)
        logger.info("smoke_runner", f"POI '{poi.name}': {result.elapsed_ms}ms")
        return result


# ── POI builder (convenience) ────────────────────────────────────


def build_poi(name: str, position: dict, wait: float = 2.0, description: str = "") -> POIStop:
    """Create a POI from a named position.

    *position* should be {x, y, z} world coordinates.
    """
    teleport = f"get_tree().get_first_node_in_group('player').global_position = Vector3({position.get('x', 0)}, {position.get('y', 0)}, {position.get('z', 0)})"
    return POIStop(name=name, teleport_expr=teleport, wait_seconds=wait, description=description)


# ── High-level orchestrator ──────────────────────────────────────


def run_smoke_test(
    pois_data: list[dict],
    *,
    output_dir: str = "/tmp/smoke",
    callbacks: dict[str, Callable] | None = None,
) -> dict:
    """Convenience wrapper: run a smoke test from a list of POI dicts.

    *pois_data*: list of {name, position: {x, y, z}, wait_seconds, description}
    *callbacks*: optional dict of callable overrides (for testing)
    """
    cb = callbacks or {}
    pois = [POIStop(
        name=p["name"],
        teleport_expr=p.get("teleport_expr", ""),
        wait_seconds=p.get("wait_seconds", 2.0),
        description=p.get("description", ""),
    ) for p in pois_data]

    runner = SmokeRunner(
        run_project_fn=cb.get("run_project"),
        stop_project_fn=cb.get("stop_project"),
        game_eval_fn=cb.get("game_eval"),
        take_screenshot_fn=cb.get("take_screenshot"),
        get_logs_fn=cb.get("get_logs"),
        get_perf_fn=cb.get("get_perf"),
    )
    report = runner.run(pois, output_dir)
    return report.to_dict()
