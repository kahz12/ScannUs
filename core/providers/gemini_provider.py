"""
core/providers/gemini_provider.py — Google Gemini wrapper (``google-genai`` SDK).
"""

import os
from typing import Iterator

from cli.ui import console, THEME
from core.providers.backoff import _retry_with_backoff


class GeminiGenerator:
    """
    Google Gemini API wrapper via the `google-genai` SDK.
    Supports buffered and streaming generation.
    """

    def __init__(self, model_name: str = "gemini-2.0-flash", timeout: float = 60.0):
        self.model_name = model_name
        self.timeout = timeout
        self.client = None
        self._initialize_client()

    def _initialize_client(self):
        """Bootstrap the Gemini client from the environment API key."""
        api_key = os.getenv("GOOGLE_API_KEY_FOR_GEMINI")
        if api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=api_key)
            except Exception as e:
                console.print(f"  [{THEME['ERROR']}]✘[/]  Gemini init error: {e}")

    def _open_stream(self, prompt: str):
        return self.client.models.generate_content_stream(
            model=self.model_name,
            contents=prompt,
        )

    def generate(self, prompt: str) -> str:
        """Streams the response, rendering tokens live; returns full text."""
        return "".join(self.stream(prompt, render=True))

    def stream(self, prompt: str, render: bool = False) -> Iterator[str]:
        """
        Yields text chunks from the Gemini streaming API with retry/backoff.

        Args:
            prompt: Prompt text.
            render:  If True, tokens are printed live to the terminal.
        """
        if not self.client:
            self._initialize_client()
            if not self.client:
                yield "Error: Gemini client not initialized — check GOOGLE_API_KEY_FOR_GEMINI."
                return

        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with Gemini ({self.model_name})…[/]"
        )

        try:
            stream = _retry_with_backoff(
                self._open_stream, prompt, label=f"Gemini {self.model_name}",
            )
        except AttributeError:
            try:
                response = _retry_with_backoff(
                    self.client.models.generate_content,
                    model=self.model_name, contents=prompt,
                    label=f"Gemini {self.model_name}",
                )
                text = response.text or ""
                if render:
                    print(text, flush=True)
                yield text
            except Exception as e:
                yield f"[Gemini error: {e}]"
            return
        except Exception as e:
            yield f"[Gemini error: {e}]"
            return

        if render:
            console.print()
        for chunk in stream:
            text = chunk.text or ""
            if text:
                if render:
                    print(text, end="", flush=True)
                yield text
        if render:
            print()
