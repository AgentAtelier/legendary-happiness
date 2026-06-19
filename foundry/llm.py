"""Standalone client for the local llama.cpp server at http://127.0.0.1:8002.

Ported normalize_gbnf from engine/devforge/infrastructure/llm/llama_client.py
so the foundry stays standalone (no engine imports).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import requests

_GRAMMAR_PATH = str(Path(__file__).resolve().parent / "grammar" / "asset_spec.gbnf")


def normalize_gbnf(text: str) -> str:
    """Join multi-line alternations onto the rule line.

    llama.cpp's PEG-based GBNF parser silently IGNORES a grammar with
    multi-line ``|`` alternation continuation lines and then generates
    UNCONSTRAINED. Single-line alternations parse correctly, so every
    grammar must pass through here before hitting the wire.
    """
    out: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("|"):
            i = len(out) - 1
            while i >= 0 and (not out[i].strip() or out[i].lstrip().startswith("#")):
                i -= 1
            if i >= 0:
                out[i] = out[i].rstrip() + " " + stripped
                continue
        out.append(line)
    return "\n".join(out)


def load_grammar(path: str = _GRAMMAR_PATH) -> str:
    """Load and normalize the asset_spec GBNF grammar."""
    raw = Path(path).read_text(encoding="utf-8")
    return normalize_gbnf(raw).strip()


class FoundryLLM:
    """Minimal llama.cpp client for the foundry pipeline.

    Sends POST /completion with a prompt + grammar and returns the
    generated text.  Designed to be passed as the injectable llm
    callable to AssetPlanner.plan().
    """

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:8002",
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout_s: int = 120,
        grammar_path: str = _GRAMMAR_PATH,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self._grammar = load_grammar(grammar_path)

    def __call__(self, prompt: str, grammar: Optional[str] = None) -> str:
        """Generate a response.  Callable signature: (prompt, grammar) -> str.

        If *grammar* is provided it overrides the default asset-spec grammar.
        """
        active_grammar = grammar if grammar is not None else self._grammar
        # Instance grammar is already normalized at load time; only normalize
        # per-call overrides (which may be raw).
        if grammar is not None and active_grammar:
            active_grammar = normalize_gbnf(active_grammar)

        payload = {
            "prompt": prompt,
            "temperature": self.temperature,
            "n_predict": self.max_tokens,
            "cache_prompt": True,
        }
        if active_grammar:
            payload["grammar"] = active_grammar

        try:
            response = requests.post(
                f"{self.endpoint}/completion",
                json=payload,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("content", "")
        except requests.ConnectionError:
            raise RuntimeError(
                f"Cannot connect to llama.cpp at {self.endpoint}. Is the server running?"
            )
        except requests.Timeout:
            raise RuntimeError(f"LLM request timed out after {self.timeout_s}s")
        except requests.HTTPError as he:
            raise RuntimeError(f"LLM HTTP error: {he}")
        except Exception as exc:
            raise RuntimeError(f"LLM request failed: {exc}")
