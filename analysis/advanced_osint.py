"""
analysis/advanced_osint.py — Screenshots, deep scraping, Wayback Machine.

Screenshot engines (auto-selected):
  1. Playwright (Chromium) — native full-page screenshot, most stable.
  2. Selenium (Firefox)     — resizes the window to the document height.
"""

import os
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from cli.ui import console, THEME, print_info, print_warn, print_error, print_success, make_table
from core.config import DIR_SCREENSHOTS


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

def _slug(url: str) -> str:
    """Filesystem-safe identifier derived from the URL host."""
    host = urlparse(url).netloc.replace(".", "_")
    return host or "unknown_domain"


def _screenshot_playwright(url: str, output_path: str, timeout_ms: int = 30_000) -> bool:
    """Playwright full-page screenshot. Returns True on success."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            page.screenshot(path=output_path, full_page=True)
            browser.close()
        return True
    except Exception as e:
        print_warn(f"Playwright screenshot failed: {e}")
        return False


def _screenshot_selenium(url: str, output_path: str) -> bool:
    """
    Selenium (Firefox headless) full-page screenshot.
    Resizes the window to match the document height before capture.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
    except ImportError:
        print_error("Selenium is not installed.")
        return False

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--width=1920")
    options.add_argument("--height=3000")

    geckodriver_path = "/data/data/com.termux/files/usr/bin/geckodriver"
    service = Service(executable_path=geckodriver_path) if os.path.exists(geckodriver_path) else None

    driver = None
    try:
        driver = webdriver.Firefox(options=options, service=service) if service \
            else webdriver.Firefox(options=options)
        driver.set_page_load_timeout(30)
        driver.get(url)

        # Resize to the full document height so a single screenshot captures everything
        total_height = driver.execute_script(
            "return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);"
        ) or 3000
        total_width = driver.execute_script(
            "return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth);"
        ) or 1920
        # Cap to avoid runaway allocations on infinite-scroll pages
        total_height = min(int(total_height), 20_000)
        total_width = min(int(total_width), 3840)
        driver.set_window_size(total_width, total_height)
        time.sleep(1)  # let layout stabilise

        # Firefox's get_full_page_screenshot_as_file is available on recent geckodriver
        saved = False
        if hasattr(driver, "get_full_page_screenshot_as_file"):
            try:
                driver.get_full_page_screenshot_as_file(output_path)
                saved = True
            except Exception:
                saved = False
        if not saved:
            driver.save_screenshot(output_path)
        return True
    except Exception as e:
        print_error(f"Selenium screenshot failed: {e}")
        return False
    finally:
        if driver:
            driver.quit()


def take_screenshot(url: str, output_dir: str = DIR_SCREENSHOTS,
                    engine: str = "auto") -> str | None:
    """
    Captures a full-page screenshot of the target URL.

    Args:
        url:        Target URL.
        output_dir: Directory to persist the PNG into.
        engine:     'playwright', 'selenium', or 'auto' (tries Playwright first).

    Returns:
        Absolute path to the PNG, or None on failure.
    """
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{_slug(url)}_screenshot.png")

    print_info(f"Capturing screenshot → {url}")

    if engine in ("auto", "playwright"):
        if _screenshot_playwright(url, output_path):
            print_success(f"Screenshot saved (Playwright): {output_path}")
            return output_path
        if engine == "playwright":
            return None

    if _screenshot_selenium(url, output_path):
        print_success(f"Screenshot saved (Selenium): {output_path}")
        return output_path
    return None


# ---------------------------------------------------------------------------
# Deep scraping (JS-rendered DOM)
# ---------------------------------------------------------------------------

