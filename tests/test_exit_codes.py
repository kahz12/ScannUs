"""What main() reports to the shell, and what --recon writes with --json."""

import json
import sys

import pytest
import requests

import main
import utils.media_downloader as md
import utils.results_parse as rp
from core.cache import SQLiteCache


PAGE = "https://site.test/gallery"
PHOTO = "https://site.test/photo.jpg"
SECOND_PHOTO = "https://site.test/second.jpg"
PHOTO_TAG = '<img src="photo.jpg">'
BOTH_PHOTO_TAGS = PHOTO_TAG + '<img src="second.jpg">'
FULL_SIZE = b"x" * (md.MIN_FILE_SIZE_BYTES + 1)


@pytest.fixture
def run_main(tmp_path, monkeypatch):
    """Returns a callable that runs main() and gives back its exit code."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rp, "DIR_REPORTS", str(tmp_path))
    monkeypatch.setattr(main, "init_directories", lambda: None)
    monkeypatch.setattr(main, "setup_logging", lambda debug: None)
    monkeypatch.setattr(main, "print_startup_banner", lambda has_key: None)
    monkeypatch.setattr(main, "load_environment", lambda: None)

    def run(*flags):
        monkeypatch.setattr(sys, "argv", ["main.py", *flags])
        with pytest.raises(SystemExit) as exit_info:
            main.main()
        return exit_info.value.code

    return run


@pytest.mark.parametrize("flags, route, result, code", [
    (["--username-enum", "jdoe88"], "search.username_enum.username_enum", [], 0),
    (["--username-enum", "jdoe88"], "search.username_enum.username_enum", None, 1),
    (["--email-enum", "a@acme-corp.io"], "search.email_enum.email_enum", [], 0),
    (["--email-enum", "a@acme-corp.io"], "search.email_enum.email_enum", None, 1),
    (["--phone-osint", "+14155552671"], "search.phone_osint.phone_osint", {"valid": True}, 0),
    (["--phone-osint", "nonsense"], "search.phone_osint.phone_osint", None, 1),
    (["--hibp-account", "a@acme-corp.io"], "analysis.hibp.check_account", {"checked": True}, 0),
    (["--hibp-account", "a@acme-corp.io"], "analysis.hibp.check_account", {"checked": False}, 1),
    (["--hibp-domain", "acme-corp.io"], "analysis.hibp.check_domain", [], 0),
    (["--hibp-domain", "acme-corp.io"], "analysis.hibp.check_domain", None, 1),
    (["--hibp-breach", "Adobe"], "analysis.hibp.hibp_breach", None, 1),
    (["--media-scrape", PAGE], "main.download_media", True, 0),
    (["--media-scrape", PAGE], "main.download_media", False, 1),
    (["-rev", "https://site.test/a.jpg"], "main.do_reverse_image_search", True, 0),
    (["-rev", "https://site.test/a.jpg"], "main.do_reverse_image_search", False, 1),
])
def test_exit_code_reflects_whether_the_command_could_run(
        run_main, monkeypatch, flags, route, result, code):
    monkeypatch.setattr(route, lambda *args, **kwargs: result)

    assert run_main(*flags) == code


def test_clean_account_is_a_success_but_a_missing_key_is_not(monkeypatch):
    from analysis import hibp

    monkeypatch.setattr(hibp, "render_breached_account", lambda *args: None)
    monkeypatch.setattr(hibp, "render_pastes_for_account", lambda *args: None)
    monkeypatch.setattr(hibp, "hibp_pastes_for_account", lambda email: None)

    monkeypatch.setattr(hibp, "hibp_breached_account", lambda email: [])
    assert hibp.check_account("a@acme-corp.io")["checked"] is True

    monkeypatch.setattr(hibp, "hibp_breached_account", lambda email: None)
    assert hibp.check_account("a@acme-corp.io")["checked"] is False


@pytest.fixture
def hibp_cache(tmp_path, monkeypatch):
    cache = SQLiteCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("core.cache.get_cache", lambda: cache)
    return cache


def test_failed_domain_lookup_is_not_cached_as_a_clean_domain(hibp_cache, monkeypatch):
    from analysis import hibp

    responses = iter([(503, "unavailable"), (200, [{"Name": "Adobe"}])])
    monkeypatch.setattr(hibp, "_get", lambda url, **kwargs: next(responses))

    assert hibp.hibp_breaches_for_domain("acme-corp.io") is None
    assert hibp.hibp_breaches_for_domain("acme-corp.io") == [{"Name": "Adobe"}]


@pytest.mark.parametrize("response", [(200, []), (404, [])])
def test_domain_without_breaches_is_a_success(hibp_cache, monkeypatch, response):
    from analysis import hibp

    monkeypatch.setattr(hibp, "_get", lambda url, **kwargs: response)

    assert hibp.check_domain("acme-corp.io") == []


@pytest.mark.parametrize("response", [(0, "transport: refused"), (200, "not json"), (429, "slow down")])
def test_domain_lookup_failure_reaches_the_caller(hibp_cache, monkeypatch, response):
    from analysis import hibp

    monkeypatch.setattr(hibp, "_get", lambda url, **kwargs: response)

    assert hibp.check_domain("acme-corp.io") is None


def test_failed_domain_lookup_is_not_shown_as_a_clean_domain(monkeypatch):
    from analysis import hibp

    failures, notes = [], []
    monkeypatch.setattr(hibp, "print_error", failures.append)
    monkeypatch.setattr(hibp, "print_info", notes.append)

    hibp.render_breaches_for_domain("acme-corp.io", None)

    assert len(failures) == 1
    assert notes == []


def test_planner_reports_a_failed_domain_lookup(monkeypatch):
    from analysis import hibp
    from core.planner import _dispatch_hibp_domain

    monkeypatch.setattr(hibp, "hibp_breaches_for_domain", lambda domain: None)

    outcome = _dispatch_hibp_domain({"domain": "acme-corp.io"}, None)

    assert outcome["status"] == "error"
    assert "acme-corp.io" in outcome["summary"]


class FakeResponse:
    def __init__(self, text="", status=200, content=FULL_SIZE):
        self.text = text
        self.status_code = status
        self.content = content
        self.headers = {"content-type": "image/jpeg"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        yield self.content


@pytest.fixture
def media_site(tmp_path, monkeypatch):
    """Serves a dict of URL to response, with yt-dlp and the browser finding nothing."""
    monkeypatch.setattr(md, "DIR_MEDIA", str(tmp_path))
    monkeypatch.setattr(md.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(md, "_download_videos_ytdlp", lambda url, folder: [])
    monkeypatch.setattr(md, "_extract_video_urls_selenium_interaction", lambda url: [])

    def serve(pages):
        def fake_get(url, **kwargs):
            answer = pages.get(url, FakeResponse(status=404))
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(md.requests, "get", fake_get)
        return tmp_path / "out.zip"

    return serve


@pytest.mark.parametrize("media_type", ["all", "images", "videos"])
def test_media_scrape_fails_when_the_page_cannot_be_read(media_site, media_type):
    archive = media_site({PAGE: requests.ConnectionError("refused")})

    assert md.download_media(PAGE, "out.zip", media_type=media_type) is False
    assert not archive.exists()


def test_media_scrape_fails_when_the_page_answers_with_a_failure_status(media_site):
    archive = media_site({PAGE: FakeResponse(status=403)})

    assert md.download_media(PAGE, "out.zip") is False
    assert not archive.exists()


def test_page_without_media_is_a_success(media_site):
    archive = media_site({PAGE: FakeResponse("<p>nothing here</p>")})

    assert md.download_media(PAGE, "out.zip") is True
    assert not archive.exists()


def test_downloaded_media_is_a_success(media_site):
    archive = media_site({PAGE: FakeResponse(PHOTO_TAG), PHOTO: FakeResponse()})

    assert md.download_media(PAGE, "out.zip") is True
    assert archive.exists()


def test_media_scrape_fails_when_every_download_fails(media_site):
    archive = media_site({PAGE: FakeResponse(PHOTO_TAG), PHOTO: FakeResponse(status=404)})

    assert md.download_media(PAGE, "out.zip") is False
    assert not archive.exists()


def test_partial_download_is_a_success(media_site):
    archive = media_site({
        PAGE: FakeResponse(BOTH_PHOTO_TAGS),
        PHOTO: FakeResponse(),
        SECOND_PHOTO: FakeResponse(status=404),
    })

    assert md.download_media(PAGE, "out.zip") is True
    assert archive.exists()


def test_assets_below_the_size_limit_are_not_a_failure(media_site):
    archive = media_site({PAGE: FakeResponse(PHOTO_TAG), PHOTO: FakeResponse(content=b"tiny")})

    assert md.download_media(PAGE, "out.zip") is True
    assert not archive.exists()


def test_a_saved_video_outweighs_an_unreadable_page(media_site, monkeypatch):
    archive = media_site({PAGE: requests.ConnectionError("refused")})

    def save_video(url, folder):
        path = f"{folder}/clip.mp4"
        with open(path, "wb") as video:
            video.write(FULL_SIZE)
        return [path]

    monkeypatch.setattr(md, "_download_videos_ytdlp", save_video)

    assert md.download_media(PAGE, "out.zip") is True
    assert archive.exists()


def test_media_scrape_fails_when_the_browser_cannot_render_the_page(media_site, monkeypatch):
    archive = media_site({})
    monkeypatch.setattr(md, "_scrape_media_urls_dynamic", lambda url, media_type: None)

    assert md.download_media(PAGE, "out.zip", media_type="images", use_selenium=True) is False
    assert not archive.exists()


def test_browser_failure_is_not_read_as_a_page_without_media(monkeypatch):
    def no_browser(**kwargs):
        raise RuntimeError("geckodriver not found")

    monkeypatch.setattr("selenium.webdriver.Firefox", no_browser)

    assert md._scrape_media_urls_dynamic(PAGE, "images") is None


def test_missing_selenium_is_not_read_as_a_page_without_media(monkeypatch):
    monkeypatch.setitem(sys.modules, "selenium", None)

    assert md._scrape_media_urls_dynamic(PAGE, "images") is None


def test_recon_json_writes_the_report(run_main, tmp_path, monkeypatch):
    report = {"domain": "acme-corp.io", "subdomains": ["www.acme-corp.io"], "seen": {1, 2}}
    monkeypatch.setattr("analysis.domain_osint.domain_recon", lambda target: report)

    assert run_main("--recon", "acme-corp.io", "--json", "recon.json") == 0

    saved = json.loads((tmp_path / "recon.json").read_text(encoding="utf-8"))
    assert saved["subdomains"] == ["www.acme-corp.io"]
    assert saved["seen"] == "{1, 2}"


def test_recon_without_json_writes_nothing(run_main, tmp_path, monkeypatch):
    monkeypatch.setattr("analysis.domain_osint.domain_recon", lambda target: {})

    assert run_main("--recon", "acme-corp.io") == 0

    assert list(tmp_path.iterdir()) == []
