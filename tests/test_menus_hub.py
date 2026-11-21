"""The Findings Hub pivot loop, driven through a scripted terminal."""

from types import SimpleNamespace

import pytest

from cli import actions, hub_menu


@pytest.fixture
def full_hub(menu_hub):
    """A hub with one finding of every kind the pivots act on."""
    menu_hub.add_url("https://acme.test/team", source="search")
    menu_hub.add_email("ana@acme.test", source="search")
    menu_hub.add_username("Ana Lee", source="guided")
    menu_hub.add_phone("+14155552671", source="guided")
    return menu_hub


def offered(tui, title):
    """The values of the last menu shown with *title*."""
    return [values for shown, values in tui.menus if shown == title][-1]


class TestMenuOffersWhatTheHubHolds:
    def test_empty_hub(self, tui, menu_hub, flat):
        tui.script("back")

        hub_menu.findings_hub_menu()

        assert offered(tui, "Next step") == ["add", "back"]
        assert "No findings yet" in flat()

    def test_hub_with_every_kind(self, tui, full_hub, flat):
        tui.script(None)

        hub_menu.findings_hub_menu()

        assert offered(tui, "Next step") == [
            "analyse", "download", "search", "recon", "user-enum", "email-enum",
            "phone-osint", "hibp", "add", "view", "clear", "back"]
        assert "ana@acme.test" in flat()

    def test_offer_opens_the_hub_only_with_findings(self, tui, menu_hub):
        hub_menu._offer_hub()
        assert tui.menus == []

        menu_hub.add_domain("acme.test")
        tui.script("back")
        hub_menu._offer_hub()
        assert len(tui.menus) == 1


class TestPivots:
    def test_analyse_opens_the_url_menu(self, tui, full_hub, monkeypatch, record):
        analyse = record()
        monkeypatch.setattr(hub_menu, "process_selected_url", analyse)
        tui.script("analyse", "https://acme.test/team", "analyse", "__cancel__", "back")

        hub_menu.findings_hub_menu(ia_agent="agent")

        assert analyse.calls == [(("https://acme.test/team", "agent"), {})]

    @pytest.mark.parametrize("value, query", [
        ("Ana Lee", '"Ana Lee"'),
        ("ana@acme.test", "ana@acme.test"),
    ])
    def test_search_pivot_quotes_values_with_spaces(self, tui, full_hub, monkeypatch, record,
                                                    value, query):
        search = record()
        monkeypatch.setattr(actions, "do_search", search)
        tui.script("search", value, "brave", "back")

        hub_menu.findings_hub_menu()

        (sent, engine), _ = search.calls[0]
        assert (sent, engine) == (query, "brave")

    def test_recon_pivot_feeds_the_hub(self, tui, full_hub, monkeypatch, record, flat):
        monkeypatch.setattr("analysis.domain_osint.domain_recon",
                            record({"subdomains": ["dev.acme.test"]}))
        tui.script("recon", "acme.test", "back")

        hub_menu.findings_hub_menu()

        assert "dev.acme.test" in [f.value for f in full_hub.of_kind("domain")]
        assert "1 new finding(s) added" in flat()

    def test_username_pivot_feeds_profile_urls(self, tui, full_hub, monkeypatch, record):
        enum = record([{"site": "GitHub", "url": "https://github.test/analee"}])
        monkeypatch.setattr("search.username_enum.username_enum", enum)
        tui.script("user-enum", "Ana Lee", "sherlock", "back")

        hub_menu.findings_hub_menu()

        assert enum.calls == [(("Ana Lee",), {"backend": "sherlock"})]
        assert "https://github.test/analee" in [f.value for f in full_hub.of_kind("url")]

    def test_email_pivot_feeds_registered_services(self, tui, full_hub, monkeypatch, record):
        enum = record([{"service": "svc", "domain": "svc.test", "status": "claimed"}])
        monkeypatch.setattr("search.email_enum.email_enum", enum)
        tui.script("email-enum", "ana@acme.test", True, "back")

        hub_menu.findings_hub_menu()

        assert enum.calls == [(("ana@acme.test",), {"only_used": True})]
        assert "svc.test" in [f.value for f in full_hub.of_kind("domain")]

    def test_phone_pivot_runs_its_footprint(self, tui, full_hub, monkeypatch, record):
        report = {"footprint": [
            {"label": "Exact number", "kind": "search", "value": '"+14155552671"'},
            {"label": "Caller ID", "kind": "link", "value": "https://lookup.test/14155552671"},
        ]}
        lookup, search = record(report), record()
        monkeypatch.setattr("search.phone_osint.phone_osint", lookup)
        monkeypatch.setattr(actions, "do_search", search)
        tui.script("phone-osint", "+14155552671", "0", "duckduckgo", "1", "__done__", "back")

        hub_menu.findings_hub_menu()

        assert lookup.calls == [(("+14155552671",), {})]
        (query, engine), _ = search.calls[0]
        assert (query, engine) == ('"+14155552671"', "duckduckgo")
        assert "https://lookup.test/14155552671" in [f.value for f in full_hub.of_kind("url")]

    def test_phone_without_report_or_footprint_offers_nothing(self, tui, full_hub,
                                                              monkeypatch, record):
        monkeypatch.setattr("search.phone_osint.phone_osint", record(None))
        tui.script("phone-osint", "+14155552671", "back")

        hub_menu.findings_hub_menu()
        hub_menu._phone_footprint_followup({"footprint": []})

        assert [title for title, _ in tui.menus].count("Run a footprint pivot?") == 0

    @pytest.mark.parametrize("target, account, domain", [
        ("account:ana@acme.test", [(("ana@acme.test",), {"include_pastes": False})], []),
        ("domain:acme.test", [], [(("acme.test",), {})]),
        ("__cancel__", [], []),
    ])
    def test_hibp_pivot(self, tui, full_hub, monkeypatch, record, target, account, domain):
        check_account, check_domain = record(), record()
        monkeypatch.setattr("analysis.hibp.check_account", check_account)
        monkeypatch.setattr("analysis.hibp.check_domain", check_domain)
        answers = ["hibp", target] + ([False] if target.startswith("account") else []) + ["back"]
        tui.script(*answers)

        hub_menu.findings_hub_menu()

        assert (check_account.calls, check_domain.calls) == (account, domain)

    def test_hibp_pivot_needs_an_email_or_domain(self, menu_hub, flat):
        hub_menu._hub_hibp_pivot(menu_hub)

        assert "No emails or domains to check" in flat()


