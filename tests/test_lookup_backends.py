"""
``search.username_enum`` backend selection, failed runs and reporting, and
``search.reverse_image_engines`` failure paths and the engine fan-out.
"""

import json
import subprocess
from types import SimpleNamespace

import pytest
import requests

from search import reverse_image_engines as rie
from search import username_enum as ue


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


# ---------------------------------------------------------------------------
# Username enumeration
# ---------------------------------------------------------------------------

@pytest.fixture
def installed(monkeypatch):
    """Sets which backends look installed: ``installed("sherlock", "maigret")``."""
    def set_to(*names):
        monkeypatch.setattr(ue, "_SHERLOCK_BIN", "sherlock" if "sherlock" in names else None)
        monkeypatch.setattr(ue, "_MAIGRET_BIN", "maigret" if "maigret" in names else None)
    return set_to


class TestBackendChoice:
    @pytest.mark.parametrize("names, preference, chosen", [
        (("sherlock", "maigret"), "auto", "sherlock"),
        (("maigret",), None, "maigret"),
        ((), "auto", None),
        (("sherlock",), "Maigret", None),
        (("maigret",), "maigret", "maigret"),
        (("sherlock",), "whatsmyname", None),
    ])
    def test_select(self, installed, names, preference, chosen):
        installed(*names)

        assert ue._select_backend(preference) == chosen

    @pytest.mark.parametrize("backend, message", [
        ("auto", "No enumeration backend available"),
        ("maigret", "Backend 'maigret' is not installed"),
    ])
    def test_menu_says_what_is_missing(self, installed, flat, backend, message):
        installed()

        assert ue.username_enum("alee", backend=backend) is None
        assert message in flat()

    def test_programmatic_lookup_without_backend_or_name(self, installed):
        installed()

        assert ue.enumerate_username("alee") == []
        assert ue.enumerate_username("   ") == []


class TestFailedRuns:
    @pytest.mark.parametrize("runner, binary", [
        (ue._run_sherlock.__wrapped__, "_SHERLOCK_BIN"),
        (ue._run_maigret.__wrapped__, "_MAIGRET_BIN"),
    ])
    @pytest.mark.parametrize("failure, message", [
        (subprocess.TimeoutExpired("tool", 1), "timed out"),
        (FileNotFoundError("gone"), "binary disappeared mid-run"),
    ])
    def test_run_failures(self, monkeypatch, flat, runner, binary, failure, message):
        def run(*args, **kwargs):
            raise failure

        monkeypatch.setattr(ue, binary, "tool")
        monkeypatch.setattr(ue.subprocess, "run", run)

        assert runner("alee", 20) == []
        assert message in flat()

    @pytest.mark.parametrize("runner, binary, name, content", [
        (ue._run_sherlock.__wrapped__, "_SHERLOCK_BIN", "renamed.csv",
         "name,url_user,exists\nGitHub,https://github.test/alee,Claimed\n"),
        (ue._run_maigret.__wrapped__, "_MAIGRET_BIN", "renamed.json",
         json.dumps({"GitHub": {"status": "Claimed", "url_user": "https://github.test/alee"}})),
    ])
    def test_report_under_another_name_is_found(self, monkeypatch, runner, binary, name, content):
        def run(cmd, **kwargs):
            folder = cmd[cmd.index("--folderoutput") + 1]
            with open(f"{folder}/{name}", "w", encoding="utf-8") as f:
                f.write(content)

        monkeypatch.setattr(ue, binary, "tool")
        monkeypatch.setattr(ue.subprocess, "run", run)

        assert [r["url"] for r in runner("alee", 20)] == ["https://github.test/alee"]

    @pytest.mark.parametrize("runner, binary, files", [
        (ue._run_sherlock.__wrapped__, "_SHERLOCK_BIN", {}),
        (ue._run_maigret.__wrapped__, "_MAIGRET_BIN", {}),
        (ue._run_maigret.__wrapped__, "_MAIGRET_BIN", {"report_alee_simple.json": "{broken"}),
    ])
    def test_missing_or_broken_report(self, monkeypatch, runner, binary, files):
        def run(cmd, **kwargs):
            folder = cmd[cmd.index("--folderoutput") + 1]
            for name, content in files.items():
                with open(f"{folder}/{name}", "w", encoding="utf-8") as f:
                    f.write(content)

        monkeypatch.setattr(ue, binary, "tool")
        monkeypatch.setattr(ue.subprocess, "run", run)

        assert runner("alee", 20) == []

    def test_maigret_backend_is_used_for_lookups(self, monkeypatch):
        monkeypatch.setattr(ue, "_run_maigret", lambda handle, timeout: [{"site": handle}])

        assert ue._lookup("maigret", "alee", 20) == [{"site": "alee"}]


