"""
cli/menus.py — Interactive TUI menus for ScannUs.

All user interaction flows through the design-system helpers in ``cli.ui``:
  - ``select_menu``  → arrow-key navigable menus (graceful numeric fallback)
  - ``confirm``      → Y/N prompts
  - ``ask``          → free-text prompts with default-value hints
  - ``header_bar``   → screen-level title bar
  - ``status_footer``→ bottom context strip
"""

import os
from urllib.parse import urlparse

from rich.panel import Panel

from cli.ui import (
    console, THEME,
    ask, confirm, select_menu,
    header_bar, status_footer, panel,
    print_success, print_error, print_warn, print_info, print_section,
    make_table,
)
from core import state
from core.case_manager import guardar_caso, cargar_caso
from core.config import env_config, openai_config
from core.ai_agent import IAAgent, GeminiGenerator, OpenAIGenerator
from search.reverse_image import do_reverse_image_search
from analysis.tech_scanner import tech_scan
from analysis.web_analyzer import (
    get_text_from_url, summarize_text_with_ia,
    translate_and_analyze_with_ia, extract_entities_and_graph,
)
from analysis.advanced_osint import take_screenshot, check_wayback_machine, get_dynamic_text_from_url
from search.smart_search import extract_information
from search.username_enum import username_enum
from utils.file_download import FileDownload
from utils.media_downloader import download_media
from utils.results_parse import ResultsParser
import cli.actions


# ---------------------------------------------------------------------------
# Common selection helpers
# ---------------------------------------------------------------------------

_ENGINE_CHOICES = [
    ("DuckDuckGo",  "duckduckgo", "privacy-friendly · default"),
    ("Google",      "google",     "broadest coverage · API key"),
    ("Brave",       "brave",      "independent index"),
]

_MEDIA_CHOICES = [
    ("All media",   "all",    "images · videos · audio"),
    ("Images only", "images", "jpg · png · webp · gif"),
    ("Videos only", "videos", "mp4 · webm · m3u8"),
    ("Audio only",  "audio",  "mp3 · ogg · wav"),
]

_ENUM_BACKEND_CHOICES = [
    ("Auto-detect", "auto",     "prefer Sherlock if available"),
    ("Sherlock",    "sherlock", "pure-Python · works on Termux"),
    ("Maigret",     "maigret",  "3000+ sites · Linux/macOS only"),
]


def _select_engine(default: str = "duckduckgo") -> str:
    """Arrow-key engine picker with safe fallback."""
    return select_menu(
        "Select search engine",
        _ENGINE_CHOICES,
        default=default,
    ) or default


def _current_case_label() -> str:
    """Short label describing the loaded case for the status footer."""
    terms = state.CASO_ACTUAL.get("terminos") if isinstance(state.CASO_ACTUAL, dict) else None
    if not terms:
        return "none"
    value = terms.get("value", "")
    if not value or value == "N/A":
        return terms.get("type", "manual")
    return value[:32] + ("…" if len(value) > 32 else "")


def _agent_label(ia_agent) -> str:
    if ia_agent is None:
        return "none"
    gen = getattr(ia_agent, "generator", None)
    name = type(gen).__name__ if gen else "unknown"
    return name.replace("Generator", "")


# ---------------------------------------------------------------------------
# AI agent selection
# ---------------------------------------------------------------------------

def select_ia_agent():
    """Arrow-key picker for the AI provider, returning an initialised IAAgent."""
    header_bar("AI Provider", "Pick the LLM used for summarisation and dorking")

    choice = select_menu(
        "Select AI provider",
        [
            ("Google Gemini",    "ge", "gemini-2.0-flash · free tier"),
            ("OpenAI GPT-4o",    "op", "paid · high quality"),
            ("Cancel",           "cancel", ""),
        ],
        default="ge",
    )

    if choice in (None, "cancel"):
        return None

    if choice == "ge":
        if not os.getenv("GOOGLE_API_KEY_FOR_GEMINI"):
            print_error("GOOGLE_API_KEY_FOR_GEMINI is missing from .env — configure it first.")
            return None
        print_success("Gemini selected.")
        return IAAgent(GeminiGenerator())

    if not os.getenv("OPENAI_API_KEY"):
        print_warn("OpenAI API key not configured — launching setup…")
        openai_config()
    print_success("OpenAI selected.")
    return IAAgent(OpenAIGenerator(model_name="gpt-4o"))


