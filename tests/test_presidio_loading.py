import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from search import smart_search
from search.smart_search import extract_information


TEXT = "contact alice@acme-corp.io"
EMAILS_ONLY = {"emails": ["alice@acme-corp.io"]}


@pytest.fixture(autouse=True)
def _fresh_presidio():
    """Each test starts unloaded, and the real analyzer returns afterwards."""
    smart_search._get_presidio.cache_clear()
    yield
    smart_search._get_presidio.cache_clear()


def use_fake_presidio(monkeypatch, engine):
    module = types.ModuleType("presidio_analyzer")
    module.AnalyzerEngine = engine
    monkeypatch.setitem(sys.modules, "presidio_analyzer", module)


def capture_warnings(monkeypatch):
    warnings = []
    monkeypatch.setattr(smart_search, "print_warn", warnings.append)
    return warnings


def test_starting_the_app_does_not_load_presidio():
    code = "import sys, main; print('presidio_analyzer' in sys.modules, 'spacy' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(smart_search.__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-2:] == ["False", "False"]


def test_analyzer_is_created_once_and_finds_entities(monkeypatch):
    created = []

    class FakeEngine:
        def __init__(self):
            created.append(self)

        def analyze(self, text, language):
            start = text.index("contact")
            return [SimpleNamespace(entity_type="PERSON", start=start, end=start + 13)]

    use_fake_presidio(monkeypatch, FakeEngine)

    extract_information(TEXT)
    result = extract_information(TEXT)

    assert result["presidio"] == {"PERSON": ["contact alice"]}
    assert len(created) == 1


def test_failed_model_download_warns_once_and_keeps_extracting(monkeypatch):
    warnings = capture_warnings(monkeypatch)

    def failed_download():
        raise SystemExit(1)

    use_fake_presidio(monkeypatch, failed_download)

    extract_information(TEXT)

    assert extract_information(TEXT) == EMAILS_ONLY
    assert len(warnings) == 1
    assert "en_core_web_lg" in warnings[0]


def test_uninstalled_presidio_is_skipped_silently(monkeypatch):
    warnings = capture_warnings(monkeypatch)
    monkeypatch.setitem(sys.modules, "presidio_analyzer", None)

    assert extract_information(TEXT) == EMAILS_ONLY
    assert warnings == []
