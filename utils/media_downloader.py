import os
import re
import json
import shutil
import hashlib
import asyncio
import tempfile
import zipfile
import time
import subprocess
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.progress import (
    Progress, BarColumn,
    TransferSpeedColumn, TimeRemainingColumn, TaskProgressColumn, TextColumn
)
from rich.table import Table
from rich.box import ROUNDED
from cli.ui import console, THEME, print_info, print_warn, print_success
from core.config import DIR_MEDIA

# aiohttp is optional — fall back to ThreadPoolExecutor if absent.
try:
    import aiohttp  # type: ignore
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False

# Minimum file size in bytes to filter out tracking pixels, spacers, and favicons.
MIN_FILE_SIZE_BYTES = 5 * 1024  # 5 KB

# Maps MIME type prefixes to (subdirectory, file extension) tuples.
MIME_MAP = {
    'image/jpeg':       ('images', '.jpg'),
    'image/png':        ('images', '.png'),
    'image/gif':        ('images', '.gif'),
    'image/webp':       ('images', '.webp'),
    'image/svg+xml':    ('images', '.svg'),
    'image/bmp':        ('images', '.bmp'),
    'image/tiff':       ('images', '.tiff'),
    'video/mp4':        ('videos', '.mp4'),
    'video/webm':       ('videos', '.webm'),
    'video/ogg':        ('videos', '.ogv'),
    'video/quicktime':  ('videos', '.mov'),
    'audio/mpeg':       ('audio',  '.mp3'),
    'audio/ogg':        ('audio',  '.ogg'),
    'audio/wav':        ('audio',  '.wav'),
    'audio/webm':       ('audio',  '.weba'),
    'application/pdf':  ('docs',   '.pdf'),
}


def _resolve_mime_info(content_type: str, fallback_ext: str = '.bin') -> tuple[str, str]:
    """
    Resolves the target subdirectory and file extension from a Content-Type header.

    Args:
        content_type: Raw Content-Type string (e.g., 'image/png; charset=utf-8').
        fallback_ext:  Extension to use if no MIME mapping is found.

    Returns:
        Tuple of (subdirectory_name, file_extension).
    """
    if not content_type:
        return 'other', fallback_ext

    # Normalize: strip parameters like '; charset=utf-8'
    mime = content_type.split(';')[0].strip().lower()

    if mime in MIME_MAP:
        return MIME_MAP[mime]

    # Generic fallback by major type
    if mime.startswith('image/'):
        ext = '.' + mime.split('/')[1]
        return 'images', ext
    if mime.startswith('video/'):
        ext = '.' + mime.split('/')[1]
        return 'videos', ext
    if mime.startswith('audio/'):
        ext = '.' + mime.split('/')[1]
        return 'audio', ext

    return 'other', fallback_ext


def _build_filename(media_url: str, content_type: str) -> tuple[str, str]:
    """
    Derives a filesystem-safe filename and target subdirectory from the media URL
    and its Content-Type header.

    Args:
        media_url:    Fully-qualified URL of the media asset.
        content_type: Content-Type value from the HTTP response headers.

    Returns:
        Tuple of (subdirectory_name, filename_with_extension).
    """
    parsed = urlparse(media_url)
    base_name = os.path.basename(parsed.path)

    # Strip existing extension to allow MIME-derived extension to take precedence
    stem, existing_ext = os.path.splitext(base_name)

    subdir, mime_ext = _resolve_mime_info(content_type, fallback_ext=existing_ext or '.bin')

    # Keep URL-derived name if it already has a valid extension, otherwise apply MIME ext
    final_ext = existing_ext if existing_ext else mime_ext
    file_name = (stem or 'media') + final_ext

    return subdir, file_name