# ---------------------------------------------------------------------------
# URL analysis sub-menu
# ---------------------------------------------------------------------------

_URL_ACTION_CHOICES = [
    ("Summarize content",          "summarize",    "AI"),
    ("Extract PII",                "pii",          "Regex + Presidio"),
    ("Scan web technologies",      "tech",         "Wappalyzer"),
    ("Download file",              "file",         "Direct HTTP"),
    ("Download media",             "media",        "Images · Video · Audio"),
    ("Capture screenshot",         "screenshot",   "Headless browser"),
    ("Wayback Machine history",    "wayback",      "Archive.org"),
    ("Deep AI analysis",           "deep-ai",      "LLM"),
    ("Entity relationship graph",  "graph",        "AI + Pyvis"),
    ("Deep scraping",              "deep-scrape",  "JS render"),
    ("Back to results",            "back",         ""),
]


def process_selected_url(url: str, ia_agent=None) -> None:
    """Deep-analysis menu for a single result URL."""
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
                ia_agent = select_ia_agent()
            if not ia_agent:
                continue
            with console.status(f"[{THEME['PRIMARY']}]Fetching and summarising…[/]", spinner="dots2"):
                page_text = get_text_from_url(url)
            if page_text:
                summary = summarize_text_with_ia(page_text, ia_agent)
                panel(summary, title="Summary", border="green")

        elif action == "pii":
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
                    for key, values in data.items():
                        tbl.add_row(key.replace("_", " ").capitalize(), "\n".join(values))
                    console.print(tbl)
                else:
                    print_info("No extractable identifiers found.")

        elif action == "tech":
            tech_scan(url)

        elif action == "file":
            print_info("Attempting direct download…")
            FileDownload().descargar_archivo_directo(url, extract_metadata=True)

        elif action == "media":
            media_type = select_menu(
                "Media type",
                _MEDIA_CHOICES,
                default="all",
            ) or "all"
            use_selenium = confirm(
                "Use Selenium for JavaScript-rendered pages?",
                default=False,
            )
            domain = urlparse(url).netloc.replace(".", "_")
            zip_name = f"{domain}_{media_type}_media.zip"
            try:
                download_media(url, zip_name, media_type=media_type, use_selenium=use_selenium)
            except Exception as e:
                print_error(str(e))

        elif action == "screenshot":
            take_screenshot(url)

        elif action == "wayback":
            check_wayback_machine(url)

        elif action == "deep-ai":
            if not ia_agent:
                print_warn("AI needed — let's set it up first.")
                ia_agent = select_ia_agent()
            if not ia_agent:
                continue
            with console.status(f"[{THEME['PRIMARY']}]Fetching for deep analysis…[/]", spinner="dots2"):
                page_text = get_text_from_url(url)
            if page_text:
                analysis = translate_and_analyze_with_ia(page_text, ia_agent)
                panel(analysis, title="AI Deep Analysis", border="yellow")

        elif action == "graph":
            if not ia_agent:
                print_warn("AI needed — let's set it up first.")
                ia_agent = select_ia_agent()
            if not ia_agent:
                continue
            with console.status(f"[{THEME['PRIMARY']}]Building entity graph…[/]", spinner="dots2"):
                page_text = get_text_from_url(url)
            if page_text:
                domain = urlparse(url).netloc.replace(".", "_")
                graph_file = f"graph_{domain}.html"
                result_file = extract_entities_and_graph(page_text, ia_agent, output_filename=graph_file)
                if result_file:
                    print_success(f"Relationship graph saved: {result_file}")

        elif action == "deep-scrape":
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
                    for key, values in data.items():
                        tbl.add_row(key.replace("_", " ").capitalize(), "\n".join(values))
                    console.print(tbl)
                else:
                    print_info("No identifiers found in deep content.")


