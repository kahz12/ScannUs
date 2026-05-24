import os
from rich.panel import Panel
from rich.text import Text
from cli.ui import console, THEME, print_success, print_error, print_warn, print_info, make_table
from search.engines.duckduckgosearch import DuckDuckGoSearch
from search.engines.bravesearch import BraveSearch
from search.engines.googlesearch import GoogleSearch
from core import state
from analysis.web_analyzer import get_text_from_url
from search.smart_search import extract_information


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def get_search_engine(engine: str, pages: int, start_page: int, lang: str, query: str):
    """
    Instantiates the correct search engine and runs the query.
    Returns a list of result dicts or raises on config error.
    """
    engine = engine.lower()
    if engine == 'duckduckgo':
        return DuckDuckGoSearch().search(query, pages=pages)

    if engine == 'brave':
        key = os.getenv("BRAVE_API_KEY")
        if not key:
            raise EnvironmentError("BRAVE_API_KEY not found in .env")
        return BraveSearch(key).search(query, pages=pages)

    # Default → Google
    api_key     = os.getenv("API_KEY_GOOGLE")
    engine_id   = os.getenv("SEARCH_ENGINE_ID")
    if not api_key or not engine_id:
        raise EnvironmentError("API_KEY_GOOGLE or SEARCH_ENGINE_ID not found in .env")
    return GoogleSearch(api_key, engine_id).search(
        query, start_page=start_page, pages=pages, lang=lang
    )


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


# ---------------------------------------------------------------------------
# Public actions
# ---------------------------------------------------------------------------

def do_deep_search(query: str, engine: str, pages: int, start_page: int, lang: str) -> None:
    """
    Intensive search: retrieves SERP results then crawls each URL to extract PII.
    """
    _print_search_header(engine, query, mode="Deep / PII Extraction")

    try:
        resultados = get_search_engine(engine, pages, start_page, lang, query)
    except Exception as e:
        print_error(str(e))
        return

    print_info(f"{len(resultados)} URLs found — beginning data extraction…")
    console.print()

    all_extracted: dict = {}
    for r in resultados:
        url = r.get("link")
        if not url:
            continue
        console.print(f"  [{THEME['DIM']}]🔗[/]  [{THEME['LINK']}]{url}[/]")
        text = get_text_from_url(url)
        if text:
            data = extract_information(text)
            for key, values in data.items():
                if key not in all_extracted:
                    all_extracted[key] = set()
                all_extracted[key].update(values)

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


def do_search(query: str, engine: str, pages: int, start_page: int,
              lang: str, interactive: bool, ia_agent) -> None:
    """
    Standard search: dispatches query to engine and renders results.
    """
    _print_search_header(engine, query)

    try:
        resultados = get_search_engine(engine, pages, start_page, lang, query)
    except Exception as e:
        print_error(str(e))
        return

    print_success(f"{len(resultados)} results retrieved.")
    console.print()

    state.CURRENT_CASE["search_params"] = {"type": "direct", "value": query}
    state.LAST_RESULTS = resultados

    if interactive:
        if not ia_agent:
            print_warn("No AI agent selected — AI-dependent features will prompt on demand.")
        from cli.menus import interactive_analysis_menu
        interactive_analysis_menu(resultados, ia_agent)
    else:
        _print_results_table(resultados)


def do_query_planner(goal: str | None = None) -> None:
    """
    LLM-driven OSINT query planner.

    Flow: select AI provider → prompt for goal → LLM generates a structured
    plan of dork/tool calls → user approves → ReAct-style stepwise execution
    with per-step confirmation → optional re-plan using observations.
    """
    from cli.menus import select_ia_agent
    from cli.ui import ask, confirm, header_bar, panel

    ia_agent = select_ia_agent()
    if not ia_agent:
        return

    if not goal:
        header_bar("AI Query Planner", "ReAct-style multi-tool investigation")
        goal = ask("Describe your investigation goal").strip()
    if not goal:
        print_error("Goal cannot be empty.")
        return

    console.print()
    with console.status(f"[{THEME['PRIMARY']}]Planning investigation…[/]", spinner="dots2"):
        plan = ia_agent.plan(goal)

    if not plan.steps:
        print_error("The planner did not return any usable steps. Try rephrasing the goal.")
        return

    if plan.summary:
        panel(plan.summary, title="Strategy", border="bright_black")

    tbl = make_table(
        f"Generated Plan · {len(plan.steps)} steps",
        ("#",         THEME["DIM"]),
        ("Tool",      THEME["PRIMARY"]),
        ("Arguments", "white"),
        ("Rationale", THEME["DIM"]),
        show_lines=True,
    )
    for i, step in enumerate(plan.steps, 1):
        args_text = ", ".join(f"{k}={v}" for k, v in step.args.items()) or "—"
        tbl.add_row(str(i), step.tool, args_text, step.rationale or "—")
    console.print()
    console.print(tbl)
    console.print()

    if not confirm("Execute this plan now?", default=True):
        return

    confirm_each = confirm("Ask before each step?", default=False)
    observations = ia_agent.execute_plan(plan, interactive=True, confirm_each=confirm_each)

    console.print()
    ok   = sum(1 for o in observations if o["status"] == "ok")
    err  = sum(1 for o in observations if o["status"] == "error")
    skip = sum(1 for o in observations if o["status"] == "skip")
    print_success(f"Plan finished — {ok} ok · {err} errors · {skip} skipped")

    if (err or skip) and confirm(
        "Re-plan with observations to refine the remaining strategy?",
        default=False,
    ):
        console.print()
        with console.status(f"[{THEME['PRIMARY']}]Re-planning…[/]", spinner="dots2"):
            new_plan = ia_agent.replan(goal, observations)
        if new_plan.steps:
            print_info("Revised plan generated. Invoke the planner again to run it.")
            tbl2 = make_table(
                f"Revised Plan · {len(new_plan.steps)} steps",
                ("#",         THEME["DIM"]),
                ("Tool",      THEME["PRIMARY"]),
                ("Arguments", "white"),
                ("Rationale", THEME["DIM"]),
                show_lines=True,
            )
            for i, step in enumerate(new_plan.steps, 1):
                args_text = ", ".join(f"{k}={v}" for k, v in step.args.items()) or "—"
                tbl2.add_row(str(i), step.tool, args_text, step.rationale or "—")
            console.print(tbl2)


def do_generate_dork_ia() -> None:
    """
    NLP-driven Google Dork generation using the configured LLM.
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
            engine = console.input(f"  Engine (google/duckduckgo/brave) [{THEME['DIM']}]duckduckgo[/] [{THEME['INPUT']}]❯[/] ").strip().lower() or "duckduckgo"
            do_search(query=dork, engine=engine, pages=1, start_page=1,
                      lang="lang_es", interactive=True, ia_agent=ia_agent)
    else:
        print_error("Failed to generate a dork. Check your AI configuration.")
