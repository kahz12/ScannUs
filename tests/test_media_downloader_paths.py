"""
``utils.media_downloader`` beyond the static page flow: MIME mapping, HTML
discovery, size limits, content deduplication, ffprobe, the aiohttp
downloader, yt-dlp, the Selenium video and scroll scrapers, and the three
video tiers of ``download_media``.
"""

import asyncio
import json
import os
import subprocess
import sys
import types
import zipfile
from types import SimpleNamespace

import aiohttp
import pytest
import requests

import utils.media_downloader as md

PAGE = "https://acme.test/gallery"
BIG = b"x" * (md.MIN_FILE_SIZE_BYTES + 10)
PROGRESS = SimpleNamespace(advance=lambda task: None)


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


# ---------------------------------------------------------------------------
# Naming and discovery
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ctype, expected", [
    ("", ("other", ".bin")),
    ("image/avif", ("images", ".avif")),
    ("video/x-matroska", ("videos", ".x-matroska")),
    ("audio/flac; rate=44100", ("audio", ".flac")),
    ("text/plain", ("other", ".bin")),
    ("image/png", ("images", ".png")),
])
def test_mime_mapping(ctype, expected):
    assert md._resolve_mime_info(ctype) == expected


def test_html_discovery():
    html = """
      <img srcset="small.jpg 400w, large.jpg 800w" data-src="/lazy.png">
      <img src="data:image/png;base64,AAAA">
      <div style="background-image: url('/bg.webp')"></div>
      <div style="background: url(data:image/gif;base64,R0)"></div>
      <video src="/clip.mp4"></video>
    """

    assert md._extract_media_urls_from_html(html, PAGE, "images") == [
        "https://acme.test/lazy.png", "https://acme.test/large.jpg", "https://acme.test/bg.webp"]
    assert md._extract_media_urls_from_html(html, PAGE, "videos") == ["https://acme.test/clip.mp4"]


# ---------------------------------------------------------------------------
# One download
# ---------------------------------------------------------------------------

class Stream:
    def __init__(self, chunks, ctype="image/png", length=None, breaks=False):
        self.chunks, self.breaks = chunks, breaks
        self.headers = {"content-type": ctype}
        if length is not None:
            self.headers["content-length"] = str(length)

    def iter_content(self, chunk_size):
        yield from self.chunks
        if self.breaks:
            raise ConnectionResetError("connection reset")


class TestDownloadSingle:
    def run(self, monkeypatch, tmp_path, response):
        def fetch(url, headers, max_retries):
            if isinstance(response, BaseException):
                raise response
            return response

        monkeypatch.setattr(md, "_fetch_with_retry", fetch)
        return md._download_single(f"{PAGE}/a.png", str(tmp_path), {}, PROGRESS, 1)

    def test_declared_size_below_the_limit_is_not_read(self, monkeypatch, tmp_path):
        ok, message = self.run(monkeypatch, tmp_path, Stream([BIG], length=100))

        assert not ok and message.startswith("Skipped (too small: 100B")
        assert list(tmp_path.iterdir()) == []

    def test_broken_stream_leaves_no_partial_file(self, monkeypatch, tmp_path):
        ok, message = self.run(monkeypatch, tmp_path, Stream([b"x" * 10], breaks=True))

        assert not ok and "Unexpected error" in message and "connection reset" in message
        assert list((tmp_path / "images").iterdir()) == []

    def test_request_failure(self, monkeypatch, tmp_path):
        ok, message = self.run(monkeypatch, tmp_path, requests.ConnectionError("refused"))

        assert not ok and message.startswith("Download failed")


# ---------------------------------------------------------------------------
# Deduplication and ffprobe
# ---------------------------------------------------------------------------

class TestDedupe:
    def test_identical_files_are_removed(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "1.jpg").write_bytes(b"same")
        (tmp_path / "a" / "2.jpg").write_bytes(b"same")
        (tmp_path / "a" / "3.jpg").write_bytes(b"other")

        assert md._dedupe_by_content_hash(str(tmp_path)) == 1
        assert sorted(p.name for p in (tmp_path / "a").iterdir()) == ["1.jpg", "3.jpg"]

    def test_unreadable_or_locked_files_are_left(self, tmp_path, monkeypatch):
        for name in ("1.jpg", "2.jpg", "3.jpg"):
            (tmp_path / name).write_bytes(b"same")
        real_sha = md._sha256

        def sha(path):
            if path.endswith("3.jpg"):
                raise PermissionError("locked")
            return real_sha(path)

        def remove(path):
            raise PermissionError("in use")

        monkeypatch.setattr(md, "_sha256", sha)
        monkeypatch.setattr(md.os, "remove", remove)

        assert md._dedupe_by_content_hash(str(tmp_path)) == 0


