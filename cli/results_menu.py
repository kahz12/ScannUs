"""
cli/results_menu.py — Interactive URL analysis and paginated search results TUI.

Heavy analysis and export modules are imported lazily inside each action so
simply loading the CLI stays fast.
"""

from urllib.parse import urlparse

from rich.panel import Panel

from cli.ui import (
    console, THEME,
    ask, confirm, select_menu,
    header_bar, status_footer, panel,
    print_success, print_error, print_warn, print_info,
    make_table,
)
from core import state
from core.case_manager import save_case


_MEDIA_CHOICES = [
    ("All media",   "all",    "images · videos · audio"),
    ("Images only", "images", "jpg · png · webp · gif"),
    ("Videos only", "videos", "mp4 · webm · m3u8"),
    ("Audio only",  "audio",  "mp3 · ogg · wav"),
]

_URL_ACTION_CHOICES = [
    ("Summarize content",          "summarize",    "AI"),
    ("Extract PII",                "pii",          "Regex + Presidio"),
    ("Scan web technologies",      "tech",         "Wappalyzer"),
    ("Download file",              "file",         "Direct HTTP"),
    ("Download media",             "media",        "Images · Video · Audio"),
    ("Capture screenshot",         "screenshot",   "Headless browser"),
    ("Wayback Machine",            "wayback",      "Timeline · fetch · PII · diff"),
    ("Deep AI analysis",           "deep-ai",      "LLM"),
    ("Entity relationship graph",  "graph",        "AI + Pyvis"),
    ("Deep scraping",              "deep-scrape",  "JS render"),
    ("Back to results",            "back",         ""),
]

_WAYBACK_CHOICES = [
    ("Snapshot timeline (CDX)",        "timeline", "list archived captures"),
    ("Fetch snapshot text",            "fetch",    "read archived copy at a date"),
    ("Extract PII from snapshot",      "extract",  "find scrubbed identifiers/secrets"),
    ("Diff two snapshots",             "diff",     "compare two dates side-by-side"),
    ("Back",                           "back",     ""),
]

PAGE_SIZE = 10


def _current_case_label() -> str:
    """Short label describing the loaded case for the status footer."""
    terms = state.CURRENT_CASE.get("search_params") if isinstance(state.CURRENT_CASE, dict) else None
    if not terms:
        return "none"
    value = terms.get("value", "")
    if not value or value == "N/A":
        return terms.get("type", "manual")
    return value[:32] + ("…" if len(value) > 32 else "")


def _agent_label(ia_agent) -> str:
    """Return a short display name for the active AI agent, or 'none'."""
    if ia_agent is None:
        return "none"
    gen = getattr(ia_agent, "generator", None)
    name = type(gen).__name__ if gen else "unknown"
    return name.replace("Generator", "")


def _record_evidence(data: dict, text: str, url: str, tool: str) -> int:
    """Adds extracted values to the active case and the hub; returns new hub findings."""
    from cli import menus as _menus
    from search.smart_search import build_evidence
    records = build_evidence(data, text, url, tool)
    state.add_evidence(records)
    return _menus.get_hub().ingest_evidence(records)


def _show_evidence() -> None:
    """Renders the active case's evidence with the origin of each value."""
    evidence = state.CURRENT_CASE.get("evidence") or []
    if not evidence:
        print_info("No evidence in this case yet.")
        return
    tbl = make_table(
        f"Evidence  [{THEME['DIM']}]({len(evidence)} values)[/]",
        ("Category",   THEME["PRIMARY"]),
        ("Value",      "white"),
        ("Confidence", THEME["ACCENT"]),
        ("Source",     THEME["LINK"]),
        ("Tool",       THEME["DIM"]),
        show_lines=False,
    )
    for record in evidence:
        tbl.add_row(record["category"].replace("_", " "), record["value"],
                    record.get("confidence") or "—", record.get("source") or "—",
                    record.get("tool") or "—")
    console.print()
    console.print(tbl)