# ---------------------------------------------------------------------------
# Results analysis menu
# ---------------------------------------------------------------------------

PAGE_SIZE = 10


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
        f"[{THEME['WARN']}]save[/]  ·  "
        f"[green]excel[/]  ·  [red]exit[/]"
    )
    console.print(Panel(commands_text, border_style=THEME["BORDER"], padding=(0, 1)))


def interactive_analysis_menu(resultados: list, ia_agent=None) -> None:
    """
    Interactive results loop with pagination.

    Typed commands:
      n / p / j <N> / all / page   → navigation
      <ID>                         → analyse result by number
      media                        → batch media download
      save · excel · exit          → case/export/quit
    """
    state.ULTIMOS_RESULTADOS = resultados

    if not state.CASO_ACTUAL["terminos"]:
        state.CASO_ACTUAL["terminos"] = {"type": "manual", "value": "N/A"}

    formatted = []
    for i, r in enumerate(resultados):
        formatted.append({
            "id":          i + 1,
            "title":       r.get("title", "N/A"),
            "description": r.get("description", "N/A"),
            "link":        r.get("link", "N/A"),
        })
    state.CASO_ACTUAL["resultados"] = formatted

    all_results = state.CASO_ACTUAL["resultados"]
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
                    f"[{THEME['WARN']}]save[/]  ·  [green]excel[/]  ·  [red]exit[/]",
                    border_style=THEME["BORDER"],
                    padding=(0, 1),
                )
            )
        else:
            _render_results_page(all_results, current_page)

        choice = ask().lower().strip()

        # ── Navigation ────────────────────────────────────────────────
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

        # ── Actions ───────────────────────────────────────────────────
        elif choice in ("exit", "salir"):
            break

        elif choice in ("save", "guardar"):
            guardar_caso()
            continue

        elif choice == "excel":
            filename = ask("Excel filename", default="results.xlsx")
            if not filename.endswith(".xlsx"):
                filename += ".xlsx"
            ResultsParser(all_results).exportar_excel(filename)
            continue

        elif choice == "media":
            ids_str = ask("Result IDs (comma-separated, e.g. 1,3,5)")
            ids = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]
            if not ids:
                print_error("No valid IDs provided.")
                continue
            media_type = select_menu(
                "Media type",
                _MEDIA_CHOICES,
                default="all",
            ) or "all"
            use_selenium = confirm(
                "Use Selenium for JavaScript-rendered pages?",
                default=False,
            )

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
                    "media · save · excel · exit"
                )


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

_MAIN_MENU_CHOICES = [
    ("Guided Search",          "guided",   "Name · Username · Email · Phone"),
    ("Direct Search",          "direct",   "Raw query or Google Dork"),
    ("AI Dork Generator",      "dork",     "LLM-assisted dork creation"),
    ("Reverse Image Lookup",   "reverse",  "Yandex visual search"),
    ("Web Technology Scan",    "tech",     "Tech stack fingerprinting"),
    ("Username Enumeration",   "user-enum","Sherlock · 400+ sites"),
    ("Load Saved Case",        "load",     "Resume a previous investigation"),
    ("Configure API Keys",     "config",   "Edit .env credentials"),
    ("Exit",                   "exit",     ""),
]