PROBE = {
    "format": {"duration": "12.5", "size": "2048", "bit_rate": "1000", "format_name": "mp4"},
    "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
                 "r_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100"}],
}


class TestFfprobe:
    @pytest.fixture
    def ffprobe(self, monkeypatch):
        holder = SimpleNamespace(result=SimpleNamespace(returncode=0, stdout=json.dumps(PROBE)))
        monkeypatch.setattr(md.shutil, "which", lambda name: "/usr/bin/ffprobe")

        def run(*args, **kwargs):
            if isinstance(holder.result, BaseException):
                raise holder.result
            return holder.result

        monkeypatch.setattr(md.subprocess, "run", run)
        return holder

    def test_metadata(self, ffprobe):
        meta = md._ffprobe_metadata("clip.mp4")

        assert (meta["width"], meta["height"], meta["video_codec"], meta["audio_codec"]) == (
            1920, 1080, "h264", "aac")

    @pytest.mark.parametrize("result", [
        SimpleNamespace(returncode=1, stdout=""),
        SimpleNamespace(returncode=0, stdout="not json"),
        subprocess.TimeoutExpired("ffprobe", 30),
    ])
    def test_unreadable_file(self, ffprobe, result):
        ffprobe.result = result

        assert md._ffprobe_metadata("clip.mp4") is None

    def test_without_ffprobe(self, monkeypatch):
        monkeypatch.setattr(md.shutil, "which", lambda name: None)

        assert md._ffprobe_metadata("clip.mp4") is None

    def test_table(self, ffprobe, tmp_path, monkeypatch, flat):
        (tmp_path / "clip.mp4").write_bytes(b"v")
        (tmp_path / "odd.mp4").write_bytes(b"v")
        metas = {"clip.mp4": md._ffprobe_metadata("x"), "odd.mp4": {"duration": "n/a"}}
        monkeypatch.setattr(md, "_ffprobe_metadata", lambda path: metas[os.path.basename(path)])

        md._print_video_metadata_table(str(tmp_path))

        out = flat()
        assert "1920x1080" in out and "12.5s" in out and "n/a" in out

    def test_table_needs_readable_videos(self, tmp_path, monkeypatch, flat):
        md._print_video_metadata_table(str(tmp_path / "missing"))
        md._print_video_metadata_table(str(tmp_path))
        (tmp_path / "clip.mp4").write_bytes(b"v")
        monkeypatch.setattr(md, "_ffprobe_metadata", lambda path: None)
        md._print_video_metadata_table(str(tmp_path))

        assert flat() == ""


# ---------------------------------------------------------------------------
# aiohttp downloader
# ---------------------------------------------------------------------------

class Content:
    def __init__(self, chunks, breaks=False):
        self.chunks, self.breaks = chunks, breaks

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk
        if self.breaks:
            raise RuntimeError("stream reset")


