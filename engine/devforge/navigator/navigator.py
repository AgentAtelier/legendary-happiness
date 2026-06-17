"""Project Navigator — search the project for scripts, symbols, and signals.

Deterministic core (tier 0): no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from devforge.infrastructure.logger import logger


@dataclass
class SearchHit:
    """A single search result from a project-wide query."""

    source: str          # "filesystem" | "symbol" | "filename"
    path: str            # res:// path to the file
    line: int = 0
    snippet: str = ""
    symbol_type: str = ""  # "function", "signal", "class", "export_var"

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "source": self.source,
            "path": self.path,
        }
        if self.line:
            d["line"] = self.line
        if self.snippet:
            d["snippet"] = self.snippet
        if self.symbol_type:
            d["symbol_type"] = self.symbol_type
        return d


class ProjectNavigator:
    """Searches a Godot project using godot-ai tools.

    Usage::

        nav = ProjectNavigator(executor)
        results = nav.search("falling damage")
    """

    def __init__(
        self,
        find_symbols_fn: Callable[[str], dict | None],
        search_filesystem_fn: Callable[..., dict | None],
    ):
        self._find_symbols = find_symbols_fn
        self._search_filesystem = search_filesystem_fn

    def search(self, query: str, search_path: str = "res://") -> dict:
        """Search the project for *query* across filesystem, filenames, and symbols.

        Returns:
            {
              "query": "falling damage",
              "hit_count": 8,
              "hits": [...SearchHit dicts...],
              "by_source": {"filesystem": 5, "symbol": 2, "filename": 1},
            }
        """
        hits: list[SearchHit] = []

        # 1. Filesystem content search
        fs_result = self._search_filesystem(query, search_path, True)
        if fs_result:
            files = fs_result.get("files", [])
            for f in files:
                if isinstance(f, str):
                    hits.append(SearchHit(source="filesystem", path=f))
                elif isinstance(f, dict):
                    hits.append(SearchHit(
                        source="filesystem",
                        path=f.get("path", ""),
                        line=f.get("line", 0),
                        snippet=f.get("snippet", ""),
                    ))

        # 2. Symbol search across files found in step 1
        seen_paths: set[str] = set()
        for hit in list(hits):
            path = hit.path
            if path in seen_paths or not path.endswith(".gd"):
                continue
            seen_paths.add(path)
            sym_result = self._find_symbols(path)
            if not sym_result:
                continue
            # Search function names, signal names, class names
            qlower = query.lower()
            for func in sym_result.get("functions", []):
                name = func.get("name", "") if isinstance(func, dict) else str(func)
                if qlower in name.lower():
                    hits.append(SearchHit(
                        source="symbol", path=path,
                        snippet=name, symbol_type="function",
                    ))
            for sig in sym_result.get("signals", []):
                name = sig.get("name", "") if isinstance(sig, dict) else str(sig)
                if qlower in name.lower():
                    hits.append(SearchHit(
                        source="symbol", path=path,
                        snippet=name, symbol_type="signal",
                    ))
            class_name = sym_result.get("class_name", "")
            if qlower in class_name.lower():
                hits.append(SearchHit(
                    source="symbol", path=path,
                    snippet=class_name, symbol_type="class",
                ))

        # Deduplicate by (source, path, snippet)
        deduped: list[SearchHit] = []
        seen: set[tuple[str, str, str]] = set()
        for h in hits:
            key = (h.source, h.path, h.snippet)
            if key not in seen:
                seen.add(key)
                deduped.append(h)

        by_source: dict[str, int] = {}
        for h in deduped:
            by_source[h.source] = by_source.get(h.source, 0) + 1

        logger.info(
            "navigator",
            f"Search '{query}': {len(deduped)} hits "
            f"(filesystem={by_source.get('filesystem', 0)}, "
            f"symbol={by_source.get('symbol', 0)})",
        )

        return {
            "query": query,
            "hit_count": len(deduped),
            "hits": [h.to_dict() for h in deduped],
            "by_source": by_source,
        }


def search_project(
    query: str,
    find_symbols_fn: Callable[[str], dict | None],
    search_filesystem_fn: Callable[..., dict | None],
    include_signals: bool = False,
) -> dict:
    """Convenience wrapper: create a ProjectNavigator and search.

    Set *include_signals* to True to also return signal dependency info
    from any .gd files found in the search.
    """
    nav = ProjectNavigator(find_symbols_fn, search_filesystem_fn)
    result = nav.search(query)

    if include_signals and result["hit_count"] > 0:
        seen_paths: set[str] = set()
        for hit in result["hits"]:
            path = hit.get("path", "")
            if path in seen_paths or not path.endswith(".gd"):
                continue
            seen_paths.add(path)

        if seen_paths:
            result["signal_files_found"] = sorted(seen_paths)
            result["hint"] = (
                "Found .gd files that may contain signals. "
                "Use signal_map with the 'source' parameter to "
                "analyze these files for signal dependencies."
            )

    return result
