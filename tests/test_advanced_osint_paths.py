"""
``analysis.advanced_osint`` with stand-ins for Playwright, Selenium and the
Wayback Machine: screenshots, the JavaScript-rendered scrape, and every
Wayback lookup with its failure paths.
"""

import sys
import types
from types import SimpleNamespace

import pytest
import requests

from analysis import advanced_osint as ao
from core import state
from core.cache import SQLiteCache
from core.findings import FindingsHub
from core.throttle import reset_buckets

URL = "https://acme.test/team"


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


@pytest.fixture
def cache(tmp_path, monkeypatch):
    sqlite_cache = SQLiteCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("core.cache.get_cache", lambda: sqlite_cache)
    reset_buckets()
    return sqlite_cache


# ---------------------------------------------------------------------------
# Browser stand-ins
# ---------------------------------------------------------------------------

class Driver:
    """A headless Firefox that serves *html* and grows by the given heights."""

    def __init__(self, html="<p>hi</p>", heights=(100, 100), width=None, full_page=True,
                 fail=None):
        self.page_source = html
        self.heights = list(heights)
        self.width = width
        self.saved = []
        self.quit_called = False
        self.fail = fail
        if not full_page:
            self.get_full_page_screenshot_as_file = None

    def set_page_load_timeout(self, seconds):
        pass

    def get(self, url):
        if self.fail:
            raise self.fail

    def execute_script(self, script, *args):
        if "scrollWidth" in script:
            return self.width
        if "scrollHeight" in script and "return" in script:
            return self.heights.pop(0) if self.heights else None
        return None

    def set_window_size(self, width, height):
        self.size = (width, height)

    def get_full_page_screenshot_as_file(self, path):
        self.saved.append(("full", path))

    def save_screenshot(self, path):
        self.saved.append(("viewport", path))

    def quit(self):
        self.quit_called = True


@pytest.fixture
def firefox(monkeypatch):
    """Makes selenium's Firefox return ``firefox.driver``."""
    holder = SimpleNamespace(driver=Driver())

    def make(*args, **kwargs):
        if isinstance(holder.driver, BaseException):
            raise holder.driver
        return holder.driver

    monkeypatch.setattr("selenium.webdriver.Firefox", make)
    monkeypatch.setattr(ao.time, "sleep", lambda seconds: None)
    return holder


def playwright_module(page_goto=None):
    """A ``playwright.sync_api`` module whose page can fail on goto."""
    shots = []

    class Page:
        def goto(self, url, **kwargs):
            if page_goto:
                raise page_goto

        def screenshot(self, path, full_page):
            shots.append((path, full_page))

    browser = SimpleNamespace(new_context=lambda **kw: SimpleNamespace(new_page=Page),
                              close=lambda: None)

    class Manager:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw: browser))

        def __exit__(self, *args):
            return False

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = Manager
    module.shots = shots
    return module


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------

class TestScreenshot:
    def test_slug(self):
        assert ao._slug(URL) == "acme_test"
        assert ao._slug("not a url") == "unknown_domain"

    def test_playwright_full_page(self, monkeypatch, tmp_path):
        module = playwright_module()
        monkeypatch.setitem(sys.modules, "playwright.sync_api", module)

        assert ao._screenshot_playwright(URL, str(tmp_path / "s.png")) is True
        assert module.shots == [(str(tmp_path / "s.png"), True)]

    def test_playwright_failure(self, monkeypatch, tmp_path, flat):
        monkeypatch.setitem(sys.modules, "playwright.sync_api",
                            playwright_module(page_goto=TimeoutError("networkidle")))

        assert ao._screenshot_playwright(URL, str(tmp_path / "s.png")) is False
        assert "Playwright screenshot failed: networkidle" in flat()

    def test_playwright_missing(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "playwright.sync_api", None)

        assert ao._screenshot_playwright(URL, str(tmp_path / "s.png")) is False

    @pytest.mark.parametrize("full_page, kind", [(True, "full"), (False, "viewport")])
    def test_selenium_resizes_to_the_page(self, firefox, tmp_path, full_page, kind):
        firefox.driver = Driver(heights=(50_000,), width=5000, full_page=full_page)

        assert ao._screenshot_selenium(URL, str(tmp_path / "s.png")) is True
        assert firefox.driver.size == (3840, 20_000)
        assert firefox.driver.saved == [(kind, str(tmp_path / "s.png"))]
        assert firefox.driver.quit_called

    def test_selenium_defaults_when_the_page_reports_no_size(self, firefox, tmp_path):
        firefox.driver = Driver(heights=())

        ao._screenshot_selenium(URL, str(tmp_path / "s.png"))

        assert firefox.driver.size == (1920, 3000)

    def test_selenium_failure(self, firefox, tmp_path, flat):
        firefox.driver = RuntimeError("geckodriver not found")

        assert ao._screenshot_selenium(URL, str(tmp_path / "s.png")) is False
        assert "Selenium screenshot failed: geckodriver not found" in flat()

    def test_selenium_missing(self, monkeypatch, tmp_path, flat):
        monkeypatch.setitem(sys.modules, "selenium", None)

        assert ao._screenshot_selenium(URL, str(tmp_path / "s.png")) is False
        assert ao.get_dynamic_text_from_url(URL) is None
        assert "Selenium is not installed" in flat()

    @pytest.mark.parametrize("engine, playwright, selenium, saved_by", [
        ("auto", True, False, "Playwright"),
        ("auto", False, True, "Selenium"),
        ("auto", False, False, None),
        ("playwright", False, True, None),
        ("selenium", True, True, "Selenium"),
    ])
    def test_engine_choice(self, monkeypatch, tmp_path, flat,
                           engine, playwright, selenium, saved_by):
        monkeypatch.setattr(ao, "_screenshot_playwright", lambda url, path: playwright)
        monkeypatch.setattr(ao, "_screenshot_selenium", lambda url, path: selenium)

        path = ao.take_screenshot(URL, output_dir=str(tmp_path), engine=engine)

        if saved_by:
            assert path == str(tmp_path / "acme_test_screenshot.png")
            assert f"Screenshot saved ({saved_by})" in flat()
        else:
            assert path is None