def _fetch_with_retry(url: str, headers: dict, max_retries: int = 3,
                      base_delay: float = 1.0, timeout: int = 20) -> requests.Response:
    """
    Performs an HTTP GET with exponential backoff retry on transient failures.

    Retry is triggered for connection errors and 5xx / 429 status codes.
    Client-side errors (4xx except 429) are not retried, as they are permanent.

    Args:
        url:         Target URL.
        headers:     HTTP headers for the request.
        max_retries: Maximum number of retry attempts (not counting the first try).
        base_delay:  Base wait time in seconds for the first retry (doubles each time).
        timeout:     Per-request timeout in seconds.

    Returns:
        The successful Response object.

    Raises:
        requests.exceptions.RequestException: When all attempts are exhausted.
    """
    retryable_status_codes = {429, 500, 502, 503, 504}
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers=headers, stream=True, timeout=timeout)

            # Don't retry permanent client errors (400, 401, 403, 404 …)
            if response.status_code not in retryable_status_codes:
                response.raise_for_status()
                return response

            # Raise to trigger the retry path for retryable codes
            response.raise_for_status()

        except requests.exceptions.RequestException as e:
            last_exception = e
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)   # 1s → 2s → 4s
                console.print(
                    f"  [dim]Retry {attempt + 1}/{max_retries} for {url[:60]}… "
                    f"waiting {wait:.0f}s[/dim]"
                )
                time.sleep(wait)
            else:
                raise last_exception


def _download_single(media_url: str, temp_dir: str, headers: dict,
                     progress: Progress, overall_task_id,
                     min_size: int = MIN_FILE_SIZE_BYTES,
                     max_retries: int = 3) -> tuple[bool, str]:
    """
    Downloads a single media asset to a temporary directory with size filtering
    and automatic retry with exponential backoff.

    Args:
        media_url:       URL of the asset to fetch.
        temp_dir:        Local directory to write the downloaded file into.
        headers:         HTTP headers to send with the request.
        progress:        Shared Rich Progress instance for updating the global bar.
        overall_task_id: ID of the overall progress task to advance.
        min_size:        Minimum acceptable file size in bytes.
        max_retries:     Maximum number of retry attempts on transient failures.

    Returns:
        Tuple of (success: bool, message: str).
    """
    try:
        # --- Medium Priority: Retry with exponential backoff ---
        response = _fetch_with_retry(media_url, headers, max_retries=max_retries)

        content_type = response.headers.get('content-type', '')
        content_length = int(response.headers.get('content-length', 0))

        # --- High Priority #3: Minimum file size filter ---
        # Reject assets declared smaller than the threshold upfront.
        # For undeclared sizes we download and check on disk afterwards.
        if content_length and content_length < min_size:
            progress.advance(overall_task_id)
            return False, f"Skipped (too small: {content_length}B < {min_size}B): {media_url}"

        subdir, file_name = _build_filename(media_url, content_type)

        # Ensure subdirectory exists inside temp_dir (e.g., temp/images/, temp/videos/)
        subdir_path = os.path.join(temp_dir, subdir)
        os.makedirs(subdir_path, exist_ok=True)

        file_path = os.path.join(subdir_path, file_name)

        # Write binary payload in 8 KB chunks
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        # Post-download size check for assets with no Content-Length header
        actual_size = os.path.getsize(file_path)
        if actual_size < min_size:
            os.remove(file_path)
            progress.advance(overall_task_id)
            return False, f"Skipped (too small after download: {actual_size}B): {media_url}"

        progress.advance(overall_task_id)
        return True, file_path

    except requests.exceptions.RequestException as e:
        progress.advance(overall_task_id)
        return False, f"Network error (all retries exhausted) for {media_url}: {e}"
    except Exception as e:
        progress.advance(overall_task_id)

        return False, f"Unexpected error for {media_url}: {e}"


# ---------------------------------------------------------------------------
# Content-based deduplication (SHA-256)
# ---------------------------------------------------------------------------

