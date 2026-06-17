"""Unit tests for configurable LLM prompt templates (WO-023).

Pins the exact prompt bytes for Gemma, ChatML, and raw templates.
All tests are offline — no live llama.cpp required.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Helpers ───────────────────────────────────────────────────


def _make_client(prompt_template="gemma", **kwargs) -> "LlamaClient":
    from devforge.infrastructure.llm.llama_client import LlamaClient

    return LlamaClient(prompt_template=prompt_template, **kwargs)


def _capture_generate_prompt(prompt_template: str, prompt: str) -> str:
    """Monkeypatch requests.post and capture the prompt sent to llama.cpp."""
    import requests

    client = _make_client(prompt_template=prompt_template)

    captured_payloads: list[dict] = []

    def _fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        captured_payloads.append(json or {})
        resp = MagicMock()
        resp.json.return_value = {"content": "ok", "stopped_limit": False}
        resp.raise_for_status = MagicMock()
        return resp

    with patch.object(requests, "post", side_effect=_fake_post):
        client.generate(prompt)

    assert len(captured_payloads) == 1, f"Expected 1 call, got {len(captured_payloads)}"
    return captured_payloads[0]["prompt"]


def _capture_chat_prompt(prompt_template: str, messages: list[dict]) -> str:
    """Monkeypatch requests.post and capture the prompt sent for chat()."""
    import requests

    client = _make_client(prompt_template=prompt_template)

    captured_payloads: list[dict] = []

    def _fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        captured_payloads.append(json or {})
        resp = MagicMock()
        resp.json.return_value = {"content": "ok", "stopped_limit": False}
        resp.raise_for_status = MagicMock()
        return resp

    with patch.object(requests, "post", side_effect=_fake_post):
        client.chat(messages)

    assert len(captured_payloads) == 1, f"Expected 1 call, got {len(captured_payloads)}"
    return captured_payloads[0]["prompt"]


# ── Test 1: gemma generate ────────────────────────────────────


def test_gemma_generate_wire_bytes() -> None:
    """gemma generate(\"hi\") → exact Gemma control tokens."""
    prompt_bytes = _capture_generate_prompt("gemma", "hi")
    assert prompt_bytes == "<start_of_turn>user\nhi<end_of_turn>\n<start_of_turn>model\n"


# ── Test 2: chatml generate ───────────────────────────────────


def test_chatml_generate_wire_bytes() -> None:
    """chatml generate(\"hi\") → exact ChatML control tokens."""
    prompt_bytes = _capture_generate_prompt("chatml", "hi")
    assert prompt_bytes == "<|im_start|>user\nhi<|im_end|>\n<|im_start|>assistant\n"


# ── Test 3: raw generate ──────────────────────────────────────


def test_raw_generate_passthrough() -> None:
    """raw generate(\"hi\") → prompt == \"hi\" (no wrapping)."""
    prompt_bytes = _capture_generate_prompt("raw", "hi")
    assert prompt_bytes == "hi"


# ── Test 4: gemma chat with system ────────────────────────────


def test_gemma_chat_system_folds_into_user() -> None:
    """gemma chat() with system folds [Instructions] into user turn."""
    prompt_bytes = _capture_chat_prompt(
        "gemma",
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ],
    )
    expected = "<start_of_turn>user\n[Instructions]\nYou are helpful.\n\nHello<end_of_turn>\n<start_of_turn>model\n"
    assert prompt_bytes == expected


# ── Test 5: chatml chat with system ───────────────────────────


def test_chatml_chat_system_emits_block() -> None:
    """chatml chat() with system emits system block BEFORE user block."""
    prompt_bytes = _capture_chat_prompt(
        "chatml",
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ],
    )
    expected = (
        "<|im_start|>system\nYou are helpful.<|im_end|>\n<|im_start|>user\nHello<|im_end|>\n<|im_start|>assistant\n"
    )
    assert prompt_bytes == expected


# ── Test 6: unknown template → ValueError ─────────────────────


