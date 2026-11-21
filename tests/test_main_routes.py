"""Command-line routes of ``main.main`` not covered by the exit-code tests."""

import sys
from types import SimpleNamespace

import pytest

import main
import utils.results_parse as rp
from core import state


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


@pytest.fixture
def run(tmp_path, monkeypatch, record):
    """Runs main() with *flags*; returns its exit code, or None when it just returns."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rp, "DIR_REPORTS", str(tmp_path))
    monkeypatch.setattr(main, "init_directories", lambda: None)
    monkeypatch.setattr(main, "setup_logging", lambda debug: None)
    monkeypatch.setattr(main, "print_startup_banner", lambda has_key: None)
    monkeypatch.setattr(main, "load_environment", lambda: None)
    monkeypatch.setattr(state, "LAST_RESULTS", [])
    monkeypatch.setattr(state, "CURRENT_CASE",
                        {"search_params": {}, "results": [], "evidence": [], "investigation": None})

    def go(*flags):
        monkeypatch.setattr(sys, "argv", ["main.py", *flags])
        try:
            main.main()
        except SystemExit as stop:
            return stop.code
        return None

    return go


class TestStartRoutes:
    def test_help(self, run, monkeypatch, record):
        shown = record()
        monkeypatch.setattr(main, "show_custom_help", shown)

        assert run("--help") == 0
        assert len(shown.calls) == 1

    def test_no_flags_opens_the_menu(self, run, monkeypatch, record):
        menu = record()
        monkeypatch.setattr(main, "show_main_menu", menu)

        assert run() == 0
        assert len(menu.calls) == 1


class TestCache:
    @pytest.fixture
    def cache(self, monkeypatch):
        fake = SimpleNamespace(cleared=[])
        fake.stats = lambda: {"rows": 3, "hits": 1}
        fake.clear = lambda namespace: fake.cleared.append(namespace) or 5
        monkeypatch.setattr("core.cache.get_cache", lambda: fake)
        return fake

    def test_stats(self, run, cache, flat):
        assert run("--cache-stats") == 0
        assert "rows: 3" in flat()

    @pytest.mark.parametrize("flags, namespace, label", [
        (["--cache-clear"], None, "everything"),
        (["--cache-clear", "whois"], "whois", "namespace 'whois'"),
    ])
    def test_clear(self, run, cache, flat, flags, namespace, label):
        assert run(*flags) == 0
        assert cache.cleared == [namespace]
        assert f"Cleared {label}: 5 row(s) removed" in flat()


class TestHibpRoutes:
    def test_breach_details(self, run, monkeypatch, flat):
        monkeypatch.setattr("analysis.hibp.hibp_breach", lambda name: {
            "Name": "Adobe", "BreachDate": "2013-10-04", "Domain": "adobe.com",
            "PwnCount": 152445165, "DataClasses": ["Passwords"], "IsVerified": True,
            "Description": "Customer records leaked."})

        assert run("--hibp-breach", "Adobe") == 0
        out = flat()
        assert "152,445,165" in out and "Customer records leaked." in out

    def test_unknown_breach(self, run, monkeypatch, flat):
        monkeypatch.setattr("analysis.hibp.hibp_breach", lambda name: None)

        assert run("--hibp-breach", "Nope") == 1
        assert "No record for breach 'Nope'" in flat()

    @pytest.mark.parametrize("typed, count, code", [
        ("hunter2", 17, 0), ("hunter2", None, 1), ("", 0, 1), (EOFError(), 0, 1)])
    def test_password(self, run, monkeypatch, typed, count, code):
        def getpass(prompt):
            if isinstance(typed, BaseException):
                raise typed
            return typed

        monkeypatch.setattr("getpass.getpass", getpass)
        monkeypatch.setattr("analysis.hibp.check_password", lambda password: count)

        assert run("--hibp-password") == code


class TestOtherRoutes:
    @pytest.mark.parametrize("found, code", [(True, 0), (False, 1)])
    def test_reverse_image(self, run, monkeypatch, found, code):
        monkeypatch.setattr(main, "do_reverse_image_search", lambda url: found)

        assert run("-rev", "https://img.test/a.png") == code

    def test_plan_that_cannot_be_saved(self, run, monkeypatch):
        monkeypatch.setattr("cli.actions.do_query_planner",
                            lambda goal: {"steps": [{"tool": "search"}]})
        monkeypatch.setattr(main, "save_case_as", lambda name: False)

        assert run("-p", "Who runs acme.test?", "--save-case", "acme") == 1


class TestAiRoutes:
    @pytest.fixture
    def agent(self, monkeypatch):
        holder = SimpleNamespace(dork="site:acme.test filetype:pdf")
        agent = SimpleNamespace(generate_gdork=lambda description: holder.dork)
        holder.agent = agent
        monkeypatch.setattr(main, "select_ia_agent", lambda: holder.agent)
        return holder

    @pytest.mark.parametrize("dork, code", [("site:acme.test filetype:pdf", 0), (None, 1)])
    def test_dork(self, run, agent, flat, dork, code):
        agent.dork = dork

        assert run("-gd", "acme reports") == code
        assert ("Dork Generated" in flat()) is (code == 0)

    def test_no_agent(self, run, agent, flat):
        agent.agent = None

        assert run("-gd", "acme reports") == 1
        assert "An AI agent is required" in flat()

    @pytest.mark.parametrize("loaded, code", [(False, 1), (True, 0)])
    def test_load_case(self, run, agent, monkeypatch, record, loaded, code):
        browser = record()
        monkeypatch.setattr(main, "load_case", lambda: loaded)
        monkeypatch.setattr("cli.menus.interactive_analysis_menu", browser)

        assert run("--load-case") == code
        assert len(browser.calls) == (1 if loaded else 0)


class TestSearchRoute:
    @pytest.fixture
    def searches(self, monkeypatch, record):
        rows = [{"title": "A", "link": "https://acme.test/report.pdf", "description": "d"},
                {"title": "B", "link": "https://acme.test/page", "description": "d"}]
        fakes = SimpleNamespace(search=record(rows), deep=record(rows), rows=rows)
        monkeypatch.setattr("cli.actions.do_search", fakes.search)
        monkeypatch.setattr("cli.actions.do_deep_search", fakes.deep)
        return fakes

    def test_guided_flags_make_an_and_query(self, run, searches):
        assert run("-n", "Ana Lee", "-u", "alee", "-b", "CEO") is None

        (query, *_), _ = searches.search.calls[0]
        assert query == '"Ana Lee" AND "alee" AND "CEO"'

    def test_email_or_phone_runs_a_deep_search(self, run, searches):
        assert run("-e", "ana@acme.test", "-t", "+14155552671") is None

        (query, *_), _ = searches.deep.calls[0]
        assert query == '"ana@acme.test" AND "+14155552671"'
        assert searches.search.calls == []

    def test_no_query(self, run, searches, flat):
        assert run("--engine", "brave") == 1
        assert "You must provide a query" in flat()

    def test_failed_search(self, run, monkeypatch, record):
        monkeypatch.setattr("cli.actions.do_search", record(None))

        assert run("-q", "acme") == 1

    def test_interactive_search_leaves_exports_to_its_menu(self, run, searches, monkeypatch,
                                                          record):
        monkeypatch.setattr(main, "select_ia_agent", lambda: "agent")
        exported = record()
        monkeypatch.setattr(main, "_export_results", exported)

        assert run("-q", "acme", "-i") is None
        assert exported.calls == []

    @pytest.mark.parametrize("types, fetched", [
        ("pdf", ["https://acme.test/report.pdf"]),
        ("all", ["https://acme.test/report.pdf", "https://acme.test/page"]),
    ])
    def test_download_by_extension(self, run, searches, monkeypatch, types, fetched):
        seen = []

        class FileDownload:
            def download_file(self, url, metadata):
                seen.append((url, metadata))

        monkeypatch.setattr(main, "FileDownload", FileDownload)

        run("-q", "acme", "--download", types, "--metadata")

        assert seen == [(url, True) for url in fetched]

    @pytest.mark.parametrize("saved, code", [(True, None), (False, 1)])
    def test_save_case(self, run, searches, monkeypatch, saved, code):
        monkeypatch.setattr(main, "save_case_as", lambda name: saved)

        assert run("-q", "acme", "--save-case", "acme") == code