class TestDynamicText:
    def test_scrolls_until_the_page_stops_growing(self, firefox):
        firefox.driver = Driver(
            html="<script>x()</script><style>p{}</style><p>Ana Lee</p>\n\n<p>CEO</p>",
            heights=(100, 200, 200))

        assert ao.get_dynamic_text_from_url(URL) == "Ana Lee\nCEO"
        assert firefox.driver.heights == []
        assert firefox.driver.quit_called

    def test_failure(self, firefox, flat):
        firefox.driver = Driver(fail=RuntimeError("page load timeout"))

        assert ao.get_dynamic_text_from_url(URL) is None
        assert "Deep scraping failed: page load timeout" in flat()


# ---------------------------------------------------------------------------
# Wayback Machine
# ---------------------------------------------------------------------------

class Reply:
    def __init__(self, payload=None, status=200, content=b"", ctype="text/html", fail=None):
        self.payload, self.status_code, self.content = payload, status, content
        self.headers = {"Content-Type": ctype}
        self.fail = fail
        self.text = content.decode(errors="ignore")

    def raise_for_status(self):
        if self.fail:
            raise self.fail

    def json(self):
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


@pytest.fixture
def archive(monkeypatch):
    """Answers every Wayback request with ``archive.reply``; keeps the params sent."""
    holder = SimpleNamespace(reply=Reply([]), params=[])

    def get(url, params=None, **kwargs):
        holder.params.append(params)
        if isinstance(holder.reply, BaseException):
            raise holder.reply
        return holder.reply

    monkeypatch.setattr(ao.requests, "get", get)
    return holder


CDX = [["timestamp", "original", "mimetype", "statuscode", "digest"]] + [
    [f"20{year}0101000000", URL, "text/html", "200", f"d{year}"] for year in range(10, 25)]


class TestTimeline:
    timeline = staticmethod(ao.check_wayback_machine.__wrapped__)

    def test_years_and_preview(self, archive, flat):
        archive.reply = Reply(CDX)

        snapshots = self.timeline(URL, limit=5, from_year=2015, to_year=2020)

        assert archive.params[0]["from"] == "2015" and archive.params[0]["to"] == "2020"
        assert archive.params[0]["limit"] == "-5"
        assert [s["date"] for s in snapshots[:2]] == ["2024-01-01 00:00:00", "2023-01-01 00:00:00"]
        assert "(+10 older snapshots not shown)" in flat()

    @pytest.mark.parametrize("reply, result, message", [
        (requests.exceptions.ConnectionError("refused"), None, "CDX network error: refused"),
        (Reply(ValueError("not json")), None, "CDX returned invalid JSON"),
        (Reply([["timestamp"]]), [], "No snapshots found"),
    ])
    def test_failures(self, archive, flat, reply, result, message):
        archive.reply = reply

        assert self.timeline(URL) == result
        assert message in flat()

    def test_no_limit_asks_for_the_last_twenty(self, archive):
        archive.reply = Reply(CDX)

        assert len(self.timeline(URL, limit=0)) == 15
        assert archive.params[0]["limit"] == "-20"

    @pytest.mark.parametrize("ts, date", [
        ("20240501123045", "2024-05-01 12:30:45"), ("20240501", "2024-05-01"), ("2024", "2024")])
    def test_timestamp_format(self, ts, date):
        assert ao._format_cdx_timestamp(ts) == date