def test_unknown_template_raises_valueerror() -> None:
    """Unknown prompt_template name raises ValueError listing valid options."""
    from devforge.infrastructure.llm.llama_client import LlamaClient

    try:
        LlamaClient(prompt_template="nonexistent")
        assert False, "Expected ValueError"
    except ValueError as e:
        msg = str(e)
        assert "nonexistent" in msg
        assert "gemma" in msg
        assert "chatml" in msg
        assert "raw" in msg


# ── Test 7: default is gemma ──────────────────────────────────


def test_default_is_gemma() -> None:
    """When nothing configured, prompt_template defaults to gemma."""
    from devforge.infrastructure.llm.llama_client import LlamaClient

    client = LlamaClient()
    assert client.prompt_template == "gemma"

    # Also verify the default produces Gemma-formatted bytes
    prompt_bytes = _capture_generate_prompt("gemma", "test")
    assert prompt_bytes.startswith("<start_of_turn>user\n")


# ── Test 8: RuntimeConfig.validate rejects bad template ───────


def test_config_validate_rejects_bad_template() -> None:
    """RuntimeConfig.validate() rejects llm_prompt_template='qwen'."""
    from devforge.infrastructure.runtime_config import RuntimeConfig

    config = RuntimeConfig(llm_prompt_template="qwen")
    errs = config.validate()
    assert len(errs) >= 1
    assert any("llm_prompt_template" in e for e in errs)
    assert any("qwen" in e for e in errs)
    assert any("gemma" in e for e in errs), "Should list valid options"


# ── Test 9: DEVFORGE_PROMPT_TEMPLATE env round-trip ───────────


def test_env_var_round_trip() -> None:
    """DEVFORGE_PROMPT_TEMPLATE=chatml survives from_env()."""
    from devforge.infrastructure.runtime_config import RuntimeConfig

    with patch.dict(os.environ, {"DEVFORGE_PROMPT_TEMPLATE": "chatml"}, clear=False):
        config = RuntimeConfig.from_env()
        assert config.llm_prompt_template == "chatml"


# ── Test 10: configure_llama passes template to client ────────


def test_configure_llama_passes_template() -> None:
    """configure_llama(prompt_template='chatml') reaches LlamaClient."""
    from devforge.infrastructure.llm.router import LLMRouter

    # Reset singleton so we get a fresh router
    LLMRouter._instance = None
    router = LLMRouter.get()

    router.configure_llama(
        endpoint="http://localhost:9999",
        prompt_template="chatml",
    )

    assert router._backend is not None
    assert router._backend.prompt_template == "chatml"

    # Clean up the singleton
    LLMRouter._instance = None


# ── Test 11: gemma chat without system ────────────────────────


def test_gemma_chat_user_only() -> None:
    """gemma chat() with only user message produces correct format."""
    prompt_bytes = _capture_chat_prompt(
        "gemma",
        [
            {"role": "user", "content": "hi"},
        ],
    )
    expected = "<start_of_turn>user\nhi<end_of_turn>\n<start_of_turn>model\n"
    assert prompt_bytes == expected


# ── Test 12: chatml chat without system ───────────────────────


def test_chatml_chat_user_only() -> None:
    """chatml chat() with only user message — no system block emitted."""
    prompt_bytes = _capture_chat_prompt(
        "chatml",
        [
            {"role": "user", "content": "hi"},
        ],
    )
    expected = "<|im_start|>user\nhi<|im_end|>\n<|im_start|>assistant\n"
    assert prompt_bytes == expected


# ── Test 13: gemma chat system-only folds properly ────────────


def test_gemma_chat_system_only() -> None:
    """gemma chat() with only system message folds into user turn."""
    prompt_bytes = _capture_chat_prompt(
        "gemma",
        [
            {"role": "system", "content": "Be concise."},
        ],
    )
    expected = "<start_of_turn>user\n[Instructions]\nBe concise.\n<end_of_turn>\n<start_of_turn>model\n"
    assert prompt_bytes == expected


# ── Tests: auto-detection of prompt template from model alias ──


