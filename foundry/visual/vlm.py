"""V Task 2: Qwen3-VL structured visual checks via llama.cpp multimodal API.

Sends a PNG image + prompt + json_schema to the llama.cpp OpenAI-compatible
``/v1/chat/completions`` endpoint, parses the structured response, and returns
a typed dict.  Malformed responses fall back to safe defaults with a
``_parse_error`` flag.

NOTE: images MUST go through ``/v1/chat/completions`` with an ``image_url``
content part.  Modern llama.cpp (libmtmd, build ≥ b9500) ignores the legacy
``/completion`` + ``image_data`` array — the model never sees the pixels and
hallucinates from text priors.  This was the bug that made every prop read
"good condition" regardless of the actual render (incl. blank frames).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional

import requests


# ── Schemas (json_schema structures for llama.cpp) ───────────────

PROP_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "textured": {"type": "boolean"},
        "material_reads_right": {"type": "boolean"},
        "has_holes_or_deformity": {"type": "boolean"},
        "floating_bits": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "required": [
        "textured",
        "material_reads_right",
        "has_holes_or_deformity",
        "floating_bits",
        "notes",
    ],
    "additionalProperties": False,
}

SCENE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "floater": {"type": "boolean"},
        "clipping": {"type": "boolean"},
        "ceiling_visible": {"type": "boolean"},
        "npcs_on_floor": {"type": "boolean"},
        "composition_ok": {"type": "boolean"},
        "theme_coherent": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "required": [
        "floater",
        "clipping",
        "ceiling_visible",
        "npcs_on_floor",
        "composition_ok",
        "theme_coherent",
        "notes",
    ],
    "additionalProperties": False,
}


# ── Safe fallback defaults (returned on parse / connection errors) ─

PROP_DEFAULTS: Dict[str, Any] = {
    "textured": True,
    "material_reads_right": True,
    "has_holes_or_deformity": False,
    "floating_bits": False,
    "notes": "",
}

SCENE_DEFAULTS: Dict[str, Any] = {
    "floater": False,
    "clipping": False,
    "ceiling_visible": True,
    "npcs_on_floor": True,
    "composition_ok": True,
    "theme_coherent": True,
    "notes": "",
}


# ── Public API ───────────────────────────────────────────────────

def check_image(
    png_path: str,
    schema: Dict[str, Any],
    prompt: str = "",
    *,
    endpoint: str = "http://127.0.0.1:8002",
    temperature: float = 0.1,
    max_tokens: int = 256,
    timeout_s: int = 60,
    seed: Optional[int] = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run a VLM structured visual check on a single PNG.

    Reads *png_path*, base64-encodes it, and sends it to llama.cpp
    along with *prompt* and the *schema* as a ``json_schema`` constraint.
    Returns the parsed dict with a ``_parse_error`` flag on failure.

    Args:
        png_path: Path to the PNG screenshot.
        schema: JSON schema dict (use ``PROP_SCHEMA`` or ``SCENE_SCHEMA``).
        prompt: Text prompt for the VLM (appended after ``<image>`` tag).
        endpoint: llama.cpp server URL.
        temperature: Sampling temperature.
        max_tokens: Maximum generation tokens.
        timeout_s: Request timeout in seconds.
        defaults: Dict of safe fallback values (auto-selected if None).

    Returns:
        Parsed dict with all schema fields populated.  Contains
        ``_parse_error: True`` if the response couldn't be parsed
        (in which case all fields carry safe defaults).
    """
    if defaults is None:
        defaults = _pick_defaults(schema)

    image_b64 = _encode_png(png_path)
    payload = _build_payload(
        prompt, image_b64, schema,
        temperature=temperature, max_tokens=max_tokens, seed=seed,
    )

    try:
        response = requests.post(
            f"{endpoint.rstrip('/')}/v1/chat/completions",
            json=payload,
            timeout=timeout_s,
        )
        response.raise_for_status()
        data = response.json()
        content = _extract_content(data)
    except requests.ConnectionError:
        return {**defaults, "_parse_error": True}
    except requests.Timeout:
        return {**defaults, "_parse_error": True}
    except requests.HTTPError:
        return {**defaults, "_parse_error": True}
    except Exception:
        return {**defaults, "_parse_error": True}

    return _parse_response(content, defaults, schema)


