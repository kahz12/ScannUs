"""Every provider raises ProviderError when it cannot answer, also partway through a stream."""

from types import SimpleNamespace

import pytest

from core.ai_agent import IAAgent
from core.providers import (
    AnthropicGenerator, GeminiGenerator, OllamaGenerator, OpenAIGenerator, ProviderError,
)


def broken_after(*chunks):
    """Yields *chunks*, then breaks like a dropped connection."""
    yield from chunks
    raise ConnectionError("connection dropped")


def read(generator):
    """The chunks a provider yields before it raises, and the failure message."""
    seen = []
    with pytest.raises(ProviderError) as failure:
        for chunk in generator.stream("prompt"):
            seen.append(chunk)
    return seen, str(failure.value)


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY_FOR_GEMINI", raising=False)
    return GeminiGenerator()


def gemini_stream(gemini, chunks):
    gemini.client = SimpleNamespace(models=SimpleNamespace(
        generate_content_stream=lambda **kwargs: chunks))


def openai_with(monkeypatch, create):
    class FakeOpenAI:
        def __init__(self, timeout=60.0):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    return OpenAIGenerator()


def claude_with(monkeypatch, stream):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")

    class FakeAnthropic:
        def __init__(self, api_key, timeout):
            self.messages = SimpleNamespace(stream=stream)

    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)
    return AnthropicGenerator()


def ollama_with(monkeypatch, lines):
    ollama = OllamaGenerator(host="http://ollama.test")
    monkeypatch.setattr(ollama, "_ping", lambda: True)
    monkeypatch.setattr(ollama._requests, "post", lambda url, json, timeout, stream: SimpleNamespace(
        raise_for_status=lambda: None, iter_lines=lambda decode_unicode=True: lines))
    return ollama


class Context:
    """Stands in for the context manager Anthropic's messages.stream() returns."""

    def __init__(self, text_stream):
        self.text_stream = text_stream

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestStreamBrokenPartway:
    def test_gemini(self, gemini):
        gemini_stream(gemini, broken_after(SimpleNamespace(text="Hel")))

        assert read(gemini) == (["Hel"], "Gemini stream: connection dropped")

    def test_openai(self, monkeypatch):
        chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hel"))])
        generator = openai_with(monkeypatch, lambda **kwargs: broken_after(chunk))

        assert read(generator) == (["Hel"], "OpenAI stream: connection dropped")

    def test_claude(self, monkeypatch):
        generator = claude_with(monkeypatch, lambda **kwargs: Context(broken_after("Hel")))

        assert read(generator) == (["Hel"], "Claude stream: connection dropped")

    def test_ollama(self, monkeypatch):
        generator = ollama_with(monkeypatch, broken_after('{"response": "Hel"}'))

        assert read(generator) == (["Hel"], "Ollama stream: connection dropped")


class TestNoReplyAtAll:
    def test_gemini_without_a_key(self, gemini):
        assert read(gemini) == ([], "Gemini: client not initialized — "
                                    "check GOOGLE_API_KEY_FOR_GEMINI.")

    def test_openai_request_rejected(self, monkeypatch):
        def reject(**kwargs):
            raise RuntimeError("invalid api key")

        assert read(openai_with(monkeypatch, reject)) == ([], "OpenAI: invalid api key")

    def test_claude_request_rejected(self, monkeypatch):
        def reject(**kwargs):
            raise RuntimeError("invalid x-api-key")

        assert read(claude_with(monkeypatch, reject)) == ([], "Claude: invalid x-api-key")

    def test_ollama_daemon_down(self, monkeypatch):
        ollama = OllamaGenerator(host="http://ollama.test")
        monkeypatch.setattr(ollama, "_ping", lambda: False)

        seen, message = read(ollama)

        assert seen == []
        assert message.startswith("Ollama: daemon not reachable at http://ollama.test")

    def test_ollama_error_line_is_reported_once(self, monkeypatch):
        generator = ollama_with(monkeypatch, iter(['{"error": "model not found"}']))

        assert read(generator) == ([], "Ollama: model not found")


class TestCallers:
    def test_rendered_output_ends_its_line_before_the_failure(self, gemini, capsys):
        gemini_stream(gemini, broken_after(SimpleNamespace(text="Hel")))

        with pytest.raises(ProviderError):
            gemini.generate("prompt")

        assert capsys.readouterr().out.endswith("Hel\n")

    def test_dork_generation_reports_the_failure(self, gemini, capsys):
        assert IAAgent(gemini).generate_gdork("acme staff") is None
        assert "client not initialized" in " ".join(capsys.readouterr().out.split())
