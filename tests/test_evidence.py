"""Findings keep their origin, survive in saved cases, and come back on load."""

import os
import sqlite3
import stat
import sys

import pytest

import main
import utils.results_parse as rp
from cli import actions, menus
from core import case_manager, state
from core.database import DBManager
from core.findings import FindingsHub
from search.smart_search import build_evidence
from utils.file_download import FileDownload


SERP = [
    {"title": "A", "description": "first", "link": "https://site-a.test/a"},
    {"title": "B", "description": "second", "link": "https://site-b.test/b"},
]
PAGES = {
    "https://site-a.test/a": "contact alice@acme-corp.io",
    "https://site-b.test/b": "contact bob@acme-corp.io and alice@acme-corp.io",
}


def record(value="a@acme-corp.io", source="https://site.test/a", category="emails"):
    return {"category": category, "value": value, "confidence": "high", "source": source,
            "tool": "deep-search", "found_at": "2026-10-31T12:00:00+00:00",
            "content_sha256": "abc"}


@pytest.fixture
def hub(monkeypatch):
    fresh = FindingsHub()
    monkeypatch.setattr(actions, "get_hub", lambda: fresh)
    monkeypatch.setattr(case_manager, "get_hub", lambda: fresh)
    monkeypatch.setattr(menus, "get_hub", lambda: fresh)
    return fresh


@pytest.fixture
def case(hub, tmp_path, monkeypatch):
    """A blank session whose cases go to a temporary database."""
    monkeypatch.setattr(state, "LAST_RESULTS", [])
    monkeypatch.setattr(state, "CURRENT_CASE",
                        {"search_params": {}, "results": [], "evidence": [], "investigation": None})
    database = str(tmp_path / "cases.db")
    monkeypatch.setattr(case_manager, "DBManager", lambda: DBManager(database))
    return state


@pytest.fixture
def run_main(case, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rp, "DIR_REPORTS", str(tmp_path))
    monkeypatch.setattr(main, "init_directories", lambda: None)
    monkeypatch.setattr(main, "setup_logging", lambda debug: None)
    monkeypatch.setattr(main, "print_startup_banner", lambda has_key: None)
    monkeypatch.setattr(main, "load_environment", lambda: None)
    monkeypatch.setattr(actions, "get_search_engine", lambda *args: list(SERP))
    monkeypatch.setattr(actions, "get_text_from_url", PAGES.get)

    def run(*flags):
        monkeypatch.setattr(sys, "argv", ["main.py", *flags])
        main.main()

    return run


def load_first_case(monkeypatch):
    monkeypatch.setattr(case_manager.console, "input", lambda *args, **kwargs: "1")
    return case_manager.load_case()


class TestSessionEvidence:
    def test_same_value_on_two_pages_stays_as_two_records(self, case):
        added = case.add_evidence([record(source="https://a.test"), record(source="https://b.test")])

        assert added == 2

    def test_same_value_from_the_same_page_counts_once(self, case):
        case.add_evidence([record()])

        assert case.add_evidence([record()]) == 0
        assert len(case.CURRENT_CASE["evidence"]) == 1

    def test_results_are_numbered_and_not_repeated(self, case):
        case.add_results(SERP[:1])
        case.add_results(SERP)

        assert [(r["id"], r["link"]) for r in case.CURRENT_CASE["results"]] == [
            (1, SERP[0]["link"]), (2, SERP[1]["link"]),
        ]


