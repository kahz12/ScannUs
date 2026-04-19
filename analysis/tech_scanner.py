"""
analysis/tech_scanner.py — Web technology fingerprinting.

Engine priority:
  1. ``Wappalyzer`` (``python-Wappalyzer`` / ``wappalyzer``)
       — maintained database of ~2,500 technology signatures.
  2. ``WebTech`` — legacy fallback when Wappalyzer is not installed.

Public API:
  ``tech_scan(url)``                 — print a styled Rich table.
  ``detect_technologies(url)``       — return a list of ``(name, version, category)``.
"""

import os
import requests
from cli.ui import console, THEME, print_info, print_warn, print_error, make_table


# ---------------------------------------------------------------------------
# Optional backends — detected once at import time
# ---------------------------------------------------------------------------

_WAPPALYZER = None  # instance-like callable returning {tech: {...}}
_WAPPALYZER_FLAVOUR = None  # 'python-Wappalyzer' | 'wappalyzer'

try:  # Preferred: python-Wappalyzer (Wappalyzer + WebPage)
    from Wappalyzer import Wappalyzer, WebPage  # type: ignore
    _WAPPALYZER = Wappalyzer.latest()
    _WAPPALYZER_FLAVOUR = "python-Wappalyzer"
except Exception:
    try:  # Alternative: wappalyzer (newer fork)
        import wappalyzer as _wa  # type: ignore
        _WAPPALYZER = _wa
        _WAPPALYZER_FLAVOUR = "wappalyzer"
    except Exception:
        _WAPPALYZER = None
        _WAPPALYZER_FLAVOUR = None

try:
    from webtech import WebTech  # type: ignore
    _HAS_WEBTECH = True
except Exception:
    _HAS_WEBTECH = False


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Ensure WebTech's fingerprint DB dir exists when that backend is active
if _HAS_WEBTECH:
    os.makedirs(os.path.expanduser("~/.local/share/webtech"), exist_ok=True)


# ---------------------------------------------------------------------------
# Detection backends
# ---------------------------------------------------------------------------

def _detect_wappalyzer(url: str) -> list[tuple[str, str, str]]:
    """Fingerprint via python-Wappalyzer."""
    if _WAPPALYZER_FLAVOUR == "python-Wappalyzer":
        try:
            webpage = WebPage.new_from_url(url, headers=_HEADERS, timeout=12, verify=False)
        except Exception as e:
            print_warn(f"Wappalyzer fetch error: {e}")
            return []
        try:
            tech = _WAPPALYZER.analyze_with_versions_and_categories(webpage)
        except Exception:
            # Older API
            raw = _WAPPALYZER.analyze(webpage)
            return [(name, "", "") for name in raw]

        out: list[tuple[str, str, str]] = []
        for name, meta in tech.items():
            versions = (meta or {}).get("versions") or []
            cats = (meta or {}).get("categories") or []
            version = versions[0] if versions else ""
            cat_names = [c["name"] if isinstance(c, dict) else str(c) for c in cats]
            out.append((name, version, ", ".join(cat_names)))
        return out

    if _WAPPALYZER_FLAVOUR == "wappalyzer":
        try:
            result = _WAPPALYZER.analyze(url)  # type: ignore[attr-defined]
        except Exception as e:
            print_warn(f"Wappalyzer fetch error: {e}")
            return []
        # The newer package returns {url: {tech: {version, categories}}}
        out: list[tuple[str, str, str]] = []
        payload = result.get(url) if isinstance(result, dict) and url in result else result
        if isinstance(payload, dict):
            for name, meta in payload.items():
                meta = meta or {}
                version = meta.get("version") or ""
                cats = meta.get("categories") or meta.get("category") or []
                if isinstance(cats, str):
                    cats = [cats]
                out.append((name, str(version), ", ".join(str(c) for c in cats)))
        return out
    return []


def _detect_webtech(url: str) -> list[tuple[str, str, str]]:
    """Fingerprint via WebTech (legacy fallback)."""
    if not _HAS_WEBTECH:
        return []
    try:
        wt = WebTech(options={"timeout": 12})
        report = wt.start_from_url(url, timeout=12)
    except Exception as e:
        print_warn(f"WebTech error: {e}")
        return []

    return _parse_webtech_report(report)


