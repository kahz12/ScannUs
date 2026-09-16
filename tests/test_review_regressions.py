from unittest.mock import MagicMock

import pytest
import requests

from core import state
from core.planner import _dispatch_deep_search
from utils.file_download import FileDownload


def test_download_collision_and_interrupted_transfer(tmp_path, monkeypatch):
    existing = tmp_path / "report.pdf"
    existing.write_bytes(b"original")
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_content.return_value = [b"new"]
    monkeypatch.setattr("utils.file_download.requests.get", lambda *a, **k: response)
    downloader = FileDownload(str(tmp_path))
    result = downloader.download_file("https://test.invalid/report.pdf")
    assert result == str(tmp_path / "report_1.pdf")
    assert existing.read_bytes() == b"original"
    assert (tmp_path / "report_1.pdf").read_bytes() == b"new"

    def interrupted(*args, **kwargs):
        yield b"partial"
        raise requests.ConnectionError("interrupted")

    response.iter_content.side_effect = interrupted
    assert downloader.download_file("https://test.invalid/report.pdf") is None
    assert not (tmp_path / "report_2.pdf").exists()
    assert existing.read_bytes() == b"original"


def test_failed_deep_search_does_not_report_stale_results(monkeypatch):
    from cli import actions

    monkeypatch.setattr(state, "LAST_RESULTS", [{"link": "https://old.invalid"}])

    def fail(*args, **kwargs):
        raise RuntimeError("network failed")

    monkeypatch.setattr(actions, "get_search_engine", fail)
    assert _dispatch_deep_search({"query": "new"}, None)["status"] == "error"


def test_empty_deep_search_is_success(monkeypatch):
    monkeypatch.setattr("cli.actions.do_deep_search", lambda *a, **k: [])
    result = _dispatch_deep_search({"query": "new"}, None)
    assert result["status"] == "ok"
    assert result["data"]["count"] == 0


def test_excel_external_fields_are_literal_text(tmp_path, monkeypatch):
    import openpyxl
    from utils.results_parse import ResultsParser

    monkeypatch.setattr("utils.results_parse.DIR_REPORTS", str(tmp_path))
    rows = [{"title": "=1+1", "description": '=HYPERLINK("https://test.invalid")',
             "link": "https://test.invalid"}]
    ResultsParser(rows).export_excel("literal.xlsx")
    wb = openpyxl.load_workbook(tmp_path / "literal.xlsx")
    try:
        for col, key in (("B", "title"), ("C", "description"), ("D", "link")):
            cell = wb.active[f"{col}2"]
            assert cell.value == rows[0][key]
            assert cell.data_type == "s"
        assert wb.active["D2"].hyperlink.target == rows[0]["link"]
    finally:
        wb.close()


def test_sqlite_connections_close_and_case_update_rolls_back(tmp_path):
    import sqlite3
    from core.cache import SQLiteCache
    from core.database import DBManager

    db = DBManager(str(tmp_path / "cases.db"))
    cache = SQLiteCache(str(tmp_path / "cache.db"))
    for owner in (db, cache):
        with owner._connect() as conn:
            conn.execute("SELECT 1")
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
        with pytest.raises(RuntimeError):
            with owner._connect() as failed_conn:
                raise RuntimeError("failed operation")
        with pytest.raises(sqlite3.ProgrammingError):
            failed_conn.execute("SELECT 1")

    original = {"search_params": {"q": "old"}, "results": [{"id": 1, "title": "old"}]}
    assert db.save_case("case", original)[0]
    assert not db.update_case("case", {"results": [None]})[0]
    restored = db.get_case_by_id(db.get_all_cases()[0][0])
    assert restored["search_params"] == original["search_params"]
    assert restored["results"][0]["title"] == "old"


def test_cache_automatically_purges_at_startup_and_during_use(tmp_path, monkeypatch):
    from core.cache import SQLiteCache

    monkeypatch.setattr("core.cache.time.time", lambda: 1000)
    monkeypatch.setattr("core.cache.time.monotonic", lambda: 10)
    path = str(tmp_path / "cache.db")
    cache = SQLiteCache(path)
    cache.set("test", "stale", "old", ttl=1)
    cache.set("test", "permanent", "keep", ttl=0)
    monkeypatch.setattr("core.cache.time.time", lambda: 1002)
    cache = SQLiteCache(path)
    assert cache.stats()["rows"] == 1
    cache.set("test", "later", "old", ttl=1)
    monkeypatch.setattr("core.cache.time.time", lambda: 1400)
    monkeypatch.setattr("core.cache.time.monotonic", lambda: 311)
    assert cache.get("test", "permanent") == "keep"
    assert cache.stats()["rows"] == 1


def test_deep_search_fetches_concurrently_in_bounded_batches(monkeypatch):
    from threading import Barrier, Lock
    from cli.actions import _fetch_search_texts

    barrier = Barrier(4)
    lock = Lock()
    active = 0
    peak = 0

    def fetch(url):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=5)
        with lock:
            active -= 1
        if url == "3":
            raise requests.ConnectionError("one failed page")
        return f"text {url}"

    monkeypatch.setattr("cli.actions.get_text_from_url", fetch)
    rows = [{"link": str(i)} for i in range(8)]
    result = list(_fetch_search_texts(rows + [rows[0], {}]))
    assert peak == 4
    assert result == [(str(i), None if i == 3 else f"text {i}") for i in range(8)]


def test_case_index_is_added_to_existing_database(tmp_path):
    from core.database import DBManager

    path = str(tmp_path / "cases.db")
    db = DBManager(path)
    assert db.save_case("saved", {"results": [{"id": 2}, {"id": 1}]})[0]
    with db._connect() as conn:
        conn.execute("DROP INDEX idx_results_case_result")
    db = DBManager(path)
    assert [r["id"] for r in db.get_case_by_id(1)["results"]] == [1, 2]
    with db._connect() as conn:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM results WHERE case_id = ? ORDER BY result_id",
            (1,),
        ).fetchall()
    details = " ".join(row[3] for row in plan)
    assert "idx_results_case_result" in details
    assert "TEMP B-TREE" not in details
