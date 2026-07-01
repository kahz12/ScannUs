"""
core/providers/anthropic_provider.py — Anthropic Claude wrapper.
"""

import os
from typing import Iterator

from cli.ui import console, THEME
from core.providers.backoff import _retry_with_backoff


class AnthropicGenerator:
    """
    Anthropic Claude wrapper via the ``anthropic`` Python SDK.

    Defaults to the latest Sonnet (claude-sonnet-4-6) for a good
    quality/cost balance. Override with the ``ANTHROPIC_MODEL`` env var or
    by passing ``model_name`` directly.
    """

    DEFAULT_MODEL    = "claude-sonnet-4-6"
    DEFAULT_MAX_TOK  = 4096

    def __init__(self, model_name: str | None = None, timeout: float = 60.0,
                 max_tokens: int = DEFAULT_MAX_TOK):
        self.model_name = (model_name
                           or os.getenv("ANTHROPIC_MODEL")
                           or self.DEFAULT_MODEL)
        self.timeout    = timeout
        self.max_tokens = max_tokens
        try:
            from anthropic import Anthropic as _Anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic SDK not installed — install with: pip install anthropic"
            ) from e
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set — run `python main.py -c` to configure."
            )
        self.client = _Anthropic(api_key=api_key, timeout=timeout)

    def generate(self, prompt: str) -> str:
        """Streams the response, rendering tokens live; returns full text."""
        return "".join(self.stream(prompt, render=True))

    def stream(self, prompt: str, render: bool = False) -> Iterator[str]:
        """Yields text chunks from Claude's streaming API with retry/backoff."""
        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with Claude ({self.model_name})…[/]"
        )

        def _open():
            return self.client.messages.stream(
                model=self.model_name,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

        try:
            ctx = _retry_with_backoff(_open, label=f"Claude {self.model_name}")
        except Exception as e:
            yield f"[Claude error: {e}]"
            return

        if render:
            console.print()
        try:
            with ctx as stream:
                for text in stream.text_stream:
                    if not text:
                        continue
                    if render:
                        print(text, end="", flush=True)
                    yield text
        except Exception as e:
            yield f"[Claude stream error: {e}]"
        if render:
            print()
