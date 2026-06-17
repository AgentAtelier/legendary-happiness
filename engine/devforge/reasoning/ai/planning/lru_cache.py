"""
LRU Plan Cache — in-memory world-state-aware cache for architecture plans.

Phase 10: Provides fast in-memory caching with world-state-aware keys
(scene hash + graph hash + prompt hash) and LRU eviction.  Tracks
hit/miss rates for telemetry reporting.

Phase 4: Prompt normalization (collapses casing/whitespace/punctuation),
structural-only scene hashing (ignores volatile transforms), and disk
persistence (.devforge/lru_cache.json) so cache survives restarts.

Usage:
    from devforge.reasoning.ai.planning.lru_cache import LRUPlanCache

    cache = LRUPlanCache(max_entries=100, disk_path=".devforge/lru_cache.json")
    plan = cache.get(prompt, scene, graph)
    if plan is None:
        plan = llm_plan(...)
        cache.set(prompt, scene, graph, plan)
"""

from __future__ import annotations

import atexit
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from devforge.infrastructure.logger import logger


def _hash_dict(data: dict) -> str:
    """Stable hash of a serializable dict."""
    return hashlib.md5(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]


def normalize_prompt(prompt: str) -> str:
    """Normalize a prompt for cache-key purposes.

    Lowercase, collapse whitespace, strip trailing punctuation.
    "Add a player." and "  add   a player  " → same key.
    """
    return re.sub(r"\s+", " ", prompt.strip().lower()).rstrip(".!?")


def _scene_structural_hash(scene: Dict[str, Any]) -> str:
    """Hash only the structural projection of a scene tree.

    Extracts (name, type, parent_path) tuples sorted, ignoring
    volatile fields like transforms and runtime positions.
    """
    items: list[tuple[str, str, str]] = []

    def walk(node: Dict[str, Any], parent_path: str = ""):
        name = str(node.get("name", ""))
        ntype = str(node.get("type", "Node"))
        path = f"{parent_path}/{name}" if parent_path else name
        items.append((name, ntype, path))
        for child in node.get("children", []):
            walk(child, path)

    walk(scene)
    items.sort()
    return hashlib.md5(
        json.dumps(items, sort_keys=True).encode()
    ).hexdigest()[:12]


