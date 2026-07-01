"""
core.providers — LLM provider wrappers with a common streaming interface.

Every generator implements:
    generate(prompt)            -> str            (full response, buffered)
    stream(prompt, render=...)  -> Iterator[str]  (token-by-token chunks)

Import them from here rather than the individual modules:
    from core.providers import GeminiGenerator, OllamaGenerator
"""

from core.providers.anthropic_provider import AnthropicGenerator
from core.providers.gemini_provider import GeminiGenerator
from core.providers.ollama_provider import OllamaGenerator
from core.providers.openai_provider import OpenAIGenerator

__all__ = [
    "OpenAIGenerator",
    "GeminiGenerator",
    "AnthropicGenerator",
    "OllamaGenerator",
]
