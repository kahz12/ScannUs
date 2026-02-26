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
from cli.ui import console, THEME


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------

class OpenAIGenerator:
    """
    OpenAI Chat Completions wrapper.
    Supports both buffered and streaming generation.
    """

    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name
        from openai import OpenAI as _OpenAI
        self.client = _OpenAI()

    def generate(self, prompt: str) -> str:
        """
        Sends a prompt and returns the full response as a single string.
        Uses streaming internally and renders a live token feed in the terminal.
        """
        return "".join(self.stream(prompt, render=True))

    def stream(self, prompt: str, render: bool = False):
        """
        Streams the model response token-by-token.

        Args:
            prompt: The instruction for the model.
            render:  If True, tokens are printed live to the terminal.

        Yields:
            str: Individual text chunks as they arrive.
        """
        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with OpenAI ({self.model_name})…[/]"
        )

        stream = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )

        buffer = []
        if render:
            # Live streaming: print each token without newlines until done
            console.print()
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    print(delta, end="", flush=True)
                    buffer.append(delta)
            print()  # Final newline after stream ends
        else:
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    buffer.append(delta)
                    yield delta

        if render:
            # When render=True, yield the full buffered result
            yield "".join(buffer)


# ---------------------------------------------------------------------------
# Gemini provider
# ---------------------------------------------------------------------------

class GeminiGenerator:
    """
    Google Gemini API wrapper via the `google-genai` SDK.
    Supports buffered and streaming generation.
    """

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.model_name = model_name
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

    def generate(self, prompt: str) -> str:
        """
        Sends a prompt and streams the response, rendering tokens live.
        Returns the full response as a single string when done.
        """
        if not self.client:
            self._initialize_client()
            if not self.client:
                return "Error: Gemini client not initialized — check GOOGLE_API_KEY_FOR_GEMINI."

        console.print(
            f"  [{THEME['DIM']}]⟳ Generating with Gemini ({self.model_name})…[/]"
        )

        try:
            chunks = []
            console.print()
            # generate_content_stream yields incremental response parts
            for chunk in self.client.models.generate_content_stream(
                model=self.model_name,
                contents=prompt,
            ):
                text = chunk.text or ""
                if text:
                    print(text, end="", flush=True)
                    chunks.append(text)
            print()  # Final newline
            return "".join(chunks)

        except AttributeError:
            # Fallback: SDK version without streaming — use buffered call
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                )
                return response.text or ""
            except Exception as e:
                return f"Error during Gemini generation: {e}"
        except Exception as e:
            return f"Error during Gemini generation: {e}"

    def stream(self, prompt: str):
        """
        Yields text chunks from the Gemini streaming API.
        Does NOT print to the terminal — caller decides how to consume.
        """
        if not self.client:
            self._initialize_client()

        try:
            for chunk in self.client.models.generate_content_stream(
                model=self.model_name,
                contents=prompt,
            ):
                text = chunk.text or ""
                if text:
                    yield text
        except Exception as e:
            yield f"[Streaming error: {e}]"


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

        Args:
            description: Human-readable target description.

        Returns:
            The generated dork string, or None on failure.
        """
        prompt = self._build_prompt(description)
        try:
            return self.generator.generate(prompt)
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