def test_detect_gemma_from_alias() -> None:
    """detect_prompt_template returns 'gemma' for gemma aliases."""
    from devforge.infrastructure.runtime_config import detect_prompt_template

    assert detect_prompt_template("gemma-26b") == "gemma"
    assert detect_prompt_template("gemma4") == "gemma"
    assert detect_prompt_template("Gemma-4-12B-QAT") == "gemma"


def test_detect_chatml_from_alias() -> None:
    """detect_prompt_template returns 'chatml' for Qwen/Yi/InternLM aliases."""
    from devforge.infrastructure.runtime_config import detect_prompt_template

    assert detect_prompt_template("Qwen3-14B-Q6_K") == "chatml"
    assert detect_prompt_template("qwen2.5-7b") == "chatml"
    assert detect_prompt_template("yi-34b") == "chatml"
    assert detect_prompt_template("internlm2-20b") == "chatml"
    assert detect_prompt_template("my-chatml-model") == "chatml"


def test_detect_unknown_returns_none() -> None:
    """detect_prompt_template returns None for unknown model aliases."""
    from devforge.infrastructure.runtime_config import detect_prompt_template

    assert detect_prompt_template("llama-3") is None
    assert detect_prompt_template("mistral-7b") is None
    assert detect_prompt_template("") is None


def test_apply_server_limits_auto_sets_template() -> None:
    """apply_server_limits auto-sets llm_prompt_template from model alias."""
    from unittest.mock import MagicMock

    from devforge.infrastructure.llm.llama_client import apply_server_limits
    from devforge.infrastructure.runtime_config import RuntimeConfig

    config = RuntimeConfig(context_token_budget=24000, llama_max_tokens=4096, llm_prompt_template="gemma")
    client = MagicMock()
    client.server_props.return_value = {
        "n_ctx": 32768,
        "total_slots": 1,
        "model_alias": "qwen3-14b",
    }

    with patch.dict(os.environ, {}, clear=True):
        # Remove DEVFORGE_PROMPT_TEMPLATE if set
        os.environ.pop("DEVFORGE_PROMPT_TEMPLATE", None)
        apply_server_limits(config, client)

    assert config.llm_prompt_template == "chatml", (
        f"Expected 'chatml' from qwen3-14b alias, got '{config.llm_prompt_template}'"
    )
    # The live LlamaClient must also be updated, not just the config
    assert client.prompt_template == "chatml", (
        f"LlamaClient.prompt_template should also be updated, got '{client.prompt_template}'"
    )


def test_apply_server_limits_respects_env_override() -> None:
    """apply_server_limits does NOT override explicit DEVFORGE_PROMPT_TEMPLATE."""
    from unittest.mock import MagicMock

    from devforge.infrastructure.llm.llama_client import apply_server_limits
    from devforge.infrastructure.runtime_config import RuntimeConfig

    config = RuntimeConfig(context_token_budget=24000, llama_max_tokens=4096, llm_prompt_template="gemma")
    client = MagicMock()
    client.server_props.return_value = {
        "n_ctx": 32768,
        "total_slots": 1,
        "model_alias": "qwen3-14b",
    }

    # Any non-empty env value blocks the auto-detection override.
    with patch.dict(os.environ, {"DEVFORGE_PROMPT_TEMPLATE": "gemma"}, clear=False):
        apply_server_limits(config, client)

    assert config.llm_prompt_template == "gemma", "Should NOT override when DEVFORGE_PROMPT_TEMPLATE is explicitly set"
    assert not hasattr(client, "prompt_template") or client.prompt_template != "chatml", (
        "Client should also not be overridden when env is set"
    )


def test_apply_server_limits_no_override_when_already_chatml() -> None:
    """apply_server_limits keeps chatml when already set and model matches."""
    from unittest.mock import MagicMock

    from devforge.infrastructure.llm.llama_client import apply_server_limits
    from devforge.infrastructure.runtime_config import RuntimeConfig

    config = RuntimeConfig(context_token_budget=24000, llama_max_tokens=4096, llm_prompt_template="chatml")
    client = MagicMock()
    client.server_props.return_value = {
        "n_ctx": 32768,
        "total_slots": 1,
        "model_alias": "qwen3-14b",
    }

    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("DEVFORGE_PROMPT_TEMPLATE", None)
        apply_server_limits(config, client)

    assert config.llm_prompt_template == "chatml", "Should stay chatml"


