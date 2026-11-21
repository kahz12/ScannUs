"""The results browser and the per-URL analysis menu, driven through a scripted terminal."""

from types import SimpleNamespace

import pytest

from cli import hub_menu, menus, results_menu
from core import state

URL = "https://acme.test/team"
AGENT = SimpleNamespace(generator=SimpleNamespace())


def rows(count):
    return [{"title": f"Result {n}", "description": "d", "link": f"https://acme.test/{n}"}
            for n in range(1, count + 1)]


# ---------------------------------------------------------------------------
# Labels and evidence
# ---------------------------------------------------------------------------

class TestLabels:
    @pytest.mark.parametrize("params, label", [
        ({}, "none"),
        ({"type": "manual", "value": "N/A"}, "manual"),
        ({"type": "plan", "value": "Who runs acme.test?"}, "Who runs acme.test?"),
        ({"type": "plan", "value": "x" * 40}, "x" * 32 + "…"),
    ])
    def test_case_label(self, menu_hub, params, label):
        state.CURRENT_CASE["search_params"] = params

        assert results_menu._current_case_label() == label

    def test_agent_label(self):
        from core.providers import OllamaGenerator

        assert results_menu._agent_label(None) == "none"
        assert results_menu._agent_label(SimpleNamespace(generator=OllamaGenerator())) == "Ollama"

    def test_evidence_table(self, menu_hub, flat):
        results_menu._show_evidence()
        assert "No evidence in this case yet" in flat()

        state.CURRENT_CASE["evidence"] = [{"category": "emails", "value": "ana@acme.test",
                                           "confidence": "high", "source": URL, "tool": "url-pii"}]
        results_menu._show_evidence()
        out = flat()
        assert "ana@acme.test" in out and "url-pii" in out


# ---------------------------------------------------------------------------
# Wayback Machine
# ---------------------------------------------------------------------------

class TestWaybackMenu:
    def test_every_tool_gets_the_url_and_dates(self, tui, monkeypatch, record, flat):
        fakes = SimpleNamespace(
            check_wayback_machine=record(),
            wayback_fetch_snapshot=record({"date": "2020-01-01", "text": "a" * 3100}),
            wayback_extract_pii=record(),
            wayback_diff=record(),
        )
        for name in vars(fakes):
            monkeypatch.setattr(f"analysis.advanced_osint.{name}", getattr(fakes, name))
        tui.script("timeline", "fetch", "2020", "extract", "", "diff", "", "2024-05", "back")

        results_menu._run_wayback_menu(URL)

        assert fakes.check_wayback_machine.calls == [((URL,), {})]
        assert fakes.wayback_fetch_snapshot.calls == [((URL, "2020"), {})]
        assert fakes.wayback_extract_pii.calls == [((URL, "latest"), {})]
        assert fakes.wayback_diff.calls == [((URL, "earliest", "2024-05"), {})]
        assert "(+100 more chars)" in flat()


# ---------------------------------------------------------------------------
# URL analysis
# ---------------------------------------------------------------------------

@pytest.fixture
def page(monkeypatch):
    """Serves *text* for any URL fetched by the analysis menu."""
    served = SimpleNamespace(text="Write to ana@acme.test for details.")
    monkeypatch.setattr("analysis.web_analyzer.get_text_from_url", lambda url: served.text)
    monkeypatch.setattr("analysis.advanced_osint.get_dynamic_text_from_url",
                        lambda url: served.text)
    return served


