"""
Unit tests for ``utils.results_parse.ResultsParser`` exporters.

Exports normally land in ``core.config.DIR_REPORTS``; each test monkeypatches
that module-level constant to a pytest ``tmp_path`` so nothing is written
outside the sandbox. We then read the files back and assert on structure and,
importantly, on HTML-escaping of untrusted result fields.
"""

import csv
import json

import openpyxl
import pytest

import utils.results_parse as rp
from utils.results_parse import ResultsParser


SAMPLE = [
    {"title": "First", "description": "desc one", "link": "https://a.example/1"},
    {"title": "Second", "description": "desc two", "link": "https://b.example/2"},
]


@pytest.fixture(autouse=True)
def _reports_to_tmp(tmp_path, monkeypatch):
    """Redirect all report output into the test's tmp dir."""
    monkeypatch.setattr(rp, "DIR_REPORTS", str(tmp_path))
    return tmp_path


class TestJSON:
    def test_roundtrip(self, tmp_path):
        ResultsParser(SAMPLE).export_json("out.json")
        data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
        assert data == SAMPLE


class TestCSV:
    def test_header_and_rows(self, tmp_path):
        ResultsParser(SAMPLE).export_csv("out.csv")
        with (tmp_path / "out.csv").open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["ID", "Title", "Description", "Link"]
        assert rows[1] == ["1", "First", "desc one", "https://a.example/1"]
        assert rows[2][0] == "2"
        assert len(rows) == 3  # header + 2 data rows


class TestHTML:
    def test_contains_content_and_count(self, tmp_path):
        ResultsParser(SAMPLE).export_html("out.html")
        html = (tmp_path / "out.html").read_text(encoding="utf-8")
        assert "First" in html
        assert "https://a.example/1" in html
        assert "2 result(s)" in html

    def test_untrusted_fields_are_escaped(self, tmp_path):
        malicious = [{
            "title": "<script>alert(1)</script>",
            "description": "a & b < c",
            "link": "https://x.example/?q=1&r=2",
        }]
        ResultsParser(malicious).export_html("xss.html")
        html = (tmp_path / "xss.html").read_text(encoding="utf-8")
        # The raw script tag must not appear un-escaped
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "a &amp; b &lt; c" in html


class TestExcel:
    def test_reopens_with_headers_and_rows(self, tmp_path):
        ResultsParser(SAMPLE).export_excel("out.xlsx")
        wb = openpyxl.load_workbook(tmp_path / "out.xlsx")
        ws = wb.active
        assert [c.value for c in ws[1]] == ["ID", "Title", "Description", "Link"]
        # Two data rows after the header
        assert ws.max_row == 3
        assert ws.cell(row=2, column=2).value == "First"
        assert ws.cell(row=3, column=1).value == 2


