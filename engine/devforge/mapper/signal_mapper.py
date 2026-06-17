"""Signal/Dependency Mapper — scan GDScript files for signals, connections, and emissions.

Deterministic core (tier 0): no LLM calls. Answers questions like:
- "What breaks if I rename this signal?"
- "Who emits 'died' and who listens for it?"
- "Show me all orphaned signals (no emitters, no listeners)."

Uses godot-ai's search_filesystem to find .gd files, then parses them
locally with regex for precision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from devforge.infrastructure.logger import logger


# ── Data model ───────────────────────────────────────────────────


@dataclass
class SignalDecl:
    """A signal declaration in a GDScript file."""

    name: str               # "died"
    params: list[str] = field(default_factory=list)  # ["old_health", "new_health"]
    file_path: str = ""     # "res://scripts/player.gd"
    line: int = 0
    class_name: str = ""    # "Player" (from class_name or extends)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "name": self.name,
            "file_path": self.file_path,
            "line": self.line,
        }
        if self.params:
            d["params"] = self.params
        if self.class_name:
            d["class_name"] = self.class_name
        return d


@dataclass
class SignalConnection:
    """A .connect() or signal.connect() call in a GDScript file."""

    signal_name: str        # "died"
    source_expr: str        # "player" (the node reference before .connect)
    target_method: str      # "_on_player_died"
    file_path: str = ""
    line: int = 0
    is_direct: bool = True  # True = signal.connect(), False = .connect("name")

    def to_dict(self) -> dict:
        return {
            "signal_name": self.signal_name,
            "source_expr": self.source_expr,
            "target_method": self.target_method,
            "file_path": self.file_path,
            "line": self.line,
        }


@dataclass
class SignalEmit:
    """A signal.emit() call in a GDScript file."""

    signal_name: str        # "died"
    file_path: str = ""
    line: int = 0
    is_emitting: bool = True

    def to_dict(self) -> dict:
        return {
            "signal_name": self.signal_name,
            "file_path": self.file_path,
            "line": self.line,
        }


# ── GDScript signal parser ──────────────────────────────────────


class SignalMapper:
    """Parses GDScript files to extract signal declarations, connections, and emissions.

    Usage::

        mapper = SignalMapper()
        mapper.scan_file("res://scripts/player.gd", source_code)
        graph = mapper.build_graph()
        impact = graph.impact_of_rename("died")
    """

    # Signal declaration: signal died  OR  signal health_changed(old_health, new_health)
    _SIGNAL_DECL_RE = re.compile(
        r"^\s*signal\s+(\w+)\s*(?:\(([^)]*)\))?",
        re.MULTILINE,
    )

    # Direct connect: node.signal_name.connect(method)
    # Matches: player.died.connect(_on_player_died)
    #          $HUD.score_changed.connect(_update_score)
    #          get_node("/root/Main/Enemy").health_changed.connect(_debug_health)
    #          find_child("SubNode").signal_name.connect(_handler)
    _DIRECT_CONNECT_RE = re.compile(
        r"(\$?\w+(?:\.\w+)*(?:\([^)]*\))?)\.(\w+)\.connect\(\s*(\w+)\s*\)",
    )

    # String connect: .connect("signal_name", ...)
    # Matches: node.connect("died", Callable(self, "_on_died"))
    _STRING_CONNECT_RE = re.compile(
        r"(\$?\w+(?:\.\w+)*)\.connect\(\s*\"(\w+)\"\s*,",
    )

    # Signal emit: signal_name.emit(args)
    # Matches: died.emit()  or  health_changed.emit(old, new)
    _EMIT_RE = re.compile(
        r"(\w+)\.emit\(",
    )

    # class_name declaration for context
    _CLASS_NAME_RE = re.compile(
        r"^\s*class_name\s+(\w+)",
        re.MULTILINE,
    )

    def __init__(self):
        self._decls: list[SignalDecl] = []
        self._conns: list[SignalConnection] = []
        self._emits: list[SignalEmit] = []

    def scan_file(self, file_path: str, source: str) -> None:
        """Parse one GDScript file and accumulate results."""
        # Extract class_name for context
        class_name = ""
        cm = self._CLASS_NAME_RE.search(source)
        if cm:
            class_name = cm.group(1)

        # Signal declarations
        for m in self._SIGNAL_DECL_RE.finditer(source):
            name = m.group(1)
            raw_params = m.group(2) or ""
            params: list[str] = []
            if raw_params:
                params = [p.strip().split(":")[0].strip()
                          for p in raw_params.split(",") if p.strip()]
            line = _line_number(source, m.start())
            self._decls.append(SignalDecl(
                name=name, params=params,
                file_path=file_path, line=line,
                class_name=class_name,
            ))

        # Direct connections: node.signal.connect(method)
        for m in self._DIRECT_CONNECT_RE.finditer(source):
            self._conns.append(SignalConnection(
                source_expr=m.group(1),
                signal_name=m.group(2),
                target_method=m.group(3),
                file_path=file_path,
                line=_line_number(source, m.start()),
                is_direct=True,
            ))

        # String connections: node.connect("signal_name", ...)
        for m in self._STRING_CONNECT_RE.finditer(source):
            self._conns.append(SignalConnection(
                source_expr=m.group(1),
                signal_name=m.group(2),
                target_method="<string_connect>",
                file_path=file_path,
                line=_line_number(source, m.start()),
                is_direct=False,
            ))

        # Signal emissions
        for m in self._EMIT_RE.finditer(source):
            name = m.group(1)
            # Skip built-in signals (tree_, visibility_, etc.) — still record them
            line = _line_number(source, m.start())
            self._emits.append(SignalEmit(
                signal_name=name,
                file_path=file_path,
                line=line,
            ))

    def build_graph(self) -> DependencyGraph:
        """Build a dependency graph from accumulated scans."""
        return DependencyGraph(
            signals={d.name: d for d in self._decls},
            connections=list(self._conns),
            emits=list(self._emits),
        )

    def clear(self) -> None:
        """Reset all accumulated data."""
        self._decls.clear()
        self._conns.clear()
        self._emits.clear()


def _line_number(source: str, char_pos: int) -> int:
    """Convert 0-indexed character position to 1-indexed line number."""
    return source[:char_pos].count("\n") + 1


# ── Dependency graph ─────────────────────────────────────────────


@dataclass
class DependencyGraph:
    """A graph of signal declarations, connections, and emissions."""

    signals: dict[str, SignalDecl] = field(default_factory=dict)
    connections: list[SignalConnection] = field(default_factory=list)
    emits: list[SignalEmit] = field(default_factory=list)

    def signal_names(self) -> list[str]:
        """All unique signal names in the graph."""
        names: set[str] = set(self.signals.keys())
        for c in self.connections:
            names.add(c.signal_name)
        for e in self.emits:
            names.add(e.signal_name)
        return sorted(names)

    def impact_of_rename(self, signal_name: str) -> dict:
        """What breaks if we rename *signal_name*?

        Returns all declarations, connections, and emissions that
        reference this signal — everything that must be updated.
        """
        decl = self.signals.get(signal_name)
        affected_conns = [c for c in self.connections if c.signal_name == signal_name]
        affected_emits = [e for e in self.emits if e.signal_name == signal_name]

        files_touched: set[str] = set()
        for c in affected_conns:
            files_touched.add(c.file_path)
        for e in affected_emits:
            files_touched.add(e.file_path)
        if decl:
            files_touched.add(decl.file_path)

        return {
            "signal_name": signal_name,
            "declared": decl is not None,
            "declaration": decl.to_dict() if decl else None,
            "connection_count": len(affected_conns),
            "connections": [c.to_dict() for c in affected_conns],
            "emit_count": len(affected_emits),
            "emits": [e.to_dict() for e in affected_emits],
            "total_affected": len(affected_conns) + len(affected_emits),
            "files_touched": sorted(files_touched),
            "hint": (
                f"Renaming '{signal_name}' requires updating "
                f"{len(affected_conns)} connection(s) and "
                f"{len(affected_emits)} emit(s) across "
                f"{len(files_touched)} file(s)."
            ),
        }

    def who_listens_to(self, signal_name: str) -> list[dict]:
        """All connection points listening to *signal_name*."""
        return [c.to_dict() for c in self.connections if c.signal_name == signal_name]

    def who_emits(self, signal_name: str) -> list[dict]:
        """All emission points for *signal_name*."""
        return [e.to_dict() for e in self.emits if e.signal_name == signal_name]

    def orphaned_signals(self) -> list[dict]:
        """Signals with no emitters OR no listeners."""
        emitted = {e.signal_name for e in self.emits}
        listened = {c.signal_name for c in self.connections}
        orphaned: list[dict] = []
        for name, decl in self.signals.items():
            issues: list[str] = []
            if name not in emitted:
                issues.append("never emitted")
            if name not in listened:
                issues.append("no listeners")
            if issues:
                orphaned.append({
                    "signal_name": name,
                    "file_path": decl.file_path,
                    "line": decl.line,
                    "issues": issues,
                })
        return orphaned

    def summary(self) -> dict:
        """High-level summary of the dependency graph."""
        return {
            "signal_count": len(self.signals),
            "connection_count": len(self.connections),
            "emit_count": len(self.emits),
            "orphaned_signal_count": len(self.orphaned_signals()),
            "signals": sorted(self.signals.keys()),
        }

    def to_dict(self) -> dict:
        return {
            "signal_count": len(self.signals),
            "connection_count": len(self.connections),
            "emit_count": len(self.emits),
            "signals": [d.to_dict() for d in self.signals.values()],
            "connections": [c.to_dict() for c in self.connections],
            "emits": [e.to_dict() for e in self.emits],
            "orphaned": self.orphaned_signals(),
        }


# ── High-level orchestrator ──────────────────────────────────────


def map_signals(
    files: dict[str, str],
) -> dict:
    """Scan multiple GDScript files and build a full dependency graph.

    *files* maps file_path → source_code.
    """
    mapper = SignalMapper()
    for file_path, source in files.items():
        mapper.scan_file(file_path, source)
    graph = mapper.build_graph()
    return graph.to_dict()


def map_signals_from_search(
    query: str,
    search_filesystem_fn: Callable[..., dict | None],
    file_reader_fn: Callable[[str], str | None],
    search_path: str = "res://",
) -> dict:
    """Search the project for signal-related patterns, scan found files.

    1. Uses *search_filesystem_fn* to find .gd files containing the query
    2. Uses *file_reader_fn* to read each file's source
    3. Builds and returns the dependency graph + individual impact analyses

    This integrates with godot-ai's search_filesystem for the file
    discovery layer, then does precision parsing locally.
    """
    mapper = SignalMapper()
    seen_paths: set[str] = set()

    # Search for files containing signal-related patterns
    patterns = [query, "signal ", ".connect(", ".emit("]
    for pattern in patterns:
        result = search_filesystem_fn(pattern, search_path, True)
        if not result:
            continue
        for f in result.get("files", []):
            path = f.get("path", "") if isinstance(f, dict) else str(f)
            if path in seen_paths or not path.endswith(".gd"):
                continue
            seen_paths.add(path)

    # Read and parse each found file
    for path in sorted(seen_paths):
        source = file_reader_fn(path)
        if source is None:
            logger.warn("signal_mapper", f"Could not read '{path}' — skipping")
            continue
        mapper.scan_file(path, source)

    graph = mapper.build_graph()
    graph_dict = graph.to_dict()

    # Add per-signal impact analysis for the query
    impact = graph.impact_of_rename(query) if query in graph.signals else None

    logger.info(
        "signal_mapper",
        f"Mapped {graph_dict['signal_count']} signals, "
        f"{graph_dict['connection_count']} connections, "
        f"{graph_dict['emit_count']} emits",
    )

    result: dict[str, Any] = {
        **graph_dict,
        "query": query,
    }
    if impact:
        result["impact"] = impact
    result["orphaned"] = graph.orphaned_signals()

    return result
