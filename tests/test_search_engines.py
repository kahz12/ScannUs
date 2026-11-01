"""Engine selection, the move to Brave when DuckDuckGo blocks, and Brave's limits."""

from types import SimpleNamespace

import pytest

from cli import actions
from cli.parser import get_parser
from core import config
from core.ai_agent import IAAgent
from core.cache import SQLiteCache
from core.planner import TOOL_CATALOG
from search.engines import bravesearch
from search.engines.bravesearch import BraveSearch
from search.engines.cache import search_cache
from search.engines.duckduckgosearch import DuckDuckGoSearch, SearchBlockedError


QUERY = "target"
RESULT = {"title": "T", "description": "D", "link": "https://site.test/a"}


@pytest.fixture(autouse=True)
def _only_brave_can_take_over(monkeypatch):
    """A developer's real keys must not move these searches to other engines."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Send the shared search cache to a temporary database."""
    sqlite_cache = SQLiteCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("search.engines.cache.get_cache", lambda: sqlite_cache)
    return sqlite_cache


class FakeBraveAPI:
    """Answers like the Brave API, recording every requested page offset."""

    def __init__(self):
        self.offsets = []
        self.last_page = 99
        self.fail_at = None

    def get(self, url, headers, params, timeout):
        offset = params["offset"]
        self.offsets.append(offset)
        if offset == self.fail_at:
            raise ConnectionError("quota exhausted")
        body = {
            "query": {"more_results_available": offset < self.last_page},
            "web": {"results": [{"title": f"Page {offset}", "description": "d",
                                 "url": f"https://site.test/{offset}"}]},
        }
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)


@pytest.fixture
def brave_api(monkeypatch):
    api = FakeBraveAPI()
    monkeypatch.setattr(bravesearch.requests, "get", api.get)
    return api


def stub_engines(monkeypatch, duckduckgo_error=None):
    """Replaces both engines; returns the keys Brave was created with."""
    brave_keys = []

    class FakeDuckDuckGo:
        def search(self, query, pages, start_page):
            if duckduckgo_error:
                raise duckduckgo_error
            return [RESULT]

    class FakeBrave:
        def __init__(self, key):
            brave_keys.append(key)

        def search(self, query, pages, start_page):
            return [RESULT]

    monkeypatch.setattr(actions, "DuckDuckGoSearch", FakeDuckDuckGo)
    monkeypatch.setattr(actions, "BraveSearch", FakeBrave)
    return brave_keys


class TestEngineChoice:
    def test_unknown_engine_is_an_error_instead_of_a_silent_default(self):
        with pytest.raises(ValueError, match="Unknown search engine 'google'"):
            actions.get_search_engine("google", 1, 1, QUERY)

    def test_command_line_rejects_google(self, capsys):
        with pytest.raises(SystemExit):
            get_parser().parse_args(["--engine", "google"])
        assert "invalid choice" in capsys.readouterr().err

    def test_command_line_accepts_any_case(self):
        assert get_parser().parse_args(["--engine", "BRAVE"]).engine == "brave"

    def test_language_flag_is_gone(self):
        with pytest.raises(SystemExit):
            get_parser().parse_args(["--lang", "lang_es"])

    def test_brave_without_a_key_names_what_is_missing(self, monkeypatch):
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="BRAVE_API_KEY"):
            actions.get_search_engine("brave", 1, 1, QUERY)

    def test_planner_is_not_offered_google(self):
        assert "google" not in TOOL_CATALOG["search"]["args"]["engine"]

    def test_setup_wizard_does_not_ask_for_google_search(self, monkeypatch):
        for name in ("GOOGLE_API_KEY_FOR_GEMINI", "BRAVE_API_KEY", "HIBP_API_KEY",
                     "ANTHROPIC_API_KEY"):
            monkeypatch.setenv(name, "kept")
        saved = []
        monkeypatch.setattr(config, "_prompt", lambda label, hint="": "")
        monkeypatch.setattr(config, "set_key", lambda path, key, value: saved.append(key))

        config.env_config()

        assert "BRAVE_API_KEY" in saved
        assert "API_KEY_GOOGLE" not in saved
        assert "SEARCH_ENGINE_ID" not in saved


