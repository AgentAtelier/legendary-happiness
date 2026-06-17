"""Tests for forge_env — the shared stack.env parser/serializer."""

import textwrap
from pathlib import Path
import tempfile

from forge_env import read_env, write_env, plan_env, validate_env, _unquote, _quote_style


class TestUnquote:
    def test_double_quoted(self):
        assert _unquote('"hello"') == "hello"

    def test_single_quoted(self):
        assert _unquote("'hello'") == "hello"

    def test_unquoted(self):
        assert _unquote("hello") == "hello"

    def test_single_quoted_json(self):
        # This is the exact value from the real stack.env:
        # LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'
        assert _unquote("""'{"enable_thinking": false}'""") == '{"enable_thinking": false}'

    def test_double_quoted_containing_single(self):
        assert _unquote('"it\'s fine"') == "it's fine"

    def test_empty_string(self):
        assert _unquote("") == ""

    def test_whitespace_around_quotes(self):
        assert _unquote('  "hello"  ') == "hello"

    def test_single_char_quoted(self):
        assert _unquote('"a"') == "a"


class TestQuoteStyle:
    def test_double(self):
        assert _quote_style('"hello"') == '"'

    def test_single(self):
        assert _quote_style("'hello'") == "'"

    def test_none(self):
        assert _quote_style("hello") is None

    def test_single_char(self):
        assert _quote_style('"') is None


