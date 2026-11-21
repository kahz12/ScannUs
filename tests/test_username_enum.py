"""Username enumeration with the backend replaced by a fake that answers per handle."""

import json
import os
import re

import pytest

from core import planner
from core.findings import FindingsHub
from search import username_enum as ue


def row(site, handle):
    return {"site": site, "url": f"https://{site.lower()}.test/{handle}", "status": "found",
            "http_status": "200", "response_time": "0.1"}


# Sites "Ghost" and "Echo" claim every handle, like the sites Sherlock reports
# for any handle that contains a dot.
CLAIMS_ANYTHING = ["Ghost", "Echo"]


@pytest.fixture
def backend(monkeypatch, tmp_path):
    """A fake Sherlock: the real handle is on GitHub and Reddit, plus the two
    sites that claim anything. Set ``.control_rows`` to change the control's answer."""
    calls = []

    def fake(handle, timeout=20):
        calls.append(handle)
        if handle == "jperez.7q":
            return [row(s, handle) for s in ["GitHub", "Reddit", *CLAIMS_ANYTHING]]
        if calls.control_rows is not None:
            return calls.control_rows
        return [row(s, handle) for s in CLAIMS_ANYTHING]

    calls = type("Calls", (list,), {})()
    calls.control_rows = None
    monkeypatch.setattr(ue, "_run_sherlock", fake)
    monkeypatch.setattr(ue, "_SHERLOCK_BIN", "sherlock")
    monkeypatch.setattr(ue, "DIR_REPORTS", str(tmp_path))
    return calls


class TestControlHandle:
    def test_keeps_the_shape_of_the_handle(self):
        control = ue._control_handle("jperez.7q")

        assert re.fullmatch(r"[a-z]{6}\.[0-9][a-z]", control)
        assert control != "jperez.7q"

    def test_keeps_upper_case_letters_and_separators(self):
        control = ue._control_handle("Ana_ru-42")

        assert re.fullmatch(r"[A-Z][a-z]{2}_[a-z]{2}-[0-9]{2}", control)

    def test_is_the_same_on_every_run(self):
        assert ue._control_handle("jperez.7q") == ue._control_handle("jperez.7q")

    def test_differs_between_handles(self):
        assert ue._control_handle("jperez.7q") != ue._control_handle("jperez.8q")

    @pytest.mark.parametrize("handle", ["bob", "a.b.c.d", "j_d1"])
    def test_short_handles_get_none(self, handle):
        assert ue._control_handle(handle) is None


class TestFalsePositives:
    def test_sites_that_claim_the_made_up_handle_are_left_out(self, backend):
        rows = ue.enumerate_username("jperez.7q")

        assert sorted(r["site"] for r in rows) == ["GitHub", "Reddit"]
        assert sorted(backend) == sorted(["jperez.7q", ue._control_handle("jperez.7q")])

    def test_a_failed_control_lookup_keeps_every_hit(self, backend):
        backend.control_rows = []

        rows = ue.enumerate_username("jperez.7q")

        assert len(rows) == 4

    def test_short_handles_run_once_without_a_control(self, backend, monkeypatch):
        seen = []
        monkeypatch.setattr(ue, "_run_sherlock",
                            lambda handle, timeout=20: seen.append(handle) or [row("GitHub", handle)])

        rows = ue.enumerate_username("bob")

        assert seen == ["bob"]
        assert [r["site"] for r in rows] == ["GitHub"]

    def test_menu_lists_what_was_left_out_and_saves_only_the_rest(self, backend, tmp_path, capsys):
        rows = ue.username_enum("jperez.7q")

        out = " ".join(capsys.readouterr().out.split())  # Rich wraps long lines
        assert "Left out 2 site(s)" in out
        assert "Echo, Ghost" in out
        assert [r["site"] for r in rows] == ["GitHub", "Reddit"]
        saved = (tmp_path / "username_jperez7q_sherlock.json").read_text(encoding="utf-8")
        assert '"Ghost"' not in saved

    def test_planner_and_hub_get_only_the_real_hits(self, backend, monkeypatch):
        hub = FindingsHub()
        monkeypatch.setattr(planner, "get_hub", lambda: hub)

        result = planner.TOOL_DISPATCH["username_enum"]({"username": "jperez.7q"}, None)

        assert result["summary"] == "username_enum: 2 claimed account(s) for @jperez.7q"
        assert all("ghost" not in f.value and "echo" not in f.value for f in hub.of_kind("url"))


def maigret_site(site, handle, status):
    """One site entry as Maigret 0.6 writes it in a simple JSON report."""
    url = f"https://{site.lower()}.test/{handle}"
    return {
        "username": handle, "parsing_enabled": False, "url_main": f"https://{site.lower()}.test/",
        "url_user": url, "http_status": 200, "rank": 1,
        "status": {"username": handle, "site_name": site, "url": url, "status": status,
                   "ids": {}, "tags": [], "keywords": [], "keyword_match_status": "No Keywords"},
        "site": {"url": f"https://{site.lower()}.test/{{username}}", "tags": []},
    }


def run_maigret(monkeypatch, report):
    """Runs the Maigret backend against a subprocess that writes ``report``."""
    def fake_run(cmd, **kwargs):
        folder = cmd[cmd.index("--folderoutput") + 1]
        with open(os.path.join(folder, f"report_{cmd[1]}_simple.json"), "w", encoding="utf-8") as f:
            json.dump(report, f)

    monkeypatch.setattr(ue.subprocess, "run", fake_run)
    monkeypatch.setattr(ue, "_MAIGRET_BIN", "maigret")
    return ue._run_maigret.__wrapped__("jperez.7q", 20)


class TestMaigretReport:
    def test_reads_the_status_object_of_maigret_0_6(self, monkeypatch):
        rows = run_maigret(monkeypatch, {"GitHub": maigret_site("GitHub", "jperez.7q", "Claimed")})

        assert rows == [{"site": "GitHub", "url": "https://github.test/jperez.7q",
                         "status": "found", "http_status": "200", "response_time": ""}]

    def test_reads_the_bare_status_of_older_releases(self, monkeypatch):
        report = {"Reddit": {"status": "Claimed", "url_user": "https://reddit.test/jperez.7q"}}

        rows = run_maigret(monkeypatch, report)

        assert [r["url"] for r in rows] == ["https://reddit.test/jperez.7q"]

    @pytest.mark.parametrize("entry", [
        maigret_site("GitHub", "jperez.7q", "Available"),
        {"status": "Available", "url_user": "https://github.test/jperez.7q"},
        {"status": "Unknown", "url_user": "https://github.test/jperez.7q"},
    ])
    def test_sites_without_the_handle_are_left_out(self, monkeypatch, entry):
        assert run_maigret(monkeypatch, {"GitHub": entry}) == []

    def test_url_falls_back_to_the_status_object(self, monkeypatch):
        entry = maigret_site("GitHub", "jperez.7q", "Claimed")
        del entry["url_user"]

        rows = run_maigret(monkeypatch, {"GitHub": entry})

        assert rows[0]["url"] == "https://github.test/jperez.7q"

    def test_entries_that_are_not_objects_are_skipped(self, monkeypatch):
        report = {"Broken": None, "Odd": "Claimed",
                  "GitHub": maigret_site("GitHub", "jperez.7q", "Claimed")}

        assert [r["site"] for r in run_maigret(monkeypatch, report)] == ["GitHub"]
