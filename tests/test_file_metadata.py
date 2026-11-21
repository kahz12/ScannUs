"""
``utils.file_download``: streaming a file to disk without overwriting, and
the metadata shown for each kind of document.
"""

import sys
from types import SimpleNamespace

import pytest
import requests

from utils import file_download
from utils.file_download import FileDownload


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


@pytest.fixture
def downloader(tmp_path):
    return FileDownload(str(tmp_path))


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

class Stream:
    def __init__(self, chunks=(b"data",), fail=None, breaks=False):
        self.chunks, self.fail, self.breaks = list(chunks), fail, breaks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        if self.fail:
            raise self.fail

    def iter_content(self, chunk_size):
        yield from self.chunks
        if self.breaks:
            raise ConnectionResetError("connection reset")


@pytest.fixture
def serve(monkeypatch):
    holder = SimpleNamespace(stream=Stream())
    monkeypatch.setattr(file_download.requests, "get",
                        lambda url, stream, timeout: holder.stream)
    return holder


class TestDownload:
    def test_same_name_gets_a_suffix(self, downloader, serve, tmp_path):
        first = downloader.download_file("https://acme.test/files/report.pdf")
        second = downloader.download_file_direct("https://acme.test/other/report.pdf")

        assert first == str(tmp_path / "report.pdf")
        assert second == str(tmp_path / "report_1.pdf")

    def test_url_without_a_name_gets_a_hash(self, downloader, serve, flat):
        path = downloader.download_file("https://acme.test/")

        assert path.endswith(".bin")
        assert "No filename in URL" in flat()

    def test_metadata_after_download(self, downloader, serve, flat):
        downloader.download_file("https://acme.test/notes.txt", extract_metadata=True)

        assert "SHA-256" in flat()

    @pytest.mark.parametrize("stream, message", [
        (Stream(fail=requests.exceptions.HTTPError("404")), "Network error downloading"),
        (Stream(breaks=True), "Unexpected error downloading"),
    ])
    def test_failures_leave_no_file(self, downloader, serve, tmp_path, flat, stream, message):
        serve.stream = stream

        assert downloader.download_file("https://acme.test/report.pdf") is None
        assert message in flat()
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_docx_properties(self, downloader, tmp_path, flat):
        import docx

        document = docx.Document()
        document.core_properties.title = "Quarterly plan"
        document.core_properties.author = "Ana Lee"
        document.add_paragraph("hello")
        path = tmp_path / "plan.docx"
        document.save(path)

        downloader.extract_metadata(str(path))

        out = flat()
        assert "Quarterly plan" in out and "Ana Lee" in out

    def test_xlsx_properties(self, downloader, tmp_path, flat):
        import openpyxl

        workbook = openpyxl.Workbook()
        workbook.properties.creator = "Ana Lee"
        workbook.active.title = "Budget"
        path = tmp_path / "budget.xlsx"
        workbook.save(path)

        downloader.extract_metadata(str(path))

        out = flat()
        assert "Ana Lee" in out and "Budget" in out

    def test_exif_without_thumbnails(self, downloader, tmp_path, monkeypatch, flat):
        path = tmp_path / "photo.jpg"
        path.write_bytes(b"\xff\xd8")
        monkeypatch.setattr("exifread.process_file", lambda f, details: {
            "Image Model": "Pixel 8", "GPS GPSLatitude": "[4, 36, 0]",
            "JPEGThumbnail": b"...", "EXIF MakerNote": "x"})

        downloader.extract_metadata(str(path))

        out = flat()
        assert "Pixel 8" in out and "GPS GPSLatitude" in out
        assert "JPEGThumbnail" not in out and "MakerNote" not in out

    def test_image_without_exif(self, downloader, tmp_path, monkeypatch, flat):
        path = tmp_path / "photo.png"
        path.write_bytes(b"\x89PNG")
        monkeypatch.setattr("exifread.process_file", lambda f, details: {})

        downloader.extract_metadata(str(path))

        assert "No metadata found" in flat()

    @pytest.mark.parametrize("name, message", [
        ("broken.docx", "DOCX metadata error"),
        ("broken.xlsx", "XLSX metadata error"),
    ])
    def test_corrupt_documents(self, downloader, tmp_path, flat, name, message):
        path = tmp_path / name
        path.write_bytes(b"not a zip")

        downloader.extract_metadata(str(path))

        assert message in flat()

    def test_exif_failure(self, downloader, tmp_path, monkeypatch, flat):
        path = tmp_path / "photo.jpg"
        path.write_bytes(b"\xff\xd8")

        def broken(f, details):
            raise ValueError("truncated")

        monkeypatch.setattr("exifread.process_file", broken)

        downloader.extract_metadata(str(path))

        assert "EXIF metadata error: truncated" in flat()

    def test_missing_file(self, downloader, tmp_path, flat):
        downloader.extract_metadata(str(tmp_path / "gone.bin"))

        assert "Basic metadata error" in flat()

    @pytest.mark.parametrize("module, name, message", [
        ("pypdf", "a.pdf", "pypdf not installed"),
        ("exifread", "a.jpg", "exifread not installed"),
        ("docx", "a.docx", "python-docx not installed"),
        ("openpyxl", "a.xlsx", "openpyxl not installed"),
    ])
    def test_missing_library(self, downloader, tmp_path, monkeypatch, flat,
                             module, name, message):
        monkeypatch.setitem(sys.modules, module, None)

        downloader.extract_metadata(str(tmp_path / name))

        assert message in flat()
