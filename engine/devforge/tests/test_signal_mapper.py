"""Unit tests for Signal/Dependency Mapper: GDScript parser, graph building, impact analysis.

Tests: signal declarations, direct/string connections, emissions, impact_of_rename,
who_listens_to, who_emits, orphaned signals, map_signals orchestrator.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Signal declarations ──────────────────────────────────────────

_SIMPLE_SCRIPT = """extends Node

signal died
signal health_changed
signal score_changed(new_score)

func _ready():
    pass
"""


def test_parse_signal_declarations() -> None:
    """Single file with 3 signal declarations is parsed correctly."""
    from devforge.mapper.signal_mapper import SignalMapper

    mapper = SignalMapper()
    mapper.scan_file("res://scripts/player.gd", _SIMPLE_SCRIPT)

    graph = mapper.build_graph()
    assert len(graph.signals) == 3
    assert "died" in graph.signals
    assert "health_changed" in graph.signals
    assert "score_changed" in graph.signals

    # Check param parsing
    score = graph.signals["score_changed"]
    assert score.params == ["new_score"]
    assert score.file_path == "res://scripts/player.gd"
    assert score.line == 5


def test_parse_signal_with_multiple_params() -> None:
    """Signal with multiple params is parsed correctly."""
    from devforge.mapper.signal_mapper import SignalMapper

    source = "extends Node\n\nsignal inventory_changed(item_id, count, source)\n"
    mapper = SignalMapper()
    mapper.scan_file("res://scripts/inv.gd", source)

    graph = mapper.build_graph()
    assert "inventory_changed" in graph.signals
    decl = graph.signals["inventory_changed"]
    assert decl.params == ["item_id", "count", "source"]


def test_parse_class_name_context() -> None:
    """class_name declaration is captured for context."""
    from devforge.mapper.signal_mapper import SignalMapper

    source = "class_name Player\nextends CharacterBody3D\n\nsignal took_damage\n"
    mapper = SignalMapper()
    mapper.scan_file("res://scripts/player.gd", source)

    graph = mapper.build_graph()
    assert graph.signals["took_damage"].class_name == "Player"


# ── Connections ──────────────────────────────────────────────────

_CONNECT_SCRIPT = """extends Node

func _ready():
    player.died.connect(_on_player_died)
    $HUD.score_changed.connect(_update_score)
"""


def test_parse_direct_connections() -> None:
    """Direct .signal.connect() calls are parsed."""
    from devforge.mapper.signal_mapper import SignalMapper

    mapper = SignalMapper()
    mapper.scan_file("res://scripts/ui.gd", _CONNECT_SCRIPT)

    graph = mapper.build_graph()
    assert len(graph.connections) == 2

    conns_by_signal = {c.signal_name: c for c in graph.connections}
    assert "died" in conns_by_signal
    assert conns_by_signal["died"].source_expr == "player"
    assert conns_by_signal["died"].target_method == "_on_player_died"
    assert conns_by_signal["died"].is_direct is True

    assert "score_changed" in conns_by_signal
    assert conns_by_signal["score_changed"].source_expr == "$HUD"


def test_parse_string_connections() -> None:
    """String-based .connect("signal_name", ...) calls are parsed."""
    from devforge.mapper.signal_mapper import SignalMapper

    source = 'extends Node\n\nfunc _ready():\n\tnode.connect("died", Callable(self, "_on_died"))\n'
    mapper = SignalMapper()
    mapper.scan_file("res://scripts/handler.gd", source)

    graph = mapper.build_graph()
    assert len(graph.connections) == 1
    conn = graph.connections[0]
    assert conn.signal_name == "died"
    assert conn.is_direct is False
    assert conn.source_expr == "node"


def test_connections_across_files() -> None:
    """Connections from multiple files accumulate correctly."""
    from devforge.mapper.signal_mapper import SignalMapper

    mapper = SignalMapper()
    mapper.scan_file("res://a.gd", 'extends Node\n\nfunc _ready():\n\tplayer.died.connect(_on_died)\n')
    mapper.scan_file("res://b.gd", 'extends Node\n\nfunc _ready():\n\tboss.died.connect(_on_boss_died)\n')

    graph = mapper.build_graph()
    died_conns = [c for c in graph.connections if c.signal_name == "died"]
    assert len(died_conns) == 2
    files = {c.file_path for c in died_conns}
    assert files == {"res://a.gd", "res://b.gd"}


# ── Emissions ────────────────────────────────────────────────────

_EMIT_SCRIPT = """extends Node

func take_damage(amount):
    hp -= amount
    if hp <= 0:
        died.emit()
    health_changed.emit(hp, max_hp)
"""


def test_parse_emits() -> None:
    """signal.emit() calls are parsed."""
    from devforge.mapper.signal_mapper import SignalMapper

    mapper = SignalMapper()
    mapper.scan_file("res://scripts/enemy.gd", _EMIT_SCRIPT)

    graph = mapper.build_graph()
    emitted_names = {e.signal_name for e in graph.emits}
    assert "died" in emitted_names
    assert "health_changed" in emitted_names


# ── Impact analysis ──────────────────────────────────────────────

_COMBINED_SCRIPT = """extends Node