# ── Internal helpers ─────────────────────────────────────────────

def _encode_png(png_path: str) -> str:
    """Read a PNG file and return its base64 string (no data URI prefix)."""
    return base64.b64encode(Path(png_path).read_bytes()).decode("ascii")


def _build_payload(
    prompt: str,
    image_b64: str,
    schema: Dict[str, Any],
    *,
    temperature: float,
    max_tokens: int,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Construct the OpenAI-compatible chat/completions multimodal payload.

    The image is passed as a base64 ``data:`` URI in an ``image_url`` content
    part — the only path libmtmd actually feeds to the vision encoder.  The
    schema is enforced via ``response_format: json_schema``.
    """
    data_uri = f"data:image/png;base64,{image_b64}"
    payload: Dict[str, Any] = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt or "Describe what you see in this image."},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "visual_check", "schema": schema, "strict": True},
        },
    }
    if seed is not None:
        payload["seed"] = seed
    return payload


def _extract_content(data: Dict[str, Any]) -> str:
    """Pull the generated text from a chat/completions response.

    Prefers the chat shape (``choices[0].message.content``); falls back to a
    top-level ``content`` field so legacy/mocked responses still parse.
    """
    try:
        choices = data.get("choices")
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content")
            if content is not None:
                return content
    except (AttributeError, IndexError, KeyError, TypeError):
        pass
    return data.get("content", "")


def _pick_defaults(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return the right defaults dict based on schema identity."""
    if schema is SCENE_SCHEMA:
        return dict(SCENE_DEFAULTS)
    if schema is PROP_SCHEMA:
        return dict(PROP_DEFAULTS)
    # Unknown schema — build generic defaults from properties
    defaults: Dict[str, Any] = {}
    for key, prop in schema.get("properties", {}).items():
        ptype = prop.get("type", "string")
        if ptype == "boolean":
            defaults[key] = False
        elif ptype == "string":
            defaults[key] = ""
        elif ptype == "number" or ptype == "integer":
            defaults[key] = 0
        else:
            defaults[key] = None
    return defaults


def _parse_response(
    content: str,
    defaults: Dict[str, Any],
    schema: Dict[str, Any],
) -> Dict[str, Any]:
    """Parse the LLM response text into a dict, falling back to defaults."""
    if not content or not content.strip():
        return {**defaults, "_parse_error": True}

    # Try direct JSON parse first
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Try extracting JSON from markdown/code fences
        parsed = _extract_json_from_text(content)
        if parsed is None:
            return {**defaults, "_parse_error": True}

    if not isinstance(parsed, dict):
        return {**defaults, "_parse_error": True}

    # Fill in missing keys from defaults, cast types, and prune extras
    result: Dict[str, Any] = {}
    for key, prop in schema.get("properties", {}).items():
        ptype = prop.get("type", "string")
        if key in parsed:
            result[key] = _coerce(parsed[key], ptype)
        else:
            result[key] = defaults.get(key) if defaults else _default_for(ptype)

    return result


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Try to extract a JSON object from text (code fences, markdown, etc.)."""
    import re

    # Try ```json ... ``` code block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try bare { ... } (non-greedy to avoid swallowing adjacent objects)
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _coerce(value: Any, ptype: str) -> Any:
    """Coerce *value* to the expected JSON schema type."""
    if ptype == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        return bool(value)
    if ptype == "string":
        return str(value) if value is not None else ""
    if ptype == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    if ptype == "integer":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return value


def _default_for(ptype: str) -> Any:
    """Return a safe default value for a JSON schema type."""
    if ptype == "boolean":
        return False
    if ptype == "string":
        return ""
    if ptype in ("number", "integer"):
        return 0
    return None