class LRUPlanCache:
    """In-memory LRU cache for architecture plans with disk persistence.

    Cache key = normalized_prompt_hash + structural_scene_hash + graph_hash
    so that semantically identical prompts hit regardless of casing/whitespace
    and scene-transform changes don't invalidate the cache.
    """

    # Debounce window: mutations within this many seconds of the last
    # disk write are batched into the next write (or the atexit flush).
    SAVE_INTERVAL_S: float = 5.0

    def __init__(self, max_entries: int = 100, disk_path: Optional[str] = None):
        self._entries: Dict[str, dict] = {}       # key → plan
        self._timestamps: Dict[str, float] = {}   # key → last_access_time
        self._max_entries = max_entries
        self._hits: int = 0
        self._misses: int = 0
        self._disk_path = Path(disk_path) if disk_path else None
        self._warmed: bool = False
        self._dirty: bool = False
        self._last_save_mono: float = 0.0

        self._load()
        if self._disk_path:
            # A crash can lose at most SAVE_INTERVAL_S of cache entries —
            # acceptable for a local plan cache; clean exits flush here.
            atexit.register(self.flush)

    # ------------------------------------------------------------------
    # Cache warming (Phase 6: N3 — pre-populate with pattern deltas)
    # ------------------------------------------------------------------

    def warm_from_patterns(
        self,
        patterns_dir: Optional[str] = None,
    ) -> int:
        """Pre-populate the cache with architecture deltas from pattern files.

        Inserts entries using a prompt-only prefix key so they match any
        scene/graph combination at lookup time (two-tier: exact match →
        prompt-only fallback).

        Returns:
            Number of entries inserted.
        """
        if self._warmed:
            return 0

        import json as _json
        from pathlib import Path as _Path

        if patterns_dir is None:
            patterns_dir = str(_Path(__file__).resolve().parents[3] / "patterns")

        patterns_path = _Path(patterns_dir)
        if not patterns_path.is_dir():
            logger.warn("lru_cache", f"Patterns directory not found: {patterns_dir}")
            return 0

        count = 0
        for pat_file in sorted(patterns_path.glob("*.json")):
            try:
                data = _json.loads(pat_file.read_text())
            except Exception:
                continue

            delta = data.get("delta")
            triggers = data.get("triggers", [])
            if not delta or not triggers:
                continue

            for trigger in triggers:
                prompt_prefix = hashlib.md5(
                    normalize_prompt(trigger).encode()
                ).hexdigest()[:8]
                # Warm key: prompt-hash only — matches any scene/graph
                # via the two-tier lookup in get()
                key = f"{prompt_prefix}:*:*"
                if key not in self._entries:
                    self._entries[key] = delta
                    self._timestamps[key] = time.time()
                    count += 1

        self._warmed = True
        if count > 0:
            logger.info(
                "lru_cache",
                f"Cache warmed with {count} pattern entries from {patterns_dir}",
            )
            self._mark_dirty()

        return count

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(
        self,
        prompt: str,
        scene: Dict[str, Any],
        graph: Any,
    ) -> Optional[Dict[str, Any]]:
        """Look up a cached plan.  Returns None on miss.

        Two-tier lookup: first try exact match (prompt+scene+graph),
        then fall back to prompt-only match (from cache warming).
        """
        key = self._make_key(prompt, scene, graph)
        if key in self._entries:
            self._timestamps[key] = time.time()
            self._hits += 1
            return self._entries[key]

        # Tier 2: prompt-only fallback (wildcard scene/graph from warming)
        prompt_prefix = hashlib.md5(
            normalize_prompt(prompt).encode()
        ).hexdigest()[:8]
        wildcard_key = f"{prompt_prefix}:*:*"
        if wildcard_key in self._entries:
            self._timestamps[wildcard_key] = time.time()
            self._hits += 1
            return self._entries[wildcard_key]

        self._misses += 1
        return None

    def set(
        self,
        prompt: str,
        scene: Dict[str, Any],
        graph: Any,
        plan: Dict[str, Any],
    ) -> None:
        """Cache a plan, evicting the least-recently-used entry if full."""
        key = self._make_key(prompt, scene, graph)

        if key in self._entries:
            self._entries[key] = plan
            self._timestamps[key] = time.time()
            self._mark_dirty()
            return

        # Evict LRU if full
        if len(self._entries) >= self._max_entries:
            oldest_key = min(self._timestamps, key=lambda k: self._timestamps[k])
            del self._entries[oldest_key]
            del self._timestamps[oldest_key]

        self._entries[key] = plan
        self._timestamps[key] = time.time()
        self._mark_dirty()

    def clear(self) -> None:
        """Clear all cached entries (written to disk immediately)."""
        self._entries.clear()
        self._timestamps.clear()
        self._hits = 0
        self._misses = 0
        self._dirty = True
        self.flush()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0.0–1.0)."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def stats(self) -> Dict[str, Any]:
        return {
            "entries": self.entry_count,
            "max_entries": self._max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self.hit_rate, 3),
        }

    # ------------------------------------------------------------------
    # Disk persistence
    # ------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        """Record a mutation; write through only outside the debounce window."""
        self._dirty = True
        if time.monotonic() - self._last_save_mono >= self.SAVE_INTERVAL_S:
            self.flush()

    def flush(self) -> None:
        """Write pending changes to disk now (no-op when clean)."""
        if not self._dirty:
            return
        self._save()
        self._dirty = False
        self._last_save_mono = time.monotonic()

    def _load(self) -> None:
        if not self._disk_path or not self._disk_path.exists():
            return
        try:
            data = json.loads(self._disk_path.read_text())
            self._entries = data.get("entries", {})
            self._timestamps = data.get("timestamps", {})
            self._hits = data.get("hits", 0)
            self._misses = data.get("misses", 0)
            logger.info(
                "lru_cache",
                f"Loaded {len(self._entries)} entries from disk",
            )
        except Exception as exc:
            logger.warn("lru_cache", f"Failed to load cache from disk: {exc}")

    def _save(self) -> None:
        if not self._disk_path:
            return
        try:
            self._disk_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "entries": self._entries,
                "timestamps": self._timestamps,
                "hits": self._hits,
                "misses": self._misses,
            }
            self._disk_path.write_text(json.dumps(data))
        except Exception as exc:
            logger.warn("lru_cache", f"Failed to save cache to disk: {exc}")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _make_key(
        self,
        prompt: str,
        scene: Dict[str, Any],
        graph: Any,
    ) -> str:
        """Generate a cache key from normalized prompt + structural scene + graph."""
        prompt_hash = hashlib.md5(
            normalize_prompt(prompt).encode()
        ).hexdigest()[:8]
        scene_hash = _scene_structural_hash(scene) if scene else "000000000000"
        graph_hash = (
            _hash_dict(graph.to_dict())
            if graph and hasattr(graph, "to_dict")
            else "000000000000"
        )
        return f"{prompt_hash}:{scene_hash}:{graph_hash}"