class TestDatabase:
    CASE = {
        "search_params": {"type": "deep", "value": "acme"},
        "results": [{"id": 1, "title": "A", "description": "d", "link": "https://a.test"}],
        "evidence": [record()],
        "investigation": {"goal": "g", "steps": [], "report": "r"},
    }

    def test_case_comes_back_complete(self, tmp_path):
        db = DBManager(str(tmp_path / "cases.db"))
        assert db.save_case("acme", self.CASE)[0]

        loaded = db.get_case_by_id(db.get_all_cases()[0][0])

        assert loaded["evidence"] == [record()]
        assert loaded["investigation"] == self.CASE["investigation"]
        assert loaded["results"] == self.CASE["results"]

    def test_update_replaces_evidence(self, tmp_path):
        db = DBManager(str(tmp_path / "cases.db"))
        db.save_case("acme", self.CASE)

        db.update_case("acme", {**self.CASE, "evidence": [record("new@acme-corp.io")]})

        loaded = db.get_case_by_id(db.get_all_cases()[0][0])
        assert [e["value"] for e in loaded["evidence"]] == ["new@acme-corp.io"]

    def test_deleting_a_case_deletes_its_evidence(self, tmp_path):
        path = str(tmp_path / "cases.db")
        db = DBManager(path)
        db.save_case("acme", self.CASE)

        db.delete_case("acme")

        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0

    def test_database_from_an_earlier_version_is_upgraded(self, tmp_path):
        path = str(tmp_path / "cases.db")
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
                    query_data TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE results (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER,
                    result_id INTEGER, title TEXT, description TEXT, link TEXT);
                INSERT INTO cases (name, query_data) VALUES ('old', '{}');
                INSERT INTO results (case_id, result_id, title, description, link)
                    VALUES (1, 1, 'T', 'D', 'https://old.test');
            """)
        conn.close()

        db = DBManager(path)
        loaded = db.get_case_by_id(1)

        assert loaded["results"][0]["link"] == "https://old.test"
        assert loaded["evidence"] == []
        assert loaded["investigation"] is None
        assert db.save_case("new", self.CASE)[0]

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
    def test_database_is_readable_by_its_owner_only(self, tmp_path):
        path = tmp_path / "cases.db"
        DBManager(str(path))

        assert stat.S_IMODE(path.stat().st_mode) == 0o600


class TestDeepSearchToSavedCase:
    def test_each_value_keeps_the_page_it_came_from(self, run_main):
        run_main("-q", "acme", "--deep")

        sources = {(e["value"], e["source"]) for e in state.CURRENT_CASE["evidence"]
                   if e["category"] == "emails"}
        assert sources == {
            ("alice@acme-corp.io", "https://site-a.test/a"),
            ("alice@acme-corp.io", "https://site-b.test/b"),
            ("bob@acme-corp.io", "https://site-b.test/b"),
        }

    def test_save_case_flag_stores_results_and_evidence(self, run_main, hub, monkeypatch):
        run_main("-q", "acme", "--deep", "--save-case", "acme-case")

        hub.clear()
        monkeypatch.setattr(state, "CURRENT_CASE",
                            {"search_params": {}, "results": [], "evidence": [], "investigation": None})
        assert load_first_case(monkeypatch) is True

        assert len(state.LAST_RESULTS) == 2
        assert {e["value"] for e in state.CURRENT_CASE["evidence"]} >= {
            "alice@acme-corp.io", "bob@acme-corp.io",
        }

    def test_loading_a_case_refills_the_hub_with_the_origin(self, run_main, hub, monkeypatch):
        run_main("-q", "acme", "--deep", "--save-case", "acme-case")
        hub.clear()

        load_first_case(monkeypatch)

        emails = {f.value: f for f in hub.of_kind("email")}
        assert "bob@acme-corp.io" in emails
        assert emails["bob@acme-corp.io"].source == "deep-search"
        assert emails["bob@acme-corp.io"].label == "https://site-b.test/b"

    def test_repeated_case_name_is_refused_with_exit_code_1(self, run_main):
        run_main("-q", "acme", "--deep", "--save-case", "acme-case")

        with pytest.raises(SystemExit) as exit_info:
            run_main("-q", "acme", "--deep", "--save-case", "acme-case")

        assert exit_info.value.code == 1

    def test_plain_search_can_be_saved_too(self, run_main, monkeypatch):
        run_main("-q", "acme", "--save-case", "plain")

        load_first_case(monkeypatch)
        assert len(state.LAST_RESULTS) == 2


class TestHubFindingsAreSaved:
    def test_recon_findings_are_stored_with_their_tool(self, case, hub, monkeypatch):
        hub.add_domain("dev.acme-corp.io", source="recon:tls-san", label="subdomain")
        hub.add_ip("8.8.8.8", source="recon:dns")
        case.add_results(SERP[:1])

        assert case_manager.save_case_as("recon") is True
        hub.clear()
        load_first_case(monkeypatch)

        stored = {e["value"]: e for e in state.CURRENT_CASE["evidence"]}
        assert stored["dev.acme-corp.io"]["tool"] == "recon:tls-san"
        assert stored["dev.acme-corp.io"]["source"] == ""
        assert stored["8.8.8.8"]["category"] == "ip"
        assert [f.value for f in hub.of_kind("domain")] == ["dev.acme-corp.io"]

    def test_values_already_in_the_evidence_are_not_repeated(self, case, hub):
        case.add_evidence([record()])
        hub.ingest_evidence([record()])

        snapshot = case_manager.case_snapshot()

        assert len(snapshot["evidence"]) == 1

    def test_result_links_are_not_repeated_as_findings(self, case, hub):
        case.add_results(SERP[:1])
        hub.ingest_results(SERP[:1], source="search")

        assert case_manager.case_snapshot()["evidence"] == []

    def test_an_empty_session_saves_nothing(self, case):
        assert case_manager.save_case_as("empty") is False


class TestOtherProducers:
    def test_wayback_extraction_records_the_archive_url(self, case, monkeypatch):
        from analysis import advanced_osint

        archive = "https://web.archive.org/web/2020id_/https://site.test/"
        monkeypatch.setattr(advanced_osint, "wayback_fetch_snapshot", lambda url, ts: {
            "text": "contact alice@acme-corp.io", "timestamp": "2020", "date": "2020-01-01",
            "archive_url": archive,
        })

        advanced_osint.wayback_extract_pii("https://site.test/")

        email = next(e for e in state.CURRENT_CASE["evidence"] if e["category"] == "emails")
        assert (email["source"], email["tool"]) == (archive, "wayback")

    def test_menu_evidence_table_lists_the_origin(self, case, capsys):
        case.add_evidence([record()])

        menus._show_evidence()

        output = capsys.readouterr().out
        assert "a@acme-corp.io" in output
        assert "deep-search" in output

    def test_menu_records_values_for_the_case_and_the_hub(self, case, hub):
        data = {"emails": ["a@acme-corp.io"]}

        added = menus._record_evidence(data, "page", "https://site.test/a", "url-pii")

        assert added == 1
        assert state.CURRENT_CASE["evidence"][0]["tool"] == "url-pii"
        assert hub.of_kind("email")[0].label == "https://site.test/a"


def test_build_evidence_matches_what_the_database_stores(tmp_path):
    records = build_evidence({"emails": ["a@acme-corp.io"]}, "text", "https://a.test", "t")
    db = DBManager(str(tmp_path / "cases.db"))
    db.save_case("c", {"search_params": {}, "results": [], "evidence": records})

    assert db.get_case_by_id(db.get_all_cases()[0][0])["evidence"] == records


def test_file_hash_covers_the_whole_file(tmp_path, monkeypatch):
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"a" * (1024 * 1024) + b"x")
    second.write_bytes(b"a" * (1024 * 1024) + b"y")
    hashes = []
    downloader = FileDownload(str(tmp_path))
    monkeypatch.setattr(downloader, "_render_table",
                        lambda title, rows: hashes.append(dict(rows)["SHA-256"]))

    downloader._extract_basic_metadata(str(first))
    downloader._extract_basic_metadata(str(second))

    assert hashes[0] != hashes[1]