def _parse_webtech_report(report) -> list[tuple[str, str, str]]:
    """Normalise WebTech's varied output shapes into (name, version, category)."""
    if report is None:
        return []

    if hasattr(report, "tech"):
        out: list[tuple[str, str, str]] = []
        for t in report.tech:
            name = getattr(t, "name", str(t))
            version = getattr(t, "version", "") or ""
            cats = getattr(t, "cats", None) or getattr(t, "categories", [])
            out.append((name, version, _resolve_webtech_category(cats)))
        return out

    if isinstance(report, dict):
        return [(name, str(v or ""), _infer_category_from_name(name)) for name, v in report.items()]

    return []


_WEBTECH_CAT_MAP = {
    1: "CMS", 2: "Message Boards", 3: "Database Manager",
    4: "Documentation", 5: "Widget", 6: "Ecommerce",
    7: "Photo Gallery", 8: "Wiki", 9: "Hosting Panels",
    10: "Analytics", 11: "Blog", 12: "JavaScript Framework",
    13: "Issue Tracker", 14: "Video", 22: "Web Framework",
    23: "Web Server", 24: "Cache", 25: "Rich Text Editor",
    26: "JavaScript Graphics", 31: "CDN", 34: "Database",
    41: "Search Engines", 42: "Web Mail", 58: "Security",
    62: "Programming Language",
}


def _resolve_webtech_category(cats) -> str:
    if not cats:
        return ""
    first = cats[0] if isinstance(cats, (list, tuple)) else cats
    if isinstance(first, int):
        return _WEBTECH_CAT_MAP.get(first, f"Cat {first}")
    return str(first)


def _infer_category_from_name(name: str) -> str:
    name_lower = name.lower()
    if any(k in name_lower for k in ("apache", "nginx", "iis", "caddy", "lighttpd")):
        return "Web Server"
    if any(k in name_lower for k in ("wordpress", "joomla", "drupal", "magento", "shopify")):
        return "CMS"
    if any(k in name_lower for k in ("react", "vue", "angular", "jquery", "bootstrap")):
        return "JavaScript Framework"
    if any(k in name_lower for k in ("php", "python", "ruby", "java", "node")):
        return "Programming Language"
    if any(k in name_lower for k in ("google analytics", "hotjar", "mixpanel", "segment")):
        return "Analytics"
    if any(k in name_lower for k in ("cloudflare", "akamai", "fastly", "cdn")):
        return "CDN"
    return "Technology"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_technologies(url: str) -> tuple[str, list[tuple[str, str, str]]]:
    """
    Returns a tuple ``(backend_name, technologies)`` where ``technologies`` is
    a list of ``(name, version, category)`` entries.
    """
    if _WAPPALYZER:
        techs = _detect_wappalyzer(url)
        if techs:
            return (f"Wappalyzer ({_WAPPALYZER_FLAVOUR})", techs)

    if _HAS_WEBTECH:
        techs = _detect_webtech(url)
        if techs:
            return ("WebTech", techs)

    return ("none", [])


def tech_scan(url: str) -> None:
    """
    Fingerprints a URL and renders the result as a styled Rich table.
    """
    if not (_WAPPALYZER or _HAS_WEBTECH):
        print_error("No fingerprinting backend available. "
                    "Install one of: 'python-Wappalyzer', 'wappalyzer', or 'webtech'.")
        return

    print_info(f"Scanning technology stack: {url}")

    backend, technologies = detect_technologies(url)
    if not technologies:
        print_warn("No technologies detected — the site may block fingerprinting.")
        return

    tbl = make_table(
        f"Technology Stack  [{THEME['DIM']}]{url} · via {backend}[/]",
        ("Technology", THEME["PRIMARY"]),
        ("Version",    "green"),
        ("Category",   THEME["DIM"]),
        show_lines=False,
    )
    for name, version, category in sorted(technologies, key=lambda x: (x[2] or "zzz", x[0].lower())):
        tbl.add_row(name, version or "—", category or "Unknown")

    console.print()
    console.print(tbl)
    console.print(f"  [{THEME['DIM']}]Total: {len(technologies)} technologies detected · backend: {backend}[/]")
