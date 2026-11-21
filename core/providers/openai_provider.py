"""
core/providers/openai_provider.py — OpenAI Chat Completions wrapper.
"""

import os
from typing import Iterator

from cli.ui import console, THEME
from core.providers.backoff import _retry_with_backoff
from core.providers.errors import ProviderError


class OpenAIGenerator:
    """
    OpenAI Chat Completions wrapper.
    Supports both buffered and streaming generation.

    Override the default model with the ``OPENAI_MODEL`` env var or by passing
    ``model_name`` directly.
    """

    DEFAULT_MODEL = "gpt-4o"
    supports_system = True

    def __init__(self, model_name: str | None = None, timeout: float = 60.0):
        self.model_name = model_name or os.getenv("OPENAI_MODEL") or self.DEFAULT_MODEL
        self.timeout = timeout
        from openai import OpenAI as _OpenAI
        self.client = _OpenAI(timeout=timeout)

    def _open_stream(self, prompt: str, system: str | None = None):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True,
            timeout=self.timeout,
        )

    def generate(self, prompt: str, system: str | None = None) -> str:
        """Buffered call that internally streams + renders to the terminal."""
        return "".join(self.stream(prompt, render=True, system=system))

    def stream(self, prompt: str, render: bool = False,
               system: str | None = None) -> Iterator[str]:
        """
        Streams the model response token-by-token, with retry/backoff on
        transient provider failures.

        Args:
            prompt: The instruction for the model.
            render:  If True, tokens are printed live to the terminal.
            system:  Optional system-role instructions separated from user data.

        Yields:
            str: Individual text chunks as they arrive.
        """
        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with OpenAI ({self.model_name})…[/]"
        )

        try:
            stream = _retry_with_backoff(
                self._open_stream, prompt, system, label=f"OpenAI {self.model_name}",
            )
        except Exception as e:
            raise ProviderError(f"OpenAI: {e}") from e

        if render:
            console.print()
        try:
            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue
                delta = getattr(chunk.choices[0].delta, "content", None) or ""
                if delta:
                    if render:
                        print(delta, end="", flush=True)
                    yield delta
        except Exception as e:
            raise ProviderError(f"OpenAI stream: {e}") from e
        finally:
            if render:
                print()
