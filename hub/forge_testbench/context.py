"""Context — injected runtime environment for tests.

Tests never reach into global state (read_env, _devforge_call, etc.).
Instead they receive a Context that provides everything they need.
This makes tests unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class Context:
    """Injected runtime for a test.

    Attributes:
        model_alias: The currently loaded model (e.g. "qwen3-5-4b").
        env: stack.env key/value pairs.
        _apply_spec: Callable for apply_spec (DevForge pipeline).
        _read_artifact: Callable for read_artifact.
        _godot_ai_call: Callable for godot-ai MCP calls.
        _llama: httpx.AsyncClient or None for raw llama API calls.
        _skip_cache: Whether to skip the plan cache (variety tests).
        _sh: Shell command runner (async).
        data_dir: Path to the output directory for this run.
    """

    model_alias: str
    env: dict[str, str] = field(default_factory=dict)
    _apply_spec: Callable[..., Awaitable[dict]] | None = None
    _read_artifact: Callable[..., Awaitable[dict]] | None = None
    _devforge_raw: Callable[..., Awaitable[dict]] | None = None
    _godot_ai_call: Callable[..., Awaitable[Any]] | None = None
    _llama: Any = None  # httpx.AsyncClient or None
    _sh: Callable[..., Awaitable[tuple[int, str]]] | None = None
    data_dir: str = ""
    skip_cache: bool = False

    # ── DevForge pipeline ────────────────────────────────────────

    async def apply_spec(
        self, prompt: str, *,
        planner: str = "room",
        temperature: float = 0.2,
        timeout_s: int = 300,
    ) -> dict:
        if self._apply_spec is None:
            raise RuntimeError("apply_spec not wired into Context")
        return await self._apply_spec(
            prompt=prompt,
            planner=planner,
            temperature=temperature,
            skip_cache=self.skip_cache,
            timeout_s=timeout_s,
        )

    async def read_artifact(self, artifact_id: str, timeout_s: int = 30) -> dict:
        if self._read_artifact is None:
            raise RuntimeError("read_artifact not wired into Context")
        return await self._read_artifact(artifact_id, timeout_s=timeout_s)

    async def devforge_call(
        self, tool: str, args: dict | None = None, timeout_s: int = 60
    ) -> dict:
        """Call any DevForge MCP tool (validate_spec, get_scene, etc.)."""
        if self._devforge_raw is None:
            raise RuntimeError("devforge_raw not wired into Context")
        return await self._devforge_raw(tool, args or {}, timeout_s)

    # ── godot-ai bridge ──────────────────────────────────────────

    async def godot_ai(self, tool: str, args: dict | None = None) -> Any:
        if self._godot_ai_call is None:
            raise RuntimeError("godot_ai_call not wired into Context")
        return await self._godot_ai_call(tool, args or {})

    # ── llama raw API ────────────────────────────────────────────

    async def llama_get(self, path: str, timeout: float = 10) -> dict:
        """GET from llama server and return parsed JSON dict."""
        if self._llama is None:
            raise RuntimeError("llama client not wired into Context")
        r = await self._llama.get(path, timeout=timeout)
        return r.json()

    async def llama_post(self, path: str, json: dict, timeout: float = 120) -> dict:
        if self._llama is None:
            raise RuntimeError("llama client not wired into Context")
        r = await self._llama.post(path, json=json, timeout=timeout)
        return r.json()

    # ── shell ────────────────────────────────────────────────────

    async def sh(self, *cmd: str, timeout: float = 30.0) -> tuple[int, str]:
        if self._sh is None:
            raise RuntimeError("shell not wired into Context")
        return await self._sh(*cmd, timeout=timeout)
