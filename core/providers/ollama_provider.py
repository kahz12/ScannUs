"""
core/providers/ollama_provider.py — Ollama local-inference wrapper (no API key).
"""

import json
import os
from typing import Iterator

from cli.ui import console, THEME
from core.providers.backoff import _retry_with_backoff


class OllamaGenerator:
    """
    Ollama HTTP-API wrapper for local model inference.

    No SDK / API key required — talks straight to ``http://localhost:11434``
    (override with ``OLLAMA_HOST``). The model must already be pulled
    (``ollama pull <model>``); the default is ``llama3`` but any installed
    model works via ``OLLAMA_MODEL`` or the constructor.
    """

    DEFAULT_HOST  = "http://localhost:11434"
    DEFAULT_MODEL = "llama3"

    def __init__(self, model_name: str | None = None, host: str | None = None,
                 timeout: float = 120.0):
        self.model_name = (model_name
                           or os.getenv("OLLAMA_MODEL")
                           or self.DEFAULT_MODEL)
        self.host = (host or os.getenv("OLLAMA_HOST")
                     or self.DEFAULT_HOST).rstrip("/")
        self.timeout = timeout
        # Lazy import so the module load doesn't depend on `requests` here
        import requests as _requests
        self._requests = _requests

    def _ping(self) -> bool:
        """Quick health check; returns True if the daemon answers ``/api/tags``."""
        try:
            r = self._requests.get(f"{self.host}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def generate(self, prompt: str) -> str:
        """Streams the response, rendering tokens live; returns full text."""
        return "".join(self.stream(prompt, render=True))

    def stream(self, prompt: str, render: bool = False) -> Iterator[str]:
        """
        Streams from Ollama's ``/api/generate`` endpoint. Each line is a JSON
        object with a ``response`` token; the final object has ``done: true``.
        """
        if not self._ping():
            yield (f"[Ollama error: daemon not reachable at {self.host}. "
                   f"Start it with `ollama serve` or set OLLAMA_HOST.]")
            return

        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with Ollama "
            f"({self.model_name} @ {self.host})…[/]"
        )

        try:
            response = _retry_with_backoff(
                self._requests.post,
                f"{self.host}/api/generate",
                json={"model": self.model_name, "prompt": prompt, "stream": True},
                timeout=self.timeout,
                stream=True,
                label=f"Ollama {self.model_name}",
            )
            response.raise_for_status()
        except Exception as e:
            yield f"[Ollama error: {e}]"
            return

        if render:
            console.print()
        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if "error" in payload:
                    yield f"[Ollama error: {payload['error']}]"
                    break
                text = payload.get("response", "")
                if text:
                    if render:
                        print(text, end="", flush=True)
                    yield text
                if payload.get("done"):
                    break
        except Exception as e:
            yield f"[Ollama stream error: {e}]"
        if render:
            print()
