from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


class EventLogger:
    def __init__(self, repo_root: Path | str):
        self.repo_root = Path(repo_root)
        self.events: list[dict[str, Any]] = []
        self.run_id = str(uuid.uuid4())
        self.counter = 0

    def log(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        event = {
            "id": self.counter,
            "run_id": self.run_id,
            "timestamp": time.time(),
            "type": event_type,
            "data": data or {},
        }
        self.events.append(event)
        self.counter += 1

    def save(self) -> Path:
        events_dir = self.repo_root / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        file_path = events_dir / f"run_{self.run_id}.json"
        file_path.write_text(json.dumps(self.events, indent=2))
        return file_path
