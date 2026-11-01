import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from cli.ui import console, THEME, print_success, print_error, print_warn, print_info, make_table
from core.config import DIR_REPORTS
from search.engines import SEARCH_ENGINES
from search.engines.duckduckgosearch import DuckDuckGoSearch, SearchBlockedError
from search.engines.exasearch import ExaSearch
from search.engines.tavilysearch import TavilySearch
from search.engines.bravesearch import BraveSearch
from core import state
from core.findings import get_hub
from analysis.web_analyzer import get_text_from_url
from search.smart_search import build_evidence, extract_information
from core.logging_setup import get_logger

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Engines that need a key, in the order a blocked DuckDuckGo search tries them.
_API_KEY_VARS = {
    "brave":  "BRAVE_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "exa":    "EXA_API_KEY",
}


def _search_with_api_engine(engine: str, pages: int, start_page: int, query: str):
    """Runs one of the engines that need a key, naming the key when it is missing."""
    key_var = _API_KEY_VARS[engine]
    api_key = os.getenv(key_var)
    if not api_key:
        raise EnvironmentError(f"{key_var} not found in .env")
    client = {"brave": BraveSearch, "tavily": TavilySearch, "exa": ExaSearch}[engine](api_key)
    return client.search(query, pages=pages, start_page=start_page)


def get_search_engine(engine: str, pages: int, start_page: int, query: str):
    """
    Instantiates the correct search engine and runs the query.
    Returns a list of result dicts or raises on bad configuration.

    When DuckDuckGo blocks a search, it moves to the first engine with a
    configured key, so one anti-bot check does not stop an investigation.
    """
    engine = engine.lower()
    _log.info("search: engine=%s query=%r pages=%s start=%s", engine, query, pages, start_page)

    if engine not in SEARCH_ENGINES:
        raise ValueError(f"Unknown search engine '{engine}'. Use: {', '.join(SEARCH_ENGINES)}.")

    if engine == 'duckduckgo':
        try:
            results = DuckDuckGoSearch().search(query, pages=pages, start_page=start_page)
        except SearchBlockedError:
            engine = next((name for name, key_var in _API_KEY_VARS.items()
                           if os.getenv(key_var)), None)
            if not engine:
                raise
            print_warn(f"DuckDuckGo blocked this search — using {engine.capitalize()} instead.")

    if engine != 'duckduckgo':
        results = _search_with_api_engine(engine, pages, start_page, query)

    _log.info("search: engine=%s returned %d result(s)", engine, len(results or []))
    return results


def _print_search_header(engine: str, query: str, mode: str = "Standard") -> None:
    """Renders a formatted header Panel for a search operation."""
    content = Text()
    content.append("  Query   ", style=THEME["DIM"])
    content.append(f"{query}\n", style=THEME["PRIMARY"])
    content.append("  Engine  ", style=THEME["DIM"])
    content.append(f"{engine.capitalize()}\n", style="white")
    content.append("  Mode    ", style=THEME["DIM"])
    content.append(mode, style=THEME["ACCENT"])

    console.print()
    console.print(
        Panel(content, title=f"[{THEME['PRIMARY']}]🔍 Search[/]",
              border_style="bright_black", padding=(0, 2)),
    )
    console.print()


def _print_results_table(resultados: list) -> None:
    """Renders search results as a professionally styled Rich table."""
    tbl = make_table(
        f"Results  [{THEME['ACCENT']}]{len(resultados)} found[/]",
        ("#", THEME["DIM"]),
        ("Title", "bold white"),
        ("Link", THEME["LINK"]),
        ("Description", THEME["DIM"]),
        show_lines=True,
    )
    for i, r in enumerate(resultados, 1):
        tbl.add_row(
            str(i),
            r.get("title", "—"),
            r.get("link",  "—"),
            r.get("description", "—")[:100] + ("…" if len(r.get("description","")) > 100 else ""),
        )
    console.print(tbl)


def _fetch_search_texts(results: list[dict]):
    """Fetch up to four pages at once, bounding buffered text and preserving order."""
    urls = list(dict.fromkeys(r["link"] for r in results if r.get("link")))

    def fetch(url):
        try:
            return get_text_from_url(url)
        except Exception:
            _log.warning("deep search could not fetch %s", url, exc_info=True)
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        for start in range(0, len(urls), 4):
            batch = urls[start:start + 4]
            yield from zip(batch, executor.map(fetch, batch))


# ---------------------------------------------------------------------------
# Public actions
# ---------------------------------------------------------------------------

def do_deep_search(query: str, engine: str, pages: int,
                   start_page: int) -> list[dict] | None:
    """
    Intensive search: retrieves SERP results then crawls each URL to extract PII.
    Returns search results on success (including an empty list), or None on failure.
    """
    _print_search_header(engine, query, mode="Deep / PII Extraction")

    try:
        resultados = get_search_engine(engine, pages, start_page, query)
    except Exception as e:
        print_error(str(e))
        return

    print_info(f"{len(resultados)} URLs found — beginning data extraction…")
    console.print()

    all_extracted: dict = {}
    evidence: list[dict] = []
    for url, text in _fetch_search_texts(resultados):
        console.print(f"  [{THEME['DIM']}]🔗[/]  [{THEME['LINK']}]{url}[/]")
        if text:
            records = build_evidence(extract_information(text), text, url, "deep-search")
            evidence.extend(records)
            for record in records:
                all_extracted.setdefault(record["category"], set()).add(record["value"])

    console.print()
    console.rule(f"[{THEME['ACCENT']}]Deep Search Results[/]")
    console.print()

    if all_extracted:
        tbl = make_table(
            "Extracted Intelligence",
            ("Category", THEME["PRIMARY"]),
            ("Values", "white"),
            show_lines=True,
        )
        for key, values in all_extracted.items():
            tbl.add_row(key.replace("_", " ").capitalize(), "\n".join(sorted(values)))
        console.print(tbl)
    else:
        print_warn("No PII or sensitive identifiers extracted from the reviewed links.")

    state.CURRENT_CASE["search_params"] = {"type": "deep", "value": query}
    state.LAST_RESULTS = resultados
    state.add_results(resultados)
    state.add_evidence(evidence)

    # Feed the findings hub so the deep-search yield is pivotable: the crawled
    # result URLs become "url" findings, and every PII identifier we extracted
    # (emails, usernames, IPs, phones) becomes its own typed finding. This is
    # what lets a deep search chain straight into Holehe/HIBP or a fresh search.
    hub = get_hub()
    hub.ingest_results(resultados, source="deep-search")
    hub.ingest_evidence(evidence)
    return resultados


