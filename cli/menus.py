"""
cli/menus.py — All interactive TUI menus for ScannUs.
Uses the shared theme from cli.ui for visual consistency.
"""

from urllib.parse import urlparse
from rich.panel import Panel
from rich.table import Table

from cli.ui import (
    console, THEME, PROMPT,
    print_success, print_error, print_warn, print_info, print_section, make_table,
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
from utils.file_download import FileDownload
from utils.media_downloader import download_media
from utils.results_parse import ResultsParser
import cli.actions
import os


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ask(label: str = "") -> str:
    """Styled inline prompt using console.input() so Rich markup renders."""
    prefix = f"  {label} " if label else "  "
    return console.input(f"{prefix}{PROMPT}").strip()


def _choose(options: list[str], label: str = "Select") -> str:
    """Generic styled choice prompt."""
    return console.input(f"  [{THEME['DIM']}]{label}[/] {PROMPT}").strip()


# ---------------------------------------------------------------------------
# AI agent selection
# ---------------------------------------------------------------------------

def select_ia_agent():
    """
    Presents a styled panel for AI provider selection and initialises the agent.
    """
    console.print()
    console.print(
        Panel(
            f"  [{THEME['PRIMARY']}]ge[/]  →  Google Gemini\n"
            f"  [{THEME['PRIMARY']}]op[/]  →  OpenAI (GPT-4o)",
            title=f"[{THEME['ACCENT']}]Select AI Provider[/]",
            border_style="bright_black",
            padding=(0, 2),
        )
    )

    respuesta = ""
    while respuesta.lower() not in ("ge", "op"):
        respuesta = _ask("Provider (ge / op)")

    if respuesta.lower() == "ge":
        if not os.getenv("GOOGLE_API_KEY_FOR_GEMINI"):
            print_error("GOOGLE_API_KEY_FOR_GEMINI not found in .env — run option 7.")
            return None
        print_success("Gemini selected.")
        return IAAgent(GeminiGenerator())

    if not os.getenv("OPENAI_API_KEY"):
        print_warn("OpenAI API Key is not configured — launching setup…")
        openai_config()
    print_success("OpenAI selected.")
    return IAAgent(OpenAIGenerator(model_name="gpt-4o"))


# ---------------------------------------------------------------------------
# URL analysis sub-menu
# ---------------------------------------------------------------------------

_URL_ACTIONS = [
    ("1",  "Summarize content",           "AI", "green"),
    ("2",  "Extract PII",                 "Regex", "green"),
    ("3",  "Scan web technologies",       "", "green"),
    ("4",  "Download file",               "Direct", "cyan"),
    ("5",  "Download media",              "Images/Video/Audio", "cyan"),
    ("6",  "Capture screenshot",          "Headless", "magenta"),
    ("7",  "Wayback Machine history",     "Archive.org", "magenta"),
    ("8",  "Deep AI analysis",            "AI", "yellow"),
    ("9",  "Entity relationship graph",   "AI + Pyvis", "yellow"),
    ("10", "Deep scraping",               "JS Render", "blue"),
    ("0",  "Back to results",             "", "red"),
]


def process_selected_url(url: str, ia_agent=None) -> None:
    """TUI menu for deep analysis of a specific search result URL."""

    while True:
        # Build action panel
        tbl = Table(box=None, show_header=False, padding=(0, 2), border_style="bright_black")
        tbl.add_column("Key",   style=THEME["PRIMARY"], width=4)
        tbl.add_column("Label", style="white")
        tbl.add_column("Tag",   style=THEME["DIM"])

        for key, label, tag, _ in _URL_ACTIONS:
            tbl.add_row(key, label, f"[{THEME['DIM']}]{tag}[/]" if tag else "")

        console.print()
        console.print(
            Panel(
                tbl,
                title=f"[{THEME['PRIMARY']}]🔗 {url[:70]}{'…' if len(url) > 70 else ''}[/]",
                subtitle=f"[{THEME['DIM']}]URL Analysis[/]",
                border_style="bright_black",
                padding=(0, 1),
            )
        )
        action = _ask()

        # --- Actions ---
        if action == "1":
            if not ia_agent:
                print_warn("AI needed — let's set it up first.")
                ia_agent = select_ia_agent()
            if not ia_agent:
                continue
            with console.status(f"[{THEME['PRIMARY']}]Fetching and summarising…[/]", spinner="dots2"):
                page_text = get_text_from_url(url)
            if page_text:
                summary = summarize_text_with_ia(page_text, ia_agent)
                console.print(Panel(summary, title=f"[{THEME['SUCCESS']}]Summary[/]",
                                    border_style="green", padding=(1, 2)))

        elif action == "2":
            with console.status(f"[{THEME['PRIMARY']}]Extracting PII…[/]", spinner="dots2"):
                page_text = get_text_from_url(url)
            if page_text:
                data = extract_information(page_text)
                if data:
                    tbl2 = make_table("Extracted PII",
                                      ("Category", THEME["PRIMARY"]), ("Values", "white"),
                                      show_lines=True)
                    for key, values in data.items():
                        tbl2.add_row(key.replace("_", " ").capitalize(), "\n".join(values))
                    console.print(tbl2)
                else:
                    print_info("No extractable identifiers found.")

        elif action == "3":
            tech_scan(url)

        elif action == "4":
            print_info("Attempting direct download…")
            fdownloader = FileDownload()
            fdownloader.descargar_archivo_directo(url, extract_metadata=True)

        elif action == "5":
            media_type = _ask("Media type (images/videos/audio/all) [all]").lower() or "all"
            if media_type not in ("images", "videos", "audio", "all"):
                media_type = "all"
            use_js = _ask("Use Selenium for JS-rendered content? (y/n) [n]").lower()
            use_selenium = use_js in ("y", "s")
            domain = urlparse(url).netloc.replace(".", "_")
            zip_name = f"{domain}_{media_type}_media.zip"
            try:
                download_media(url, zip_name, media_type=media_type, use_selenium=use_selenium)
            except Exception as e:
                print_error(str(e))

        elif action == "6":
            take_screenshot(url)

        elif action == "7":
            check_wayback_machine(url)

        elif action == "8":
            if not ia_agent:
                print_warn("AI needed — let's set it up first.")
                ia_agent = select_ia_agent()
            if not ia_agent:
                continue
            with console.status(f"[{THEME['PRIMARY']}]Fetching content for deep analysis…[/]", spinner="dots2"):
                page_text = get_text_from_url(url)
            if page_text:
                analysis = translate_and_analyze_with_ia(page_text, ia_agent)
                console.print(Panel(analysis, title=f"[{THEME['SUCCESS']}]AI Deep Analysis[/]",
                                    border_style="yellow", padding=(1, 2)))

        elif action == "9":
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

        elif action == "10":
            with console.status(f"[{THEME['PRIMARY']}]Deep scraping (JS)…[/]", spinner="dots2"):
                page_text = get_dynamic_text_from_url(url)
            if page_text:
                print_success(f"Retrieved {len(page_text):,} characters.")
                data = extract_information(page_text)
                if data:
                    tbl3 = make_table("Extracted Information (Deep)",
                                      ("Category", THEME["PRIMARY"]), ("Values", "white"),
                                      show_lines=True)
                    for key, values in data.items():
                        tbl3.add_row(key.replace("_", " ").capitalize(), "\n".join(values))
                    console.print(tbl3)
                else:
                    print_info("No identifiers found in deep content.")

        elif action == "0":
            break
        else:
            print_warn("Invalid option — enter a number from the list.")


# ---------------------------------------------------------------------------
# Results analysis menu
# ---------------------------------------------------------------------------

PAGE_SIZE = 10  # results shown per page


def _render_results_page(results: list, page: int) -> None:
    """Renders a single page of the results table with a navigation footer."""
    total   = len(results)
    pages   = max(1, -(-total // PAGE_SIZE))   # ceiling division
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

    # Navigation hint
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
    console.print(Panel(commands_text, border_style="bright_black", padding=(0, 1)))


def interactive_analysis_menu(resultados: list, ia_agent=None) -> None:
    """
    Main interactive results loop with pagination.

    Navigation commands:
      n          → next page
      p          → previous page
      j <N>      → jump to page N
      all        → display all results (no pagination)
      <ID>       → analyse result by ID
      media      → batch media download for selected IDs
      save       → persist current case to DB
      excel      → export to Excel
      exit       → return to main menu
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
    show_all = False   # when True, bypass pagination and render everything

    while True:
        # --- Display ---
        if show_all or len(all_results) <= PAGE_SIZE:
            # Render all results as a single table
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
                    border_style="bright_black",
                    padding=(0, 1),
                )
            )
        else:
            _render_results_page(all_results, current_page)

        choice = _ask().lower().strip()

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
            filename = _ask("Excel filename [results.xlsx]") or "results.xlsx"
            if not filename.endswith(".xlsx"):
                filename += ".xlsx"
            ResultsParser(all_results).exportar_excel(filename)
            continue

        elif choice == "media":
            ids_str = _ask("Result IDs (comma-separated, e.g. 1,3,5)")
            ids = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]
            if not ids:
                print_error("No valid IDs provided.")
                continue
            media_type = (_ask("Media type (images/videos/audio/all) [all]").lower() or "all")
            if media_type not in ("images", "videos", "audio", "all"):
                media_type = "all"
            use_js = _ask("Use Selenium for JS-rendered content? (y/n) [n]").lower()
            use_selenium = use_js in ("y", "s")

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


_MAIN_MENU_ITEMS = [
    ("1", "Guided Search",          "Name · Username · Email · Phone", "cyan"),
    ("2", "Direct Search",          "Raw query / Google Dork",         "cyan"),
    ("3", "AI Dork Generator",      "LLM-assisted dork creation",       "magenta"),
    ("4", "Reverse Image Lookup",   "Yandex visual search",             "blue"),
    ("5", "Web Technology Scan",    "Tech stack fingerprinting",         "blue"),
    ("6", "Load Saved Case",        "Resume investigation",             "green"),
    ("7", "Configure API Keys",     "Edit .env credentials",            "yellow"),
    ("8", "Exit",                   "",                                 "red"),
]


def show_main_menu() -> None:
    """Root navigation menu for ScannUs."""
    while True:
        # Build menu table
        tbl = Table(box=None, show_header=False, padding=(0, 2))
        tbl.add_column("Key",   style=THEME["PRIMARY"], width=4, no_wrap=True)
        tbl.add_column("Label", style="bold white",     no_wrap=True)
        tbl.add_column("Desc",  style=THEME["DIM"],     no_wrap=False)

        for key, label, desc, colour in _MAIN_MENU_ITEMS:
            tbl.add_row(
                f"[{colour}]{key}[/]",
                f"[{colour}]{label}[/]",
                desc,
            )

        console.print()
        console.print(
            Panel(
                tbl,
                title=f"[{THEME['PRIMARY']}]⬡  ScannUs[/]",
                subtitle=f"[{THEME['DIM']}]Advanced OSINT & Search Framework[/]",
                border_style="bright_black",
                padding=(1, 2),
            )
        )

        choice = _ask()

        # --- Option 1: Guided Search ---
        if choice == "1":
            print_section("Guided Search")
            nombre   = _ask("Full name         (optional)")
            usuario  = _ask("Username / handle (optional)")
            email    = _ask("Email address     (optional)")
            telefono = _ask("Phone number      (optional)")
            buscar   = _ask("General term      (optional)")

            parts = []
            if nombre:   parts.append(f'"{nombre}"')
            if usuario:  parts.append(f'"{usuario}"')
            if email:    parts.append(f'"{email}"')
            if telefono: parts.append(f'"{telefono}"')
            if buscar:   parts.append(f'"{buscar}"')

            if not parts:
                print_error("At least one search term is required.")
                continue

            query  = " AND ".join(parts)
            engine = _ask("Engine (google/duckduckgo/brave) [duckduckgo]").lower() or "duckduckgo"

            if email or telefono:
                print_info("PII detected — switching to deep extraction mode…")
                cli.actions.do_deep_search(query, engine, pages=1, start_page=1, lang="lang_es")
            else:
                cli.actions.do_search(query, engine, pages=1, start_page=1,
                                      lang="lang_es", interactive=False, ia_agent=None)
                if state.ULTIMOS_RESULTADOS:
                    interactive_analysis_menu(state.ULTIMOS_RESULTADOS, ia_agent=None)

        # --- Option 2: Direct Search ---
        elif choice == "2":
            print_section("Direct Search")
            query = _ask("Search query / dork")
            if not query:
                print_error("Query cannot be empty.")
                continue
            engine = _ask("Engine (google/duckduckgo/brave) [duckduckgo]").lower() or "duckduckgo"
            cli.actions.do_search(query, engine, pages=1, start_page=1,
                                  lang="lang_es", interactive=False, ia_agent=None)
            if state.ULTIMOS_RESULTADOS:
                interactive_analysis_menu(state.ULTIMOS_RESULTADOS, ia_agent=None)

        # --- Option 3: AI Dork Generator ---
        elif choice == "3":
            cli.actions.do_generate_dork_ia()

        # --- Option 4: Reverse Image Lookup ---
        elif choice == "4":
            do_reverse_image_search()

        # --- Option 5: Web Technology Scan ---
        elif choice == "5":
            print_section("Web Technology Scan")
            url = _ask("Target URL")
            if url:
                tech_scan(url)
            else:
                print_error("URL cannot be empty.")

        # --- Option 6: Load Saved Case ---
        elif choice == "6":
            ia_agent = select_ia_agent()
            if ia_agent and cargar_caso():
                interactive_analysis_menu(state.ULTIMOS_RESULTADOS, ia_agent)

        # --- Option 7: Configure API Keys ---
        elif choice == "7":
            env_config()
            openai_config()

        # --- Option 8: Exit ---
        elif choice == "8":
            console.print()
            console.print(
                Panel(
                    f"[{THEME['SUCCESS']}]Session closed. Stay curious.[/]",
                    border_style="green",
                    padding=(0, 4),
                )
            )
            break

        else:
            print_warn("Invalid option — choose a number from 1 to 8.")