class TestUrlAnalysis:
    @pytest.mark.parametrize("action", ["summarize", "deep-ai", "graph"])
    def test_ai_actions_need_an_agent(self, tui, menu_hub, monkeypatch, record, flat, action):
        picker = record(None)
        monkeypatch.setattr(menus, "select_ia_agent", picker)
        tui.script(action, "back")

        results_menu.process_selected_url(URL)

        assert len(picker.calls) == 1
        assert "AI needed" in flat()

    def test_summary(self, tui, menu_hub, page, monkeypatch, record, flat):
        summarize = record("Acme sells anvils.")
        monkeypatch.setattr("analysis.web_analyzer.summarize_text_with_ia", summarize)
        tui.script("summarize", "back")

        results_menu.process_selected_url(URL, AGENT)

        assert summarize.calls == [((page.text, AGENT), {})]
        assert "Acme sells anvils." in flat()

    def test_agent_picked_once_is_kept(self, tui, menu_hub, page, monkeypatch, record):
        picker = record(AGENT)
        analyse = record("Deep analysis.")
        monkeypatch.setattr(menus, "select_ia_agent", picker)
        monkeypatch.setattr("analysis.web_analyzer.translate_and_analyze_with_ia", analyse)
        tui.script("deep-ai", "deep-ai", "back")

        results_menu.process_selected_url(URL)

        assert len(picker.calls) == 1
        assert len(analyse.calls) == 2

    def test_graph_is_named_after_the_domain(self, tui, menu_hub, page, monkeypatch, record,
                                             flat):
        graph = record("outputs/graph_acme_test.html")
        monkeypatch.setattr("analysis.web_analyzer.extract_entities_and_graph", graph)
        tui.script("graph", "back")

        results_menu.process_selected_url(URL, AGENT)

        assert graph.calls == [((page.text, AGENT), {"output_filename": "graph_acme_test.html"})]
        assert "Relationship graph saved: outputs/graph_acme_test.html" in flat()

    @pytest.mark.parametrize("action, tool", [("pii", "url-pii"), ("deep-scrape", "url-pii-deep")])
    def test_extraction_records_evidence_and_feeds_the_hub(self, tui, menu_hub, page, flat,
                                                           action, tool):
        tui.script(action, "back")

        results_menu.process_selected_url(URL)

        evidence = state.CURRENT_CASE["evidence"]
        assert [(e["value"], e["source"], e["tool"]) for e in evidence] == [
            ("ana@acme.test", URL, tool)]
        assert [f.value for f in menu_hub.of_kind("email")] == ["ana@acme.test"]
        assert "1 new finding(s) added to the hub" in flat()

    @pytest.mark.parametrize("action, message", [
        ("pii", "No extractable identifiers found"),
        ("deep-scrape", "No identifiers found in deep content"),
    ])
    def test_extraction_with_nothing_found(self, tui, menu_hub, page, flat, action, message):
        page.text = "Nothing to see here."
        tui.script(action, "back")

        results_menu.process_selected_url(URL)

        assert message in flat()
        assert state.CURRENT_CASE["evidence"] == []

    def test_single_tools(self, tui, menu_hub, monkeypatch, record):
        fakes = SimpleNamespace(tech=record(), file=record(), shot=record())

        class FileDownload:
            def download_file_direct(self, url, extract_metadata):
                fakes.file.calls.append(((url,), {"extract_metadata": extract_metadata}))

        monkeypatch.setattr("analysis.tech_scanner.tech_scan", fakes.tech)
        monkeypatch.setattr("utils.file_download.FileDownload", FileDownload)
        monkeypatch.setattr("analysis.advanced_osint.take_screenshot", fakes.shot)
        tui.script("tech", "file", "screenshot", "wayback", "back", None)

        results_menu.process_selected_url(URL)

        assert fakes.tech.calls == fakes.shot.calls == [((URL,), {})]
        assert fakes.file.calls == [((URL,), {"extract_metadata": True})]

    def test_media_download(self, tui, menu_hub, monkeypatch, record):
        media = record()
        monkeypatch.setattr("utils.media_downloader.download_media", media)
        tui.script("media", "videos", True, "back")

        results_menu.process_selected_url(URL)

        assert media.calls == [((URL, "acme_test_videos_media.zip"),
                                {"media_type": "videos", "use_selenium": True})]

    def test_media_failure_is_reported(self, tui, menu_hub, monkeypatch, flat):
        def broken(*args, **kwargs):
            raise RuntimeError("selenium missing")

        monkeypatch.setattr("utils.media_downloader.download_media", broken)
        tui.script("media", None, False, "back")

        results_menu.process_selected_url(URL)

        assert "selenium missing" in flat()