def do_search(query: str, engine: str, pages: int, start_page: int,
              interactive: bool, ia_agent) -> list[dict] | None:
    """
    Standard search: dispatches query to engine and renders results.
    Returns search results on success (including an empty list), or None on failure.
    """
    _print_search_header(engine, query)

    try:
        resultados = get_search_engine(engine, pages, start_page, query)
    except Exception as e:
        print_error(str(e))
        return

    print_success(f"{len(resultados)} results retrieved.")
    console.print()

    state.CURRENT_CASE["search_params"] = {"type": "direct", "value": query}
    state.LAST_RESULTS = resultados
    state.add_results(resultados)

    # Pool the result URLs into the findings hub so they can be pivoted into
    # downloads, PII extraction, recon, etc. — even when this search was run
    # non-interactively (e.g. as a hub pivot itself).
    get_hub().ingest_results(resultados, source="search")

    if interactive:
        if not ia_agent:
            print_warn("No AI agent selected — AI-dependent features will prompt on demand.")
        from cli.menus import interactive_analysis_menu
        interactive_analysis_menu(resultados, ia_agent)
    else:
        _print_results_table(resultados)
    return resultados


def _save_report(report: str) -> str:
    """Writes an investigation report to the reports folder and returns its path."""
    os.makedirs(DIR_REPORTS, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(DIR_REPORTS, f"investigation_{stamp}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    return path


def do_query_planner(goal: str | None = None) -> dict | None:
    """
    LLM-driven OSINT investigation.

    Flow: select AI provider → prompt for goal → the model picks one tool at a
    time, seeing every earlier result → final report, shown on screen, saved to
    the reports folder and kept in the active case.

    Text from websites reaches the model and could try to steer it, so each
    step asks for confirmation unless the user opts out.

    Returns:
        The investigation dict, or None if it could not start.
    """
    from cli.menus import select_ia_agent
    from cli.ui import ask, confirm, header_bar, panel

    ia_agent = select_ia_agent()
    if not ia_agent:
        return None

    if not goal:
        header_bar("AI Query Planner", "Step-by-step multi-tool investigation")
        goal = ask("Describe your investigation goal").strip()
    if not goal:
        print_error("Goal cannot be empty.")
        return None

    ask_each_step = confirm("Ask before each step?", default=True)
    approve_step = (lambda step: confirm("Run this step?", default=True)) if ask_each_step else None
    investigation = ia_agent.investigate(goal, confirm_step=approve_step)

    state.CURRENT_CASE["search_params"] = {"type": "plan", "value": goal}
    state.CURRENT_CASE["investigation"] = investigation

    steps = investigation["steps"]
    ok   = sum(1 for s in steps if s["status"] == "ok")
    err  = sum(1 for s in steps if s["status"] == "error")
    skip = sum(1 for s in steps if s["status"] == "skip")

    console.print()
    panel(Markdown(investigation["report"]), title="Investigation Report", border="green")
    print_info(f"{ok} ok · {err} failed · {skip} skipped — "
               f"stopped because {investigation['stopped_because']}.")
    print_success(f"Report saved → {_save_report(investigation['report'])}")
    return investigation


def do_generate_dork_ia() -> None:
    """
    NLP-driven dork generation using the configured LLM.
    """
    from cli.menus import select_ia_agent
    ia_agent = select_ia_agent()
    if not ia_agent:
        return

    description = console.input(f"\n  [{THEME['DIM']}]Describe what you're looking for:[/] [{THEME['INPUT']}]❯[/] ").strip()
    if not description:
        print_error("Description cannot be empty.")
        return

    console.print()
    with console.status(f"[{THEME['PRIMARY']}]Generating dork…[/]", spinner="dots2"):
        dork = ia_agent.generate_gdork(description)

    if dork:
        console.print(
            Panel(
                f"[{THEME['PRIMARY']}]{dork.strip()}[/]",
                title=f"[{THEME['SUCCESS']}]✔ Dork Generated[/]",
                border_style="green",
                padding=(1, 2),
            )
        )
        ans = console.input(f"\n  Run a search with this dork? (y/n) [{THEME['DIM']}]n[/] [{THEME['INPUT']}]❯[/] ").strip().lower()
        if ans in ("y", "s"):
            engine = console.input(f"  Engine ({'/'.join(SEARCH_ENGINES)}) [{THEME['DIM']}]duckduckgo[/] [{THEME['INPUT']}]❯[/] ").strip().lower() or "duckduckgo"
            do_search(query=dork, engine=engine, pages=1, start_page=1,
                      interactive=True, ia_agent=ia_agent)
    else:
        print_error("Failed to generate a dork. Check your AI configuration.")
