"""Unified plan cache with optional world-state-aware invalidation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from devforge.core.execution_plan import ExecutionPlan


def _serialize(obj: Any) -> str:
    """Convert non-JSON objects (UUID, datetime) to strings."""
    return str(obj)


class PlanCache:
    """Cache execution plans by goal string or structured key data."""

    def __init__(self, repo_root: Path | str):
        self.repo_root = Path(repo_root)
        self.cache_dir = self.repo_root / "planner_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _hash_key(self, key_data: str | dict[str, Any]) -> str:
        if isinstance(key_data, str):
            raw = key_data
        else:
            raw = json.dumps(key_data, sort_keys=True, default=_serialize)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _compute_world_state_hash(self) -> str:
        state_data: list[str] = []

        game_dir = self.repo_root / "game"
        if game_dir.exists():
            for gd_file in sorted(game_dir.rglob("*.gd")):
                rel_path = str(gd_file.relative_to(self.repo_root))
                mtime = gd_file.stat().st_mtime
                state_data.append(f"{rel_path}:{mtime}")

        specs_dir = self.repo_root / "specs"
        if specs_dir.exists():
            for spec_file in sorted(specs_dir.rglob("*.yaml")):
                rel_path = str(spec_file.relative_to(self.repo_root))
                mtime = spec_file.stat().st_mtime
                state_data.append(f"{rel_path}:{mtime}")

        return hashlib.sha256("".join(state_data).encode()).hexdigest()

    def get(self, key: str | dict[str, Any]) -> ExecutionPlan | None:
        lookup: str | dict[str, Any]
        if isinstance(key, dict):
            lookup = dict(key)
            lookup["world_state_hash"] = self._compute_world_state_hash()
        else:
            lookup = key

        cache_key = self._hash_key(lookup)
        cache_file = self.cache_dir / f"{cache_key}.json"
        if not cache_file.exists():
            return None

        data = json.loads(cache_file.read_text())
        return ExecutionPlan.model_validate(data)

    def set(self, key: str | dict[str, Any], plan: ExecutionPlan) -> None:
        lookup: str | dict[str, Any]
        if isinstance(key, dict):
            lookup = dict(key)
            lookup["world_state_hash"] = self._compute_world_state_hash()
        else:
            lookup = key

        cache_key = self._hash_key(lookup)
        cache_file = self.cache_dir / f"{cache_key}.json"
        data = plan.model_dump(mode="json")
        cache_file.write_text(json.dumps(data, indent=2, default=_serialize))

    def clear(self) -> None:
        if self.cache_dir.exists():
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