# ---------------------------------------------------------------------------
# Results browser
# ---------------------------------------------------------------------------

@pytest.fixture
def browser(monkeypatch, record):
    """Stand-ins for everything the results browser hands work to."""
    fakes = SimpleNamespace(analyse=record(), hub=record(), save=record(), media=record(),
                            exported=[])

    class ResultsParser:
        def __init__(self, results, extracted=None):
            self.count = len(results)

        def export_excel(self, filename):
            fakes.exported.append((filename, self.count))

    monkeypatch.setattr(results_menu, "process_selected_url", fakes.analyse)
    monkeypatch.setattr(hub_menu, "findings_hub_menu", fakes.hub)
    monkeypatch.setattr(results_menu, "save_case", fakes.save)
    monkeypatch.setattr("utils.media_downloader.download_media", fakes.media)
    monkeypatch.setattr("utils.results_parse.ResultsParser", ResultsParser)
    return fakes


class TestResultsBrowser:
    def test_results_join_the_case_and_the_hub(self, tui, menu_hub, browser):
        tui.script("exit")

        results_menu.interactive_analysis_menu(rows(3))

        assert [r["id"] for r in state.CURRENT_CASE["results"]] == [1, 2, 3]
        assert state.CURRENT_CASE["search_params"] == {"type": "manual", "value": "N/A"}
        assert len(menu_hub.of_kind("url")) == 3

    def test_paging(self, tui, menu_hub, browser, flat):
        tui.script("p", "n", "n", "n", "j 2", "j 9", "j x", "all", "page", "exit")

        results_menu.interactive_analysis_menu(rows(23))

        out = flat()
        for text in ("Already on the first page", "page 3/3", "Already on the last page",
                     "Page out of range — enter 1 to 3", "Usage: j <page number>",
                     "(23 total)"):
            assert text in out

    def test_commands(self, tui, menu_hub, browser):
        tui.script("hub", "evidence", "save", "excel", "found", "excel", "", "exit")

        results_menu.interactive_analysis_menu(rows(3), ia_agent=AGENT)

        assert browser.hub.calls == [((AGENT,), {})]
        assert len(browser.save.calls) == 1
        assert browser.exported == [("found.xlsx", 3), ("results.xlsx", 3)]

    def test_picking_a_result_opens_its_analysis(self, tui, menu_hub, browser, flat):
        tui.script("2", "9", "what", "salir")

        results_menu.interactive_analysis_menu(rows(3), ia_agent=AGENT)

        assert browser.analyse.calls == [(("https://acme.test/2", AGENT), {})]
        out = flat()
        assert "Index out of range" in out
        assert "Enter a result ID" in out

    def test_media_for_several_results(self, tui, menu_hub, browser, flat):
        tui.script("media", "1, 3, 9, x", "images", False, "media", "none", "exit")

        results_menu.interactive_analysis_menu(rows(3))

        assert [args for args, _ in browser.media.calls] == [
            ("https://acme.test/1", "acme_test_images_media.zip"),
            ("https://acme.test/3", "acme_test_images_media.zip")]
        out = flat()
        assert "ID 9 is out of range" in out
        assert "No valid IDs provided" in out

    def test_media_failure_names_the_result(self, tui, menu_hub, browser, monkeypatch, flat):
        def broken(*args, **kwargs):
            raise RuntimeError("timeout")

        monkeypatch.setattr("utils.media_downloader.download_media", broken)
        tui.script("media", "2", None, False, "exit")

        results_menu.interactive_analysis_menu(rows(3))

        assert "ID 2: timeout" in flat()