class TestMoveToBrave:
    def test_blocked_duckduckgo_uses_brave_and_says_so(self, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "brave-key")
        brave_keys = stub_engines(monkeypatch, SearchBlockedError("blocked"))
        warnings = []
        monkeypatch.setattr(actions, "print_warn", warnings.append)

        assert actions.get_search_engine("duckduckgo", 1, 1, QUERY) == [RESULT]

        assert brave_keys == ["brave-key"]
        assert "Brave" in warnings[0]

    def test_blocked_duckduckgo_without_a_key_stays_an_error(self, monkeypatch):
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        brave_keys = stub_engines(monkeypatch, SearchBlockedError("blocked"))

        with pytest.raises(SearchBlockedError):
            actions.get_search_engine("duckduckgo", 1, 1, QUERY)

        assert brave_keys == []

    def test_working_duckduckgo_spends_no_brave_credit(self, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "brave-key")
        brave_keys = stub_engines(monkeypatch)

        assert actions.get_search_engine("duckduckgo", 1, 1, QUERY) == [RESULT]
        assert brave_keys == []

    def test_network_errors_spend_no_brave_credit(self, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "brave-key")
        brave_keys = stub_engines(monkeypatch, RuntimeError("network down"))

        with pytest.raises(RuntimeError, match="network down"):
            actions.get_search_engine("duckduckgo", 1, 1, QUERY)

        assert brave_keys == []


class TestBravePaging:
    def test_requests_stop_when_no_page_is_left(self, cache, brave_api):
        brave_api.last_page = 1

        results = BraveSearch("key").search(QUERY, pages=5)

        assert brave_api.offsets == [0, 1]
        assert len(results) == 2

    def test_missing_availability_flag_stops_paging(self, cache, monkeypatch):
        offsets = []

        def fake_get(url, headers, params, timeout):
            offsets.append(params["offset"])
            body = {"web": {"results": [{"title": "T", "description": "D", "url": "u"}]}}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)

        monkeypatch.setattr(bravesearch.requests, "get", fake_get)

        BraveSearch("key").search(QUERY, pages=3)

        assert offsets == [0]

    def test_start_page_sets_the_first_offset(self, cache, brave_api):
        BraveSearch("key").search(QUERY, pages=2, start_page=3)

        assert brave_api.offsets == [2, 3]

    def test_pages_past_the_limit_are_not_requested(self, cache, brave_api, monkeypatch):
        warnings = []
        monkeypatch.setattr(bravesearch, "print_warn", warnings.append)

        results = BraveSearch("key").search(QUERY, pages=15)

        assert brave_api.offsets == list(range(10))
        assert len(results) == 10
        assert "10 pages" in warnings[0]

    def test_start_page_past_the_limit_is_an_error(self, cache, brave_api):
        with pytest.raises(RuntimeError, match="10 pages"):
            BraveSearch("key").search(QUERY, start_page=11)

        assert brave_api.offsets == []

    def test_failure_on_a_later_page_keeps_results_uncached(self, cache, brave_api, monkeypatch):
        warnings = []
        monkeypatch.setattr(bravesearch, "print_warn", warnings.append)
        brave_api.fail_at = 1

        results = BraveSearch("key").search(QUERY, pages=3)

        assert [r["title"] for r in results] == ["Page 0"]
        assert "page 2" in warnings[0]
        key = search_cache.make_key("brave", QUERY, pages=3, start=1)
        assert cache.get("search", key) is None

    def test_failure_on_the_first_page_is_an_error(self, cache, brave_api):
        brave_api.fail_at = 0

        with pytest.raises(RuntimeError, match="page 1"):
            BraveSearch("key").search(QUERY)

    def test_different_start_pages_do_not_share_a_cache_entry(self, cache, brave_api):
        brave_api.last_page = 0
        BraveSearch("key").search(QUERY)
        BraveSearch("key").search(QUERY, start_page=2)

        assert brave_api.offsets == [0, 1]


def test_duckduckgo_start_page_moves_the_offset(cache, monkeypatch):
    sent = []

    def fake_post(self, url, data, timeout):
        sent.append(data)
        return SimpleNamespace(text="<div>none</div>", status_code=200,
                               raise_for_status=lambda: None)

    monkeypatch.setattr("requests.Session.post", fake_post)

    DuckDuckGoSearch().search(QUERY, start_page=3)

    assert sent[0]["s"] == "60"


class TestDorkPrompts:
    def test_dork_prompt_teaches_only_shared_operators(self):
        prompt = IAAgent(None)._build_prompt("anything")
        examples = prompt.split("Examples:")[1]

        assert "inurl:" not in examples
        assert "|" not in examples
        assert "Do not use `inurl:`" in prompt
        assert "Google" not in prompt

    def test_planner_prompt_teaches_only_shared_operators(self):
        prompt = IAAgent(None)._planner_prompt("goal", None)

        assert "inurl:" not in prompt
        assert "Google Dork" not in prompt
        assert "Google-Dork" not in prompt