signal died
signal health_changed

func _ready():
    $Player.died.connect(_on_player_died)

func take_damage():
    died.emit()
    health_changed.emit()
"""


def test_impact_of_rename() -> None:
    """Impact analysis shows all affected references."""
    from devforge.mapper.signal_mapper import SignalMapper

    mapper = SignalMapper()
    mapper.scan_file("res://scripts/game.gd", _COMBINED_SCRIPT)

    graph = mapper.build_graph()
    impact = graph.impact_of_rename("died")

    assert impact["declared"] is True
    assert impact["declaration"] is not None
    assert impact["declaration"]["name"] == "died"
    assert impact["connection_count"] == 1
    assert impact["emit_count"] == 1
    assert impact["total_affected"] == 2
    assert "res://scripts/game.gd" in impact["files_touched"]


def test_impact_of_unreferenced_signal() -> None:
    """Impact analysis for a non-existent signal shows empty results."""
    from devforge.mapper.signal_mapper import SignalMapper

    mapper = SignalMapper()
    mapper.scan_file("res://scripts/game.gd", _COMBINED_SCRIPT)

    graph = mapper.build_graph()
    impact = graph.impact_of_rename("nonexistent")

    assert impact["declared"] is False
    assert impact["declaration"] is None
    assert impact["connection_count"] == 0
    assert impact["emit_count"] == 0
    assert impact["total_affected"] == 0


def test_who_listens_to() -> None:
    """who_listens_to returns all connection points."""
    from devforge.mapper.signal_mapper import SignalMapper

    mapper = SignalMapper()
    mapper.scan_file("res://a.gd", "extends Node\n\nfunc _ready():\n\tplayer.died.connect(_a)\n\tboss.died.connect(_b)\n")

    graph = mapper.build_graph()
    listeners = graph.who_listens_to("died")
    assert len(listeners) == 2
    methods = {l["target_method"] for l in listeners}
    assert methods == {"_a", "_b"}


def test_who_emits() -> None:
    """who_emits returns all emission points."""
    from devforge.mapper.signal_mapper import SignalMapper

    mapper = SignalMapper()
    mapper.scan_file("res://a.gd", "extends Node\nsignal died\n\nfunc _process():\n\tdied.emit()\n")

    graph = mapper.build_graph()
    emitters = graph.who_emits("died")
    assert len(emitters) == 1
    assert emitters[0]["file_path"] == "res://a.gd"


# ── Orphaned signals ─────────────────────────────────────────────

def test_orphaned_signals_detected() -> None:
    """Signals with no emitters and no listeners are flagged as orphaned."""
    from devforge.mapper.signal_mapper import SignalMapper

    mapper = SignalMapper()
    # Declare 3 signals, but only connect and emit "died"
    mapper.scan_file("res://orphan.gd", """extends Node

signal died
signal unused_signal
signal never_connected

func _ready():
    player.died.connect(_on_died)

func _process():
    died.emit()
""")

    graph = mapper.build_graph()
    orphaned = graph.orphaned_signals()
    orphaned_names = {o["signal_name"] for o in orphaned}
    assert "unused_signal" in orphaned_names
    assert "never_connected" in orphaned_names
    assert "died" not in orphaned_names  # has emitter and listener


# ── map_signals orchestrator ─────────────────────────────────────

def test_map_signals_multiple_files() -> None:
    """map_signals orchestrates scanning multiple files."""
    from devforge.mapper.signal_mapper import map_signals

    files = {
        "res://player.gd": "extends Node\n\nsignal died\n\nfunc _process():\n\tdied.emit()\n",
        "res://ui.gd": "extends Node\n\nfunc _ready():\n\tplayer.died.connect(_update_ui)\n",
    }
    result = map_signals(files)

    assert result["signal_count"] == 1
    assert result["connection_count"] == 1
    assert result["emit_count"] == 1
    assert len(result["orphaned"]) == 0


def test_map_signals_empty_files() -> None:
    """Empty file list returns an empty graph."""
    from devforge.mapper.signal_mapper import map_signals

    result = map_signals({})
    assert result["signal_count"] == 0
    assert result["connection_count"] == 0
    assert result["emit_count"] == 0


def test_line_numbers_accurate() -> None:
    """Signal declarations report correct line numbers."""
    from devforge.mapper.signal_mapper import SignalMapper

    source = """extends Node

# comment
signal died

signal health_changed
"""

    mapper = SignalMapper()
    mapper.scan_file("res://test.gd", source)
    graph = mapper.build_graph()

    assert graph.signals["died"].line == 4
    assert graph.signals["health_changed"].line == 6


# ── Main ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_parse_signal_declarations,
        test_parse_signal_with_multiple_params,
        test_parse_class_name_context,
        test_parse_direct_connections,
        test_parse_string_connections,
        test_connections_across_files,
        test_parse_emits,
        test_impact_of_rename,
        test_impact_of_unreferenced_signal,
        test_who_listens_to,
        test_who_emits,
        test_orphaned_signals_detected,
        test_map_signals_multiple_files,
        test_map_signals_empty_files,
        test_line_numbers_accurate,
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
