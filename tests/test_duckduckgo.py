import pytest

from cli import actions
from core import state
from core.cache import SQLiteCache
from core.planner import _dispatch_search
from search.engines import duckduckgosearch
from search.engines.cache import search_cache
from search.engines.duckduckgosearch import DuckDuckGoSearch


QUERY = "target"
CHALLENGE = (
    '<div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div>'
    '<img src="../assets/anomaly/images/challenge/18bfa8e9.jpg">'
)


def results_page(title="Example", snippet="A snippet", link="https://site.test/a"):
    return (
        '<div class="result results_links web-result">'
        f'<h2 class="result__title"><a class="result__a" href="{link}">{title}</a></h2>'
        f'<a class="result__snippet" href="{link}">{snippet}</a>'
        "</div>"
    )


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def _no_engine_keys(monkeypatch):
    """A developer's real key must not move these searches to another engine."""
    for name in ("BRAVE_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Send the shared search cache to a temporary database."""
    sqlite_cache = SQLiteCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("search.engines.cache.get_cache", lambda: sqlite_cache)
    return sqlite_cache


@pytest.fixture
def serve(monkeypatch):
    """Queue the responses DuckDuckGo gives; returns the list of remaining ones."""
    queued = []

    def queue(*responses):
        queued.extend(responses)
        return queued

    def fake_post(self, url, data, timeout):
        return queued.pop(0)

    monkeypatch.setattr("requests.Session.post", fake_post)
    return queue


def cache_key(pages=1):
    return search_cache.make_key("duckduckgo", QUERY, pages=pages, start=1)


def test_challenge_raises_and_is_not_cached(cache, serve):
    serve(FakeResponse(CHALLENGE, status_code=202))

    with pytest.raises(RuntimeError, match="blocked"):
        DuckDuckGoSearch().search(QUERY)

    assert cache.get("search", cache_key()) is None


def test_challenge_served_with_http_200_is_detected(cache, serve):
    serve(FakeResponse(CHALLENGE))

    with pytest.raises(RuntimeError, match="blocked"):
        DuckDuckGoSearch().search(QUERY)


def test_results_mentioning_the_marker_are_not_a_block(cache, serve):
    serve(FakeResponse(results_page(title="anomaly detection", snippet="assets/anomaly/ docs")))

    results = DuckDuckGoSearch().search(QUERY)

    assert [r["title"] for r in results] == ["anomaly detection"]


def test_page_without_results_is_empty_and_not_cached(cache, serve):
    remaining = serve(FakeResponse("<div>No results.</div>"), FakeResponse(results_page()))

    assert DuckDuckGoSearch().search(QUERY) == []
    assert len(remaining) == 1

    assert len(DuckDuckGoSearch().search(QUERY)) == 1
    assert remaining == []


def test_results_are_served_from_cache_on_the_second_search(cache, serve):
    remaining = serve(FakeResponse(results_page()))

    first = DuckDuckGoSearch().search(QUERY)
    second = DuckDuckGoSearch().search(QUERY)

    assert second == first
    assert remaining == []


def test_empty_entry_left_by_an_earlier_block_is_ignored(cache, serve):
    cache.set("search", cache_key(), [])
    serve(FakeResponse(results_page()))

    assert len(DuckDuckGoSearch().search(QUERY)) == 1


def test_block_on_a_later_page_keeps_results_without_caching(cache, serve, monkeypatch):
    warnings = []
    monkeypatch.setattr(duckduckgosearch, "print_warn", warnings.append)
    serve(FakeResponse(results_page()), FakeResponse(CHALLENGE, status_code=202))

    results = DuckDuckGoSearch().search(QUERY, pages=2)

    assert len(results) == 1
    assert "page 2" in warnings[0]
    assert cache.get("search", cache_key(pages=2)) is None


def test_block_reaches_the_user_as_an_error(cache, serve, monkeypatch):
    errors, successes = [], []
    monkeypatch.setattr(actions, "print_error", errors.append)
    monkeypatch.setattr(actions, "print_success", successes.append)
    monkeypatch.setattr(state, "LAST_RESULTS", [{"link": "https://old.test"}])
    serve(FakeResponse(CHALLENGE, status_code=202))

    actions.do_search(QUERY, "duckduckgo", 1, 1, False, None)

    assert "blocked" in errors[0]
    assert successes == []
    assert state.LAST_RESULTS == [{"link": "https://old.test"}]


def test_block_reaches_the_planner_as_an_error(cache, serve):
    serve(FakeResponse(CHALLENGE, status_code=202))

    result = _dispatch_search({"query": QUERY}, None)

    assert result["status"] == "error"
    assert "blocked" in result["summary"]
