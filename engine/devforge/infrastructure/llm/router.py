"""LLM Router — central abstraction for all LLM calls in DevForge.

This is the ONLY place that talks to LLM backends.
Everything else calls router.generate() or router.chat().
"""

from __future__ import annotations

import inspect
import time
from typing import Optional

from devforge.infrastructure.logger import logger

# Per-turn token budget tracking (Phase 2).
# The ContextVar lives in llama_client.py (where the header is built)
# so concurrent apply_spec calls read their own turn_id at request
# time without copying through shared mutable state.
from devforge.infrastructure.llm.llama_client import _turn_id_ctx


class LLMRouter:
    """Routes LLM requests to configured backend."""

    _instance: Optional["LLMRouter"] = None

    # Circuit breaker: after this many consecutive failures, open the breaker
    CIRCUIT_BREAKER_THRESHOLD: int = 3
    # Cooldown in seconds before the breaker resets
    CIRCUIT_BREAKER_COOLDOWN: float = 30.0

    def __init__(self):
        self._backend = None
        self._backend_name = "none"
        self._consecutive_failures: int = 0
        self._breaker_open_until: float = 0.0

    @classmethod
    def get(cls) -> "LLMRouter":
        if cls._instance is None:
            cls._instance = LLMRouter()
        return cls._instance

    def configure_llama(
        self,
        endpoint: str = "http://localhost:8080",
        grammar_path: str = "",
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_s: int = 300,
        prompt_template: str = "gemma",
    ) -> None:
        from devforge.infrastructure.llm.llama_client import LlamaClient

        self._backend = LlamaClient(
            endpoint=endpoint,
            grammar_path=grammar_path or None,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            prompt_template=prompt_template,
        )
        self._backend_name = "llama"
        logger.info("llm_router", f"Configured llama backend at {endpoint}")

    def configure_claude(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 8192,
    ) -> None:
        from devforge.infrastructure.llm.claude_client import ClaudeClient

        self._backend = ClaudeClient(
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
        )
        self._backend_name = "claude"
        logger.info("llm_router", f"Configured Claude backend ({model})")

    def configure_mock(self, response_fn=None) -> None:
        """Configure a mock backend for testing."""
        self._backend = _MockBackend(response_fn)
        self._backend_name = "mock"
        logger.info("llm_router", "Configured mock backend")

    @property
    def is_configured(self) -> bool:
        return self._backend is not None

    @property
    def backend_name(self) -> str:
        return self._backend_name

    @property
    def last_truncated(self) -> bool:
        """Whether the most recent LLM response was truncated (hit n_predict)."""
        if self._backend is None:
            return False
        return getattr(self._backend, "last_truncated", False)

    # ------------------------------------------------------------------
    # Per-turn budget tracking (Phase 2)
    # ------------------------------------------------------------------

    def set_turn_id(self, turn_id: str) -> None:
        """Set the turn_id for per-turn token budget tracking.

        All subsequent LLM calls in the current async context will
        carry an ``X-Turn-Id`` header so the LLM Gateway can enforce
        a per-turn token budget.  Uses a ``ContextVar`` so concurrent
        ``apply_spec`` calls don't interfere with each other.

        Call ``clear_turn_id()`` when the turn is complete.
        """
        _turn_id_ctx.set(turn_id)

    def clear_turn_id(self) -> None:
        """Clear the turn_id after the pipeline completes."""
        _turn_id_ctx.set(None)

    def generate(
        self,
        prompt: str,
        grammar: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
    ) -> str:
        """Generate a response from a single prompt string.

        Args:
            prompt: The prompt to send.
            grammar: Optional GBNF grammar text overriding the backend default.
            temperature, top_p, top_k: Optional per-call sampler overrides
                for per-stage profiles (P2) and greedy-decoding final retries.
        """
        if not self._backend:
            raise RuntimeError(
                "LLM not configured. Call router.configure_llama() or router.configure_claude() first."
            )

        logger.debug("llm_router", "generate()", backend=self._backend_name, prompt_len=len(prompt))

        # Circuit breaker: if backend is failing repeatedly, fail fast
        if time.time() < self._breaker_open_until:
            raise RuntimeError(
                f"LLM backend ({self._backend_name}) unavailable — "
                "circuit breaker open.  Check if the model server is running."
            )

        # Build kwargs: only pass non-None overrides
        kwargs: dict[str, object] = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if top_k is not None:
            kwargs["top_k"] = top_k

        # Capability detection: forward grammar + sampler overrides if backend accepts them.
        try:
            sig = inspect.signature(self._backend.generate)
            if grammar and "grammar" in sig.parameters:
                kwargs["grammar"] = grammar

            result = self._backend.generate(prompt, **kwargs)

            # Success — reset circuit breaker
            self._consecutive_failures = 0
            return result

        except Exception:
            self._consecutive_failures += 1
            self._trip_breaker_if_needed()
            raise

    def chat(
        self,
        messages: list[dict],
        grammar: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
    ) -> str:
        """Generate from a list of chat messages."""
        if not self._backend:
            raise RuntimeError("LLM not configured.")

        # Circuit breaker check — same as generate()
        if time.time() < self._breaker_open_until:
            raise RuntimeError(
                f"LLM backend ({self._backend_name}) unavailable — "
                "circuit breaker open.  Check if the model server is running."
            )

        logger.debug("llm_router", "chat()", backend=self._backend_name, msg_count=len(messages))

        # Forward grammar + sampler overrides if backend supports them
        kwargs: dict[str, object] = {}
        if grammar is not None:
            kwargs["grammar"] = grammar
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if top_k is not None:
            kwargs["top_k"] = top_k

        try:
            sig = inspect.signature(self._backend.chat)
            supported = {k: v for k, v in kwargs.items() if k in sig.parameters}
            result = self._backend.chat(messages, **supported)

            # Success — reset circuit breaker
            self._consecutive_failures = 0
            return result

        except Exception:
            self._consecutive_failures += 1
            self._trip_breaker_if_needed()
            raise

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------

    def _trip_breaker_if_needed(self) -> None:
        """Open the circuit breaker if failure threshold is reached."""
        if self._consecutive_failures >= self.CIRCUIT_BREAKER_THRESHOLD:
            self._breaker_open_until = time.time() + self.CIRCUIT_BREAKER_COOLDOWN
            logger.error(
                "llm_router",
                f"Circuit breaker OPEN — {self._consecutive_failures} consecutive failures. "
                f"Cooldown: {self.CIRCUIT_BREAKER_COOLDOWN}s",
            )


class _MockBackend:
    """Mock backend for testing without a real LLM."""

    def __init__(self, response_fn=None):
        self._fn = response_fn or (lambda p: '{"systems":[],"entities":[],"connections":[]}')
        self.last_truncated: bool = False

    def generate(self, prompt: str, grammar: Optional[str] = None) -> str:
        return self._fn(prompt)

    def chat(self, messages: list[dict], grammar: Optional[str] = None) -> str:
        # Use the last user message as the prompt
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return self.generate(msg["content"])
        return self.generate("")