class TestDownloadPivot:
    @pytest.fixture
    def downloads(self, monkeypatch, record):
        fakes = SimpleNamespace(file=record(), media=record())

        class FileDownload:
            def download_file_direct(self, url, extract_metadata):
                fakes.file.calls.append(((url,), {"extract_metadata": extract_metadata}))

        monkeypatch.setattr("utils.file_download.FileDownload", FileDownload)
        monkeypatch.setattr("utils.media_downloader.download_media", fakes.media)
        return fakes

    def test_direct_file(self, tui, full_hub, downloads):
        tui.script("download", "https://acme.test/team", "file", "back")

        hub_menu.findings_hub_menu()

        assert downloads.file.calls == [(("https://acme.test/team",), {"extract_metadata": True})]

    def test_page_media(self, tui, full_hub, downloads):
        tui.script("download", "https://acme.test/team", "media", "images", True, "back")

        hub_menu.findings_hub_menu()

        assert downloads.media.calls == [(
            ("https://acme.test/team", "acme_test_images_media.zip"),
            {"media_type": "images", "use_selenium": True})]

    def test_media_failure_is_reported(self, tui, full_hub, monkeypatch, flat):
        def broken(*args, **kwargs):
            raise RuntimeError("no media found")

        monkeypatch.setattr("utils.media_downloader.download_media", broken)
        tui.script("download", "https://acme.test/team", "media", None, False, "back")

        hub_menu.findings_hub_menu()

        assert "no media found" in flat()

    def test_cancelled_url_downloads_nothing(self, tui, full_hub, downloads):
        tui.script("download", "__cancel__", "back")

        hub_menu.findings_hub_menu()

        assert downloads.file.calls == downloads.media.calls == []


class TestManageFindings:
    def test_add_a_target_once(self, tui, menu_hub, flat):
        tui.script("add", "email", "Ana@Acme.test", "add", "email", "ana@acme.test", "back")

        hub_menu.findings_hub_menu()

        assert [f.value for f in menu_hub.of_kind("email")] == ["ana@acme.test"]
        out = flat()
        assert "Added email: Ana@Acme.test" in out
        assert "Already present" in out

    def test_add_needs_a_kind_and_a_value(self, tui, menu_hub, flat):
        tui.script("add", None, "add", "url", "", "back")

        hub_menu.findings_hub_menu()

        assert menu_hub.is_empty()
        assert "Value cannot be empty" in flat()

    def test_view_lists_every_finding_with_its_source(self, tui, full_hub, flat):
        tui.script("view", "back")

        hub_menu.findings_hub_menu()

        out = flat()
        assert "All Findings" in out and "+14155552671" in out and "guided" in out

    @pytest.mark.parametrize("sure, left", [(True, 0), (False, 4)])
    def test_clear_asks_first(self, tui, full_hub, sure, left):
        tui.script("clear", sure, "back")

        hub_menu.findings_hub_menu()

        assert len(full_hub) == left

    def test_picker_with_nothing_to_pick(self, flat):
        assert hub_menu._pick_value([], "Pick a URL") is None
        assert "Nothing of that kind" in flat()
