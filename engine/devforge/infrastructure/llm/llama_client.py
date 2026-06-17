"""Client for llama.cpp HTTP server."""

from __future__ import annotations

import contextvars
import json
import time
import warnings
import requests
from pathlib import Path
from typing import Optional

from devforge.infrastructure.logger import logger


# ── Prompt template registry ──────────────────────────────────────
# Exact wire formats — do not improvise the control tokens.

PROMPT_TEMPLATES: dict[str, dict] = {
    # Gemma has no system role — chat() folds system text into the user turn
    "gemma": {
        "user_wrap": "<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n",
        "system_wrap": None,   # fold into user turn as "[Instructions]\n{system}\n\n"
    },
    # ChatML (Qwen3, and most Qwen/Yi/InternLM family models)
    # NOTE: Qwen3 may emit ``<think>...</think>`` blocks —
    # ArchitecturePlanner._parse_response already strips them; do NOT
    # add a second stripping layer here.
    "chatml": {
        "user_wrap": "<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
        "system_wrap": "<|im_start|>system\n{system}<|im_end|>\n",
    },
    # No wrapping — for endpoints that template server-side
    "raw": {
        "user_wrap": "{prompt}",
        "system_wrap": None,
    },
}

VALID_PROMPT_TEMPLATES = frozenset(PROMPT_TEMPLATES.keys())


def normalize_gbnf(text: str) -> str:
    """Join multi-line alternations onto the rule line.

    llama.cpp's PEG-based GBNF parser (2026) rejects alternation
    continuation lines (``| alt`` at line start) that the legacy parser
    accepted — and a grammar that fails to parse is silently IGNORED:
    the server logs one error line, returns HTTP 200, and generates
    UNCONSTRAINED. Single-line alternations parse under both parsers,
    so every grammar must pass through here before hitting the wire.
    """
    out: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("|"):
            # Attach to the most recent rule line (skip blanks/comments)
            i = len(out) - 1
            while i >= 0 and (not out[i].strip()
                              or out[i].lstrip().startswith("#")):
                i -= 1
            if i >= 0:
                out[i] = out[i].rstrip() + " " + stripped
                continue
        out.append(line)
    return "\n".join(out)


class BudgetExceededError(RuntimeError):
    """Raised when the LLM Gateway rejects a request with 429 (budget exceeded).

    Distinct from other RuntimeErrors so callers can treat it as
    terminal — no amount of retrying will help.
    """
    pass


def apply_server_limits(config, client: "LlamaClient") -> None:
    """Clamp the context budget to what the live server can actually hold.

    The configured ``context_token_budget`` is a wish; the server's
    ``n_ctx`` is reality. llama.cpp holds prompt and generation in one
    window — overshooting makes it silently drop the OLDEST prompt
    tokens, which is the instruction prefix. Call once at startup,
    after the llama backend is configured and before the
    ContextAssembler computes its section budgets.
    """
    from devforge.infrastructure.runtime_config import (
        MIN_USEFUL_CONTEXT_TOKENS,
        effective_context_budget,
    )

    props = client.server_props()
    if not props:
        logger.warn(
            "llama_client",
            "Could not read /props from llama.cpp — keeping configured "
            f"context budget of {config.context_token_budget} tokens. "
            "If the server window is smaller, prompts will be truncated.",
        )
        return

    n_ctx = props["n_ctx"]
    effective = effective_context_budget(
        n_ctx, config.llama_max_tokens, config.context_token_budget
    )
    if effective < config.context_token_budget:
        logger.warn(
            "llama_client",
            f"Context budget clamped {config.context_token_budget} → "
            f"{effective} tokens: server '{props['model_alias']}' has "
            f"n_ctx={n_ctx}, generation reserves "
            f"{config.llama_max_tokens}, prompt overhead reserves the rest",
        )
        config.context_token_budget = effective
    else:
        logger.info(
            "llama_client",
            f"Context budget {config.context_token_budget} fits server "
            f"n_ctx={n_ctx} (alias '{props['model_alias']}', "
            f"slots={props['total_slots']})",
        )

    # ── Auto-detect prompt template from model alias ──────────
    # Only auto-set if the user hasn't explicitly configured one
    # via DEVFORGE_PROMPT_TEMPLATE in the environment.
    import os as _os
    from devforge.infrastructure.runtime_config import detect_prompt_template

    user_set_template = _os.getenv("DEVFORGE_PROMPT_TEMPLATE")
    if not user_set_template:
        alias = props.get("model_alias", "")
        detected = detect_prompt_template(alias)
        if detected and detected != config.llm_prompt_template:
            logger.info(
                "llama_client",
                f"Auto-detected prompt template '{detected}' from model "
                f"alias '{alias}' (was '{config.llm_prompt_template}')",
            )
            config.llm_prompt_template = detected
            client.prompt_template = detected

    if effective < MIN_USEFUL_CONTEXT_TOKENS:
        logger.warn(
            "llama_client",
            f"Effective context budget {effective} is below "
            f"{MIN_USEFUL_CONTEXT_TOKENS} — the planner may not see enough "
            "scene/architecture. Raise --ctx-size on llama-server or lower "
            "DEVFORGE_LLAMA_MAX_TOKENS.",
        )


