from types import SimpleNamespace

import pytest

from cli import menus
from core.providers import GeminiGenerator


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY_FOR_GEMINI", raising=False)


def test_default_model_is_used_without_configuration():
    assert GeminiGenerator().model_name == GeminiGenerator.DEFAULT_MODEL


def test_default_model_is_not_a_retired_one():
    assert GeminiGenerator.DEFAULT_MODEL != "gemini-2.0-flash"


def test_env_var_overrides_the_default(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")

    assert GeminiGenerator().model_name == "gemini-custom"


def test_blank_env_var_keeps_the_default(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "")

    assert GeminiGenerator().model_name == GeminiGenerator.DEFAULT_MODEL


def test_explicit_model_wins_over_the_env_var(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")

    assert GeminiGenerator(model_name="gemini-explicit").model_name == "gemini-explicit"


def test_requests_are_sent_with_the_configured_model(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")
    calls = []

    def fake_stream(model, contents):
        calls.append((model, contents))
        return iter([SimpleNamespace(text="Hello"), SimpleNamespace(text=None)])

    generator = GeminiGenerator()
    generator.client = SimpleNamespace(
        models=SimpleNamespace(generate_content_stream=fake_stream)
    )

    assert list(generator.stream("prompt")) == ["Hello"]
    assert calls == [("gemini-custom", "prompt")]


@pytest.mark.parametrize("configured, shown", [
    (None, GeminiGenerator.DEFAULT_MODEL),
    ("gemini-custom", "gemini-custom"),
])
def test_provider_menu_shows_the_model_in_use(monkeypatch, configured, shown):
    if configured:
        monkeypatch.setenv("GEMINI_MODEL", configured)
    seen = {}

    def fake_select(title, options, default=None):
        seen["options"] = options
        return "cancel"

    monkeypatch.setattr(menus, "select_menu", fake_select)

    assert menus.select_ia_agent() is None
    gemini_option = next(o for o in seen["options"] if o[1] == "ge")
    assert shown in gemini_option[2]