class TestResolveTimestamp:
    resolve = staticmethod(ao.wayback_resolve_timestamp.__wrapped__)

    @pytest.mark.parametrize("when, sent", [
        ("latest", {"limit": "-1"}),
        ("earliest", {"limit": "1"}),
        ("2018", {"from": "2018", "to": "2018", "limit": "-1"}),
        ("2018-05", {"from": "201805", "to": "201805", "limit": "-1"}),
    ])
    def test_fuzzy_specs(self, archive, when, sent):
        archive.reply = Reply([["timestamp"], ["20180512000000"]])

        assert self.resolve(URL, when) == "20180512000000"
        assert {k: archive.params[0][k] for k in sent} == sent

    def test_literal_timestamp_needs_no_request(self, archive):
        assert self.resolve(URL, "20180512000000") == "20180512000000"
        assert archive.params == []

    @pytest.mark.parametrize("when, reply", [
        ("someday", Reply([])),
        ("latest", Reply([["timestamp"]])),
        ("latest", requests.exceptions.ConnectionError("refused")),
    ])
    def test_nothing_found(self, archive, when, reply):
        archive.reply = reply

        assert self.resolve(URL, when) is None


class TestSnapshots:
    fetch = staticmethod(ao._wayback_fetch_uncached.__wrapped__)

    @pytest.mark.parametrize("ctype, content, text", [
        ("text/html; charset=utf-8", b"<script>x()</script><p>Ana Lee</p>", "Ana Lee"),
        ("text/plain", b"plain words", "plain words"),
        ("image/png", b"\x89PNG", ""),
    ])
    def test_text_by_content_type(self, archive, ctype, content, text):
        archive.reply = Reply(content=content, ctype=ctype)

        snap = self.fetch(URL, "20200101000000")

        assert snap["text"] == text
        assert snap["archive_url"] == f"https://web.archive.org/web/20200101000000id_/{URL}"

    def test_fetch_failure(self, archive, flat):
        archive.reply = Reply(fail=requests.exceptions.HTTPError("404"))

        assert self.fetch(URL, "20200101000000") is None
        assert "Wayback fetch failed: 404" in flat()

    def test_no_snapshot_for_the_spec(self, monkeypatch, flat):
        monkeypatch.setattr(ao, "wayback_resolve_timestamp", lambda url, when: None)

        assert ao.wayback_fetch_snapshot(URL, "1999") is None
        assert "No Wayback snapshot found" in flat()


def snapshot(text, ts="20200101000000"):
    return {"timestamp": ts, "date": ao._format_cdx_timestamp(ts), "archive_url": f"a/{ts}",
            "mime": "text/html", "size": len(text), "text": text}


@pytest.fixture
def snapshots(monkeypatch):
    """Serves ``snapshots[spec]`` for each requested timestamp spec."""
    table: dict = {}
    monkeypatch.setattr(ao, "wayback_fetch_snapshot", lambda url, ts=None: table.get(ts))
    return table


class TestExtract:
    def test_identifiers_become_evidence(self, snapshots, monkeypatch, flat):
        hub = FindingsHub()
        monkeypatch.setattr("core.findings.get_hub", lambda: hub)
        monkeypatch.setattr(state, "CURRENT_CASE",
                            {"search_params": {}, "results": [], "evidence": [], "investigation": None})
        snapshots["2020"] = snapshot("Write to ana@acme.test")

        result = ao.wayback_extract_pii(URL, "2020")

        assert result["counts"] == {"emails": 1}
        assert state.CURRENT_CASE["evidence"][0]["source"] == "a/20200101000000"
        assert [f.value for f in hub.of_kind("email")] == ["ana@acme.test"]
        assert "Wayback PII" in flat()

    def test_nothing_found(self, snapshots, flat):
        snapshots["2020"] = snapshot("Nothing here.")

        assert ao.wayback_extract_pii(URL, "2020")["counts"] == {}
        assert "No identifiers extracted" in flat()

    def test_no_snapshot(self, snapshots):
        assert ao.wayback_extract_pii(URL, "1999") is None


class TestDiff:
    def test_changes_are_counted_and_cut(self, snapshots, flat):
        snapshots["a"] = snapshot("\n".join(f"old {n}" for n in range(60)), "20200101000000")
        snapshots["b"] = snapshot("\n".join(f"new {n}" for n in range(60)), "20240101000000")

        result = ao.wayback_diff(URL, "a", "b", max_lines=10)

        assert (result["added_count"], result["removed_count"]) == (60, 60)
        assert result["identical"] is False
        assert "more diff lines not shown" in flat()

    def test_identical_snapshots(self, snapshots, flat):
        snapshots["a"] = snapshot("same", "20200101000000")
        snapshots["b"] = snapshot("same", "20240101000000")

        assert ao.wayback_diff(URL, "a", "b")["identical"] is True
        assert "content-identical" in flat()

    def test_missing_or_empty_snapshot(self, snapshots, flat):
        snapshots["a"] = snapshot("", "20200101000000")
        snapshots["b"] = snapshot("text", "20240101000000")

        assert ao.wayback_diff(URL, "a", "missing") is None
        assert ao.wayback_diff(URL, "a", "b") is None
        assert "no extractable text" in flat()
