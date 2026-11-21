"""
``analysis.web_analyzer`` (page text, AI summaries and the entity graph) and
``analysis.tech_scanner`` (every fingerprinting backend and report shape).
"""

from types import SimpleNamespace

import pytest
import requests

from analysis import tech_scanner as ts
from analysis import web_analyzer as wa

URL = "https://acme.test/about"
ARTICLE = "Acme builds anvils for road runners. " * 5


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


# ---------------------------------------------------------------------------
# Page text
# ---------------------------------------------------------------------------

class Page:
    def __init__(self, text="", ctype="text/html; charset=utf-8", fail=None):
        self.text, self.fail = text, fail
        self.headers = {"content-type": ctype}

    def raise_for_status(self):
        if self.fail:
            raise self.fail


@pytest.fixture
def serve(monkeypatch):
    """Answers every page request with ``serve.page``; an exception is raised."""
    holder = SimpleNamespace(page=Page())

    def get(url, **kwargs):
        if isinstance(holder.page, BaseException):
            raise holder.page
        return holder.page

    monkeypatch.setattr(wa.requests, "get", get)
    return holder


class TestPageText:
    def test_trafilatura_article(self, serve, monkeypatch):
        serve.page = Page("<html>…</html>")
        monkeypatch.setattr(wa, "_HAS_TRAFILATURA", True)
        monkeypatch.setattr(wa, "trafilatura",
                            SimpleNamespace(extract=lambda html, **kw: ARTICLE), raising=False)

        assert wa._fetch_and_clean(URL) == ARTICLE

    def test_readability_when_trafilatura_finds_too_little(self, serve, monkeypatch):
        serve.page = Page("<html>…</html>")
        monkeypatch.setattr(wa, "_HAS_TRAFILATURA", True)
        monkeypatch.setattr(wa, "trafilatura", SimpleNamespace(extract=lambda html, **kw: "short"),
                            raising=False)
        monkeypatch.setattr(wa, "_HAS_READABILITY", True)
        monkeypatch.setattr(wa, "Document", lambda html: SimpleNamespace(
            summary=lambda html_partial: f"<article><p>{ARTICLE}</p></article>"), raising=False)

        assert wa._fetch_and_clean(URL) == ARTICLE.strip()

    def test_soup_when_readability_fails(self, serve, monkeypatch):
        serve.page = Page("<nav>menu</nav><p>Ana Lee</p><script>x()</script>")
        monkeypatch.setattr(wa, "_HAS_TRAFILATURA", False)
        monkeypatch.setattr(wa, "_HAS_READABILITY", True)

        def broken(html):
            raise ValueError("not an article")

        monkeypatch.setattr(wa, "Document", broken, raising=False)

        assert wa._fetch_and_clean(URL) == "Ana Lee"

    @pytest.mark.parametrize("page, message", [
        (Page("%PDF", ctype="application/pdf"), "Skipping non-HTML content (application/pdf)"),
        (Page("   "), ""),
        (requests.exceptions.ConnectionError("refused"), "Network error fetching"),
        (Page(fail=ValueError("odd")), "Unexpected error processing"),
    ])
    def test_nothing_usable(self, serve, flat, page, message):
        serve.page = page

        assert wa._fetch_and_clean(URL) is None
        assert message in flat()


# ---------------------------------------------------------------------------
# AI over page text
# ---------------------------------------------------------------------------

