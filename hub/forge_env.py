"""
forge_env — single-source-of-truth parser/serializer for stack.env.

Used by BOTH hub.py and the forge-model CLI so they can never diverge.
Handles single-quoted AND double-quoted values correctly (the old
duplicated copies both did only `.strip('"')`, silently breaking single-
quoted values like LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}').

Phase 6: adds validate_env() schema validator replacing the ad-hoc
"LLAMA_BIN" in text check.

Public API:
    read_env(path) -> dict[str, str]
    write_env(path, updates) -> None
    plan_env(path, updates) -> dict   (dry-run preview)
    validate_env(text) -> list[str]   (schema validation errors)
"""

from __future__ import annotations

import re
from pathlib import Path

HOME = Path.home()
ENVFILE = HOME / ".config/forge-stack/stack.env"

# Phase 6: stack.env schema
REQUIRED_KEYS = [
    "LLAMA_BIN",
    "MODEL",
    "MODEL_ALIAS",
    "LLAMA_PORT",
    "LLAMA_BASE_ARGS",
    "LLAMA_ARGS",
    "GODOT_BIN",
    "GAME_PROJECT",
    "DEVFORGE_DIR",
    "MCP_PORT",
    "DEVFORGE_PROMPT_TEMPLATE",
    "ODYSSEUS_DIR",
    "ODYSSEUS_URL",
    "GODOT_AI_PORT",
]

# Safety invariants that must be present in LLAMA_BASE_ARGS
REQUIRED_SAFETY_CAPS = ["--n-predict"]


def _unquote(v: str) -> str:
    """Strip matching quote pairs (single or double) from a value."""
    v = v.strip()
    if len(v) >= 2:
        if v[0] == v[-1] and v[0] in ('"', "'"):
            return v[1:-1]
    return v


def _quote_style(v: str) -> str | None:
    """Return '"', "'", or None depending on how v is quoted."""
    v = v.strip()
    if len(v) >= 2:
        if v[0] == v[-1] and v[0] in ('"', "'"):
            return v[0]
    return None


def read_env(path: Path) -> dict[str, str]:
    """Parse a shell-style .env file into a dict.

    Handles:
      - Single-quoted values: FOO='bar' → 'bar' stripped → bar
      - Double-quoted values: FOO="bar" → "bar" stripped → bar
      - Unquoted values: FOO=bar → bar
      - Comments (lines starting with #)
      - Blank lines (silently skipped)
      - Values containing = (partition on first = only)
    """
    env: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "=" not in s:
                continue
            k, _, v = s.partition("=")
            env[k.strip()] = _unquote(v)
    except OSError:
        pass
    return env


def write_env(path: Path, updates: dict[str, str]) -> None:
    """Write key=value updates into an existing .env file.

    Preserves the original formatting (comments, blank lines, quoting style
    of unchanged keys). Replaces existing keys in-place; appends new keys
    at the end. Keys that previously had quotes get their new values
    re-quoted the same way; new keys are written unquoted (caller should
    quote if needed — the forge-model CLI handles this in cmd_apply).
    """
    lines: list[str] = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        lines = []

    orig_styles: dict[str, str | None] = {}
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, v = s.partition("=")
            orig_styles[k.strip()] = _quote_style(v)

    done: set[str] = set()
    for i, line in enumerate(lines):
        for k, v in updates.items():
            if re.match(rf"^{re.escape(k)}=", line.strip()):
                style = orig_styles.get(k)
                if style is not None:
                    lines[i] = f"{k}={style}{v}{style}"
                else:
                    lines[i] = f"{k}={v}"
                done.add(k)

    for k in [k for k in updates if k not in done]:
        lines.append(f"{k}={updates[k]}")

    path.write_text("\n".join(lines) + "\n")


def plan_env(path: Path, updates: dict[str, str]) -> dict:
    """Dry-run: return what write_env WOULD do without touching the file."""
    current = read_env(path)
    changes: dict[str, dict[str, str]] = {}
    new_keys: list[str] = []
    for k, v in updates.items():
        old = current.get(k)
        if old is None:
            new_keys.append(k)
        elif old != v:
            changes[k] = {"old": old, "new": v}
    return {"changes": changes, "new_keys": new_keys}


# ── Phase 6: schema validation ───────────────────────────────────


def validate_env(text: str) -> list[str]:
    """Validate stack.env content for required keys and safety invariants.

    Returns a list of human-readable error strings. Empty list = valid.
    Replaces the old ad-hoc '"LLAMA_BIN" in text' check.
    """
    errors: list[str] = []

    # Parse
    env: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, _, v = s.partition("=")
        env[k.strip()] = _unquote(v)

    # Required keys
    for key in REQUIRED_KEYS:
        if key not in env:
            errors.append(f"missing required key: {key}")
        elif not env[key].strip():
            errors.append(f"required key is empty: {key}")

    # Safety caps
    base_args = env.get("LLAMA_BASE_ARGS", "")
    for cap in REQUIRED_SAFETY_CAPS:
        if cap not in base_args:
            errors.append(
                f"LLAMA_BASE_ARGS is missing safety cap: {cap} (without it, one runaway request blocks the whole chain)"
            )

    # Port numbers should be numeric
    port_keys = ["LLAMA_PORT", "MCP_PORT", "GODOT_AI_PORT"]
    for pk in port_keys:
        v = env.get(pk, "")
        if v and not re.match(r"^\d{1,5}$", v):
            errors.append(f"{pk} should be a port number, got: {v}")

    # Paths should look plausible
    bin_keys = ["LLAMA_BIN", "GODOT_BIN"]
    for bk in bin_keys:
        v = env.get(bk, "")
        if v and "/" not in v:
            errors.append(f"{bk} should be an absolute path, got: {v}")

    return errors
