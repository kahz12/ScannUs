from pypdf import PdfWriter

from utils.file_download import FileDownload


def write_pdf(path):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Author": "Alice", "/Title": "Annual report"})
    with path.open("wb") as f:
        writer.write(f)


def test_pdf_metadata_is_read(tmp_path, monkeypatch):
    pdf = tmp_path / "report.pdf"
    write_pdf(pdf)
    tables = []
    downloader = FileDownload(str(tmp_path))
    monkeypatch.setattr(downloader, "_render_table", lambda title, rows: tables.append(rows))

    downloader.extract_metadata(str(pdf))

    rows = dict(tables[0])
    assert rows["Pages"] == "1"
    assert rows["Author"] == "Alice"
    assert rows["Title"] == "Annual report"


def test_corrupt_pdf_reports_an_error_instead_of_crashing(tmp_path, monkeypatch):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"not a pdf")
    errors = []
    monkeypatch.setattr("utils.file_download.print_error", errors.append)

    FileDownload(str(tmp_path)).extract_metadata(str(pdf))

    assert "PDF metadata error" in errors[0]
