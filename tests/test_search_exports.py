"""
End-to-end tests for what ``main.main()`` writes after a search. The search
engine and the page fetcher are stubbed; extraction and the exporters are real,
and every file lands in a pytest ``tmp_path``.
"""

import csv
import json
import sys

import openpyxl
import pytest

import main
import utils.results_parse as rp
from cli import actions
from core import state
from core.findings import FindingsHub
from search.smart_search import iter_extracted


SERP = [
    {"title": "A", "description": "first", "link": "https://site-a.test/a"},
    {"title": "B", "description": "second", "link": "https://site-b.test/b.pdf"},
]
PAGES = {
    "https://site-a.test/a": "contact alice@acme-corp.io",
    "https://site-b.test/b.pdf": "contact bob@acme-corp.io",
}
EXPORT_FLAGS = ["--json", "out.json", "--csv", "out.csv",
                "--excel", "out.xlsx", "--html", "out.html"]


@pytest.fixture
def run_main(tmp_path, monkeypatch):
    """Returns a callable that runs main() with the given command-line flags."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").touch()
    monkeypatch.setattr(rp, "DIR_REPORTS", str(tmp_path))
    monkeypatch.setattr(main, "init_directories", lambda: None)
    monkeypatch.setattr(main, "setup_logging", lambda debug: None)
    monkeypatch.setattr(main, "print_startup_banner", lambda has_key: None)
    monkeypatch.setattr(main, "load_environment", lambda: None)
    monkeypatch.setattr(main, "select_ia_agent", object)
    monkeypatch.setattr(actions, "get_search_engine", lambda *args: list(SERP))
    monkeypatch.setattr(actions, "get_text_from_url", PAGES.get)
    hub = FindingsHub()
    monkeypatch.setattr(actions, "get_hub", lambda: hub)
    monkeypatch.setattr(state, "LAST_RESULTS", [])
    monkeypatch.setattr(state, "CURRENT_CASE",
                        {"search_params": {}, "results": [], "evidence": [], "investigation": None})

    def run(*flags):
        monkeypatch.setattr(sys, "argv", ["main.py", *flags])
        main.main()

    return run


def emails_by_source(extracted):
    return {e["value"]: e["source"] for e in extracted if e["category"] == "emails"}


EXPECTED_EMAILS = {
    "alice@acme-corp.io": "https://site-a.test/a",
    "bob@acme-corp.io": "https://site-b.test/b.pdf",
}


@pytest.mark.parametrize("mode", [["--deep"], ["-e", "a@acme-corp.io"], ["-t", "+14155552671"]])
def test_deep_modes_export_results_and_extracted_values(run_main, tmp_path, mode):
    run_main("-q", "target", *mode, *EXPORT_FLAGS)

    data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert [r["link"] for r in data["results"]] == [r["link"] for r in SERP]
    assert emails_by_source(data["extracted"]) == EXPECTED_EMAILS

    with (tmp_path / "out_extracted.csv").open(encoding="utf-8") as f:
        rows = [{key.lower(): value for key, value in row.items()} for row in csv.DictReader(f)]
    assert emails_by_source(rows) == EXPECTED_EMAILS

    sheet = openpyxl.load_workbook(tmp_path / "out.xlsx")["Extracted"]
    values = [row[1] for row in sheet.iter_rows(min_row=2, values_only=True)]
    assert set(EXPECTED_EMAILS) <= set(values)

    assert "alice@acme-corp.io" in (tmp_path / "out.html").read_text(encoding="utf-8")


def test_plain_search_keeps_its_export_format(run_main, tmp_path):
    run_main("-q", "target", *EXPORT_FLAGS)

    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8")) == SERP
    assert not (tmp_path / "out_extracted.csv").exists()
    assert openpyxl.load_workbook(tmp_path / "out.xlsx").sheetnames == ["Results"]


@pytest.mark.parametrize("mode", [[], ["--deep"]])
def test_failed_search_writes_nothing(run_main, tmp_path, monkeypatch, mode):
    def blocked(*args):
        raise RuntimeError("DuckDuckGo blocked this search")

    monkeypatch.setattr(actions, "get_search_engine", blocked)

    with pytest.raises(SystemExit) as exit_info:
        run_main("-q", "target", *mode, *EXPORT_FLAGS)

    assert exit_info.value.code == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]


def test_search_without_results_still_exports(run_main, tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "get_search_engine", lambda *args: [])

    run_main("-q", "target", "--deep", "--json", "out.json")

    data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert data == {"results": [], "extracted": []}


def test_deep_search_runs_requested_downloads(run_main, monkeypatch):
    downloaded = []

    class FakeDownloader:
        def __init__(self, *custom_folder):
            assert custom_folder == ()

        def download_file(self, url, metadata):
            downloaded.append(url)

    monkeypatch.setattr(main, "FileDownload", FakeDownloader)

    run_main("-q", "target", "--deep", "--download", "pdf")

    assert downloaded == ["https://site-b.test/b.pdf"]


def test_interactive_flag_does_not_skip_deep_exports(run_main, tmp_path):
    run_main("-q", "target", "--deep", "-i", "--json", "out.json")

    assert (tmp_path / "out.json").exists()


def test_interactive_search_leaves_exports_to_its_menu(run_main, tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "do_search", lambda *args: list(SERP))

    run_main("-q", "target", "-i", "--json", "out.json")

    assert not (tmp_path / "out.json").exists()


def test_presidio_values_survive_a_deep_search(run_main, monkeypatch):
    nested = {"emails": ["alice@acme-corp.io"], "presidio": {"PERSON": ["Maria Gonzalez"]}}
    monkeypatch.setattr(actions, "extract_information", lambda text: nested)
    monkeypatch.setattr(actions, "get_search_engine", lambda *args: SERP[:1])

    run_main("-q", "target", "--deep")

    record = next(e for e in state.CURRENT_CASE["evidence"] if e["value"] == "Maria Gonzalez")
    assert record["category"] == "presidio_person"
    assert record["confidence"] == "low"
    assert record["source"] == SERP[0]["link"]


def test_iter_extracted_flattens_nested_entities():
    data = {"emails": ["a@b.co"], "presidio": {"PERSON": ["Ann", "Bo"], "LOCATION": ["Rome"]}}

    assert list(iter_extracted(data)) == [
        ("emails", "a@b.co"),
        ("presidio_person", "Ann"),
        ("presidio_person", "Bo"),
        ("presidio_location", "Rome"),
    ]
