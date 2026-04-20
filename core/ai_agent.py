"""
core/ai_agent.py — AI provider wrappers with streaming support.

Providers:
  - OpenAIGenerator  — OpenAI Chat Completions (streaming)
  - GeminiGenerator  — Google Gemini (streaming)

Both generators implement a consistent interface:
  generate(prompt)         → str   (full response, buffered)
  stream(prompt)           → Iterator[str] (token-by-token chunks)
"""

import os
import time
import random
from typing import Callable, Iterator
from cli.ui import console, THEME


# ---------------------------------------------------------------------------
# Transient-failure retry helper (exponential backoff with jitter)
# ---------------------------------------------------------------------------

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_DELAY = 1.0
_DEFAULT_MAX_DELAY = 30.0


def _is_transient_error(exc: Exception) -> bool:
    """Best-effort detection of retryable provider errors across SDK variants."""
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    transient_markers = (
        "timeout", "timed out", "rate limit", "temporarily", "unavailable",
        "overloaded", "connection reset", "econnreset", "502", "503", "504",
    )
    return any(marker in msg for marker in transient_markers)


def _retry_with_backoff(
    fn: Callable,
    *args,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_delay: float = _DEFAULT_BASE_DELAY,
    max_delay: float = _DEFAULT_MAX_DELAY,
    label: str = "provider call",
    **kwargs,
):
    """
    Invokes ``fn(*args, **kwargs)`` with exponential-backoff retry on transient
    errors. Non-transient errors propagate immediately.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt >= max_retries or not _is_transient_error(e):
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            delay += random.uniform(0, delay * 0.25)  # 0–25% jitter
            console.print(
                f"  [{THEME['DIM']}]↻ {label}: transient error "
                f"(attempt {attempt + 1}/{max_retries}) — retrying in {delay:.1f}s[/]"
            )
            time.sleep(delay)
    if last_exc:
        raise last_exc


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Gemini provider
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Strategy-based orchestrator
# ---------------------------------------------------------------------------

class IAAgent:
    """
    Orchestrator that wraps any text generator (Strategy Pattern) and
    exposes domain-specific OSINT tasks: Google Dork generation, etc.
    """

    def __init__(self, generator):
        self.generator = generator

    def generate_gdork(self, description: str) -> str | None:
        """
        Synthesizes an optimized Google Dork from a natural-language description.
        Streams tokens live to the terminal (real token-by-token rendering)
        and returns the assembled dork. Retries automatically on transient
        provider errors via the underlying generator.

        Args:
            description: Human-readable target description.

        Returns:
            The generated dork string (stripped), or None on failure.
        """
        prompt = self._build_prompt(description)
        try:
            buffer: list[str] = []
            console.print()
            for token in self.generator.stream(prompt, render=False):
                if not token:
                    continue
                print(token, end="", flush=True)
                buffer.append(token)
            print()
            result = "".join(buffer).strip()
            return result or None
        except TypeError:
            # Generator.stream() may not accept the render kwarg in older versions.
            try:
                return self.generator.generate(prompt)
            except Exception as e:
                console.print(f"  [{THEME['ERROR']}]✘[/]  Error generating dork: {e}")
                return None
        except Exception as e:
            console.print(f"  [{THEME['ERROR']}]✘[/]  Error generating dork: {e}")
            return None

    def _build_prompt(self, description: str) -> str:
        return f"""
Your task is to act as an OSINT expert and generate a precise and effective Google Dork
based on the user's description. A Google Dork uses advanced search operators to find
specific information that is not easily accessible through conventional searches.

Instructions:
1. Analyze the user's description to identify keywords, file types, domains, and any other constraints.
2. Translate these requirements into the corresponding Google operators (e.g., `site:`, `filetype:`, `inurl:`, `intitle:`, etc.).
3. Combine the operators logically to create a cohesive and efficient dork.
4. Return ONLY the generated dork, without any additional explanations or text.

Examples:

User description: "Find annual reports in PDF format from Microsoft."
Google Dork: filetype:pdf "annual report" site:microsoft.com

User description: "Search for admin login pages on educational sites in Colombia."
Google Dork: site:.edu.co intitle:"admin login" | inurl:"admin"

User description: "I want to find Excel spreadsheets containing price lists for electronic products."
Google Dork: filetype:xlsx "price list" "electronic products"

Now, generate the Google Dork for the following description:

User description: "{description}"
"""