class TestReadEnv:
    def test_basic(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text("FOO=bar\nBAZ=qux\n")
        try:
            env = read_env(tmp)
            assert env == {"FOO": "bar", "BAZ": "qux"}
        finally:
            tmp.unlink()

    def test_single_quoted_value(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text("""LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'\n""")
        try:
            env = read_env(tmp)
            assert env["LLAMA_ARG_CHAT_TEMPLATE_KWARGS"] == '{"enable_thinking": false}'
        finally:
            tmp.unlink()

    def test_double_quoted_value(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text('LLAMA_ARGS="--host 0.0.0.0 --n-predict 4096"\n')
        try:
            env = read_env(tmp)
            assert env["LLAMA_ARGS"] == "--host 0.0.0.0 --n-predict 4096"
        finally:
            tmp.unlink()

    def test_comments_ignored(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text("# this is a comment\nFOO=bar\n# another comment\nBAZ=qux\n")
        try:
            env = read_env(tmp)
            assert env == {"FOO": "bar", "BAZ": "qux"}
        finally:
            tmp.unlink()

    def test_blank_lines_ignored(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text("\n\nFOO=bar\n\nBAZ=qux\n\n")
        try:
            env = read_env(tmp)
            assert env == {"FOO": "bar", "BAZ": "qux"}
        finally:
            tmp.unlink()

    def test_value_contains_equals(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text("GREETING=hello=world\n")
        try:
            env = read_env(tmp)
            assert env["GREETING"] == "hello=world"
        finally:
            tmp.unlink()

    def test_missing_file(self):
        env = read_env(Path("/tmp/does_not_exist_9238472.env"))
        assert env == {}

    def test_round_trip_double_quoted(self):
        """A double-quoted value should round-trip byte-identically."""
        tmp = Path(tempfile.mktemp(suffix=".env"))
        original = 'LLAMA_ARGS="--host 0.0.0.0 --n-predict 4096"\n'
        tmp.write_text(original)
        try:
            env = read_env(tmp)
            write_env(tmp, {"LLAMA_ARGS": env["LLAMA_ARGS"]})
            result = tmp.read_text()
            assert result == original
        finally:
            tmp.unlink()

    def test_round_trip_single_quoted_json(self):
        """A single-quoted JSON value should round-trip byte-identically."""
        tmp = Path(tempfile.mktemp(suffix=".env"))
        original = """LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'\n"""
        tmp.write_text(original)
        try:
            env = read_env(tmp)
            write_env(tmp, {"LLAMA_ARG_CHAT_TEMPLATE_KWARGS": env["LLAMA_ARG_CHAT_TEMPLATE_KWARGS"]})
            result = tmp.read_text()
            assert result == original
        finally:
            tmp.unlink()

    def test_multi_line_preserves_comments(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        original = "# top comment\nFOO=bar\n# mid comment\nBAZ=qux\n"
        tmp.write_text(original)
        try:
            env = read_env(tmp)
            write_env(tmp, {"FOO": "newval"})
            result = tmp.read_text()
            assert "FOO=newval" in result
            assert "# top comment" in result
            assert "# mid comment" in result
            assert "BAZ=qux" in result
        finally:
            tmp.unlink()

    def test_new_key_appended(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text("FOO=bar\n")
        try:
            write_env(tmp, {"NEWKEY": "newval"})
            result = tmp.read_text()
            assert "FOO=bar" in result
            assert "NEWKEY=newval" in result
        finally:
            tmp.unlink()


class TestWriteEnv:
    def test_update_existing_preserves_other_keys(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text("FOO=bar\nBAZ=qux\n")
        try:
            write_env(tmp, {"FOO": "updated"})
            result = read_env(tmp)
            assert result == {"FOO": "updated", "BAZ": "qux"}
        finally:
            tmp.unlink()


class TestPlanEnv:
    def test_no_changes(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text("FOO=bar\n")
        try:
            plan = plan_env(tmp, {"FOO": "bar"})
            assert plan["changes"] == {}
            assert plan["new_keys"] == []
        finally:
            tmp.unlink()

    def test_change_detected(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text("FOO=bar\n")
        try:
            plan = plan_env(tmp, {"FOO": "baz"})
            assert plan["changes"] == {"FOO": {"old": "bar", "new": "baz"}}
        finally:
            tmp.unlink()

    def test_new_key_detected(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        tmp.write_text("FOO=bar\n")
        try:
            plan = plan_env(tmp, {"NEWKEY": "newval"})
            assert plan["new_keys"] == ["NEWKEY"]
            assert plan["changes"] == {}
        finally:
            tmp.unlink()

    def test_plan_is_read_only(self):
        tmp = Path(tempfile.mktemp(suffix=".env"))
        original = "FOO=bar\n"
        tmp.write_text(original)
        try:
            plan = plan_env(tmp, {"FOO": "baz"})
            assert plan["changes"] == {"FOO": {"old": "bar", "new": "baz"}}
            # File must be unchanged
            assert tmp.read_text() == original
        finally:
            tmp.unlink()


class TestValidateEnv:
    """Phase 6: schema validation tests."""

    def test_valid_config_passes(self):
        text = """LLAMA_BIN=/usr/bin/llama-server
MODEL=/home/mrg/models/test.gguf
MODEL_ALIAS=test
LLAMA_PORT=8002
LLAMA_BASE_ARGS=--host 0.0.0.0 --n-predict 4096
LLAMA_ARGS="--host 0.0.0.0 --n-predict 4096 --ctx-size 16384"
GODOT_BIN=/usr/bin/godot
GAME_PROJECT=/home/mrg/dev/games/rpg
DEVFORGE_DIR=/home/mrg/dev/games/Forge
MCP_PORT=8001
DEVFORGE_PROMPT_TEMPLATE=gemma
ODYSSEUS_DIR=/home/mrg/dev/ai/odysseus
ODYSSEUS_URL=http://127.0.0.1:7000
GODOT_AI_PORT=8000
"""
        errors = validate_env(text)
        assert errors == []

    def test_missing_required_key(self):
        text = "LLAMA_BIN=/usr/bin/llama-server\nMODEL=test.gguf\n"
        errors = validate_env(text)
        assert len(errors) > 0
        assert any("missing required key" in e for e in errors)

    def test_missing_safety_cap(self):
        text = """LLAMA_BIN=/usr/bin/llama-server
MODEL=/home/mrg/models/test.gguf
MODEL_ALIAS=test
LLAMA_PORT=8002
LLAMA_BASE_ARGS=--host 0.0.0.0
LLAMA_ARGS="--host 0.0.0.0 --ctx-size 16384"
GODOT_BIN=/usr/bin/godot
GAME_PROJECT=/home/mrg/dev/games/rpg
DEVFORGE_DIR=/home/mrg/dev/games/Forge
MCP_PORT=8001
DEVFORGE_PROMPT_TEMPLATE=gemma
ODYSSEUS_DIR=/home/mrg/dev/ai/odysseus
ODYSSEUS_URL=http://127.0.0.1:7000
GODOT_AI_PORT=8000
"""
        errors = validate_env(text)
        assert any("--n-predict" in e for e in errors)

    def test_invalid_port(self):
        text = """LLAMA_BIN=/usr/bin/llama-server
MODEL=/home/mrg/models/test.gguf
MODEL_ALIAS=test
LLAMA_PORT=abc
LLAMA_BASE_ARGS=--host 0.0.0.0 --n-predict 4096
LLAMA_ARGS="--host 0.0.0.0 --n-predict 4096 --ctx-size 16384"
GODOT_BIN=/usr/bin/godot
GAME_PROJECT=/home/mrg/dev/games/rpg
DEVFORGE_DIR=/home/mrg/dev/games/Forge
MCP_PORT=8001
DEVFORGE_PROMPT_TEMPLATE=gemma
ODYSSEUS_DIR=/home/mrg/dev/ai/odysseus
ODYSSEUS_URL=http://127.0.0.1:7000
GODOT_AI_PORT=8000
"""
        errors = validate_env(text)
        assert any("LLAMA_PORT" in e for e in errors)

    def test_empty_values(self):
        text = """LLAMA_BIN=
MODEL=/home/mrg/models/test.gguf
MODEL_ALIAS=test
LLAMA_PORT=8002
LLAMA_BASE_ARGS=--host 0.0.0.0 --n-predict 4096
LLAMA_ARGS="--host 0.0.0.0 --n-predict 4096 --ctx-size 16384"
GODOT_BIN=/usr/bin/godot
GAME_PROJECT=/home/mrg/dev/games/rpg
DEVFORGE_DIR=/home/mrg/dev/games/Forge
MCP_PORT=8001
DEVFORGE_PROMPT_TEMPLATE=gemma
ODYSSEUS_DIR=/home/mrg/dev/ai/odysseus
ODYSSEUS_URL=http://127.0.0.1:7000
GODOT_AI_PORT=8000
"""
        errors = validate_env(text)
        assert any("LLAMA_BIN" in e and "empty" in e for e in errors)