# ── GBNF normalization (PEG parser compatibility) ─────────────


def test_normalize_gbnf_joins_continuation_lines():
    """Multi-line alternations must collapse onto the rule line.

    llama.cpp's PEG-based GBNF parser rejects `| alt` continuation
    lines and then generates UNCONSTRAINED (HTTP 200, one server-side
    log line) — measured live June 12, 2026.
    """
    from devforge.infrastructure.llm.llama_client import normalize_gbnf

    src = (
        'system-list ::= ""\n'
        '              | system (ws "," ws system)*\n'
        "\n"
        'entity ::= "a"\n'
        '         | "b"\n'
        '         | "c"\n'
    )
    out = normalize_gbnf(src)
    assert "| " in out  # alternations preserved...
    assert not any(l.strip().startswith("|") for l in out.split("\n")), "no line may start with |"
    assert 'system-list ::= "" | system (ws "," ws system)*' in out
    assert 'entity ::= "a" | "b" | "c"' in out


def test_normalize_gbnf_skips_comments_and_blanks():
    from devforge.infrastructure.llm.llama_client import normalize_gbnf

    src = 'rule ::= "x"\n# a comment between alternatives\n\n       | "y"\n'
    out = normalize_gbnf(src)
    assert 'rule ::= "x" | "y"' in out
    assert "# a comment between alternatives" in out


def test_normalize_gbnf_idempotent_on_single_line():
    from devforge.infrastructure.llm.llama_client import normalize_gbnf

    src = 'root ::= "a" | "b"\nws ::= [ \\t]*'
    assert normalize_gbnf(src) == src


def test_generated_grammar_file_has_no_continuation_lines():
    from devforge.knowledge.scene.godot_node_types import generate_grammar_file
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        path = generate_grammar_file(output_dir=td)
        text = open(path, encoding="utf-8").read()
    offenders = [l for l in text.split("\n") if l.strip().startswith("|")]
    assert not offenders, f"continuation lines survive generation: {offenders[:3]}"


def test_loaded_grammar_is_normalized():
    """LlamaClient must normalize grammar files at load time."""
    import tempfile, os as _os
    from devforge.infrastructure.llm.llama_client import LlamaClient

    with tempfile.NamedTemporaryFile("w", suffix=".gbnf", delete=False) as f:
        f.write('root ::= "a"\n       | "b"\n')
        gpath = f.name
    try:
        client = LlamaClient(grammar_path=gpath)
        assert client.grammar == 'root ::= "a" | "b"'
    finally:
        _os.unlink(gpath)


# ── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_gemma_generate_wire_bytes,
        test_chatml_generate_wire_bytes,
        test_raw_generate_passthrough,
        test_gemma_chat_system_folds_into_user,
        test_chatml_chat_system_emits_block,
        test_unknown_template_raises_valueerror,
        test_default_is_gemma,
        test_config_validate_rejects_bad_template,
        test_env_var_round_trip,
        test_configure_llama_passes_template,
        test_gemma_chat_user_only,
        test_chatml_chat_user_only,
        test_gemma_chat_system_only,
        test_detect_gemma_from_alias,
        test_detect_chatml_from_alias,
        test_detect_unknown_returns_none,
        test_apply_server_limits_auto_sets_template,
        test_apply_server_limits_respects_env_override,
        test_apply_server_limits_no_override_when_already_chatml,
        test_normalize_gbnf_joins_continuation_lines,
        test_normalize_gbnf_skips_comments_and_blanks,
        test_normalize_gbnf_idempotent_on_single_line,
        test_generated_grammar_file_has_no_continuation_lines,
        test_loaded_grammar_is_normalized,
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