class Agent:
    """Answers each prompt with the next reply; an exception is raised instead."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.generator = SimpleNamespace(generate=self.generate)

    def generate(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class TestAiText:
    def test_long_text_is_summarised_in_chunks_and_merged(self, flat):
        agent = Agent("part 1", "part 2", "part 3", "merged")

        assert wa.summarize_text_with_ia("x" * 25_000, agent) == "merged"
        assert "processing in 3 chunks" in flat()
        assert "part 1\n\n---\n\npart 2" in agent.prompts[-1]

    @pytest.mark.parametrize("function, empty", [
        (wa.summarize_text_with_ia, "No text provided for summarisation."),
        (wa.translate_and_analyze_with_ia, "No text provided for analysis."),
    ])
    def test_empty_text_and_failures(self, function, empty):
        assert function("", Agent()) == empty
        assert function("text", Agent(RuntimeError("quota"))) == "AI Generation Error: quota"

    def test_analysis_prompt_wraps_the_page(self):
        agent = Agent("report")

        assert wa.translate_and_analyze_with_ia("Ana Lee runs Acme", agent) == "report"
        assert "<page_text>" in agent.prompts[0] and "Ana Lee runs Acme" in agent.prompts[0]


class TestEntityGraph:
    @pytest.fixture(autouse=True)
    def graphs(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wa, "DIR_GRAPHS", str(tmp_path))
        return tmp_path

    def test_relationships_become_a_graph(self, graphs):
        agent = Agent("Ana Lee | Person | works at | Acme | Organization\n"
                      "Acme | Organization | owns | acme.test | Domain\n"
                      "not a relationship line")

        path = wa.extract_entities_and_graph("text", agent, output_filename="../g.html")

        assert path == str(graphs / "g.html")
        html = (graphs / "g.html").read_text()
        assert "Ana Lee" in html and "acme.test" in html

    @pytest.mark.parametrize("reply, message", [
        ("NO_RELATIONSHIPS", "No sufficient entities found"),
        ("just prose", "No valid relationships parsed"),
        (RuntimeError("quota"), "Graph generation failure: quota"),
    ])
    def test_no_graph(self, flat, reply, message):
        assert wa.extract_entities_and_graph("text", Agent(reply)) is None
        assert message in flat()

    def test_empty_text(self, flat):
        assert wa.extract_entities_and_graph("", Agent()) is None
        assert "No text available for graph analysis" in flat()


# ---------------------------------------------------------------------------
# Technology fingerprinting
# ---------------------------------------------------------------------------

@pytest.fixture
def wappalyzer(monkeypatch):
    """Selects the python-Wappalyzer backend with a stand-in analyzer."""
    holder = SimpleNamespace(with_versions=None, plain=["Nginx"], get_fails=None)

    class Analyzer:
        def analyze_with_versions_and_categories(self, page):
            if isinstance(holder.with_versions, BaseException):
                raise holder.with_versions
            return holder.with_versions

        def analyze(self, page):
            return holder.plain

    calls = []

    def get(url, **kwargs):
        calls.append(kwargs.get("verify"))
        if holder.get_fails and kwargs.get("verify"):
            raise holder.get_fails
        return SimpleNamespace(url=url)

    holder.verify_calls = calls
    monkeypatch.setattr(ts, "_WAPPALYZER", Analyzer())
    monkeypatch.setattr(ts, "_WAPPALYZER_FLAVOUR", "python-Wappalyzer")
    monkeypatch.setattr(ts.requests, "get", get)
    monkeypatch.setattr(ts, "WebPage", SimpleNamespace(new_from_response=lambda r: r),
                        raising=False)
    return holder


class TestWappalyzer:
    def test_versions_and_categories(self, wappalyzer):
        wappalyzer.with_versions = {
            "Nginx": {"versions": ["1.25"], "categories": [{"name": "Web servers"}]},
            "React": {"versions": [], "categories": ["JavaScript frameworks"]},
            "Odd": None,
        }

        assert ts._detect_wappalyzer(URL) == [
            ("Nginx", "1.25", "Web servers"), ("React", "", "JavaScript frameworks"),
            ("Odd", "", "")]

    def test_older_api_gives_names_only(self, wappalyzer):
        wappalyzer.with_versions = AttributeError("old release")

        assert ts._detect_wappalyzer(URL) == [("Nginx", "", "")]

    def test_bad_certificate_is_retried_unverified(self, wappalyzer, flat):
        wappalyzer.get_fails = requests.exceptions.SSLError("self-signed")
        wappalyzer.with_versions = {}

        ts._detect_wappalyzer(URL)

        assert wappalyzer.verify_calls == [True, False]
        assert "retrying without certificate check" in flat()

    def test_unreachable_page(self, wappalyzer, monkeypatch, flat):
        def refused(url, **kwargs):
            raise requests.exceptions.ConnectionError("refused")

        monkeypatch.setattr(ts.requests, "get", refused)

        assert ts._detect_wappalyzer(URL) == []
        assert "Wappalyzer fetch error: refused" in flat()


class TestWappalyzerFork:
    @pytest.fixture
    def fork(self, monkeypatch):
        holder = SimpleNamespace(result=None)

        def analyze(url):
            if isinstance(holder.result, BaseException):
                raise holder.result
            return holder.result

        monkeypatch.setattr(ts, "_WAPPALYZER", SimpleNamespace(analyze=analyze))
        monkeypatch.setattr(ts, "_WAPPALYZER_FLAVOUR", "wappalyzer")
        return holder

    @pytest.mark.parametrize("result", [
        {URL: {"Nginx": {"version": "1.25", "categories": ["Web servers"]},
               "PHP": {"category": "Programming languages"}, "Bare": None}},
        {"Nginx": {"version": "1.25", "categories": ["Web servers"]},
         "PHP": {"category": "Programming languages"}, "Bare": None},
    ])
    def test_both_report_shapes(self, fork, result):
        fork.result = result

        assert ts._detect_wappalyzer(URL) == [
            ("Nginx", "1.25", "Web servers"), ("PHP", "", "Programming languages"),
            ("Bare", "", "")]

    def test_failure(self, fork, flat):
        fork.result = RuntimeError("blocked")

        assert ts._detect_wappalyzer(URL) == []
        assert "Wappalyzer fetch error: blocked" in flat()

    def test_unknown_flavour(self, monkeypatch):
        monkeypatch.setattr(ts, "_WAPPALYZER_FLAVOUR", None)

        assert ts._detect_wappalyzer(URL) == []


class TestWebTech:
    def test_not_installed(self, monkeypatch):
        monkeypatch.setattr(ts, "_HAS_WEBTECH", False)

        assert ts._detect_webtech(URL) == []

    def test_failure(self, monkeypatch, flat):
        class Broken:
            def __init__(self, options):
                raise RuntimeError("no data folder")

        monkeypatch.setattr(ts, "_HAS_WEBTECH", True)
        monkeypatch.setattr(ts, "WebTech", Broken, raising=False)

        assert ts._detect_webtech(URL) == []
        assert "WebTech error: no data folder" in flat()

    def test_report_objects(self):
        report = SimpleNamespace(tech=[
            SimpleNamespace(name="Nginx", version="1.25", cats=[23]),
            SimpleNamespace(name="Mystery", version=None, categories=[999]),
            SimpleNamespace(name="Named", version="", cats="Hosting"),
            SimpleNamespace(name="Bare", version="", cats=None, categories=[]),
        ])

        assert ts._parse_webtech_report(report) == [
            ("Nginx", "1.25", "Web Server"), ("Mystery", "", "Cat 999"),
            ("Named", "", "Hosting"), ("Bare", "", "")]

    @pytest.mark.parametrize("report", [None, "plain text report"])
    def test_unusable_reports(self, report):
        assert ts._parse_webtech_report(report) == []

    @pytest.mark.parametrize("name, category", [
        ("nginx", "Web Server"), ("WordPress", "CMS"), ("jQuery", "JavaScript Framework"),
        ("PHP", "Programming Language"), ("Google Analytics", "Analytics"),
        ("Cloudflare", "CDN"), ("Mystery", "Technology"),
    ])
    def test_category_from_the_name(self, name, category):
        assert ts._infer_category_from_name(name) == category


class TestTechScan:
    def test_table_sorted_by_category(self, monkeypatch, flat):
        monkeypatch.setattr(ts, "detect_technologies", lambda url: ("WebTech", [
            ("React", "", "JavaScript Framework"), ("Nginx", "1.25", "Web Server"),
            ("Mystery", "", "")]))

        assert ts.tech_scan(URL)[0] == "WebTech"
        out = flat()
        assert out.index("React") < out.index("Nginx") < out.index("Mystery")
        assert "Total: 3 technologies detected" in out

    def test_nothing_detected(self, monkeypatch, flat):
        monkeypatch.setattr(ts, "detect_technologies", lambda url: ("none", []))

        assert ts.tech_scan(URL) == ("none", [])
        assert "No technologies detected" in flat()

    def test_no_backend_installed(self, monkeypatch, flat):
        monkeypatch.setattr(ts, "_WAPPALYZER", None)
        monkeypatch.setattr(ts, "_HAS_WEBTECH", False)

        assert ts.tech_scan(URL) == ("none", [])
        assert ts.detect_technologies(URL) == ("none", [])
        assert "No fingerprinting backend available" in flat()

    def test_webtech_after_an_empty_wappalyzer(self, monkeypatch):
        monkeypatch.setattr(ts, "_WAPPALYZER", object())
        monkeypatch.setattr(ts, "_detect_wappalyzer", lambda url: [])
        monkeypatch.setattr(ts, "_HAS_WEBTECH", True)
        monkeypatch.setattr(ts, "_detect_webtech", lambda url: [])

        assert ts.detect_technologies(URL) == ("none", [])