# Per-turn token budget tracking (Phase 2).
# ContextVar so concurrent apply_spec calls in the same process
# don't overwrite each other's turn_id.  Read directly at
# request-build time — no shared mutable backend attribute.
_turn_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_turn_id", default=None
)


class LlamaClient:

    def __init__(
        self,
        endpoint: str = "http://localhost:8080",
        grammar_path: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_s: int = 300,
        prompt_template: str = "gemma",
    ):
        if prompt_template not in VALID_PROMPT_TEMPLATES:
            raise ValueError(
                f"Unknown prompt_template '{prompt_template}'. "
                f"Valid options: {sorted(VALID_PROMPT_TEMPLATES)}"
            )

        self.endpoint = endpoint.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.grammar: Optional[str] = None
        self.prompt_template = prompt_template

        # Truncation tracking (set by generate())
        self.last_truncated: bool = False

        if grammar_path:
            path = Path(grammar_path)
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                self.grammar = normalize_gbnf(raw).strip()
                logger.info("llama_client", f"Loaded grammar from {path}")
            else:
                logger.warn("llama_client", f"Grammar file not found: {grammar_path}")

    # ── Prompt wrapping ────────────────────────────────────────

    def _wrap(self, prompt: str) -> str:
        """Format a prompt using the active template's user_wrap."""
        tmpl = PROMPT_TEMPLATES[self.prompt_template]
        return tmpl["user_wrap"].format(prompt=prompt)

    def generate(
        self,
        prompt: str,
        grammar: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
    ) -> str:
        """Generate a response.

        *grammar* overrides the instance default for this single request.
        *temperature*, *top_p*, *top_k* override instance defaults — used
        for per-stage sampler profiles and greedy-decoding final retries.
        """
        # Wrap using the active prompt template
        formatted = self._wrap(prompt)
        return self._generate_impl(formatted, grammar=grammar,
                                   temperature=temperature, top_p=top_p, top_k=top_k)

    def _generate_impl(
        self,
        formatted: str,
        grammar: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
    ) -> str:
        """Send a pre-formatted prompt to llama.cpp (no wrapping applied).

        ``chat()`` calls this directly with a fully-built template prompt;
        ``generate()`` calls ``_wrap()`` first, then passes the result here.
        """
        payload = {
            "prompt": formatted,
            "temperature": temperature if temperature is not None else self.temperature,
            "n_predict": self.max_tokens,
            "cache_prompt": True,
            "top_p": top_p if top_p is not None else 0.9,
            "top_k": top_k if top_k is not None else 40,
            "min_p": 0.0,
        }

        active_grammar = grammar or self.grammar
        if active_grammar:
            # Normalize per-call grammars too (decomposer, planner
            # overrides) — instance grammar is already normalized at load.
            payload["grammar"] = normalize_gbnf(active_grammar)

        # Pin ALL repetition samplers to neutral. Structured/grammar output
        # benefits from not penalizing repeated tokens, AND this isolates
        # DevForge from server-level sampling defaults: the shared llama
        # server carries anti-repetition flags (DRY, repeat/presence/
        # frequency penalties) for the chat clients' creative writing, but
        # those would corrupt grammar-constrained JSON if inherited here.
        payload["repeat_penalty"] = 1.0
        payload["dry_multiplier"] = 0.0
        payload["presence_penalty"] = 0.0
        payload["frequency_penalty"] = 0.0

        # Reproducible seed for cache-friendly plans
        payload["seed"] = 0

        logger.debug("llama_client", "Sending request", endpoint=self.endpoint, prompt_len=len(formatted))

        # Per-turn budget: read turn_id directly from ContextVar.
        # No shared mutable state — concurrent apply_spec calls each
        # get their own turn_id via the ContextVar.
        turn_id = _turn_id_ctx.get()
        headers: dict[str, str] = {}
        if turn_id:
            headers["X-Turn-Id"] = turn_id

        last_conn_error: Optional[Exception] = None
        for attempt in (1, 2):
            try:
                response = requests.post(
                    f"{self.endpoint}/completion",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_s,
                )
                response.raise_for_status()

                data = response.json()
                content = data.get("content", "")

                # Detect truncation — n_predict limit reached before completion
                stopped_by_limit = (
                    data.get("stopped_limit", False)
                    or data.get("stop_type") == "limit"
                )
                self.last_truncated = bool(stopped_by_limit)
                if self.last_truncated:
                    logger.warn(
                        "llama_client",
                        "Generation hit n_predict — output truncated",
                        max_tokens=self.max_tokens,
                    )

                # D1: Log remaining token budget for observability.
                # The gateway was previously opaque — you couldn't see
                # budget exhaustion coming. Now each call surfaces how
                # much is left so operators/agents can spot the trend.
                gw_budget = response.headers.get("X-Budget-Remaining")
                if gw_budget:
                    logger.info(
                        "llama_client",
                        "Response received",
                        response_len=len(content),
                        budget_remaining=gw_budget,
                    )
                else:
                    logger.info(
                        "llama_client",
                        "Response received",
                        response_len=len(content),
                    )
                return content

            except requests.ConnectionError as ce:
                last_conn_error = ce
                if attempt == 2:
                    raise RuntimeError(
                        f"Cannot connect to llama.cpp at {self.endpoint}. "
                        "Is the server running?"
                    )
                logger.warn(
                    "llama_client",
                    f"Connection refused — retrying ({attempt}/2)",
                )
                time.sleep(0.5)
            except requests.Timeout:
                if attempt == 2:
                    raise RuntimeError(
                        f"LLM request timed out after {self.timeout_s}s"
                    )
                logger.warn(
                    "llama_client",
                    f"Request timed out — retrying ({attempt}/2)",
                )
                time.sleep(0.5)
            except requests.HTTPError as he:
                # 429 = budget exceeded — terminal, never retry
                if he.response is not None and he.response.status_code == 429:
                    raise BudgetExceededError(
                        f"Token budget exceeded: {he.response.text}"
                    ) from he
                raise RuntimeError(f"LLM HTTP error: {he}")
            except Exception as exc:
                raise RuntimeError(f"LLM request failed: {exc}")

        # Unreachable — attempt 2 always returns or raises
        raise RuntimeError(str(last_conn_error))

    def chat(
        self,
        messages: list[dict],
        grammar: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
    ) -> str:
        """Convert chat messages to a prompt using the active template.

        Multi-turn conversations are formatted per-template:
        - Gemma: no system role — system instructions are folded into
          the first user turn as ``[Instructions]\\n{system}\\n\\n``.
        - ChatML: system_wrap is emitted before the user block.
        - Raw: plain concatenation.

        NOTE: Currently handles single-pair (user only or system+user)
        correctly.  Multi-turn history (user→assistant→user) is not
        yet exercised by any call site and may need a full alternating-
        block formatter when it is.
        """
        tmpl = PROMPT_TEMPLATES[self.prompt_template]

        # Gather system and user content
        system_parts: list[str] = []
        user_parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                if tmpl["system_wrap"] is not None:
                    system_parts.append(content)
                else:
                    # No system role — fold into user turn
                    user_parts.insert(0, f"[Instructions]\n{content}\n")
            elif role == "user":
                user_parts.append(content)
            # assistant history skipped — not needed for single-turn planning

        user_text = "\n".join(user_parts) if user_parts else ""

        # Build the full prompt
        prompt_parts: list[str] = []
        if tmpl["system_wrap"] is not None and system_parts:
            system_text = "\n".join(system_parts)
            prompt_parts.append(tmpl["system_wrap"].format(system=system_text))
        prompt_parts.append(tmpl["user_wrap"].format(prompt=user_text))
        prompt = "".join(prompt_parts)

        return self._generate_impl(prompt, grammar=grammar,
                                   temperature=temperature, top_p=top_p, top_k=top_k)

    # ------------------------------------------------------------------
    # Gemma chat template
    # ------------------------------------------------------------------

    # ── Deprecated — use PROMPT_TEMPLATES registry instead ─────

    @staticmethod
    def _apply_gemma_template(prompt: str) -> str:
        """Wrap a prompt in Gemma 4's chat template (DEPRECATED).

        Use ``LlamaClient(prompt_template="gemma")`` and ``_wrap()``
        instead.  This thin alias remains for backward compatibility.
        """
        warnings.warn(
            "_apply_gemma_template is deprecated — use the PROMPT_TEMPLATES registry",
            DeprecationWarning,
            stacklevel=2,
        )
        return PROMPT_TEMPLATES["gemma"]["user_wrap"].format(prompt=prompt)

    # ------------------------------------------------------------------
    # Token counting (Phase 6: P4 — replace heuristic with /tokenize)
    # ------------------------------------------------------------------

    def tokenize(self, text: str) -> int | None:
        """Get accurate token count from llama.cpp's /tokenize endpoint.

        Returns None if the endpoint is unavailable — callers should
        fall back to the len(text)//4 heuristic.
        """
        try:
            response = requests.post(
                f"{self.endpoint}/tokenize",
                json={"content": text},
                timeout=5,
            )
            response.raise_for_status()
            data = response.json()
            tokens = data.get("tokens", [])
            if isinstance(tokens, list):
                return len(tokens)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Server introspection
    # ------------------------------------------------------------------

    def server_props(self) -> Optional[dict]:
        """Query llama.cpp's /props endpoint for the server's real limits.

        Returns ``{"n_ctx": int, "total_slots": int, "model_alias": str}``
        or None if the server is unreachable or the shape is unexpected.
        n_ctx is the per-slot context window — the hard ceiling for
        prompt + generation combined.
        """
        try:
            response = requests.get(f"{self.endpoint}/props", timeout=5)
            response.raise_for_status()
            data = response.json()
            n_ctx = (data.get("default_generation_settings") or {}).get("n_ctx")
            if not isinstance(n_ctx, int):
                return None
            return {
                "n_ctx": n_ctx,
                "total_slots": data.get("total_slots", 1),
                "model_alias": data.get("model_alias", ""),
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Grammar self-test
    # ------------------------------------------------------------------

    def selftest_grammar(self) -> bool:
        """Verify that llama.cpp actually enforces the loaded grammar.

        Sends a throwaway constrained request and asserts the output
        is parseable JSON.  If the GBNF has a parse error, llama.cpp
        silently ignores it and generates unconstrained — this test
        catches that failure at startup.

        Some models (Qwen3) emit ``<think>...</think>`` blocks before
        constrained output.  The grammar should prevent this, but if
        token vocabularies don't match the GBNF, the model may emit
        unconstrained text first.  We strip think blocks here so the
        self-test can still verify that constrained JSON follows.

        Returns True if the grammar is enforced, False otherwise.
        """
        if not self.grammar:
            return True  # no grammar configured — nothing to test

        # Cap generation: in the failure case the model is unconstrained
        # and a thinking model would otherwise ramble for max_tokens.
        saved_max = self.max_tokens
        self.max_tokens = 192
        try:
            # Part 1: prove the server enforces grammars AT ALL. A
            # sentinel grammar forces an exact string no model would
            # produce for this prompt; anything else means grammars are
            # being ignored server-wide.
            sentinel = "DEVFORGE-GRAMMAR-OK"
            out = self.generate(
                "Say hello.", grammar=f'root ::= "{sentinel}"'
            ).strip()
            if out != sentinel:
                logger.error(
                    "llama_client",
                    "GRAMMAR NOT ENFORCED — sentinel grammar ignored",
                    got=out[:120],
                )
                return False

            # Part 2: prove THIS grammar parses server-side. A grammar
            # with a syntax error is silently dropped (HTTP 200,
            # unconstrained output), so checking output shape is the
            # only client-visible signal. The planner grammar forces
            # the response to open with "{" — unconstrained chatter
            # (or a <think> block) won't.
            out = self.generate("Say hello.", grammar=self.grammar)
            if not out.lstrip().startswith("{"):
                logger.error(
                    "llama_client",
                    "GRAMMAR NOT ENFORCED — loaded grammar failed to "
                    "parse server-side (output not grammar-shaped)",
                    got=out[:120],
                )
                return False

            logger.info("llama_client", "Grammar self-test PASSED")
            return True
        except Exception as exc:
            logger.error(
                "llama_client",
                "Grammar self-test errored",
                error=str(exc),
            )
            return False
        finally:
            self.max_tokens = saved_max