class TestDedupOperations:
    """D10: Verify _dedupe_operations can't silently merge distinct ops."""

    def _dedupe(self, ops):
        from devforge.compilation.pipeline.engine import PipelineEngine

        return PipelineEngine._dedupe_operations(ops)

    def test_identical_ops_deduped(self):
        ops = [
            {"type": "add_node", "parent": "/root/Main", "node_type": "Camera3D", "name": "Cam"},
            {"type": "add_node", "parent": "/root/Main", "node_type": "Camera3D", "name": "Cam"},
        ]
        result = self._dedupe(ops)
        assert len(result) == 1, f"Expected 1, got {len(result)}: {result}"

    def test_different_name_not_merged(self):
        ops = [
            {"type": "add_node", "parent": "/root/Main", "node_type": "Camera3D", "name": "CamA"},
            {"type": "add_node", "parent": "/root/Main", "node_type": "Camera3D", "name": "CamB"},
        ]
        result = self._dedupe(ops)
        assert len(result) == 2, f"Expected 2 distinct ops, got {len(result)}"

    def test_different_node_type_not_merged(self):
        ops = [
            {"type": "add_node", "parent": "/root/Main", "node_type": "Camera3D", "name": "X"},
            {"type": "add_node", "parent": "/root/Main", "node_type": "DirectionalLight3D", "name": "X"},
        ]
        result = self._dedupe(ops)
        assert len(result) == 2, f"Expected 2 distinct ops, got {len(result)}"

    def test_different_property_value_not_merged(self):
        ops = [
            {"type": "set_property", "node": "/root/Main/Light", "property": "light_energy", "value": 0.8},
            {"type": "set_property", "node": "/root/Main/Light", "property": "light_energy", "value": 1.5},
        ]
        result = self._dedupe(ops)
        assert len(result) == 2, f"Expected 2 distinct ops, got {len(result)}"

    def test_different_parent_not_merged(self):
        ops = [
            {"type": "add_node", "parent": "/root/Main", "node_type": "MeshInstance3D", "name": "Cube"},
            {"type": "add_node", "parent": "/root/Main/Sub", "node_type": "MeshInstance3D", "name": "Cube"},
        ]
        result = self._dedupe(ops)
        assert len(result) == 2, f"Expected 2 distinct ops, got {len(result)}"


class TestNormalizeGbnfStrongIdempotency:
    """D7: Stronger idempotency test — normalize(normalize(x)) == normalize(x)."""

    def test_idempotent_multi_line_alternation(self):
        from devforge.infrastructure.llm.llama_client import normalize_gbnf

        src = 'root ::= "a"\n | "b"\n | "c"\n\nws ::= [ \\t\\n]*'
        once = normalize_gbnf(src)
        twice = normalize_gbnf(once)
        assert once == twice, f"Not idempotent:\nonce: {once!r}\ntwice: {twice!r}"
        assert "|" not in once.split("\n")[1], f"Continuation line not joined: {once}"

    def test_idempotent_complex_grammar(self):
        from devforge.infrastructure.llm.llama_client import normalize_gbnf

        src = 'root ::= object\nobject ::= "{" ws pair (ws "," ws pair)* ws "}"\npair ::= string ws ":" ws value\nstring ::= "\\"" char* "\\""\nchar ::= [^"\\\\]\n | "\\\\" escape\nescape ::= ["\\\\/bfnrt]\nvalue ::= string\n | number\n | object\n | array\n | "true" | "false" | "null"\nws ::= [ \\t\\n]*'
        once = normalize_gbnf(src)
        twice = normalize_gbnf(once)
        assert once == twice, f"Complex grammar not idempotent"
        # Verify no standalone | lines remain
        for line in once.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                assert not stripped.startswith("|"), f"Standalone | still present: {line!r}"

    def test_already_normalized_unchanged(self):
        from devforge.infrastructure.llm.llama_client import normalize_gbnf

        src = 'root ::= "a" | "b" | "c"'
        assert normalize_gbnf(src) == src
        assert normalize_gbnf(normalize_gbnf(src)) == src
