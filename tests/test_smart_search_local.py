"""
``search.smart_search`` outside the page extractors: Presidio failures,
local directory analysis, the Yandex reverse-image scraper and the
standalone command line.
"""

import runpy
import sys
from types import SimpleNamespace

import pytest

from search import smart_search as ss


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


class TestPresidio:
    def test_without_presidio(self, monkeypatch):
        monkeypatch.setattr(ss, "_get_presidio", lambda: None)

        assert ss._extract_presidio_entities("Ana Lee lives in Bogotá") == {}

    def test_analyzer_failure(self, monkeypatch):
        def analyze(text, language):
            raise RuntimeError("model missing")

        monkeypatch.setattr(ss, "_get_presidio", lambda: SimpleNamespace(analyze=analyze))

        assert ss._extract_presidio_entities("Ana Lee") == {}

    def test_empty_text_skips_presidio(self, monkeypatch):
        monkeypatch.setattr(ss, "_get_presidio", lambda: pytest.fail("loaded for nothing"))

        assert ss._extract_presidio_entities("") == {}


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "contacts.txt").write_text("Write to ana@acme.test or call +14155552671")
    (tmp_path / "notes.txt").write_text("nothing to see")
    (tmp_path / "sub").mkdir()
    return tmp_path


class TestLocalFiles:
    def test_reads_only_files(self, folder):
        assert sorted(ss.SmartSearch(str(folder)).files) == ["contacts.txt", "notes.txt"]

    def test_not_a_directory(self, tmp_path, flat):
        assert ss.SmartSearch(str(tmp_path / "missing")).files == {}
        assert "is not a valid directory" in flat()

    def test_unreadable_file_is_reported(self, folder, monkeypatch, flat):
        real_open = open

        def guarded(path, *args, **kwargs):
            if str(path).endswith("notes.txt"):
                raise PermissionError("denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", guarded)

        assert list(ss.SmartSearch(str(folder)).files) == ["contacts.txt"]
        assert "Error reading file" in flat()

    def test_regex_search_ignores_case(self, folder):
        assert ss.SmartSearch(str(folder)).regex_search(r"ANA@\S+") == {
            "contacts.txt": ["ana@acme.test"]}

    def test_extract_from_files(self, folder, monkeypatch, flat):
        monkeypatch.setattr(ss, "_extract_presidio_entities", lambda text: {})

        found = ss.SmartSearch(str(folder)).extract_from_files()

        assert list(found) == ["contacts.txt"]
        assert found["contacts.txt"]["emails"] == ["ana@acme.test"]
        out = flat()
        assert "ana@acme.test" in out and "No relevant information found" in out


class Node:
    def __init__(self, title=None, href=None):
        self.text, self.href = title, href

    def get_attribute(self, name):
        return self.href


class Item:
    def __init__(self, title, href):
        self.title, self.href = title, href

    def find_element(self, by, selector):
        if self.title is None:
            raise LookupError("no title")
        return Node(self.title) if "Title" in selector else Node(href=self.href)


class YandexDriver:
    def __init__(self, items=(), fail=None, quit_fails=False):
        self.items, self.fail, self.quit_fails = list(items), fail, quit_fails
        self.visited = []

    def get(self, url):
        if self.fail:
            raise self.fail
        self.visited.append(url)

    def find_element(self, by, selector):
        return Node()

    def find_elements(self, by, selector):
        return self.items

    def quit(self):
        if self.quit_fails:
            raise RuntimeError("already closed")


@pytest.fixture
def yandex(monkeypatch):
    holder = SimpleNamespace(driver=YandexDriver())
    monkeypatch.setattr("selenium.webdriver.Firefox", lambda *args, **kwargs: holder.driver)
    return holder


class TestReverseImage:
    def test_results_are_read_from_the_page(self, yandex):
        yandex.driver = YandexDriver(
            items=[Item("Ana Lee — Acme", "https://acme.test/team"), Item(None, None),
                   Item("", "https://x.test")],
            quit_fails=True)

        results = ss.SmartSearch().reverse_image_search("https://img.test/a.png")

        assert results == [{"title": "Ana Lee — Acme", "link": "https://acme.test/team",
                            "description": "Source: acme.test"}]
        assert yandex.driver.visited[0].endswith("url=https://img.test/a.png")

    def test_page_failure(self, yandex):
        yandex.driver = YandexDriver(fail=RuntimeError("blocked"))

        assert ss.SmartSearch().reverse_image_search("https://img.test/a.png") == []

    def test_selenium_missing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "selenium", None)

        assert ss.SmartSearch().reverse_image_search("https://img.test/a.png") == []


class TestCommandLine:
    def run(self, monkeypatch, *args):
        monkeypatch.setattr(sys, "argv", ["smart_search.py", *args])
        runpy.run_path(ss.__file__, run_name="__main__")

    def test_regex_and_extract_on_a_folder(self, monkeypatch, folder, flat):
        self.run(monkeypatch, "-d", str(folder), "-r", r"ana@\S+")

        out = flat()
        assert "Regex Match Results" in out and "ana@acme.test" in out

    def test_extract_on_a_folder(self, monkeypatch, folder, flat):
        # run_path executes a fresh copy of the module, so Presidio is kept out
        # through the import system rather than by patching the module.
        monkeypatch.setitem(sys.modules, "presidio_analyzer", None)
        self.run(monkeypatch, "-d", str(folder), "-e")

        assert "Analyzing file: contacts.txt" in flat()

    def test_reverse_image(self, monkeypatch, yandex, flat):
        yandex.driver = YandexDriver(items=[Item("Acme", "https://acme.test/")])

        self.run(monkeypatch, "--reverse-image", "https://img.test/a.png")

        assert "Link: https://acme.test/" in flat()

    def test_folder_is_required_for_local_search(self, monkeypatch, flat):
        self.run(monkeypatch, "-r", "x")

        assert "A target directory (-d) is required" in flat()
