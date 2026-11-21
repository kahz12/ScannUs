"""
Sherlock, Maigret and Holehe write their reports with their own installed code,
with the network replaced, and ScannUs reads those reports back.

A release that renames a flag, moves the report or changes its columns fails
here instead of in a live run, as when Maigret 0.6 turned the per-site status
into an object.
"""

import os
import sys
from types import SimpleNamespace

import pytest

from search import email_enum
from search import username_enum as ue

HANDLE = "jperez.7q"
EMAIL = "ana@example.com"


def offline(*args, **kwargs):
    raise ConnectionError("offline test")


# ---------------------------------------------------------------------------
# Sherlock: its real main() parses our command line and writes the CSV
# ---------------------------------------------------------------------------

def run_sherlock(monkeypatch, claimed, available):
    sherlock = pytest.importorskip("sherlock_project.sherlock")
    from sherlock_project.result import QueryResult, QueryStatus

    class Sites(list):
        def remove_nsfw_sites(self, do_not_remove=None):
            pass

    def sites(**kwargs):
        return Sites(SimpleNamespace(name=name, information={})
                     for name in [*claimed, *available])

    def query(username, site_data, query_notify, **kwargs):
        results = {}
        for name in site_data:
            url = f"https://{name.lower()}.test/{username}"
            status = QueryStatus.CLAIMED if name in claimed else QueryStatus.AVAILABLE
            results[name] = {"url_main": f"https://{name.lower()}.test/", "url_user": url,
                             "status": QueryResult(username, name, url, status, query_time=0.25),
                             "http_status": 200}
        return results

    monkeypatch.setattr(sherlock.requests, "get", offline)        # release check
    monkeypatch.setattr(sherlock, "SitesInformation", sites)      # remote site list
    monkeypatch.setattr(sherlock, "sherlock", query)              # per-site requests
    monkeypatch.setattr(sherlock, "init", lambda **kwargs: None)  # colorama wraps stdout
    monkeypatch.setattr(sherlock.signal, "signal", lambda *args: None)

    def run(cmd, **kwargs):
        monkeypatch.setattr(sys, "argv", ["sherlock", *cmd[1:]])
        sherlock.main()

    monkeypatch.setattr(ue.subprocess, "run", run)
    monkeypatch.setattr(ue, "_SHERLOCK_BIN", "sherlock")
    return ue._run_sherlock.__wrapped__(HANDLE, 20)


class TestSherlock:
    def test_claimed_sites_are_read_from_its_csv(self, monkeypatch):
        rows = run_sherlock(monkeypatch, claimed=["GitHub"], available=["Reddit"])

        assert rows == [{"site": "GitHub", "url": "https://github.test/jperez.7q",
                         "status": "found", "http_status": "200", "response_time": "0.25"}]


# ---------------------------------------------------------------------------
# Maigret: its argument parser reads our command line, its writer the report
# ---------------------------------------------------------------------------

def run_maigret(monkeypatch, statuses):
    pytest.importorskip("maigret")
    from maigret.maigret import setup_arguments_parser
    from maigret.report import save_json_report
    from maigret.result import MaigretCheckResult, MaigretCheckStatus
    from maigret.settings import Settings

    settings = Settings()
    loaded, problem = settings.load()
    assert loaded, problem

    def run(cmd, **kwargs):
        args = setup_arguments_parser(settings).parse_args(cmd[1:])
        username = args.username[0]
        results = {}
        for name, status in statuses.items():
            url = f"https://{name.lower()}.test/{username}"
            results[name] = {
                "username": username, "url_main": f"https://{name.lower()}.test/",
                "url_user": url, "http_status": 200, "rank": 1,
                "status": MaigretCheckResult(username, name, url,
                                             getattr(MaigretCheckStatus, status)),
                "site": SimpleNamespace(json={"url": url}),
            }
        # maigret.main() names the report with 'report_{username}{postfix}'
        # and the postfix f'_{args.json}.json'.
        path = os.path.join(args.folderoutput, f"report_{username}_{args.json}.json")
        save_json_report(path, username, results, report_type=args.json)

    monkeypatch.setattr(ue.subprocess, "run", run)
    monkeypatch.setattr(ue, "_MAIGRET_BIN", "maigret")
    return ue._run_maigret.__wrapped__(HANDLE, 20)


class TestMaigret:
    def test_claimed_sites_are_read_from_its_json_report(self, monkeypatch):
        rows = run_maigret(monkeypatch, {"GitHub": "CLAIMED", "Reddit": "AVAILABLE"})

        assert rows == [{"site": "GitHub", "url": "https://github.test/jperez.7q",
                         "status": "found", "http_status": "200", "response_time": ""}]


# ---------------------------------------------------------------------------
# Holehe: its real maincore() and Instagram module, with a stand-in HTTP client
# ---------------------------------------------------------------------------

def run_holehe(monkeypatch, blocked):
    pytest.importorskip("holehe")
    trio = pytest.importorskip("trio")
    import holehe.core as core
    from holehe.modules.social_media import instagram

    class Reply:
        def __init__(self, text="", body=None):
            self.text, self.body = text, body

        def json(self):
            return self.body

    class Client:
        def __init__(self, timeout=None):
            pass

        async def get(self, url, **kwargs):
            if blocked:
                raise ConnectionError("offline test")
            return Reply(text='{"config":{"csrf_token":"token"}}')

        async def post(self, url, **kwargs):
            return Reply(body={"status": "ok",
                               "errors": {"email": [{"code": "email_is_taken"}]}})

        async def aclose(self):
            pass

    monkeypatch.setattr(core, "check_update", lambda: None)
    monkeypatch.setattr(core, "import_submodules",
                        lambda package: {"holehe.modules.social_media.instagram": instagram})
    monkeypatch.setattr(core.httpx, "AsyncClient", Client)

    def run(cmd, cwd, **kwargs):
        monkeypatch.setattr(sys, "argv", ["holehe", *cmd[1:]])
        before = os.getcwd()
        os.chdir(cwd)
        try:
            with pytest.raises(SystemExit):   # holehe exits once the CSV is written
                trio.run(core.maincore)
        finally:
            os.chdir(before)

    monkeypatch.setattr(email_enum.subprocess, "run", run)
    monkeypatch.setattr(email_enum, "_HOLEHE_BIN", "holehe")
    return email_enum._run_holehe.__wrapped__(EMAIL)


class TestHolehe:
    def test_registered_service_is_read_from_its_csv(self, monkeypatch):
        rows = run_holehe(monkeypatch, blocked=False)

        assert [(r["service"], r["domain"], r["status"]) for r in rows] == [
            ("instagram", "instagram.com", "claimed")]

    def test_blocked_service_is_read_as_unchecked(self, monkeypatch):
        rows = run_holehe(monkeypatch, blocked=True)

        assert [(r["service"], r["status"], r["rate_limited"]) for r in rows] == [
            ("instagram", "unchecked", True)]
