from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StepTelemetry:
    step_id: str
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    apply_time: float = 0.0
    validation_time: float = 0.0
    files_created: list[str] = field(default_factory=list)
    files_deleted: list[str] = field(default_factory=list)
    success: bool = False
    error: str | None = None

    def finish(self) -> None:
        self.end_time = time.time()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TelemetryCollector:
    def __init__(self):
        self.steps: list[StepTelemetry] = []

    def record(self, telemetry: StepTelemetry) -> None:
        self.steps.append(telemetry)

    def summary(self) -> dict[str, int]:
        success = sum(1 for step in self.steps if step.success)
        return {
            "total_steps": len(self.steps),
            "successful_steps": success,
            "failed_steps": len(self.steps) - success,
        }

    def export(self, repo_root: Path | str) -> Path:
        path = Path(repo_root) / "runs"
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / f"telemetry_{int(time.time() * 1000)}.json"
        payload = {
            "summary": self.summary(),
            "steps": [step.to_dict() for step in self.steps],
        }
        file_path.write_text(json.dumps(payload, indent=2))
        return file_path