def get_dynamic_text_from_url(url: str) -> str | None:
    """
    Extracts text from a webpage after JavaScript execution.
    Essential for SPAs and lazy-loaded content.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
    except ImportError:
        print_error("Selenium is not installed — cannot deep-scrape.")
        return None

    options = Options()
    options.add_argument("--headless")

    geckodriver_path = "/data/data/com.termux/files/usr/bin/geckodriver"
    service = Service(executable_path=geckodriver_path) if os.path.exists(geckodriver_path) else None

    driver = None
    try:
        print_info(f"Deep scraping: {url}")
        driver = webdriver.Firefox(options=options, service=service) if service \
            else webdriver.Firefox(options=options)
        driver.set_page_load_timeout(45)
        driver.get(url)

        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        lines = (line.strip() for line in text.splitlines())
        return "\n".join(line for line in lines if line)

    except Exception as e:
        print_error(f"Deep scraping failed: {e}")
        return None
    finally:
        if driver:
            driver.quit()


# ---------------------------------------------------------------------------
# Wayback Machine — CDX timeline
# ---------------------------------------------------------------------------

_CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"


def _format_cdx_timestamp(ts: str) -> str:
    """YYYYMMDDhhmmss → YYYY-MM-DD HH:MM:SS"""
    if len(ts) >= 14:
        return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}:{ts[12:14]}"
    if len(ts) >= 8:
        return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
    return ts


def check_wayback_machine(url: str, limit: int = 20,
                          from_year: int | None = None,
                          to_year: int | None = None) -> list[dict] | None:
    """
    Queries the Wayback Machine **CDX** API for the full snapshot timeline.

    Args:
        url:       Target URL.
        limit:     Max snapshots to render (negative → most recent first).
        from_year: Optional lower bound (e.g. 2015).
        to_year:   Optional upper bound (e.g. 2024).

    Returns:
        List of snapshot dicts ``{'timestamp', 'date', 'status', 'mime', 'url'}``,
        or None on failure. The full list is returned even when ``limit`` caps
        the rendered preview.
    """
    params = {
        "url":    url,
        "output": "json",
        "fl":     "timestamp,original,mimetype,statuscode,digest",
        "filter": "statuscode:200",
        "collapse": "digest",          # collapse identical captures
    }
    if from_year:
        params["from"] = str(from_year)
    if to_year:
        params["to"] = str(to_year)
    # Negative limit means "last N" on the CDX API
    params["limit"] = str(-abs(limit)) if limit else "-20"

    print_info(f"Querying Wayback CDX for: {url}")
    try:
        response = requests.get(_CDX_ENDPOINT, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print_error(f"CDX network error: {e}")
        return None
    except ValueError:
        print_error("CDX returned invalid JSON.")
        return None

    if not data or len(data) < 2:
        print_warn("No snapshots found in the Wayback Machine.")
        return []

    # First row is the column header
    header, *rows = data
    idx = {col: i for i, col in enumerate(header)}

    snapshots: list[dict] = []
    for row in rows:
        ts = row[idx["timestamp"]]
        original = row[idx["original"]]
        archive_url = f"https://web.archive.org/web/{ts}/{original}"
        snapshots.append({
            "timestamp": ts,
            "date":      _format_cdx_timestamp(ts),
            "status":    row[idx["statuscode"]],
            "mime":      row[idx["mimetype"]],
            "url":       archive_url,
        })

    # Render a Rich timeline table (most recent first)
    snapshots_sorted = sorted(snapshots, key=lambda s: s["timestamp"], reverse=True)
    preview = snapshots_sorted[:limit] if limit else snapshots_sorted

    tbl = make_table(
        f"Wayback Timeline  [{THEME['DIM']}]{len(snapshots)} snapshots[/]",
        ("Date",   "green"),
        ("Status", THEME["DIM"]),
        ("MIME",   THEME["DIM"]),
        ("Archive URL", THEME["LINK"]),
        show_lines=False,
    )
    for snap in preview:
        tbl.add_row(snap["date"], snap["status"], snap["mime"], snap["url"])

    console.print()
    console.print(tbl)
    if len(snapshots) > len(preview):
        console.print(f"  [{THEME['DIM']}](+{len(snapshots) - len(preview)} older snapshots not shown)[/]")

    return snapshots_sorted


# ---------------------------------------------------------------------------
# Wayback Machine — content fetch, PII extraction, snapshot diff
# ---------------------------------------------------------------------------

import difflib as _difflib
import hashlib as _hashlib


def wayback_resolve_timestamp(url: str, when: str = "latest") -> str | None:
    """
    Resolve a fuzzy time spec to a concrete CDX timestamp for *url*.

    Args:
        when: ``"latest"`` (default), ``"earliest"``, a 4-digit year
              (e.g. ``"2018"``), or ``"YYYY-MM"``. Anything else is treated
              as a literal CDX timestamp and returned unchanged.

    Returns:
        14-digit CDX timestamp (``YYYYMMDDhhmmss``), or ``None`` if no
        snapshot matches.
    """
    when = (when or "latest").strip()
    if when.isdigit() and len(when) >= 8:
        return when

    params: dict[str, str] = {
        "url":    url,
        "output": "json",
        "fl":     "timestamp",
        "filter": "statuscode:200",
        "limit":  "1",
    }
    if when == "latest":
        params["limit"] = "-1"
    elif when == "earliest":
        params["limit"] = "1"
    elif len(when) == 4 and when.isdigit():
        params["from"] = when
        params["to"]   = when
        params["limit"] = "-1"
    elif len(when) == 7 and when[4] == "-" and when[:4].isdigit() and when[5:].isdigit():
        params["from"] = when[:4] + when[5:]
        params["to"]   = when[:4] + when[5:]
        params["limit"] = "-1"
    else:
        return None

    try:
        r = requests.get(_CDX_ENDPOINT, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None
    if not data or len(data) < 2:
        return None
    return data[1][0]


def _wayback_raw_url(timestamp: str, url: str) -> str:
    """Build the ``id_`` (raw, un-rewritten) snapshot URL for *url* at *timestamp*."""
    return f"https://web.archive.org/web/{timestamp}id_/{url}"


def _wayback_fetch_uncached(url: str, ts: str) -> dict | None:
    """Uncached Wayback snapshot fetch + HTML-to-text extraction."""
    archive_url = _wayback_raw_url(ts, url)
    try:
        r = requests.get(archive_url, timeout=30,
                         headers={"User-Agent": "ScannUs/1.0 (OSINT)"})
        r.raise_for_status()
    except Exception as e:
        print_error(f"Wayback fetch failed: {e}")
        return None

    mime = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
    text = ""
    if mime.startswith("text/html") or mime.endswith("+xml") or mime == "text/xml":
        try:
            soup = BeautifulSoup(r.content, "html.parser")
            for tag in soup(("script", "style", "noscript")):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        except Exception:
            text = ""
    elif mime.startswith("text/"):
        text = r.text

    # Only the JSON-safe view is cached — raw bytes are dropped on cache hits
    return {
        "timestamp":   ts,
        "date":        _format_cdx_timestamp(ts),
        "archive_url": archive_url,
        "status":      r.status_code,
        "mime":        mime,
        "size":        len(r.content),
        "text":        text,
    }


def wayback_fetch_snapshot(url: str, timestamp: str | None = None) -> dict | None:
    """
    Fetch the raw archived content of *url* at *timestamp* with persistent
    SQLite caching (TTL: 30d, since Wayback snapshots are immutable).

    Uses the ``id_`` flag so the response is the original bytes Archive.org
    captured — no Wayback toolbar injection, no link rewriting.

    Args:
        url:       The original URL.
        timestamp: 14-digit CDX timestamp, or a fuzzy spec accepted by
                   :func:`wayback_resolve_timestamp` (``"latest"``,
                   ``"earliest"``, a year, or ``YYYY-MM``).

    Returns:
        ``{"timestamp", "archive_url", "status", "mime", "size", "text"}``
        on success, ``None`` on failure. ``text`` is the HTML-stripped
        text (empty for non-HTML payloads). Raw response bytes are not
        retained across cache hits to keep the DB compact.
    """
    from core.cache import cached_call

    ts = wayback_resolve_timestamp(url, timestamp or "latest")
    if not ts:
        print_warn(f"No Wayback snapshot found for {url}")
        return None

    snap = cached_call("wayback", [url, ts],
                       lambda: _wayback_fetch_uncached(url, ts))
    if snap:
        print_info(f"Fetched snapshot {snap['date']} · "
                   f"{snap['mime']} · {snap['size']} bytes")
    return snap


def wayback_extract_pii(url: str, timestamp: str | None = None) -> dict | None:
    """
    Fetch a Wayback snapshot of *url* and run the full PII/secret extractor on it.

    Killer OSINT use case: surfaces identifiers, leaked credentials, and other
    sensitive strings that may have been scrubbed from the live site.

    Returns:
        ``{"timestamp", "date", "archive_url", "by_category", "counts"}`` or
        ``None`` if the snapshot cannot be retrieved or yields no extractable text.
    """
    from search.smart_search import extract_information

    snap = wayback_fetch_snapshot(url, timestamp)
    if not snap or not snap.get("text"):
        return None
    data = extract_information(snap["text"])
    counts = {k: (len(v) if not isinstance(v, dict) else len(v))
              for k, v in data.items()}

    if data:
        tbl = make_table(
            f"Wayback PII  [{THEME['DIM']}]{snap['date']}[/]",
            ("Category", THEME["PRIMARY"]),
            ("Count",    THEME["ACCENT"]),
            ("Sample",   "white"),
            show_lines=True,
        )
        for cat, vals in data.items():
            if isinstance(vals, dict):
                sample = ", ".join(f"{k}×{len(v)}" for k, v in list(vals.items())[:3])
            else:
                sample = ", ".join(map(str, vals[:3]))
            tbl.add_row(cat.replace("_", " "), str(counts[cat]), sample)
        console.print(tbl)
    else:
        print_warn("No identifiers extracted from archived content.")

    return {
        "timestamp":   snap["timestamp"],
        "date":        snap["date"],
        "archive_url": snap["archive_url"],
        "by_category": data,
        "counts":      counts,
    }


def _stable_lines(text: str) -> list[str]:
    """Tokenise text to non-empty, stripped lines — stable input for difflib."""
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def wayback_diff(url: str, ts_a: str, ts_b: str,
                 context: int = 2, max_lines: int = 80) -> dict | None:
    """
    Diff two Wayback snapshots of *url* by their visible text content.

    Args:
        ts_a, ts_b: Either 14-digit CDX timestamps or fuzzy specs
                    (``"latest"``, ``"earliest"``, year, or YYYY-MM).
        context:    Unified-diff context lines.
        max_lines:  Cap on the rendered diff (full counts always reported).

    Returns:
        ``{"ts_a", "ts_b", "added_count", "removed_count", "added", "removed",
        "diff"}`` or ``None`` on failure.
    """
    snap_a = wayback_fetch_snapshot(url, ts_a)
    snap_b = wayback_fetch_snapshot(url, ts_b)
    if not (snap_a and snap_b):
        return None
    if not (snap_a.get("text") and snap_b.get("text")):
        print_warn("One or both snapshots have no extractable text.")
        return None

    lines_a = _stable_lines(snap_a["text"])
    lines_b = _stable_lines(snap_b["text"])
    diff_lines = list(_difflib.unified_diff(
        lines_a, lines_b,
        fromfile=f"@{snap_a['date']}",
        tofile=f"@{snap_b['date']}",
        n=context, lineterm="",
    ))

    added   = [ln[1:] for ln in diff_lines
               if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln[1:] for ln in diff_lines
               if ln.startswith("-") and not ln.startswith("---")]

    preview = "\n".join(diff_lines[:max_lines])

    h_a = _hashlib.sha256(snap_a["text"].encode("utf-8", errors="ignore")).hexdigest()[:12]
    h_b = _hashlib.sha256(snap_b["text"].encode("utf-8", errors="ignore")).hexdigest()[:12]

    print_info(f"Diff {snap_a['date']} (sha {h_a}) -> {snap_b['date']} (sha {h_b}): "
               f"+{len(added)} -{len(removed)}")
    if h_a == h_b:
        print_warn("Snapshots are content-identical.")
    elif preview:
        console.print(preview)
    if len(diff_lines) > max_lines:
        console.print(f"  [{THEME['DIM']}](+{len(diff_lines) - max_lines} "
                      f"more diff lines not shown)[/]")

    return {
        "ts_a":          snap_a["timestamp"],
        "ts_b":          snap_b["timestamp"],
        "date_a":        snap_a["date"],
        "date_b":        snap_b["date"],
        "added_count":   len(added),
        "removed_count": len(removed),
        "added":         added,
        "removed":       removed,
        "diff":          diff_lines,
        "identical":     h_a == h_b,
    }
