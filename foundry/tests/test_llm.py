"""Tests for FoundryLLM's grammar handling at the wire boundary.

The grammar argument is overloaded in a way that caused a silent, high-impact
bug: passing ``grammar=None`` falls back to the DEFAULT asset-spec GBNF, so a
caller that meant "no grammar, answer freely" (multi-NPC quest generation)
instead forced every model into the asset {asset_id, generator, params} schema.
The multi-NPC dialogue then collapsed to canned fallbacks for ALL models.

These tests pin the contract so the footgun can't silently reappear.
"""

from __future__ import annotations

from unittest.mock import patch

from llm import FoundryLLM


class _FakeResp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"content": "ok"}


def _capture_payload(grammar_arg):
    """Call FoundryLLM with *grammar_arg* and return the POSTed JSON payload."""
    llm = FoundryLLM()
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResp()

    with patch("llm.requests.post", side_effect=fake_post):
        llm("a prompt", grammar_arg)
    return captured["payload"]


def test_grammar_none_falls_back_to_default_asset_grammar():
    """grammar=None → the default asset-spec grammar IS sent (documented footgun)."""
    payload = _capture_payload(None)
    assert "grammar" in payload
    assert payload["grammar"]  # non-empty asset GBNF


def test_grammar_empty_string_sends_no_grammar():
    """grammar='' → NO grammar key in the payload; the model answers freely.

    This is the contract multi-NPC quest generation relies on.
    """
    payload = _capture_payload("")
    assert "grammar" not in payload


def test_grammar_explicit_is_used():
    """A non-empty grammar string is forwarded (normalized) on the wire."""
    payload = _capture_payload('root ::= "x"')
    assert "grammar" in payload
    assert payload["grammar"]