class TestReporting:
    def test_no_accounts(self, installed, monkeypatch, flat):
        installed("sherlock")
        monkeypatch.setattr(ue, "_run_sherlock", lambda handle, timeout=20: [])

        assert ue.username_enum("alee") == []
        assert "No accounts found for 'alee'" in flat()

    def test_report_is_not_written_when_the_folder_fails(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ue, "DIR_REPORTS", str(tmp_path))

        def refuse(*args, **kwargs):
            raise PermissionError("read-only")

        monkeypatch.setattr("builtins.open", refuse)

        assert ue._save_results_json("alee", "sherlock", [{"site": "GitHub"}]) is None
        assert ue._save_results_json("alee", "sherlock", []) is None


# ---------------------------------------------------------------------------
# Reverse image engines
# ---------------------------------------------------------------------------

def reply(payload=None, fail=None):
    def check():
        if fail:
            raise fail

    return SimpleNamespace(raise_for_status=check, json=lambda: payload)


class TestTinEye:
    def test_needs_both_keys(self, monkeypatch):
        monkeypatch.delenv("TINEYE_PUBLIC_KEY", raising=False)
        monkeypatch.setenv("TINEYE_PRIVATE_KEY", "private")

        assert rie.tineye_search("https://img.test/a.png") == []

    def test_request_failure(self, monkeypatch):
        monkeypatch.setattr(rie.requests, "get", lambda *a, **k: reply(
            fail=requests.exceptions.HTTPError("403")))

        assert rie.tineye_search("https://img.test/a.png", public_key="p", private_key="s") == []

    def test_matches_without_backlinks_are_skipped(self, monkeypatch):
        payload = {"results": {"matches": [
            {"backlinks": []},
            {"score": 90, "backlinks": [{"url": "https://acme.test/a.png"}]}]}}
        monkeypatch.setattr(rie.requests, "get", lambda *a, **k: reply(payload))

        results = rie.tineye_search("https://img.test/a.png", public_key="p", private_key="s")

        assert [(r["title"], r["link"]) for r in results] == [
            ("TinEye match", "https://acme.test/a.png")]


class TestBing:
    def test_needs_a_key(self, monkeypatch):
        for name in ("BING_VISUAL_SEARCH_KEY", "BING_SEARCH_KEY"):
            monkeypatch.delenv(name, raising=False)

        assert rie.bing_visual_search("https://img.test/a.png") == []

    def test_request_failure(self, monkeypatch):
        monkeypatch.setattr(rie.requests, "post", lambda *a, **k: reply(
            fail=requests.exceptions.ConnectionError("refused")))

        assert rie.bing_visual_search("https://img.test/a.png", api_key="k") == []

    def test_other_actions_and_items_without_links_are_skipped(self, monkeypatch):
        payload = {"tags": [{"actions": [
            {"actionType": "ShoppingSources", "data": {"value": [{"hostPageUrl": "x"}]}},
            {"actionType": "PagesIncluding", "data": {"value": [{"name": "no link"}]}},
        ]}]}
        monkeypatch.setattr(rie.requests, "post", lambda *a, **k: reply(payload))

        assert rie.bing_visual_search("https://img.test/a.png", api_key="k") == []


class TestYandexAndFanOut:
    def test_yandex_results_are_labelled(self, monkeypatch):
        monkeypatch.setattr("search.smart_search.SmartSearch.reverse_image_search",
                            lambda self, url: [{"title": "A", "link": "https://acme.test",
                                                "description": "Source: acme.test"},
                                               {"title": "B", "link": "https://b.test",
                                                "description": "[Yandex] b.test"}])

        results = rie.yandex_search("https://img.test/a.png")

        assert [r["description"] for r in results] == [
            "[Yandex] Source: acme.test", "[Yandex] b.test"]
        assert {r["engine"] for r in results} == {"yandex"}

    def test_yandex_failure(self, monkeypatch):
        def broken(self, url):
            raise RuntimeError("selector drift")

        monkeypatch.setattr("search.smart_search.SmartSearch.reverse_image_search", broken)

        assert rie.yandex_search("https://img.test/a.png") == []

    @pytest.mark.parametrize("engines, include_manual, ran", [
        (None, True, ["tineye", "bing", "yandex", "manual"]),
        (["bing", "manual"], False, ["bing"]),
    ])
    def test_fan_out(self, monkeypatch, engines, include_manual, ran):
        def engine(name):
            return lambda url: [{"engine": name}]

        for name, function in (("tineye", "tineye_search"), ("bing", "bing_visual_search"),
                               ("yandex", "yandex_search"), ("manual", "manual_lookup_urls")):
            monkeypatch.setattr(rie, function, engine(name))

        results = rie.reverse_image_aggregate("https://img.test/a.png", engines=engines,
                                              include_manual=include_manual)

        assert [r["engine"] for r in results] == ran