def _sha256(path: str, chunk_size: int = 1024 * 1024) -> str:
    """Computes the SHA-256 hex digest of a file by streaming 1 MB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _dedupe_by_content_hash(root_dir: str) -> int:
    """
    Walks ``root_dir`` recursively and removes files whose SHA-256 digest has
    already been seen. The first occurrence of each digest is preserved.

    Returns the number of duplicate files removed.
    """
    seen: dict[str, str] = {}
    removed = 0
    for root, _, files in os.walk(root_dir):
        for name in sorted(files):
            full = os.path.join(root, name)
            try:
                digest = _sha256(full)
            except OSError:
                continue
            if digest in seen:
                try:
                    os.remove(full)
                    removed += 1
                except OSError:
                    pass
            else:
                seen[digest] = full
    return removed


# ---------------------------------------------------------------------------
# Video metadata via ffprobe
# ---------------------------------------------------------------------------

def _ffprobe_metadata(path: str) -> dict | None:
    """
    Runs ``ffprobe`` on a media file and returns a dict with the most relevant
    technical metadata. Returns None if ffprobe is unavailable or the file
    cannot be parsed.
    """
    if shutil.which("ffprobe") is None:
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None

    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    meta = {
        "duration": fmt.get("duration"),
        "size":     fmt.get("size"),
        "bitrate":  fmt.get("bit_rate"),
        "format":   fmt.get("format_name"),
    }
    if video_stream:
        meta["video_codec"] = video_stream.get("codec_name")
        meta["width"]       = video_stream.get("width")
        meta["height"]      = video_stream.get("height")
        meta["fps"]         = video_stream.get("r_frame_rate")
    if audio_stream:
        meta["audio_codec"] = audio_stream.get("codec_name")
        meta["sample_rate"] = audio_stream.get("sample_rate")
    return meta


def _print_video_metadata_table(video_dir: str) -> None:
    """Renders an ffprobe metadata table for every video file in ``video_dir``."""
    if not os.path.isdir(video_dir):
        return
    video_files = [
        os.path.join(video_dir, f) for f in sorted(os.listdir(video_dir))
        if os.path.isfile(os.path.join(video_dir, f))
    ]
    if not video_files:
        return

    rows: list[tuple[str, dict]] = []
    for path in video_files:
        meta = _ffprobe_metadata(path)
        if meta:
            rows.append((os.path.basename(path), meta))

    if not rows:
        return

    tbl = Table(title="Video Metadata (ffprobe)", box=ROUNDED,
                header_style=f"bold {THEME['PRIMARY']}")
    tbl.add_column("File", style="cyan", overflow="fold")
    tbl.add_column("Resolution", style="green")
    tbl.add_column("Duration", style="green")
    tbl.add_column("Video", style=THEME["DIM"])
    tbl.add_column("Audio", style=THEME["DIM"])

    for name, meta in rows:
        w, h = meta.get("width"), meta.get("height")
        resolution = f"{w}x{h}" if w and h else "—"
        duration = meta.get("duration")
        try:
            duration = f"{float(duration):.1f}s" if duration else "—"
        except (TypeError, ValueError):
            duration = str(duration or "—")
        tbl.add_row(
            name, resolution, duration,
            meta.get("video_codec") or "—",
            meta.get("audio_codec") or "—",
        )
    console.print(tbl)


# ---------------------------------------------------------------------------
# Asynchronous download path (aiohttp)
# ---------------------------------------------------------------------------

async def _async_download_single(
    session, media_url: str, temp_dir: str, headers: dict,
    progress: Progress, overall_task_id, min_size: int,
) -> tuple[bool, str]:
    """aiohttp variant of ``_download_single`` — streams a single asset."""
    try:
        async with session.get(media_url, headers=headers, timeout=20) as resp:
            if resp.status >= 400:
                progress.advance(overall_task_id)
                return False, f"HTTP {resp.status} for {media_url}"

            content_type = resp.headers.get("content-type", "")
            content_length = int(resp.headers.get("content-length") or 0)

            if content_length and content_length < min_size:
                progress.advance(overall_task_id)
                return False, f"Skipped (too small: {content_length}B): {media_url}"

            subdir, file_name = _build_filename(media_url, content_type)
            subdir_path = os.path.join(temp_dir, subdir)
            os.makedirs(subdir_path, exist_ok=True)
            file_path = os.path.join(subdir_path, file_name)

            with open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(8192):
                    if chunk:
                        f.write(chunk)

        actual_size = os.path.getsize(file_path)
        if actual_size < min_size:
            os.remove(file_path)
            progress.advance(overall_task_id)
            return False, f"Skipped (too small after download: {actual_size}B): {media_url}"

        progress.advance(overall_task_id)
        return True, file_path

    except Exception as e:
        progress.advance(overall_task_id)
        return False, f"Async error for {media_url}: {e}"


async def _download_media_async(
    media_urls: list[str], temp_dir: str, headers: dict,
    progress: Progress, overall_task_id, min_size: int,
    max_concurrent: int = 16,
) -> tuple[int, int, int]:
    """
    aiohttp-based concurrent downloader. Returns (success, skip, error) counts.
    """
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=30)
    connector = aiohttp.TCPConnector(limit=max_concurrent, ssl=False)
    sem = asyncio.Semaphore(max_concurrent)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async def bounded(url):
            async with sem:
                return await _async_download_single(
                    session, url, temp_dir, headers,
                    progress, overall_task_id, min_size,
                )

        results = await asyncio.gather(*(bounded(u) for u in media_urls),
                                       return_exceptions=True)

    success = skip = error = 0
    for r in results:
        if isinstance(r, Exception):
            error += 1
            continue
        ok, msg = r
        if ok:
            success += 1
        elif "Skipped" in msg:
            skip += 1
            console.print(f"  [dim]{msg}[/dim]")
        else:
            error += 1
            console.print(f"  [yellow]{msg}[/yellow]")
    return success, skip, error


def _download_videos_ytdlp(url: str, output_dir: str) -> list[str]:
    """
    Downloads videos from a URL using yt-dlp.

    yt-dlp handles 1000+ sites natively, including:
    - YouTube, Vimeo, Dailymotion, Twitch, TikTok, Instagram, Twitter/X
    - HLS (.m3u8) and DASH (.mpd) adaptive streams
    - Embedded players and lazy-loaded video elements
    - Password-protected or age-gated content (where credentials provided)

    Args:
        url:        Target page URL.
        output_dir: Local directory to save downloaded video files.

    Returns:
        List of absolute paths to downloaded video files.
    """
    try:
        import yt_dlp
    except ImportError:
        print_warn("yt-dlp not installed. Run: pip install yt-dlp")
        return []

    downloaded_files: list[str] = []
    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

    ydl_opts = {
        # --- Output ---
        "outtmpl":          output_template,
        "format":           "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",

        # --- Network ---
        "retries":          3,
        "fragment_retries": 5,
        "socket_timeout":   30,

        # --- Subtlety ---
        "quiet":            True,      # suppress yt-dlp's own progress output
        "no_warnings":      True,
        "ignoreerrors":     True,       # skip failed fragments/playlists

        # --- Post-processing hooks ---
        "progress_hooks":   [
            lambda d: downloaded_files.append(d["filename"])
            if d["status"] == "finished" else None
        ],
    }

    print_info(f"Trying yt-dlp for: {url}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return []

            # Some extractors return a playlist of entries
            entries = info.get("entries") or [info]
            for entry in entries:
                if entry and entry.get("requested_downloads"):
                    for rd in entry["requested_downloads"]:
                        fp = rd.get("filepath") or rd.get("filename")
                        if fp and os.path.exists(fp):
                            downloaded_files.append(fp)

    except Exception as e:
        print_warn(f"yt-dlp could not extract {url}: {e}")

    # Deduplicate (hooks may fire multiple times)
    return list(dict.fromkeys(f for f in downloaded_files if os.path.exists(f)))


def _extract_video_urls_selenium_interaction(url: str) -> list[str]:
    """
    Selenium fallback: clicks all visible play buttons, waits for the player
    to populate the video src attribute, then collects the resolved URLs.

    This covers sites where yt-dlp has no extractor and the video src is
    injected dynamically after user interaction.

    Strategy:
      1. Load the page and scroll to trigger lazy-loading.
      2. Find and click every candidate play-button element.
      3. Wait 2 seconds (typical player init time).
      4. Re-read the DOM to capture newly populated <video src> attributes.
      5. Also scan for HLS/DASH manifest URLs (.m3u8 / .mpd) in page source.

    Returns:
        List of discovered video URLs (src attributes or manifest URLs).
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        from selenium.webdriver.common.by import By
    except ImportError:
        print_warn("Selenium not available for interactive video extraction.")
        return []

    options = Options()
    options.add_argument("--headless")

    geckodriver_path = "/data/data/com.termux/files/usr/bin/geckodriver"
    service = Service(executable_path=geckodriver_path) if os.path.exists(geckodriver_path) else None

    driver = None
    video_urls: list[str] = []

    try:
        print_info("Launching headless browser for interactive video extraction…")
        driver = webdriver.Firefox(options=options, service=service) \
            if service else webdriver.Firefox(options=options)
        driver.set_page_load_timeout(45)
        driver.get(url)

        # 1. Scroll to trigger lazy-loading
        for _ in range(4):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

        # 2. Click play buttons — common CSS selectors for video players
        PLAY_SELECTORS = [
            "[class*='play']",
            "[aria-label*='Play']",
            "[data-testid*='play']",
            "button[class*='play']",
            ".vjs-big-play-button",          # Video.js
            ".ytp-large-play-button",         # YouTube
            ".plyr__control--overlaid",       # Plyr.io
            ".jwplayer .jw-icon-display",     # JW Player
            "video",                          # Click the video element directly
        ]

        clicked = 0
        for selector in PLAY_SELECTORS:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements[:5]:   # limit to first 5 per selector
                    try:
                        driver.execute_script("arguments[0].scrollIntoView(true);", el)
                        driver.execute_script("arguments[0].click();", el)
                        clicked += 1
                    except Exception:
                        pass
            except Exception:
                pass

        if clicked:
            print_info(f"  Clicked {clicked} play element(s). Waiting for player init…")
            time.sleep(2)   # standard player init wait
        else:
            print_info("  No play buttons found — reading DOM directly.")

        # 3. Collect <video src> from the live DOM
        page_source = driver.page_source
        videos = driver.find_elements(By.TAG_NAME, "video")
        for v in videos:
            src = v.get_attribute("src") or v.get_attribute("currentSrc")
            if src and not src.startswith("blob:") and not src.startswith("data:"):
                video_urls.append(src)
            # Check child <source> elements
            sources = v.find_elements(By.TAG_NAME, "source")
            for s in sources:
                s_src = s.get_attribute("src")
                if s_src and not s_src.startswith("blob:"):
                    video_urls.append(urljoin(url, s_src))

        # 4. Scan page source for HLS/DASH manifest URLs
        hls_dash = re.findall(
            r'https?://[^\s\'"<>]+\.(?:m3u8|mpd)(?:[^\s\'"<>]*)?',
            page_source
        )
        video_urls.extend(hls_dash)

    except Exception as e:
        print_warn(f"Interactive Selenium extraction failed: {e}")
    finally:
        if driver:
            driver.quit()

    return list(dict.fromkeys(video_urls))