def _run_wayback_menu(url: str) -> None:
    """Interactive Wayback Machine submenu exposing timeline, fetch, PII and diff."""
    from analysis.advanced_osint import (
        check_wayback_machine,
        wayback_diff,
        wayback_extract_pii,
        wayback_fetch_snapshot,
    )
    while True:
        choice = select_menu("Wayback Machine", _WAYBACK_CHOICES, default="timeline")
        if choice in (None, "back"):
            break
        if choice == "timeline":
            check_wayback_machine(url)
        elif choice == "fetch":
            ts = ask("Timestamp or spec (latest | earliest | YYYY | YYYY-MM)", default="latest")
            snap = wayback_fetch_snapshot(url, ts)
            if snap and snap.get("text"):
                preview = snap["text"][:3000]
                if len(snap["text"]) > 3000:
                    preview += f"\n… (+{len(snap['text']) - 3000:,} more chars)"
                panel(preview, title=f"Snapshot {snap['date']}", border="cyan")
        elif choice == "extract":
            ts = ask("Timestamp or spec (latest | earliest | YYYY | YYYY-MM)", default="latest")
            wayback_extract_pii(url, ts)
        elif choice == "diff":
            ts_a = ask("First snapshot (earliest | YYYY | YYYY-MM | timestamp)", default="earliest")
            ts_b = ask("Second snapshot (latest | YYYY | YYYY-MM | timestamp)", default="latest")
            wayback_diff(url, ts_a, ts_b)


def process_selected_url(url: str, ia_agent=None) -> None:
    """Deep-analysis menu for a single result URL."""
    from cli import menus as _menus
    while True:
        short_url = url if len(url) <= 70 else url[:67] + "…"
        header_bar("URL Analysis", short_url, glyph="🔗")

        action = select_menu(
            "Pick an action",
            _URL_ACTION_CHOICES,
            default="summarize",
        )

        if action in (None, "back"):
            break

        if action == "summarize":
            if not ia_agent:
                print_warn("AI needed — let's set it up first.")
                ia_agent = _menus.select_ia_agent()
            if not ia_agent:
                continue
            from analysis.web_analyzer import get_text_from_url, summarize_text_with_ia
            with console.status(f"[{THEME['PRIMARY']}]Fetching and summarising…[/]", spinner="dots2"):
                page_text = get_text_from_url(url)
            if page_text:
                summary = summarize_text_with_ia(page_text, ia_agent)
                panel(summary, title="Summary", border="green")

        elif action == "pii":
            from analysis.web_analyzer import get_text_from_url
            from search.smart_search import extract_information, flatten_extracted
            with console.status(f"[{THEME['PRIMARY']}]Extracting PII…[/]", spinner="dots2"):
                page_text = get_text_from_url(url)
            if page_text:
                data = extract_information(page_text)
                if data:
                    tbl = make_table(
                        "Extracted PII",
                        ("Category", THEME["PRIMARY"]), ("Values", "white"),
                        show_lines=True,
                    )
                    for key, values in flatten_extracted(data).items():
                        tbl.add_row(key.replace("_", " ").capitalize(), "\n".join(values))
                    console.print(tbl)
                    added = _record_evidence(data, page_text, url, "url-pii")
                    if added:
                        print_info(f"{added} new finding(s) added to the hub.")
                else:
                    print_info("No extractable identifiers found.")

        elif action == "tech":
            from analysis.tech_scanner import tech_scan
            tech_scan(url)

        elif action == "file":
            from utils.file_download import FileDownload
            print_info("Attempting direct download…")
            FileDownload().download_file_direct(url, extract_metadata=True)

        elif action == "media":
            from utils.media_downloader import download_media
            media_type = select_menu("Media type", _MEDIA_CHOICES, default="all") or "all"
            use_selenium = confirm("Use Selenium for JavaScript-rendered pages?", default=False)
            domain = urlparse(url).netloc.replace(".", "_")
            zip_name = f"{domain}_{media_type}_media.zip"
            try:
                download_media(url, zip_name, media_type=media_type, use_selenium=use_selenium)
            except Exception as e:
                print_error(str(e))

        elif action == "screenshot":
            from analysis.advanced_osint import take_screenshot
            take_screenshot(url)

        elif action == "wayback":
            _run_wayback_menu(url)

        elif action == "deep-ai":
            if not ia_agent:
                print_warn("AI needed — let's set it up first.")
                ia_agent = _menus.select_ia_agent()
            if not ia_agent:
                continue
            from analysis.web_analyzer import get_text_from_url, translate_and_analyze_with_ia
            with console.status(f"[{THEME['PRIMARY']}]Fetching for deep analysis…[/]", spinner="dots2"):
                page_text = get_text_from_url(url)
            if page_text:
                analysis = translate_and_analyze_with_ia(page_text, ia_agent)
                panel(analysis, title="AI Deep Analysis", border="yellow")

        elif action == "graph":
            if not ia_agent:
                print_warn("AI needed — let's set it up first.")
                ia_agent = _menus.select_ia_agent()
            if not ia_agent:
                continue
            from analysis.web_analyzer import get_text_from_url, extract_entities_and_graph
            with console.status(f"[{THEME['PRIMARY']}]Building entity graph…[/]", spinner="dots2"):
                page_text = get_text_from_url(url)
            if page_text:
                domain = urlparse(url).netloc.replace(".", "_")
                graph_file = f"graph_{domain}.html"
                result_file = extract_entities_and_graph(page_text, ia_agent, output_filename=graph_file)
                if result_file:
                    print_success(f"Relationship graph saved: {result_file}")

        elif action == "deep-scrape":
            from analysis.advanced_osint import get_dynamic_text_from_url
            from search.smart_search import extract_information, flatten_extracted
            with console.status(f"[{THEME['PRIMARY']}]Deep scraping (JS)…[/]", spinner="dots2"):
                page_text = get_dynamic_text_from_url(url)
            if page_text:
                print_success(f"Retrieved {len(page_text):,} characters.")
                data = extract_information(page_text)
                if data:
                    tbl = make_table(
                        "Extracted Information (Deep)",
                        ("Category", THEME["PRIMARY"]), ("Values", "white"),
                        show_lines=True,
                    )
                    for key, values in flatten_extracted(data).items():
                        tbl.add_row(key.replace("_", " ").capitalize(), "\n".join(values))
                    console.print(tbl)
                    added = _record_evidence(data, page_text, url, "url-pii-deep")
                    if added:
                        print_info(f"{added} new finding(s) added to the hub.")
                else:
                    print_info("No identifiers found in deep content.")