def _run_guided_search() -> None:
    header_bar("Guided Search", "Compose an AND-query from target attributes")
    nombre   = ask("Full name         (optional)")
    usuario  = ask("Username / handle (optional)")
    email    = ask("Email address     (optional)")
    telefono = ask("Phone number      (optional)")
    buscar   = ask("General term      (optional)")

    parts = []
    if nombre:   parts.append(f'"{nombre}"')
    if usuario:  parts.append(f'"{usuario}"')
    if email:    parts.append(f'"{email}"')
    if telefono: parts.append(f'"{telefono}"')
    if buscar:   parts.append(f'"{buscar}"')

    if not parts:
        print_error("At least one search term is required.")
        return

    query  = " AND ".join(parts)
    engine = _select_engine()

    if email or telefono:
        print_info("PII detected — switching to deep extraction mode…")
        cli.actions.do_deep_search(query, engine, pages=1, start_page=1, lang="lang_es")
    else:
        cli.actions.do_search(query, engine, pages=1, start_page=1,
                              lang="lang_es", interactive=False, ia_agent=None)
        if state.ULTIMOS_RESULTADOS:
            interactive_analysis_menu(state.ULTIMOS_RESULTADOS, ia_agent=None)


def _run_direct_search() -> None:
    header_bar("Direct Search", "Raw query or Google-style Dork")
    query = ask("Search query / dork")
    if not query:
        print_error("Query cannot be empty.")
        return
    engine = _select_engine()
    cli.actions.do_search(query, engine, pages=1, start_page=1,
                          lang="lang_es", interactive=False, ia_agent=None)
    if state.ULTIMOS_RESULTADOS:
        interactive_analysis_menu(state.ULTIMOS_RESULTADOS, ia_agent=None)


def _run_tech_scan() -> None:
    header_bar("Web Technology Scan", "Fingerprint the target's stack")
    url = ask("Target URL")
    if url:
        tech_scan(url)
    else:
        print_error("URL cannot be empty.")


def _run_username_enum() -> None:
    header_bar("Username Enumeration", "Check 400+ social networks")
    handle = ask("Username / handle")
    if not handle:
        print_error("Username cannot be empty.")
        return
    backend = select_menu(
        "Enumeration backend",
        _ENUM_BACKEND_CHOICES,
        default="auto",
    ) or "auto"
    timeout_str = ask("Per-site timeout in seconds", default="20")
    try:
        timeout = max(5, int(timeout_str))
    except ValueError:
        timeout = 20
    username_enum(handle, backend=backend, timeout=timeout)


def show_main_menu() -> None:
    """Root navigation menu for ScannUs."""
    while True:
        header_bar("ScannUs", "Advanced OSINT & Search Framework")
        status_footer([
            ("env",    ".env" if os.path.exists(".env") else "missing",
                       "on" if os.path.exists(".env") else "off"),
            ("case",   _current_case_label(),    "info"),
        ])

        choice = select_menu(
            "Main menu",
            _MAIN_MENU_CHOICES,
            default="guided",
        )

        if choice in (None, "exit"):
            console.print()
            panel(
                f"[{THEME['SUCCESS']}]Session closed. Stay curious.[/]",
                border="green",
                padding=(0, 4),
            )
            break

        if choice == "guided":
            _run_guided_search()
        elif choice == "direct":
            _run_direct_search()
        elif choice == "dork":
            header_bar("AI Dork Generator", "Turn a natural-language brief into a Google Dork")
            cli.actions.do_generate_dork_ia()
        elif choice == "reverse":
            header_bar("Reverse Image Lookup", "Yandex visual search")
            do_reverse_image_search()
        elif choice == "tech":
            _run_tech_scan()
        elif choice == "user-enum":
            _run_username_enum()
        elif choice == "load":
            header_bar("Load Case", "Restore a saved investigation")
            ia_agent = select_ia_agent()
            if ia_agent and cargar_caso():
                interactive_analysis_menu(state.ULTIMOS_RESULTADOS, ia_agent)
        elif choice == "config":
            header_bar("API Credentials", "Update .env file")
            env_config()
            openai_config()