def _scrape_media_urls_static(url: str, headers: dict, media_type: str) -> list[str]:
    """
    Extracts media URLs from a page using static HTML parsing via BeautifulSoup.
    Handles <img>, <video>, <source>, <audio> tags and inline CSS background-image.

    Args:
        url:        Target page URL.
        headers:    HTTP headers for the request.
        media_type: 'images', 'videos', 'audio', or 'all'.

    Returns:
        Deduplicated list of absolute media URLs.
    """
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Error accessing URL:[/bold red] {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    media_urls = []

    # Tag selector map by media type
    tag_map = {
        'images': ['img'],
        'videos': ['video', 'source'],
        'audio':  ['audio', 'source'],
        'all':    ['img', 'video', 'audio', 'source'],
    }
    tags_to_find = tag_map.get(media_type, tag_map['all'])

    # --- Standard src/href attributes ---
    for tag in soup.find_all(tags_to_find):
        for attr in ('src', 'data-src', 'data-lazy-src'):
            src = tag.get(attr)
            if src and not src.startswith('data:'):
                media_urls.append(urljoin(url, src))

        # srcset="img-400.jpg 400w, img-800.jpg 800w" — pick the highest resolution
        srcset = tag.get('srcset')
        if srcset:
            candidates = [s.strip().split()[0] for s in srcset.split(',') if s.strip()]
            if candidates:
                # Last entry typically has the highest resolution
                media_urls.append(urljoin(url, candidates[-1]))

    # --- CSS background-image on any element (inline style) ---
    if media_type in ('images', 'all'):
        css_url_pattern = re.compile(r'url\(["\']?([^"\')\s]+)["\']?\)', re.IGNORECASE)
        for tag in soup.find_all(style=True):
            for match in css_url_pattern.finditer(tag['style']):
                raw = match.group(1)
                if not raw.startswith('data:'):
                    media_urls.append(urljoin(url, raw))

    return list(dict.fromkeys(media_urls))  # deduplicate preserving order


def _scrape_media_urls_dynamic(url: str, media_type: str) -> list[str]:
    """
    Extracts media URLs from a JavaScript-rendered page using Selenium.
    Scrolls the page to trigger lazy-loading before extracting the DOM.

    Args:
        url:        Target page URL.
        media_type: 'images', 'videos', 'audio', or 'all'.

    Returns:
        Deduplicated list of absolute media URLs found in the rendered DOM.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
    except ImportError:
        console.print("[bold red]Selenium is not installed. Cannot use dynamic scraping.[/bold red]")
        return []

    options = Options()
    options.add_argument("--headless")

    # Support Termux path for geckodriver
    geckodriver_path = "/data/data/com.termux/files/usr/bin/geckodriver"
    service = Service(executable_path=geckodriver_path) if os.path.exists(geckodriver_path) else None

    driver = None
    try:
        console.print("[cyan]Launching headless browser for JS rendering...[/cyan]")
        driver = webdriver.Firefox(options=options, service=service) if service else webdriver.Firefox(options=options)
        driver.set_page_load_timeout(45)
        driver.get(url)

        # Incremental scroll to trigger lazy-load hydration
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(4):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        html = driver.page_source

    except Exception as e:
        console.print(f"[bold red]Selenium error:[/bold red] {e}")
        return []
    finally:
        if driver:
            driver.quit()

    # Parse the fully rendered DOM
    soup = BeautifulSoup(html, 'html.parser')
    media_urls = []

    tag_map = {
        'images': ['img'],
        'videos': ['video', 'source'],
        'audio':  ['audio', 'source'],
        'all':    ['img', 'video', 'audio', 'source'],
    }
    tags_to_find = tag_map.get(media_type, tag_map['all'])

    for tag in soup.find_all(tags_to_find):
        for attr in ('src', 'data-src', 'data-lazy-src'):
            src = tag.get(attr)
            if src and not src.startswith('data:'):
                media_urls.append(urljoin(url, src))
        srcset = tag.get('srcset')
        if srcset:
            candidates = [s.strip().split()[0] for s in srcset.split(',') if s.strip()]
            if candidates:
                media_urls.append(urljoin(url, candidates[-1]))

    if media_type in ('images', 'all'):
        css_url_pattern = re.compile(r'url\(["\']?([^"\')\s]+)["\']?\)', re.IGNORECASE)
        for tag in soup.find_all(style=True):
            for match in css_url_pattern.finditer(tag['style']):
                raw = match.group(1)
                if not raw.startswith('data:'):
                    media_urls.append(urljoin(url, raw))

    return list(dict.fromkeys(media_urls))


def download_media(
    url:          str,
    output_path:  str  = "media_download.zip",
    media_type:   str  = "all",
    use_selenium: bool = False,
    max_workers:  int  = 8,
    min_size:     int  = MIN_FILE_SIZE_BYTES,
    use_async:    bool = False,
) -> None:
    """
    Orchestrates media scraping and parallel downloading from a target URL.

    Video download strategy (three tiers):
      1. yt-dlp  — primary method. Handles 1000+ sites, HLS, DASH,
                   lazy-loaded players, and embedded iframes.
      2. Selenium click-play — fallback for sites with custom players
                   not supported by yt-dlp. Clicks play buttons, waits
                   2 s, then reads the populated <video src>.
      3. Static HTML scraping — last resort for simple direct-linked videos.

    Images and audio use the existing static / Selenium-scroll paths.

    Args:
        url:          Target webpage URL.
        output_path:  Filename for the output ZIP archive.
        media_type:   'images', 'videos', 'audio', or 'all'.
        use_selenium: If True, forces Selenium for non-video scraping.
        max_workers:  Parallel download threads (applies to image/audio).
        min_size:     Minimum file size in bytes (default 5 KB).
        use_async:    If True and ``aiohttp`` is installed, uses an asyncio
                      downloader instead of ``ThreadPoolExecutor`` for the
                      image/audio pipeline.
    """
    output_zip_path = os.path.join(DIR_MEDIA, os.path.basename(output_path))

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        success_count = 0
        skip_count    = 0
        error_count   = 0

        # ── VIDEO DOWNLOAD — Three-tier strategy ───────────────────────────
        if media_type in ("videos", "all"):
            print_info(f"Starting video extraction for: {url}")

            video_subdir = os.path.join(temp_dir, "videos")
            os.makedirs(video_subdir, exist_ok=True)

            # Tier 1: yt-dlp
            ytdlp_files = _download_videos_ytdlp(url, video_subdir)
            success_count += len(ytdlp_files)

            if ytdlp_files:
                print_success(
                    f"yt-dlp downloaded {len(ytdlp_files)} video(s): "
                    + ", ".join(os.path.basename(f) for f in ytdlp_files)
                )
            else:
                print_warn("yt-dlp found no videos — trying Selenium click-play…")

                # Tier 2: Selenium interaction
                video_urls = _extract_video_urls_selenium_interaction(url)

                if video_urls:
                    print_info(f"Selenium found {len(video_urls)} video URL(s) — downloading…")

                    with Progress(
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(), TaskProgressColumn(),
                        "•", TransferSpeedColumn(),
                        "•", TimeRemainingColumn(),
                        console=console,
                    ) as progress:
                        task = progress.add_task(
                            "[cyan]Downloading videos…", total=len(video_urls)
                        )
                        with ThreadPoolExecutor(max_workers=min(max_workers, len(video_urls))) as ex:
                            futures = {
                                ex.submit(_download_single, vu, video_subdir,
                                          headers, progress, task, min_size): vu
                                for vu in video_urls
                            }
                            for future in as_completed(futures):
                                ok, msg = future.result()
                                if ok:
                                    success_count += 1
                                elif "Skipped" in msg:
                                    skip_count += 1
                                else:
                                    error_count += 1

                else:
                    # Tier 3: Static scraping
                    print_warn(
                        "No video URLs from interactive extraction — "
                        "falling back to static HTML scraping."
                    )
                    static_video_urls = _scrape_media_urls_static(url, headers, "videos")
                    if static_video_urls:
                        print_info(f"Static scraping found {len(static_video_urls)} URL(s).")
                        with Progress(
                            TextColumn("[progress.description]{task.description}"),
                            BarColumn(), TaskProgressColumn(), console=console,
                        ) as progress:
                            task = progress.add_task(
                                "[cyan]Downloading…", total=len(static_video_urls)
                            )
                            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                                futures = {
                                    ex.submit(_download_single, vu, video_subdir,
                                              headers, progress, task, min_size): vu
                                    for vu in static_video_urls
                                }
                                for future in as_completed(futures):
                                    ok, msg = future.result()
                                    if ok:      success_count += 1
                                    elif "Skipped" in msg: skip_count += 1
                                    else:       error_count += 1
                    else:
                        print_warn("No videos found on the page through any method.")

        # ── IMAGE / AUDIO DOWNLOAD — Original pipeline ─────────────────────
        if media_type in ("images", "audio", "all"):
            img_audio_type = media_type if media_type != "all" else "all"

            if use_selenium:
                print_info("Using Selenium for JS-rendered image/audio scraping…")
                media_urls = _scrape_media_urls_dynamic(url, img_audio_type)
            else:
                media_urls = _scrape_media_urls_static(url, headers, img_audio_type)

            # Filter out video URLs — they're handled above
            media_urls = [
                u for u in media_urls
                if not any(u.lower().endswith(ext)
                           for ext in (".mp4", ".webm", ".ogv", ".mov", ".m3u8", ".mpd"))
            ]

            if media_urls:
                # Discovery summary table
                tbl = Table(
                    title=f"Discovered Assets ({len(media_urls)})",
                    box=ROUNDED, header_style="bold blue", title_style="bold magenta",
                )
                tbl.add_column("#", style="dim", width=4)
                tbl.add_column("URL", style="cyan")
                for i, u in enumerate(media_urls[:30], 1):   # cap preview at 30
                    tbl.add_row(str(i), u)
                if len(media_urls) > 30:
                    tbl.add_row("…", f"[dim]+{len(media_urls) - 30} more[/dim]")
                console.print(tbl)

                with Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(), TaskProgressColumn(),
                    "•", TransferSpeedColumn(),
                    "•", TimeRemainingColumn(),
                    console=console,
                ) as progress:
                    overall = progress.add_task(
                        f"[cyan]Downloading {len(media_urls)} assets…",
                        total=len(media_urls),
                    )

                    if use_async and _HAS_AIOHTTP:
                        print_info("Using aiohttp async downloader.")
                        s, k, e = asyncio.run(_download_media_async(
                            media_urls, temp_dir, headers,
                            progress, overall, min_size,
                            max_concurrent=max(max_workers, 8),
                        ))
                        success_count += s
                        skip_count    += k
                        error_count   += e
                    else:
                        if use_async and not _HAS_AIOHTTP:
                            print_warn("aiohttp not installed — falling back to ThreadPoolExecutor.")
                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                            futures = {
                                executor.submit(
                                    _download_single, u, temp_dir, headers,
                                    progress, overall, min_size
                                ): u
                                for u in media_urls
                            }
                            for future in as_completed(futures):
                                ok, msg = future.result()
                                if ok:
                                    success_count += 1
                                elif "Skipped" in msg:
                                    skip_count += 1
                                    console.print(f"  [dim]{msg}[/dim]")
                                else:
                                    error_count += 1
                                    console.print(f"  [yellow]{msg}[/yellow]")

        # ── Summary ────────────────────────────────────────────────────────
        console.print(
            f"\n  [{THEME['SUCCESS']}]✔[/]  Downloaded: [green]{success_count}[/green]  "
            f"  ⏩ Skipped: [yellow]{skip_count}[/yellow]  "
            f"  [{THEME['ERROR']}]✘[/]  Errors: [red]{error_count}[/red]"
        )

        if success_count == 0:
            print_warn("No files were downloaded. ZIP archive will not be created.")
            return

        # Content-based deduplication across all downloaded assets
        removed = _dedupe_by_content_hash(temp_dir)
        if removed:
            print_info(f"Removed {removed} duplicate file(s) by SHA-256 content hash.")
            success_count -= removed

        # Video metadata via ffprobe (best-effort)
        if media_type in ("videos", "all"):
            _print_video_metadata_table(os.path.join(temp_dir, "videos"))

        # Compress all assets preserving subdirectory structure
        print_info(f"Compressing → {output_zip_path}")
        with zipfile.ZipFile(output_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    arcname   = os.path.relpath(full_path, temp_dir)
                    zipf.write(full_path, arcname=arcname)

        print_success(f"{success_count} file(s) archived → {output_zip_path}")