class TestExtracted:
    EXTRACTED = [
        {"category": "emails", "value": "alice@acme-corp.io", "confidence": "high",
         "source": "https://a.example/1", "tool": "deep-search",
         "found_at": "2026-10-31T12:00:00+00:00", "content_sha256": "abc123"},
        {"category": "presidio_person", "value": "<b>Maria</b>",
         "source": "https://b.example/2?x=1&y=2"},
    ]

    def parser(self):
        return ResultsParser(SAMPLE, extracted=self.EXTRACTED)

    def test_json_holds_results_and_extracted(self, tmp_path):
        self.parser().export_json("out.json")
        data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
        assert data == {"results": SAMPLE, "extracted": self.EXTRACTED}

    def test_json_shape_stays_the_same_when_nothing_was_extracted(self, tmp_path):
        ResultsParser(SAMPLE, extracted=[]).export_json("out.json")
        data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
        assert data == {"results": SAMPLE, "extracted": []}

    def test_csv_writes_a_companion_file(self, tmp_path):
        self.parser().export_csv("out.csv")
        with (tmp_path / "out.csv").open(encoding="utf-8") as f:
            assert next(csv.reader(f)) == ["ID", "Title", "Description", "Link"]
        with (tmp_path / "out_extracted.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["Category"] == "emails"
        assert rows[0]["Value"] == "alice@acme-corp.io"
        assert rows[0]["Source"] == "https://a.example/1"
        assert rows[0]["Confidence"] == "high"
        assert rows[0]["Tool"] == "deep-search"
        assert rows[0]["Found at"] == "2026-10-31T12:00:00+00:00"
        assert rows[0]["Content SHA-256"] == "abc123"
        assert len(rows) == 2

    def test_plain_search_writes_no_companion_csv(self, tmp_path):
        ResultsParser(SAMPLE).export_csv("out.csv")
        assert not (tmp_path / "out_extracted.csv").exists()

    def test_html_section_is_escaped(self, tmp_path):
        self.parser().export_html("out.html")
        html = (tmp_path / "out.html").read_text(encoding="utf-8")
        assert "Extracted data (2)" in html
        assert "alice@acme-corp.io" in html
        assert "<b>Maria</b>" not in html
        assert "&lt;b&gt;Maria&lt;/b&gt;" in html
        assert 'href="https://b.example/2?x=1&amp;y=2"' in html

    def test_plain_search_html_has_no_extracted_section(self, tmp_path):
        ResultsParser(SAMPLE).export_html("out.html")
        html = (tmp_path / "out.html").read_text(encoding="utf-8")
        assert "Extracted data" not in html
        assert "{{ extracted }}" not in html

    def test_html_placeholder_inside_scraped_text_stays_literal(self, tmp_path):
        rows = [{"title": "{{ extracted }}", "description": "{{ total }}", "link": ""}]
        ResultsParser(rows, extracted=self.EXTRACTED).export_html("out.html")
        html = (tmp_path / "out.html").read_text(encoding="utf-8")
        assert "<h5>{{ extracted }}</h5>" in html
        assert "<p>{{ total }}</p>" in html
        assert html.count("Extracted data (2)") == 1

    def test_excel_adds_a_sheet_with_literal_text_and_links(self, tmp_path):
        extracted = [{"category": "usernames", "value": "=1+1",
                      "source": "https://a.example/1"}]
        ResultsParser(SAMPLE, extracted=extracted).export_excel("out.xlsx")
        wb = openpyxl.load_workbook(tmp_path / "out.xlsx")
        assert wb.sheetnames == ["Results", "Extracted"]
        ws = wb["Extracted"]
        assert [c.value for c in ws[1]][:4] == ["Category", "Value", "Confidence", "Source"]
        assert ws["B2"].value == "=1+1"
        assert ws["B2"].data_type == "s"
        assert ws["D2"].hyperlink.target == "https://a.example/1"

    def test_only_web_addresses_become_links(self, tmp_path):
        extracted = [{"category": "domain", "value": "a.test", "source": "javascript:alert(1)"}]
        ResultsParser(SAMPLE, extracted=extracted).export_excel("out.xlsx")
        ResultsParser(SAMPLE, extracted=extracted).export_html("out.html")

        ws = openpyxl.load_workbook(tmp_path / "out.xlsx")["Extracted"]
        assert ws["D2"].hyperlink is None
        assert 'href="javascript' not in (tmp_path / "out.html").read_text(encoding="utf-8")

    def test_excel_sheet_exists_when_nothing_was_extracted(self, tmp_path):
        ResultsParser(SAMPLE, extracted=[]).export_excel("out.xlsx")
        wb = openpyxl.load_workbook(tmp_path / "out.xlsx")
        assert wb["Extracted"].max_row == 1

    def test_plain_search_excel_has_one_sheet(self, tmp_path):
        ResultsParser(SAMPLE).export_excel("out.xlsx")
        assert openpyxl.load_workbook(tmp_path / "out.xlsx").sheetnames == ["Results"]


class TestTable:
    def test_row_and_column_counts(self):
        table = ResultsParser(SAMPLE).to_table()
        assert table.row_count == 2
        assert len(table.columns) == 4

    def test_long_description_truncated(self):
        long_desc = "x" * 250
        table = ResultsParser(
            [{"title": "t", "description": long_desc, "link": "l"}]
        ).to_table()
        # Rendering the last column's cell should be truncated with an ellipsis
        desc_cell = table.columns[3]._cells[0]
        assert "…" in desc_cell
        assert len(desc_cell) < len(long_desc)
