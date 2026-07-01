"""
core/providers/openai_provider.py — OpenAI Chat Completions wrapper.
"""

from typing import Iterator

from cli.ui import console, THEME
from core.providers.backoff import _retry_with_backoff


class OpenAIGenerator:
    """
    OpenAI Chat Completions wrapper.
    Supports both buffered and streaming generation.
    """

    def __init__(self, model_name: str = "gpt-4o", timeout: float = 60.0):
        self.model_name = model_name
        self.timeout = timeout
        from openai import OpenAI as _OpenAI
        self.client = _OpenAI(timeout=timeout)

    def _open_stream(self, prompt: str):
        return self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            timeout=self.timeout,
        )

    def generate(self, prompt: str) -> str:
        """Buffered call that internally streams + renders to the terminal."""
        return "".join(self.stream(prompt, render=True))

    def stream(self, prompt: str, render: bool = False) -> Iterator[str]:
        """
        Streams the model response token-by-token, with retry/backoff on
        transient provider errors.

        Args:
            prompt: The instruction for the model.
            render:  If True, tokens are printed live to the terminal.

        Yields:
            str: Individual text chunks as they arrive.
        """
        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with OpenAI ({self.model_name})…[/]"
        )

        stream = _retry_with_backoff(
            self._open_stream, prompt, label=f"OpenAI {self.model_name}",
        )

        if render:
            console.print()
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                if render:
                    print(delta, end="", flush=True)
                yield delta
        if render:
            print()
