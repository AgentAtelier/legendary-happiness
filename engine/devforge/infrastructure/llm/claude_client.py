"""Claude API client for higher-quality generation."""

from __future__ import annotations

import os
from devforge.infrastructure.logger import logger

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


class ClaudeClient:

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 8192,
    ):
        if Anthropic is None:
            raise RuntimeError("Anthropic SDK not installed. Run: pip install anthropic")

        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        self.model = model
        self.max_tokens = max_tokens
        self.client = Anthropic(api_key=self.api_key)

    def generate(self, prompt: str) -> str:
        return self.chat([{"role": "user", "content": prompt}])

    def chat(self, messages: list[dict]) -> str:
        logger.debug("claude_client", "Sending request", model=self.model, msg_count=len(messages))
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=messages,
            )
            # content can carry non-text blocks (e.g. thinking) first —
            # take the first text block, not blindly content[0]
            content = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            logger.info("claude_client", "Response received", response_len=len(content))
            return content
        except Exception as exc:
            logger.error("claude_client", f"Request failed: {exc}")
            raise