def _render_results_page(results: list, page: int) -> None:
    total   = len(results)
    pages   = max(1, -(-total // PAGE_SIZE))
    start   = page * PAGE_SIZE
    end     = min(start + PAGE_SIZE, total)
    page_items = results[start:end]

    tbl = make_table(
        f"Search Results  "
        f"[{THEME['DIM']}]{total} total · page {page + 1}/{pages}[/]",
        ("#",     THEME["DIM"]),
        ("Title", "bold white"),
        ("Link",  THEME["LINK"]),
        show_lines=False,
    )
    for res in page_items:
        tbl.add_row(str(res["id"]), res["title"], res["link"])

    console.print()
    console.print(tbl)

    nav_parts = []
    if page > 0:
        nav_parts.append(f"[{THEME['PRIMARY']}]p[/] prev")
    if end < total:
        nav_parts.append(f"[{THEME['PRIMARY']}]n[/] next")
    nav_parts.append(f"[{THEME['DIM']}]j <N>[/] jump")
    nav_parts.append(f"[{THEME['DIM']}]all[/] full list")
    nav_str = "  ·  ".join(nav_parts)

    commands_text = (
        f"  ID to analyse  ·  {nav_str}\n"
        f"  [{THEME['ACCENT']}]media[/] download  ·  "
        f"[{THEME['PRIMARY']}]next[/] hub  ·  "
        f"[{THEME['PRIMARY']}]evidence[/]  ·  "
        f"[{THEME['WARN']}]save[/]  ·  "
        f"[green]excel[/]  ·  [red]exit[/]"
    )
    console.print(Panel(commands_text, border_style=THEME["BORDER"], padding=(0, 1)))


def interactive_analysis_menu(results: list, ia_agent=None) -> None:
    """
    Interactive results loop with pagination.
    """
    from cli import menus as _menus
    from cli.hub_menu import findings_hub_menu

    state.LAST_RESULTS = results
    _menus.get_hub().ingest_results(results, source="search")

    if not state.CURRENT_CASE["search_params"]:
        state.CURRENT_CASE["search_params"] = {"type": "manual", "value": "N/A"}

    formatted = []
    for i, r in enumerate(results):
        formatted.append({
            "id":          i + 1,
            "title":       r.get("title", "N/A"),
            "description": r.get("description", "N/A"),
            "link":        r.get("link", "N/A"),
        })
    state.CURRENT_CASE["results"] = formatted

    all_results = state.CURRENT_CASE["results"]
    total_pages = max(1, -(-len(all_results) // PAGE_SIZE))
    current_page = 0
    show_all = False

    while True:
        header_bar("Search Results", f"{len(all_results)} entries")
        status_footer([
            ("case",  _current_case_label(),              "info"),
            ("agent", _agent_label(ia_agent),             "on" if ia_agent else "off"),
            ("page",  f"{current_page + 1}/{total_pages}", "info"),
        ])

        if show_all or len(all_results) <= PAGE_SIZE:
            tbl = make_table(
                f"Search Results  [{THEME['DIM']}]({len(all_results)} total)[/]",
                ("#",     THEME["DIM"]),
                ("Title", "bold white"),
                ("Link",  THEME["LINK"]),
                show_lines=False,
            )
            for res in all_results:
                tbl.add_row(str(res["id"]), res["title"], res["link"])
            console.print()
            console.print(tbl)
            console.print(
                Panel(
                    f"  ID to analyse  ·  [{THEME['PRIMARY']}]page[/] back to paginated view\n"
                    f"  [{THEME['ACCENT']}]media[/] download  ·  "
                    f"[{THEME['PRIMARY']}]next[/] hub  ·  "
                    f"[{THEME['PRIMARY']}]evidence[/]  ·  "
                    f"[{THEME['WARN']}]save[/]  ·  [green]excel[/]  ·  [red]exit[/]",
                    border_style=THEME["BORDER"],
                    padding=(0, 1),
                )
            )
        else:
            _render_results_page(all_results, current_page)

        choice = ask().lower().strip()

        if choice == "n":
            if current_page < total_pages - 1:
                current_page += 1
                show_all = False
            else:
                print_warn("Already on the last page.")
            continue

        elif choice == "p":
            if current_page > 0:
                current_page -= 1
                show_all = False
            else:
                print_warn("Already on the first page.")
            continue

        elif choice.startswith("j "):
            try:
                pg = int(choice.split()[1]) - 1
                if 0 <= pg < total_pages:
                    current_page = pg
                    show_all = False
                else:
                    print_warn(f"Page out of range — enter 1 to {total_pages}.")
            except (ValueError, IndexError):
                print_warn("Usage: j <page number>  e.g.  j 3")
            continue

        elif choice == "all":
            show_all = True
            continue

        elif choice == "page":
            show_all = False
            continue

        elif choice in ("next", "hub"):
            findings_hub_menu(ia_agent)
            continue

        elif choice in ("exit", "salir"):
            break

        elif choice in ("evidence", "evidencia"):
            _show_evidence()
            continue

        elif choice in ("save", "guardar"):
            save_case()
            continue

        elif choice == "excel":
            from utils.results_parse import ResultsParser
            filename = ask("Excel filename", default="results.xlsx")
            if not filename.endswith(".xlsx"):
                filename += ".xlsx"
            evidence = state.CURRENT_CASE.get("evidence") or None
            ResultsParser(all_results, extracted=evidence).export_excel(filename)
            continue

        elif choice == "media":
            from utils.media_downloader import download_media
            ids_str = ask("Result IDs (comma-separated, e.g. 1,3,5)")
            ids = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]
            if not ids:
                print_error("No valid IDs provided.")
                continue
            media_type = select_menu("Media type", _MEDIA_CHOICES, default="all") or "all"
            use_selenium = confirm("Use Selenium for JavaScript-rendered pages?", default=False)

            for idx in ids:
                if 0 < idx <= len(all_results):
                    url = all_results[idx - 1]["link"]
                    print_info(f"Starting media download for #{idx}: {url}")
                    try:
                        domain = urlparse(url).netloc.replace(".", "_")
                        download_media(url, f"{domain}_{media_type}_media.zip",
                                       media_type=media_type, use_selenium=use_selenium)
                    except Exception as e:
                        print_error(f"ID {idx}: {e}")
                else:
                    print_warn(f"ID {idx} is out of range.")
            continue

        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(all_results):
                    selected_url = all_results[idx]["link"]
                    process_selected_url(selected_url, ia_agent)
                else:
                    print_warn("Index out of range — try again.")
            except ValueError:
                print_warn(
                    "Enter a result ID, or: n · p · j <N> · all · "
                    "media · next · save · excel · exit"
                )