class AsyncReply:
    def __init__(self, status=200, chunks=(BIG,), length=None, breaks=False):
        self.status = status
        self.headers = {"content-type": "image/png"}
        if length is not None:
            self.headers["content-length"] = str(length)
        self.content = Content(list(chunks), breaks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class Session:
    """Answers each get with the next reply; an exception is raised instead."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


@pytest.fixture
def no_wait(monkeypatch):
    async def sleep(seconds):
        return None

    monkeypatch.setattr(md.asyncio, "sleep", sleep)


class TestAsyncDownloadSingle:
    def run(self, tmp_path, session):
        return asyncio.run(md._async_download_single(
            session, f"{PAGE}/a.png", str(tmp_path), {}, PROGRESS, 1, md.MIN_FILE_SIZE_BYTES))

    def test_success(self, tmp_path):
        ok, path = self.run(tmp_path, Session(AsyncReply()))

        assert ok and os.path.getsize(path) == len(BIG)

    @pytest.mark.parametrize("reply, start", [
        (AsyncReply(404), "HTTP 404"),
        (AsyncReply(length=100), "Skipped (too small: 100B)"),
        (AsyncReply(chunks=[b"tiny"]), "Skipped (too small after download: 4B)"),
        (AsyncReply(chunks=[b"x"], breaks=True), "Async error"),
        (ValueError("bad url"), "Async error"),
    ])
    def test_no_file_is_kept(self, tmp_path, reply, start):
        ok, message = self.run(tmp_path, Session(reply))

        assert not ok and message.startswith(start)
        assert not any(p.is_file() for p in tmp_path.rglob("*"))

    def test_connection_failures_are_retried_then_given_up(self, tmp_path, no_wait):
        session = Session(*[aiohttp.ClientConnectionError("refused")] * 4)

        ok, message = self.run(tmp_path, session)

        assert not ok and "refused" in message
        assert session.calls == 4

    def test_busy_server_is_retried_until_the_last_attempt(self, tmp_path, no_wait):
        session = Session(*[AsyncReply(503)] * 4)

        ok, message = self.run(tmp_path, session)

        assert (ok, message, session.calls) == (False, f"HTTP 503 for {PAGE}/a.png", 4)


def test_async_batch_counts_each_outcome(monkeypatch, tmp_path, flat):
    outcomes = iter([(True, "a"), (False, "Skipped (too small: 1B): b"),
                     (False, "HTTP 404 for c"), RuntimeError("crashed")])

    async def single(session, url, *args):
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    class Plain:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(md, "_async_download_single", single)
    monkeypatch.setattr(md.aiohttp, "TCPConnector", lambda **kwargs: None)
    monkeypatch.setattr(md.aiohttp, "ClientSession", Plain)

    counts = asyncio.run(md._download_media_async(list("abcd"), str(tmp_path), {}, PROGRESS, 1, 1))

    assert counts == (1, 1, 2)
    out = flat()
    assert "Skipped (too small: 1B): b" in out and "HTTP 404 for c" in out


# ---------------------------------------------------------------------------
# yt-dlp
# ---------------------------------------------------------------------------

def ytdlp_module(info=None, fail=None, hook_files=()):
    """A ``yt_dlp`` module whose YoutubeDL returns *info* or raises *fail*."""
    module = types.ModuleType("yt_dlp")

    class YoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            for name in hook_files:
                for hook in self.options["progress_hooks"]:
                    hook({"status": "finished", "filename": name})
            if fail:
                raise fail
            return info

    module.YoutubeDL = YoutubeDL
    return module


class TestYtDlp:
    def test_files_from_entries_and_hooks(self, monkeypatch, tmp_path):
        clip, other = tmp_path / "clip.mp4", tmp_path / "hooked.mp4"
        clip.write_bytes(b"v")
        other.write_bytes(b"v")
        info = {"entries": [{"requested_downloads": [{"filepath": str(clip)},
                                                     {"filename": str(tmp_path / "gone.mp4")}]},
                            None]}
        monkeypatch.setitem(sys.modules, "yt_dlp",
                            ytdlp_module(info, hook_files=[str(other), str(other)]))

        assert md._download_videos_ytdlp(PAGE, str(tmp_path)) == [str(other), str(clip)]

    def test_nothing_extracted(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "yt_dlp", ytdlp_module(None))

        assert md._download_videos_ytdlp(PAGE, str(tmp_path)) == []

    def test_unsupported_site(self, monkeypatch, tmp_path, flat):
        monkeypatch.setitem(sys.modules, "yt_dlp",
                            ytdlp_module(fail=RuntimeError("Unsupported URL")))

        assert md._download_videos_ytdlp(PAGE, str(tmp_path)) == []
        assert "yt-dlp could not extract" in flat()

    def test_not_installed(self, monkeypatch, tmp_path, flat):
        monkeypatch.setitem(sys.modules, "yt_dlp", None)

        assert md._download_videos_ytdlp(PAGE, str(tmp_path)) == []
        assert "pip install yt-dlp" in flat()


# ---------------------------------------------------------------------------
# Selenium scrapers
# ---------------------------------------------------------------------------

class Element:
    def __init__(self, attrs=None, children=(), clickable=True):
        self.attrs, self.children, self.clickable = attrs or {}, list(children), clickable

    def get_attribute(self, name):
        return self.attrs.get(name)

    def find_elements(self, by, value):
        return self.children


class Driver:
    def __init__(self, html="", heights=(100, 100), videos=(), play=(), fail=None):
        self.page_source = html
        self.heights = list(heights)
        self.videos, self.play, self.fail = list(videos), list(play), fail
        self.quit_called = False

    def set_page_load_timeout(self, seconds):
        pass

    def get(self, url):
        if self.fail:
            raise self.fail

    def execute_script(self, script, *args):
        if args and not args[0].clickable and "click" in script:
            raise RuntimeError("not clickable")
        if script.startswith("return"):
            return self.heights.pop(0) if self.heights else 100
        return None

    def find_elements(self, by, value):
        if value == "video" and by == "tag name":
            return self.videos
        if value == "[class*='play']":
            return self.play
        if value == "[aria-label*='Play']":
            raise RuntimeError("bad selector")
        return []

    def quit(self):
        self.quit_called = True


@pytest.fixture
def firefox(monkeypatch):
    holder = SimpleNamespace(driver=Driver())
    monkeypatch.setattr("selenium.webdriver.Firefox", lambda *args, **kwargs: holder.driver)
    monkeypatch.setattr(md.time, "sleep", lambda seconds: None)
    return holder


class TestSeleniumVideos:
    def test_clicks_play_and_reads_sources_and_manifests(self, firefox, flat):
        firefox.driver = Driver(
            html='<script>load("https://cdn.acme.test/live/index.m3u8?t=1")</script>',
            play=[Element(), Element(clickable=False)],
            videos=[Element({"src": "https://cdn.acme.test/a.mp4"},
                            children=[Element({"src": "/b.webm"}), Element({"src": "blob:x"})]),
                    Element({"src": "blob:https://acme.test/1"})],
        )

        urls = md._extract_video_urls_selenium_interaction(PAGE)

        assert urls == ["https://cdn.acme.test/a.mp4", "https://acme.test/b.webm",
                        "https://cdn.acme.test/live/index.m3u8?t=1"]
        assert "Clicked 1 play element(s)" in flat()
        assert firefox.driver.quit_called

    def test_page_without_play_buttons(self, firefox, flat):
        assert md._extract_video_urls_selenium_interaction(PAGE) == []
        assert "No play buttons found" in flat()

    def test_browser_failure(self, firefox, flat):
        firefox.driver = Driver(fail=RuntimeError("geckodriver not found"))

        assert md._extract_video_urls_selenium_interaction(PAGE) == []
        assert "Interactive Selenium extraction failed" in flat()

    def test_selenium_missing(self, monkeypatch, flat):
        monkeypatch.setitem(sys.modules, "selenium", None)

        assert md._extract_video_urls_selenium_interaction(PAGE) == []
        assert md._scrape_media_urls_dynamic(PAGE, "images") is None
        assert "Selenium is not installed" in flat()


class TestSeleniumScroll:
    def test_rendered_page_is_scrolled_then_parsed(self, firefox):
        firefox.driver = Driver(html='<img src="/a.jpg">', heights=(100, 300, 300))

        assert md._scrape_media_urls_dynamic(PAGE, "images") == ["https://acme.test/a.jpg"]
        assert firefox.driver.heights == []

    def test_render_failure(self, firefox, flat):
        firefox.driver = Driver(fail=RuntimeError("timeout"))

        assert md._scrape_media_urls_dynamic(PAGE, "all") is None
        assert "Selenium error: timeout" in flat()


# ---------------------------------------------------------------------------
# download_media tiers
# ---------------------------------------------------------------------------

@pytest.fixture
def tiers(monkeypatch, tmp_path):
    """Stand-ins for every discovery and download step; batches write real files."""
    monkeypatch.setattr(md, "DIR_MEDIA", str(tmp_path))
    plan = SimpleNamespace(ytdlp=[], selenium=[], static=[], dynamic=[], batches=[],
                           metadata=[])

    def batch(urls, temp_dir, headers, min_size, workers, label, *, force_subdir=None,
              verbose=False):
        plan.batches.append((list(urls), force_subdir))
        folder = os.path.join(temp_dir, force_subdir or "images")
        os.makedirs(folder, exist_ok=True)
        for n, url in enumerate(urls):
            with open(os.path.join(folder, f"{len(plan.batches)}_{n}.bin"), "wb") as f:
                f.write(url.encode())
        return len(urls), 0, 0

    def ytdlp(url, folder):
        paths = []
        for name in plan.ytdlp:
            path = os.path.join(folder, name)
            with open(path, "wb") as f:
                f.write(name.encode())
            paths.append(path)
        return paths

    monkeypatch.setattr(md, "_download_videos_ytdlp", ytdlp)
    monkeypatch.setattr(md, "_extract_video_urls_selenium_interaction", lambda url: plan.selenium)
    monkeypatch.setattr(md, "_scrape_media_urls_static",
                        lambda url, headers, kind: plan.static if kind != "videos" else plan.static_videos)
    monkeypatch.setattr(md, "_scrape_media_urls_dynamic", lambda url, kind: plan.dynamic)
    monkeypatch.setattr(md, "_download_batch_sync", batch)
    monkeypatch.setattr(md, "_print_video_metadata_table", plan.metadata.append)
    plan.static_videos = []
    plan.archive = tmp_path / "out.zip"
    return plan


def archived(plan):
    with zipfile.ZipFile(plan.archive) as zf:
        return sorted(zf.namelist())


class TestDownloadMedia:
    def test_ytdlp_videos_skip_the_other_tiers(self, tiers, flat):
        tiers.ytdlp = ["talk.mp4"]

        assert md.download_media(PAGE, "out.zip", media_type="videos") is True
        assert archived(tiers) == ["videos/talk.mp4"]
        assert tiers.batches == []
        assert len(tiers.metadata) == 1
        assert "yt-dlp downloaded 1 video(s): talk.mp4" in flat()

    def test_selenium_tier(self, tiers):
        tiers.selenium = ["https://cdn.acme.test/a.mp4"]

        assert md.download_media(PAGE, "out.zip", media_type="videos") is True
        assert tiers.batches == [(["https://cdn.acme.test/a.mp4"], "videos")]

    def test_static_tier(self, tiers):
        tiers.static_videos = ["https://acme.test/b.mp4"]

        assert md.download_media(PAGE, "out.zip", media_type="videos") is True
        assert tiers.batches == [(["https://acme.test/b.mp4"], "videos")]

    def test_scrolled_page_for_images_and_video_links_left_out(self, tiers, flat):
        tiers.dynamic = [f"https://acme.test/{n}.jpg" for n in range(32)] + [
            "https://acme.test/clip.MP4"]

        assert md.download_media(PAGE, "out.zip", media_type="images", use_selenium=True) is True
        assert len(tiers.batches[0][0]) == 32
        assert "+2 more" in flat()

    def test_unrenderable_page_is_a_failure(self, tiers):
        tiers.dynamic = None

        assert md.download_media(PAGE, "out.zip", media_type="images", use_selenium=True) is False

    def test_identical_downloads_are_archived_once(self, tiers, monkeypatch, flat):
        tiers.static = ["https://acme.test/a.jpg"]

        def same_bytes(urls, temp_dir, *args, **kwargs):
            folder = os.path.join(temp_dir, "images")
            os.makedirs(folder, exist_ok=True)
            for name in ("a.jpg", "b.jpg"):
                with open(os.path.join(folder, name), "wb") as f:
                    f.write(b"same")
            return 2, 0, 0

        monkeypatch.setattr(md, "_download_batch_sync", same_bytes)

        assert md.download_media(PAGE, "out.zip", media_type="images") is True
        assert archived(tiers) == ["images/a.jpg"]
        assert "Removed 1 duplicate file(s)" in flat()

    def test_async_downloader(self, tiers, monkeypatch, flat):
        tiers.static = ["https://acme.test/a.jpg"]
        seen = {}

        async def download(urls, temp_dir, headers, progress, task, min_size, **kwargs):
            seen.update(kwargs)
            os.makedirs(os.path.join(temp_dir, "images"), exist_ok=True)
            with open(os.path.join(temp_dir, "images", "a.jpg"), "wb") as f:
                f.write(b"a")
            return 1, 0, 0

        monkeypatch.setattr(md, "_HAS_AIOHTTP", True)
        monkeypatch.setattr(md, "_download_media_async", download)

        assert md.download_media(PAGE, "out.zip", media_type="images", use_async=True,
                                 verify_ssl=False) is True
        assert seen == {"max_concurrent": 8, "verify_ssl": False}
        assert "Using aiohttp async downloader" in flat()

    def test_async_without_aiohttp_uses_threads(self, tiers, monkeypatch, flat):
        tiers.static = ["https://acme.test/a.jpg"]
        monkeypatch.setattr(md, "_HAS_AIOHTTP", False)

        assert md.download_media(PAGE, "out.zip", media_type="images", use_async=True) is True
        assert len(tiers.batches) == 1
        assert "aiohttp not installed" in flat()
