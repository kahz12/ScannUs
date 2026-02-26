"""
analysis/tech_scanner.py — Web technology fingerprinting via WebTech.

Improvements:
  - Handles WebTech's Report object properly (not just plain dicts)
  - Shows Category column for CMS / Framework / Server grouping
  - Uses Rich theme helpers for consistent visual output
"""

import os
from rich.panel import Panel
from webtech import WebTech

from cli.ui import console, THEME, print_info, print_warn, print_error, make_table

# Ensure the WebTech fingerprint DB directory exists
_DATA_DIR = os.path.expanduser("~/.local/share/webtech")
os.makedirs(_DATA_DIR, exist_ok=True)


def tech_scan(url: str) -> None:
    """
    Fingerprints the technology stack of a target URL using WebTech.

    Handles both the legacy dict format and the modern Report object format
    returned by different WebTech SDK versions.

    Identified technologies are rendered in a Rich table grouped by category
    (CMS, Framework, Programming Language, Server, Analytics, …).
    """
    print_info(f"Scanning technology stack: {url}")

    try:
        wt = WebTech(options={"timeout": 12})
        report = wt.start_from_url(url, timeout=12)

        technologies = _parse_report(report)

        if not technologies:
            print_warn("No technologies detected — the site may block fingerprinting.")
            return

        tbl = make_table(
            f"Technology Stack  [{THEME['DIM']}]{url}[/]",
            ("Technology", THEME["PRIMARY"]),
            ("Version",    "green"),
            ("Category",   THEME["DIM"]),
            show_lines=False,
        )

        for name, version, category in sorted(technologies, key=lambda x: x[2]):
            tbl.add_row(
                name,
                version or "—",
                category or "Unknown",
            )

        console.print()
        console.print(tbl)
        console.print(
            f"  [{THEME['DIM']}]Total: {len(technologies)} technology/ies detected[/]"
        )

    except Exception as e:
        print_error(f"Tech scan failed for {url}: {e}")


# ---------------------------------------------------------------------------
# Report parsing — handles multiple WebTech SDK output formats
# ---------------------------------------------------------------------------

def _parse_report(report) -> list[tuple[str, str, str]]:
    """
    Normalises a WebTech report into a list of (name, version, category) tuples.

    WebTech may return:
      - A Report object (modern SDK) with a `.tech` attribute (list of Tech objects)
      - A plain dict {tech_name: version_str}
      - A string (error or no-results message)
      - None / empty
    """
    technologies: list[tuple[str, str, str]] = []

    if report is None:
        return technologies

    # ── Modern SDK: Report object with .tech list ──────────────────────────
    if hasattr(report, "tech"):
        tech_list = report.tech  # list of Tech objects
        for tech in tech_list:
            name     = getattr(tech, "name", str(tech))
            version  = getattr(tech, "version", "") or ""
            # WebTech Tech objects sometimes have a .cats or .categories attribute
            cats     = getattr(tech, "cats", None) or getattr(tech, "categories", [])
            category = _resolve_category(cats)
            technologies.append((name, version, category))
        return technologies

    # ── Legacy SDK: plain dict {name: version} ─────────────────────────────
    if isinstance(report, dict):
        for name, version in report.items():
            technologies.append((
                name,
                str(version) if version else "",
                _infer_category_from_name(name),
            ))
        return technologies

    return technologies


def _resolve_category(cats) -> str:
    """
    Converts a WebTech category list (ints or strings) to a human-readable label.
    """
    # WebTech uses numeric category IDs mapped to descriptive strings
    CATEGORY_MAP = {
        1:  "CMS", 2:  "Message Boards", 3: "Database Manager",
        4:  "Documentation", 5: "Widget", 6: "Ecommerce",
        7:  "Photo Gallery", 8: "Wiki", 9: "Hosting Panels",
        10: "Analytics", 11: "Blog", 12: "JavaScript Framework",
        13: "Issue Tracker", 14: "Video", 22: "Web Framework",
        23: "Web Server", 24: "Cache", 25: "Rich Text Editor",
        26: "JavaScript Graphics", 31: "CDN", 34: "Database",
        41: "Search Engines", 42: "Web Mail", 58: "Security",
        62: "Programming Language",
    }
    if not cats:
        return ""
    first = cats[0] if isinstance(cats, (list, tuple)) else cats
    if isinstance(first, int):
        return CATEGORY_MAP.get(first, f"Cat {first}")
    return str(first)


def _infer_category_from_name(name: str) -> str:
    """
    Heuristic category assignment for the legacy dict format where category
    metadata is unavailable.
    """
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
