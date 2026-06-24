"""Unit tests for foundry.visual.vlm (V Task 2) — VLM mocked.

All VLM calls are mocked (requests.post replaced with canned responses).
The VLM itself is never unit-tested — it's the judge.
"""

from __future__ import annotations

import base64
import json

import pytest
import requests
from visual.vlm import (
    PROP_DEFAULTS,
    PROP_SCHEMA,
    SCENE_DEFAULTS,
    SCENE_SCHEMA,
    _build_payload,
    _coerce,
    _encode_png,
    _extract_content,
    _extract_json_from_text,
    _parse_response,
    _pick_defaults,
    check_image,
)

# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def fake_png(tmp_path):
    """Create a minimal 1x1 red PNG for base64 encoding tests."""
    # Minimal valid PNG (1x1 red pixel)
    png = tmp_path / "test.png"
    # 1x1 red PNG, 67 bytes
    minimal_png = (
        b'\x89PNG\r\n\x1a\n'
        b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
        b'\x00\x00\x00\x10IDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x01\x01\x00\x05\x18\xd8N.'
        b'\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    png.write_bytes(minimal_png)
    return str(png)


def _fake_post_factory(response_json, status=200):
    """Return a requests.post mock that returns *response_json*."""

    class FakeResponse:
        def __init__(self):
            self.status_code = status
            self._json = response_json

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception(f"HTTP {self.status_code}")

        def json(self):
            return self._json

    def fake_post(url, json=None, timeout=None):
        return FakeResponse()

    return fake_post


# ── _encode_png ───────────────────────────────────────────────────

def test_encode_png_returns_base64(fake_png):
    b64 = _encode_png(fake_png)
    assert isinstance(b64, str)
    # Decode back and verify it's a PNG
    decoded = base64.b64decode(b64)
    assert decoded[:4] == b'\x89PNG'


def test_encode_png_no_data_uri_prefix(fake_png):
    b64 = _encode_png(fake_png)
    assert not b64.startswith("data:")


# ── _build_payload ────────────────────────────────────────────────

def _user_content(payload):
    """Extract the user message content parts from a chat payload."""
    return payload["messages"][0]["content"]


def test_build_payload_has_image_url():
    payload = _build_payload(
        "Describe this prop.",
        "ZmFrZQ==",
        PROP_SCHEMA,
        temperature=0.1,
        max_tokens=256,
    )
    parts = _user_content(payload)
    img = next(p for p in parts if p["type"] == "image_url")
    assert img["image_url"]["url"] == "data:image/png;base64,ZmFrZQ=="


def test_build_payload_has_json_schema_response_format():
    payload = _build_payload(
        "Check for floaters.",
        "ZmFrZQ==",
        SCENE_SCHEMA,
        temperature=0.1,
        max_tokens=256,
    )
    rf = payload["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["schema"] == SCENE_SCHEMA


def test_build_payload_prompt_in_text_part():
    payload = _build_payload(
        "Is this textured?",
        "ZmFrZQ==",
        PROP_SCHEMA,
        temperature=0.1,
        max_tokens=256,
    )
    parts = _user_content(payload)
    text = next(p for p in parts if p["type"] == "text")
    assert text["text"] == "Is this textured?"


def test_build_payload_empty_prompt():
    payload = _build_payload(
        "",
        "ZmFrZQ==",
        PROP_SCHEMA,
        temperature=0.1,
        max_tokens=256,
    )
    parts = _user_content(payload)
    text = next(p for p in parts if p["type"] == "text")
    # Empty prompt → a sensible default instruction, never empty
    assert text["text"]


def test_build_payload_includes_temperature_and_max_tokens():
    payload = _build_payload(
        "test", "ZmFrZQ==", PROP_SCHEMA,
        temperature=0.7, max_tokens=128,
    )
    assert payload["temperature"] == 0.7
    assert payload["max_tokens"] == 128


# ── _pick_defaults ────────────────────────────────────────────────

def test_pick_defaults_prop_schema():
    defaults = _pick_defaults(PROP_SCHEMA)
    assert defaults["textured"] is True
    assert "floater" not in defaults


def test_pick_defaults_scene_schema():
    defaults = _pick_defaults(SCENE_SCHEMA)
    assert defaults["floater"] is False
    assert "textured" not in defaults


def test_pick_defaults_unknown_schema():
    schema = {
        "type": "object",
        "properties": {
            "score": {"type": "number"},
            "label": {"type": "string"},
            "ok": {"type": "boolean"},
        },
        "required": ["score", "label", "ok"],
    }
    defaults = _pick_defaults(schema)
    assert defaults["score"] == 0
    assert defaults["label"] == ""
    assert defaults["ok"] is False


# ── _coerce ───────────────────────────────────────────────────────

def test_coerce_boolean_true_strings():
    assert _coerce("true", "boolean") is True
    assert _coerce("TRUE", "boolean") is True
    assert _coerce("yes", "boolean") is True
    assert _coerce("1", "boolean") is True


def test_coerce_boolean_false_strings():
    assert _coerce("false", "boolean") is False
    assert _coerce("no", "boolean") is False
    assert _coerce("", "boolean") is False


def test_coerce_boolean_python_bool():
    assert _coerce(True, "boolean") is True
    assert _coerce(False, "boolean") is False


def test_coerce_boolean_non_bool_truthy():
    assert _coerce(1, "boolean") is True
    # Unknown strings default to False (only "true"/"1"/"yes" are True)
    assert _coerce("anything-else", "boolean") is False


def test_coerce_string():
    assert _coerce("hello", "string") == "hello"
    assert _coerce(42, "string") == "42"
    assert _coerce(None, "string") == ""


def test_coerce_number():
    assert _coerce(3.14, "number") == 3.14
    assert _coerce("2.5", "number") == 2.5
    assert _coerce(None, "number") == 0.0


def test_coerce_integer():
    assert _coerce(42, "integer") == 42
    assert _coerce("99", "integer") == 99
    assert _coerce(None, "integer") == 0


# ── _extract_json_from_text ───────────────────────────────────────

def test_extract_json_code_fence():
    text = 'Here is analysis:\n```json\n{"textured": true, "notes": "ok"}\n```\nEnd.'
    result = _extract_json_from_text(text)
    assert result == {"textured": True, "notes": "ok"}


def test_extract_json_bare_object():
    text = '{"floater": false, "notes": "clean"}'
    result = _extract_json_from_text(text)
    assert result == {"floater": False, "notes": "clean"}


def test_extract_json_no_json():
    result = _extract_json_from_text("no json here")
    assert result is None


def test_extract_json_invalid():
    result = _extract_json_from_text("{not valid json}")
    assert result is None


def test_extract_json_multiline_object():
    text = """```json
{
    "textured": true,
    "material_reads_right": false,
    "has_holes_or_deformity": false,
    "floating_bits": false,
    "notes": "Looks good overall"
}
```"""
    result = _extract_json_from_text(text)
    assert result is not None
    assert result["textured"] is True
    assert result["material_reads_right"] is False


# ── _parse_response ───────────────────────────────────────────────

def test_parse_valid_json():
    result = _parse_response(
        '{"textured": true, "material_reads_right": true, "has_holes_or_deformity": false, "floating_bits": false, "notes": "clean"}',
        PROP_DEFAULTS,
        PROP_SCHEMA,
    )
    assert result["textured"] is True
    assert result["material_reads_right"] is True
    assert result["has_holes_or_deformity"] is False
    assert result["floating_bits"] is False
    assert result["notes"] == "clean"


def test_parse_malformed_json_returns_defaults():
    result = _parse_response(
        "not json at all",
        PROP_DEFAULTS,
        PROP_SCHEMA,
    )
    assert result["textured"] is True  # from defaults
    assert result.get("_parse_error") is True


def test_parse_empty_response():
    result = _parse_response("", PROP_DEFAULTS, PROP_SCHEMA)
    assert result.get("_parse_error") is True


def test_parse_missing_keys_filled_from_defaults():
    """Keys missing from LLM response are filled from defaults."""
    result = _parse_response(
        '{"textured": false, "notes": "rough"}',
        PROP_DEFAULTS,
        PROP_SCHEMA,
    )
    assert result["textured"] is False  # from LLM
    assert result["material_reads_right"] is True  # from defaults
    assert result["has_holes_or_deformity"] is False  # from defaults
    assert result["floating_bits"] is False  # from defaults
    assert result["notes"] == "rough"


def test_parse_extra_keys_stripped():
    """Extra keys not in schema are not included in result."""
    result = _parse_response(
        '{"textured": true, "material_reads_right": true, "has_holes_or_deformity": false, "floating_bits": false, "notes": "ok", "extra_field": "should be removed"}',
        PROP_DEFAULTS,
        PROP_SCHEMA,
    )
    assert "extra_field" not in result


def test_parse_scene_schema():
    result = _parse_response(
        '{"floater": false, "clipping": true, "ceiling_visible": true, "npcs_on_floor": true, "composition_ok": false, "theme_coherent": true, "notes": "clipping on left wall"}',
        SCENE_DEFAULTS,
        SCENE_SCHEMA,
    )
    assert result["floater"] is False
    assert result["clipping"] is True
    assert result["ceiling_visible"] is True
    assert result["composition_ok"] is False
    assert result["notes"] == "clipping on left wall"


# ── _extract_content ──────────────────────────────────────────────

def test_extract_content_chat_shape():
    """Reads choices[0].message.content from a chat/completions response."""
    data = {"choices": [{"message": {"content": '{"textured": true}'}}]}
    assert _extract_content(data) == '{"textured": true}'


def test_extract_content_legacy_fallback():
    """Falls back to a top-level content field when no choices present."""
    assert _extract_content({"content": "hello"}) == "hello"


def test_extract_content_empty_when_missing():
    assert _extract_content({}) == ""


def test_check_image_reads_chat_response(fake_png, monkeypatch):
    """check_image parses the real chat/completions response shape."""
    response = {
        "choices": [
            {"message": {"content": json.dumps({
                "textured": False,
                "material_reads_right": False,
                "has_holes_or_deformity": False,
                "floating_bits": False,
                "notes": "blank",
            })}}
        ]
    }
    monkeypatch.setattr(
        "visual.vlm.requests.post",
        _fake_post_factory(response),
    )
    result = check_image(fake_png, PROP_SCHEMA, "Inspect.")
    assert result["textured"] is False
    assert result["notes"] == "blank"
    assert "_parse_error" not in result


# ── check_image (VLM mocked) ──────────────────────────────────────

def test_check_image_valid_prop(fake_png, monkeypatch):
    """Valid VLM response → parsed dict without error flag."""
    response = {
        "content": json.dumps({
            "textured": True,
            "material_reads_right": True,
            "has_holes_or_deformity": False,
            "floating_bits": True,
            "notes": "small floater above the shelf",
        }),
    }
    monkeypatch.setattr(
        "visual.vlm.requests.post",
        _fake_post_factory(response),
    )
    result = check_image(fake_png, PROP_SCHEMA, "Describe this prop.")
    assert result["textured"] is True
    assert result["floating_bits"] is True
    assert result["notes"] == "small floater above the shelf"
    assert "_parse_error" not in result


def test_check_image_valid_scene(fake_png, monkeypatch):
    """Valid VLM scene check response."""
    response = {
        "content": json.dumps({
            "floater": False,
            "clipping": False,
            "ceiling_visible": True,
            "npcs_on_floor": True,
            "composition_ok": True,
            "theme_coherent": False,
            "notes": "carpet doesn't match the stone walls",
        }),
    }
    monkeypatch.setattr(
        "visual.vlm.requests.post",
        _fake_post_factory(response),
    )
    result = check_image(fake_png, SCENE_SCHEMA, "Review this scene.")
    assert result["floater"] is False
    assert result["theme_coherent"] is False
    assert "carpet" in result["notes"]
    assert "_parse_error" not in result


def test_check_image_malformed_json(fake_png, monkeypatch):
    """Malformed VLM response → safe defaults + _parse_error flag."""
    response = {"content": "not valid json at all"}
    monkeypatch.setattr(
        "visual.vlm.requests.post",
        _fake_post_factory(response),
    )
    result = check_image(fake_png, PROP_SCHEMA)
    assert result["_parse_error"] is True
    assert result["textured"] is True  # from PROP_DEFAULTS
    assert result["material_reads_right"] is True


def test_check_image_connection_error(fake_png, monkeypatch):
    """ConnectionError → safe defaults + _parse_error flag."""
    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("Connection refused")

    monkeypatch.setattr(
        "visual.vlm.requests.post",
        raise_connection_error,
    )
    result = check_image(fake_png, SCENE_SCHEMA)
    assert result["_parse_error"] is True
    assert result["floater"] is False  # from SCENE_DEFAULTS


def test_check_image_http_500(fake_png, monkeypatch):
    """HTTP 500 → safe defaults + _parse_error flag."""
    monkeypatch.setattr(
        "visual.vlm.requests.post",
        _fake_post_factory({}, status=500),
    )
    result = check_image(fake_png, PROP_SCHEMA)
    assert result["_parse_error"] is True


def test_check_image_json_in_code_fence(fake_png, monkeypatch):
    """VLM wraps JSON in ```json ... ``` → still parsed."""
    response = {
        "content": """```json
{
    "textured": false,
    "material_reads_right": false,
    "has_holes_or_deformity": true,
    "floating_bits": false,
    "notes": "missing texture on the legs"
}
```""",
    }
    monkeypatch.setattr(
        "visual.vlm.requests.post",
        _fake_post_factory(response),
    )
    result = check_image(fake_png, PROP_SCHEMA)
    assert "_parse_error" not in result
    assert result["textured"] is False
    assert result["has_holes_or_deformity"] is True
    assert "missing texture" in result["notes"]


def test_check_image_auto_selects_defaults(fake_png, monkeypatch):
    """When defaults=None, check_image picks the right one from schema."""
    response = {
        "content": json.dumps({
            "floater": True,
            "clipping": False,
            "ceiling_visible": True,
            "npcs_on_floor": True,
            "composition_ok": True,
            "theme_coherent": True,
            "notes": "",
        }),
    }
    monkeypatch.setattr(
        "visual.vlm.requests.post",
        _fake_post_factory(response),
    )
    # Don't pass defaults — should auto-select SCENE_DEFAULTS
    result = check_image(fake_png, SCENE_SCHEMA, defaults=None)
    assert result["floater"] is True
    assert "_parse_error" not in result


def test_check_image_empty_content(fake_png, monkeypatch):
    """Empty content from VLM → safe defaults + _parse_error."""
    response = {"content": ""}
    monkeypatch.setattr(
        "visual.vlm.requests.post",
        _fake_post_factory(response),
    )
    result = check_image(fake_png, PROP_SCHEMA)
    assert result["_parse_error"] is True


def test_check_image_custom_defaults(fake_png, monkeypatch):
    """Custom defaults arg is used instead of auto-selected."""
    custom = {
        "textured": False,
        "material_reads_right": False,
        "has_holes_or_deformity": True,
        "floating_bits": True,
        "notes": "custom fallback",
    }
    response = {"content": "unparseable"}
    monkeypatch.setattr(
        "visual.vlm.requests.post",
        _fake_post_factory(response),
    )
    result = check_image(fake_png, PROP_SCHEMA, defaults=custom)
    assert result["_parse_error"] is True
    assert result["textured"] is False  # from custom
    assert result["notes"] == "custom fallback"


def test_check_image_coerces_wrong_types(fake_png, monkeypatch):
    """String 'true' for boolean is coerced to True."""
    response = {
        "content": json.dumps({
            "textured": "true",  # string, not bool
            "material_reads_right": 1,  # int, not bool
            "has_holes_or_deformity": "no",
            "floating_bits": False,
            "notes": 123,  # int, not string
        }),
    }
    monkeypatch.setattr(
        "visual.vlm.requests.post",
        _fake_post_factory(response),
    )
    result = check_image(fake_png, PROP_SCHEMA)
    assert result["textured"] is True
    assert result["material_reads_right"] is True
    assert result["has_holes_or_deformity"] is False
    assert result["notes"] == "123"
