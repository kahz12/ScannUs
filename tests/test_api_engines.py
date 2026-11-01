"""Tavily and Exa: the requests they send, their limits, and the engine that takes over."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from cli import actions, menus
from cli.parser import get_parser
from core import config
from core.cache import SQLiteCache
from core.planner import TOOL_CATALOG
from search.engines import SEARCH_ENGINES, api_query
from search.engines.api_query import result_window, split_site_filters, warn_ignored_operators
from search.engines.duckduckgosearch import SearchBlockedError
from search.engines.exasearch import ExaSearch
from search.engines.tavilysearch import TavilySearch


QUERY = "target"
KEY_VARS = ("BRAVE_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY")
RESULT = {"title": "T", "description": "D", "link": "https://site.test/a"}


def api_results(count):
    return [{"title": f"Title {n}", "url": f"https://site.test/{n}",
             "content": f"Snippet {n}", "highlights": [f"First {n}", f"Second {n}"]}
            for n in range(count)]


class FakeAPI:
    """Answers like a JSON search API, recording every request."""

    def __init__(self):
        self.calls = []
        self.status = 200
        self.body = {"results": api_results(25)}

    def post(self, url, headers, json, timeout):
        self.calls.append(SimpleNamespace(url=url, headers=headers, payload=json))

        def raise_for_status():
            if self.status >= 400:
                raise requests.HTTPError(f"HTTP {self.status}")

        def parse():
            if self.body is None:
                raise ValueError("not JSON")
            return self.body

        return SimpleNamespace(status_code=self.status,
                               raise_for_status=raise_for_status, json=parse)


@pytest.fixture
def api(tmp_path, monkeypatch):
    sqlite_cache = SQLiteCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("search.engines.cache.get_cache", lambda: sqlite_cache)
    fake = FakeAPI()
    monkeypatch.setattr(api_query.requests, "post", fake.post)
    return fake


@pytest.fixture
def warnings(monkeypatch):
    shown = []
    monkeypatch.setattr(api_query, "print_warn", shown.append)
    return shown


@pytest.fixture(params=[TavilySearch, ExaSearch], ids=["tavily", "exa"])
def engine(request):
    return request.param("secret-key")


class TestTavilyRequest:
    def test_sends_the_key_as_a_bearer_token(self, api):
        TavilySearch("secret-key").search(QUERY)

        call = api.calls[0]
        assert call.url == "https://api.tavily.com/search"
        assert call.headers == {"Authorization": "Bearer secret-key"}

    def test_uses_the_depth_that_costs_one_credit(self, api):
        TavilySearch("key").search(QUERY)

        assert api.calls[0].payload == {
            "query": QUERY, "search_depth": "basic", "max_results": 10,
        }

    def test_maps_the_response_to_the_shared_shape(self, api):
        results = TavilySearch("key").search(QUERY)

        assert results[0] == {"title": "Title 0", "description": "Snippet 0",
                              "link": "https://site.test/0"}

    def test_quoted_phrases_ask_for_an_exact_match(self, api):
        TavilySearch("key").search('"Juan Perez" acme')

        assert api.calls[0].payload["exact_match"] is True

    def test_site_operators_become_domain_lists(self, api):
        TavilySearch("key").search("report site:acme-corp.io -site:news.test")

        payload = api.calls[0].payload
        assert payload["query"] == "report"
        assert payload["include_domains"] == ["acme-corp.io"]
        assert payload["exclude_domains"] == ["news.test"]


class TestExaRequest:
    def test_sends_the_key_in_its_header(self, api):
        ExaSearch("secret-key").search(QUERY)

        call = api.calls[0]
        assert call.url == "https://api.exa.ai/search"
        assert call.headers == {"x-api-key": "secret-key"}

    def test_asks_for_snippets_without_paid_summaries(self, api):
        ExaSearch("key").search(QUERY)

        assert api.calls[0].payload == {
            "query": QUERY, "type": "auto", "numResults": 10,
            "contents": {"highlights": {"maxCharacters": 500}},
        }

    def test_maps_the_response_to_the_shared_shape(self, api):
        results = ExaSearch("key").search(QUERY)

        assert results[0] == {"title": "Title 0", "description": "First 0 Second 0",
                              "link": "https://site.test/0"}

    def test_site_operators_become_domain_lists(self, api):
        ExaSearch("key").search("report site:acme-corp.io -site:news.test")

        payload = api.calls[0].payload
        assert payload["query"] == "report"
        assert payload["includeDomains"] == ["acme-corp.io"]
        assert payload["excludeDomains"] == ["news.test"]


class TestSharedBehaviour:
    def test_second_search_spends_no_credit(self, api, engine):
        first = engine.search(QUERY)
        second = engine.search(QUERY)

        assert first == second
        assert len(api.calls) == 1

    def test_second_page_is_the_next_ten_results(self, api, engine):
        results = engine.search(QUERY, start_page=2)

        assert [r["link"] for r in results] == [f"https://site.test/{n}" for n in range(10, 20)]

    def test_start_pages_do_not_share_a_cache_entry(self, api, engine):
        engine.search(QUERY)
        engine.search(QUERY, start_page=2)

        assert len(api.calls) == 2

    def test_start_page_past_the_limit_spends_no_credit(self, api, engine):
        with pytest.raises(RuntimeError, match="results per query"):
            engine.search(QUERY, start_page=4)

        assert api.calls == []

    def test_results_without_a_link_are_dropped(self, api, engine):
        api.body = {"results": [{"title": "No link"}] + api_results(1)}

        assert [r["link"] for r in engine.search(QUERY)] == ["https://site.test/0"]

    def test_missing_title_and_snippet_stay_printable(self, api, engine):
        api.body = {"results": [{"title": None, "url": "https://site.test/x"}]}

        assert engine.search(QUERY) == [{"title": "https://site.test/x", "description": "",
                                         "link": "https://site.test/x"}]

    def test_empty_results_are_a_success_and_stay_uncached(self, api, engine):
        api.body = {"results": []}

        assert engine.search(QUERY) == []
        engine.search(QUERY)
        assert len(api.calls) == 2

    @pytest.mark.parametrize("status", [401, 429])
    def test_documented_rejections_explain_themselves(self, api, engine, status):
        api.status = status

        with pytest.raises(RuntimeError, match="rejected|rate limit"):
            engine.search(QUERY)

    def test_rejection_is_not_cached(self, api, engine):
        api.status = 401
        with pytest.raises(RuntimeError):
            engine.search(QUERY)

        api.status = 200
        assert engine.search(QUERY)

    def test_other_statuses_are_failures(self, api, engine):
        api.status = 500

        with pytest.raises(RuntimeError, match="Search API Error"):
            engine.search(QUERY)

    def test_unreadable_response_is_a_failure(self, api, engine):
        api.body = None

        with pytest.raises(RuntimeError, match="Search API Error"):
            engine.search(QUERY)

    def test_network_failure_is_a_failure(self, api, engine, monkeypatch):
        def refuse(*args, **kwargs):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(api_query.requests, "post", refuse)

        with pytest.raises(RuntimeError, match="refused"):
            engine.search(QUERY)

    def test_failure_messages_never_show_the_key(self, api, engine):
        api.status = 500

        with pytest.raises(RuntimeError) as failure:
            engine.search(QUERY)

        assert "secret-key" not in str(failure.value)

    def test_ignored_operators_warn_even_from_the_cache(self, api, engine, warnings):
        engine.search("filetype:pdf report")
        engine.search("filetype:pdf report")

        assert len(warnings) == 2
        assert "filetype:" in warnings[0]


def test_tavily_stops_at_twenty_results(api):
    with pytest.raises(RuntimeError, match="20 results"):
        TavilySearch("key").search(QUERY, start_page=3)

    assert api.calls == []


def test_exa_serves_the_results_left_on_a_short_last_page(api):
    results = ExaSearch("key").search(QUERY, start_page=3)

    assert len(results) == 5
    assert api.calls[0].payload["numResults"] == 25


@pytest.mark.parametrize("status, text", [(432, "plan limit"), (433, "pay-as-you-go")])
def test_tavily_explains_its_usage_limits(api, status, text):
    api.status = status

    with pytest.raises(RuntimeError, match=text):
        TavilySearch("key").search(QUERY)


def test_exa_explains_it_ran_out_of_credit(api):
    api.status = 402

    with pytest.raises(RuntimeError, match="no credit left"):
        ExaSearch("key").search(QUERY)


class TestResultWindow:
    @pytest.mark.parametrize("pages, start, expected", [
        (1, 1, (0, 10)),
        (2, 1, (0, 20)),
        (1, 2, (10, 20)),
        (0, 0, (0, 10)),
    ])
    def test_pages_become_a_slice(self, warnings, pages, start, expected):
        assert result_window("Tavily", pages, start, 10, 20) == expected
        assert warnings == []

    def test_request_past_the_limit_stops_there_and_warns(self, warnings):
        assert result_window("Exa", 5, 1, 10, 25) == (0, 25)
        assert "25 results" in warnings[0]

    def test_page_that_starts_inside_the_limit_is_served(self, warnings):
        assert result_window("Exa", 1, 3, 10, 25) == (20, 25)


class TestSiteFilters:
    @pytest.mark.parametrize("query, expected", [
        ("plain words", ("plain words", [], [])),
        ("report site:a.test", ("report", ["a.test"], [])),
        ("SITE:a.test report", ("report", ["a.test"], [])),
        ("site:a.test OR site:b.test report", ("report", ["a.test", "b.test"], [])),
        ("(site:a.test OR site:b.test) report", ("report", ["a.test", "b.test"], [])),
        ("report -site:a.test", ("report", [], ["a.test"])),
        ("site:a.test", ("a.test", ["a.test"], [])),
        ('"site:a.test" report', ('"site:a.test" report', [], [])),
        ("website:a.test report", ("website:a.test report", [], [])),
        ('filetype:pdf "annual report" site:a.test',
         ('filetype:pdf "annual report"', ["a.test"], [])),
    ])
    def test_split(self, query, expected):
        assert split_site_filters(query) == expected


class TestOperatorWarning:
    @pytest.mark.parametrize("query, names", [
        ("filetype:pdf report", ["filetype:"]),
        ("intitle:login -inurl:admin", ["inurl:", "intitle:"]),
        ("(intext:secret)", ["intext:"]),
    ])
    def test_operators_are_named(self, warnings, query, names):
        warn_ignored_operators("Tavily", query)

        assert all(name in warnings[0] for name in names)

    @pytest.mark.parametrize("query", ["plain words", "site:a.test report", "https://a.test/x"])
    def test_supported_queries_stay_quiet(self, warnings, query):
        warn_ignored_operators("Tavily", query)

        assert warnings == []


def stub_engines(monkeypatch, duckduckgo_error=None):
    """Replaces every engine; returns the (engine, key) pairs that were created."""
    created = []

    class FakeDuckDuckGo:
        def search(self, query, pages, start_page):
            if duckduckgo_error:
                raise duckduckgo_error
            return [RESULT]

    def fake(name):
        class FakeEngine:
            def __init__(self, key):
                created.append((name, key))

            def search(self, query, pages, start_page):
                return [RESULT]

        return FakeEngine

    monkeypatch.setattr(actions, "DuckDuckGoSearch", FakeDuckDuckGo)
    monkeypatch.setattr(actions, "BraveSearch", fake("brave"))
    monkeypatch.setattr(actions, "TavilySearch", fake("tavily"))
    monkeypatch.setattr(actions, "ExaSearch", fake("exa"))
    return created


@pytest.fixture
def no_keys(monkeypatch):
    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class TestEngineSelection:
    @pytest.mark.parametrize("engine_name, variable", [
        ("tavily", "TAVILY_API_KEY"), ("exa", "EXA_API_KEY"),
    ])
    def test_engine_without_a_key_names_what_is_missing(self, no_keys, engine_name, variable):
        with pytest.raises(EnvironmentError, match=variable):
            actions.get_search_engine(engine_name, 1, 1, QUERY)

    @pytest.mark.parametrize("engine_name, variable", [
        ("tavily", "TAVILY_API_KEY"), ("exa", "EXA_API_KEY"),
    ])
    def test_engine_gets_its_own_key(self, no_keys, engine_name, variable):
        created = stub_engines(no_keys)
        no_keys.setenv(variable, "its-key")

        assert actions.get_search_engine(engine_name, 1, 1, QUERY) == [RESULT]
        assert created == [(engine_name, "its-key")]

    def test_empty_key_from_the_template_counts_as_missing(self, no_keys):
        no_keys.setenv("TAVILY_API_KEY", "")

        with pytest.raises(EnvironmentError, match="TAVILY_API_KEY"):
            actions.get_search_engine("tavily", 1, 1, QUERY)

    @pytest.mark.parametrize("name", ["TAVILY", "Exa"])
    def test_command_line_accepts_them(self, name):
        assert get_parser().parse_args(["--engine", name]).engine == name.lower()

    def test_every_engine_is_offered_everywhere(self):
        assert [choice[1] for choice in menus._ENGINE_CHOICES] == list(SEARCH_ENGINES)
        for name in SEARCH_ENGINES:
            assert name in TOOL_CATALOG["search"]["args"]["engine"]


class TestMoveFromDuckDuckGo:
    @pytest.mark.parametrize("variables, expected", [
        (["TAVILY_API_KEY"], "tavily"),
        (["EXA_API_KEY"], "exa"),
        (["TAVILY_API_KEY", "EXA_API_KEY"], "tavily"),
        (["BRAVE_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY"], "brave"),
    ])
    def test_block_moves_to_the_first_engine_with_a_key(self, no_keys, variables, expected):
        created = stub_engines(no_keys, SearchBlockedError("blocked"))
        for variable in variables:
            no_keys.setenv(variable, "key")
        shown = []
        no_keys.setattr(actions, "print_warn", shown.append)

        assert actions.get_search_engine("duckduckgo", 1, 1, QUERY) == [RESULT]
        assert [name for name, _ in created] == [expected]
        assert expected.capitalize() in shown[0]

    def test_block_without_any_key_stays_a_failure(self, no_keys):
        created = stub_engines(no_keys, SearchBlockedError("blocked"))

        with pytest.raises(SearchBlockedError):
            actions.get_search_engine("duckduckgo", 1, 1, QUERY)

        assert created == []

    def test_working_duckduckgo_spends_no_credit(self, no_keys):
        created = stub_engines(no_keys)
        no_keys.setenv("TAVILY_API_KEY", "key")

        actions.get_search_engine("duckduckgo", 1, 1, QUERY)

        assert created == []


class TestConfiguration:
    def run_wizard(self, monkeypatch, tmp_path, answers):
        monkeypatch.chdir(tmp_path)
        saved = {}
        monkeypatch.setattr(config, "_prompt",
                            lambda label, hint="": answers.get(label.split()[0], ""))
        monkeypatch.setattr(config, "set_key",
                            lambda path, key, value: saved.__setitem__(key, value))
        for name in ("GOOGLE_API_KEY_FOR_GEMINI", "HIBP_API_KEY", "ANTHROPIC_API_KEY",
                     *KEY_VARS):
            monkeypatch.setenv(name, "kept")
        config.env_config()
        return saved

    def test_wizard_saves_both_keys(self, monkeypatch, tmp_path):
        saved = self.run_wizard(monkeypatch, tmp_path, {"Tavily": "tvly-new", "Exa": "exa-new"})

        assert saved["TAVILY_API_KEY"] == "tvly-new"
        assert saved["EXA_API_KEY"] == "exa-new"

    def test_blank_answer_keeps_the_saved_keys(self, monkeypatch, tmp_path):
        saved = self.run_wizard(monkeypatch, tmp_path, {})

        assert "TAVILY_API_KEY" not in saved
        assert "EXA_API_KEY" not in saved

    def test_template_lists_both_keys(self):
        template = Path(__file__).parent.parent / ".env.example"
        lines = template.read_text(encoding="utf-8").splitlines()

        assert "TAVILY_API_KEY=" in lines
        assert "EXA_API_KEY=" in lines
