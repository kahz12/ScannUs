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
    print_success, print_error, print_warn, print_info,
    make_table,
)
from core import state
from core.findings import get_hub, KINDS
from core.case_manager import save_case, load_case
from core.config import env_config, openai_config
from core.ai_agent import (IAAgent, GeminiGenerator, OpenAIGenerator,
                            AnthropicGenerator, OllamaGenerator)
from search.reverse_image import do_reverse_image_search
from analysis.tech_scanner import tech_scan
from analysis.web_analyzer import (
    get_text_from_url, summarize_text_with_ia,
    translate_and_analyze_with_ia, extract_entities_and_graph,
)
from analysis.advanced_osint import take_screenshot, check_wayback_machine, get_dynamic_text_from_url
from analysis.domain_osint import (
    domain_recon,
    whois_lookup, dns_records, email_security,
    tls_certificate, http_security_headers,
    subdomains_crtsh, shodan_host, _normalize_target, _resolve_first_ip,
)
from search.smart_search import extract_information
from search.username_enum import username_enum
from search.email_enum import email_enum
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
    terms = state.CURRENT_CASE.get("search_params") if isinstance(state.CURRENT_CASE, dict) else None
    if not terms:
        return "none"
    value = terms.get("value", "")
    if not value or value == "N/A":
        return terms.get("type", "manual")
    return value[:32] + ("…" if len(value) > 32 else "")


def _agent_label(ia_agent) -> str:
    """Return a short display name for the active AI agent, or 'none'.

    Strips the 'Generator' suffix that every LLM backend class appends
    so the footer stays compact (e.g. 'GeminiGenerator' → 'Gemini').
    """
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
            ("Google Gemini",     "ge",     "gemini-2.0-flash · free tier"),
            ("OpenAI GPT-4o",     "op",     "paid · high quality"),
            ("Anthropic Claude",  "claude", "claude-sonnet-4-6 · paid"),
            ("Ollama (local)",    "ollama", "free · runs on your machine"),
            ("Cancel",            "cancel", ""),
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

    if choice == "op":
        if not os.getenv("OPENAI_API_KEY"):
            print_warn("OpenAI API key not configured — launching setup…")
            openai_config()
        print_success("OpenAI selected.")
        return IAAgent(OpenAIGenerator(model_name="gpt-4o"))

    if choice == "claude":
        if not os.getenv("ANTHROPIC_API_KEY"):
            print_error("ANTHROPIC_API_KEY is missing from .env — run `python main.py -c`.")
            return None
        try:
            gen = AnthropicGenerator()
        except RuntimeError as e:
            print_error(str(e))
            return None
        print_success(f"Claude selected ({gen.model_name}).")
        return IAAgent(gen)

    if choice == "ollama":
        try:
            gen = OllamaGenerator()
        except Exception as e:
            print_error(f"Ollama init failed: {e}")
            return None
        if not gen._ping():
            print_error(f"Ollama daemon not reachable at {gen.host}. "
                        f"Start it with `ollama serve` or set OLLAMA_HOST.")
            return None
        print_success(f"Ollama selected ({gen.model_name} @ {gen.host}).")
        return IAAgent(gen)

    return None


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
                    # Pivot fuel: push extracted emails/usernames/IPs/phones into
                    # the findings hub so the user can chain straight into Holehe,
                    # HIBP, or a fresh search without re-typing anything.
                    added = get_hub().ingest_pii(data, source="url-pii")
                    if added:
                        print_info(f"{added} new finding(s) added to the hub.")
                else:
                    print_info("No extractable identifiers found.")

        elif action == "tech":
            tech_scan(url)

        elif action == "file":
            print_info("Attempting direct download…")
            FileDownload().download_file_direct(url, extract_metadata=True)

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
                    added = get_hub().ingest_pii(data, source="url-pii-deep")
                    if added:
                        print_info(f"{added} new finding(s) added to the hub.")
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
        f"[{THEME['PRIMARY']}]next[/] hub  ·  "
        f"[{THEME['WARN']}]save[/]  ·  "
        f"[green]excel[/]  ·  [red]exit[/]"
    )
    console.print(Panel(commands_text, border_style=THEME["BORDER"], padding=(0, 1)))


def interactive_analysis_menu(results: list, ia_agent=None) -> None:
    """
    Interactive results loop with pagination.

    Typed commands:
      n / p / j <N> / all / page   → navigation
      <ID>                         → analyse result by number
      media                        → batch media download
      next                         → open the Findings Hub (pivot onward)
      save · excel · exit          → case/export/quit
    """
    state.LAST_RESULTS = results

    # Pool these results so the Findings Hub (reachable via the "next" command)
    # can pivot any result URL into a download, recon, or further analysis.
    get_hub().ingest_results(results, source="search")

    # Guard: ensure the session dict always has a search_params entry so
    # every downstream reader (e.g. _current_case_label) can safely call .get().
    if not state.CURRENT_CASE["search_params"]:
        state.CURRENT_CASE["search_params"] = {"type": "manual", "value": "N/A"}

    # Assign stable integer IDs (1-based) to each result so users can refer
    # to them by number in the command loop below.
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
        elif choice in ("next", "hub"):
            # Hand off to the Findings Hub. These results are already pooled
            # (ingested on entry), so the hub immediately offers to pivot them.
            findings_hub_menu(ia_agent)
            continue

        elif choice in ("exit", "salir"):
            break

        elif choice in ("save", "guardar"):
            save_case()
            continue

        elif choice == "excel":
            filename = ask("Excel filename", default="results.xlsx")
            if not filename.endswith(".xlsx"):
                filename += ".xlsx"
            ResultsParser(all_results).export_excel(filename)
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
                    "media · next · save · excel · exit"
                )


# ---------------------------------------------------------------------------
# Findings Hub — the sequential pivot spine
# ---------------------------------------------------------------------------
#
# Every producing tool drops its discoveries into the shared pool in
# core.findings. This hub reads that pool and offers the natural next step for
# whatever is present, so chains compose freely:
#
#     dork → search → [result URLs] → analyse → [extracted emails] → Holehe/HIBP
#     recon → [subdomains] → search → [URLs] → download
#     username-enum → [profile URLs] → analyse → download
#
# Each pivot calls the underlying tool directly (NOT the _run_* menu wrappers),
# ingests whatever that tool discovers back into the same pool, and returns to
# this loop — so the chain can continue without ever nesting menus or bouncing
# through the main menu.

# Display labels for the artifact kinds (core.findings.KINDS uses bare codes).
_HUB_KIND_LABEL = {
    "url": "URL", "domain": "Domain", "email": "Email",
    "username": "Username", "ip": "IP", "phone": "Phone",
}


def _kind_options(hub, kind: str) -> list[tuple[str, str]]:
    """Build ``(value, hint)`` pairs for every finding of *kind*, for a picker.

    The hint folds in the originating tool and any human label (e.g. the result
    title or the social site a profile URL came from).
    """
    options = []
    for f in hub.of_kind(kind):
        hint = f.label or ""
        if f.source:
            hint = f"{hint} · {f.source}" if hint else f.source
        options.append((f.value, hint))
    return options


def _pick_value(options: list[tuple[str, str]], prompt: str) -> str | None:
    """Arrow-key picker over ``(value, hint)`` pairs (value shown as the label).

    Returns the chosen value, or None if the list is empty or the user cancels.
    """
    if not options:
        print_warn("Nothing of that kind in the findings hub yet.")
        return None
    choices = [(val, val, hint) for val, hint in options]
    choices.append(("← cancel", "__cancel__", ""))
    chosen = select_menu(prompt, choices, default=options[0][0])
    if chosen in (None, "__cancel__"):
        return None
    return chosen


def _render_findings_overview(hub) -> None:
    """Compact per-kind summary table (kind · count · most recent value)."""
    counts = hub.counts()
    tbl = make_table(
        f"Findings  [{THEME['DIM']}]{len(hub)} total[/]",
        ("Kind",   THEME["PRIMARY"]),
        ("Count",  "white"),
        ("Latest", THEME["DIM"]),
        show_lines=False,
    )
    for kind in KINDS:
        if counts.get(kind):
            latest = hub.of_kind(kind)[-1].value
            latest = latest if len(latest) <= 50 else latest[:47] + "…"
            tbl.add_row(_HUB_KIND_LABEL[kind], str(counts[kind]), latest)
    console.print()
    console.print(tbl)


def _render_findings_full(hub) -> None:
    """Full listing of every finding (kind · value · source)."""
    tbl = make_table(
        f"All Findings  [{THEME['DIM']}]{len(hub)} total[/]",
        ("Kind",   THEME["PRIMARY"]),
        ("Value",  "white"),
        ("Source", THEME["DIM"]),
        show_lines=False,
    )
    for f in hub.all():
        tbl.add_row(_HUB_KIND_LABEL.get(f.kind, f.kind), f.value, f.source or "—")
    console.print()
    console.print(tbl)


def _hub_search_pivot(hub, ia_agent) -> None:
    """Pivot: turn any searchable finding into a SERP query.

    Runs the search non-interactively so its result URLs flow straight back
    into the hub (do_search ingests them); the user then picks "Analyse a URL"
    to act on them. Keeping the search non-interactive avoids nesting the
    results browser inside this loop.
    """
    options = []
    for kind in ("email", "username", "domain", "phone", "url"):
        for f in hub.of_kind(kind):
            options.append((f.value, f"{_HUB_KIND_LABEL[kind]} · {f.source or ''}"))
    value = _pick_value(options, "Pick a finding to search for")
    if not value:
        return
    engine = _select_engine()
    # Quote multi-word values so the engine treats them as a single phrase.
    query = f'"{value}"' if " " in value else value
    cli.actions.do_search(query, engine, pages=1, start_page=1,
                          lang="lang_es", interactive=False, ia_agent=ia_agent)
    print_info("Result URLs added to the hub — use “Analyse a URL” to act on them.")


def _hub_recon_pivot(hub) -> None:
    """Pivot: run full domain recon on a discovered domain (or a result URL's
    host) and fold the subdomains/SANs/IPs/contact-emails it finds back in."""
    domain = _pick_value(hub.candidate_domains(), "Pick a domain to recon")
    if not domain:
        return
    report = domain_recon(domain)
    added = get_hub().ingest_recon(report, source="recon")
    if added:
        print_info(f"{added} new finding(s) added to the hub.")


def _hub_username_pivot(hub) -> None:
    """Pivot: enumerate a discovered username across social sites; pool the
    profile URLs it returns."""
    handle = _pick_value(_kind_options(hub, "username"), "Pick a username to enumerate")
    if not handle:
        return
    backend = select_menu(
        "Enumeration backend", _ENUM_BACKEND_CHOICES, default="auto",
    ) or "auto"
    results = username_enum(handle, backend=backend)
    added = get_hub().ingest_username_enum(results, source="user-enum")
    if added:
        print_info(f"{added} profile URL(s) added to the hub.")


def _hub_email_pivot(hub) -> None:
    """Pivot: enumerate a discovered email via Holehe; pool the service domains
    where it is registered."""
    email = _pick_value(_kind_options(hub, "email"), "Pick an email to enumerate")
    if not email:
        return
    only_used = confirm(
        "Show only services where the email is registered?", default=True,
    )
    results = email_enum(email, only_used=only_used)
    added = get_hub().ingest_email_enum(results, source="email-enum")
    if added:
        print_info(f"{added} service domain(s) added to the hub.")


def _hub_hibp_pivot(hub) -> None:
    """Pivot: breach/leak check against a discovered email (account lookup) or
    domain (free domain lookup)."""
    choices = []
    for f in hub.of_kind("email"):
        choices.append((f"Account · {f.value}", f"account:{f.value}", f.source or ""))
    for dom, src in hub.candidate_domains():
        choices.append((f"Domain · {dom}", f"domain:{dom}", src))
    if not choices:
        print_warn("No emails or domains to check.")
        return
    choices.append(("← cancel", "__cancel__", ""))
    chosen = select_menu(
        "Pick a target for the breach check", choices, default=choices[0][1],
    )
    if chosen in (None, "__cancel__"):
        return
    mode, _, target = chosen.partition(":")
    if mode == "account":
        from analysis.hibp import check_account
        include_pastes = confirm("Also check pastes?", default=True)
        check_account(target, include_pastes=include_pastes)
    else:
        from analysis.hibp import check_domain
        check_domain(target)


def _hub_download_pivot(hub) -> None:
    """Pivot: download from a discovered URL — a direct file grab or a media
    scrape of the page. This is the tail end of the headline search→download
    chain."""
    url = _pick_value(_kind_options(hub, "url"), "Pick a URL to download from")
    if not url:
        return
    mode = select_menu(
        "Download type",
        [
            ("Direct file",                "file",  "single HTTP GET + metadata"),
            ("Media (images/video/audio)", "media", "scrape page media into a zip"),
        ],
        default="file",
    )
    if mode == "file":
        print_info("Attempting direct download…")
        FileDownload().download_file_direct(url, extract_metadata=True)
    elif mode == "media":
        media_type = select_menu("Media type", _MEDIA_CHOICES, default="all") or "all"
        use_selenium = confirm(
            "Use Selenium for JavaScript-rendered pages?", default=False,
        )
        domain = urlparse(url).netloc.replace(".", "_")
        try:
            download_media(url, f"{domain}_{media_type}_media.zip",
                           media_type=media_type, use_selenium=use_selenium)
        except Exception as e:
            print_error(str(e))


def _hub_add_target(hub) -> None:
    """Seed a finding by hand so a chain can start from a value the user already
    has (e.g. paste an email, then immediately enumerate or breach-check it)."""
    kind = select_menu(
        "What kind of target?",
        [
            ("URL",      "url",      "a web page or file link"),
            ("Domain",   "domain",   "example.com"),
            ("Email",    "email",    "person@example.com"),
            ("Username", "username", "a handle"),
            ("IP",       "ip",       "an IPv4/IPv6 address"),
            ("Phone",    "phone",    "a phone number"),
        ],
        default="url",
    )
    if not kind:
        return
    value = ask(f"{_HUB_KIND_LABEL.get(kind, kind)} value")
    if not value:
        print_error("Value cannot be empty.")
        return
    if hub.add(kind, value, source="manual"):
        print_success(f"Added {kind}: {value}")
    else:
        print_warn("Already present (or not a valid value) — nothing added.")


def findings_hub_menu(ia_agent=None) -> None:
    """Findings Hub — the sequential pivot loop.

    Shows every artifact discovered so far (pooled across all tools) and offers
    the next action for whatever is present. The action list is rebuilt each
    iteration from the pool's contents, so options appear and disappear as the
    investigation grows. ``ia_agent`` is threaded into the URL-analysis pivot
    (its AI-dependent actions) and any search launched from here.
    """
    hub = get_hub()
    while True:
        header_bar("Findings Hub", "Pivot any discovery into the next tool", glyph="🧭")
        status_footer([
            ("findings", hub.summary_line(), "info" if not hub.is_empty() else "off"),
            ("agent",    _agent_label(ia_agent), "on" if ia_agent else "off"),
        ])

        if hub.is_empty():
            print_info("No findings yet. Add a target to seed a chain, "
                       "or run a tool from the main menu.")
        else:
            _render_findings_overview(hub)

        kinds = hub.kinds_present()
        has_domains = bool(hub.candidate_domains())

        # Build the next-step list dynamically: only offer a pivot when the pool
        # actually holds an artifact that pivot can consume.
        actions: list[tuple[str, str, str]] = []
        if hub.of_kind("url"):
            actions.append(("Analyse a URL",       "analyse",  "download · PII · media · wayback · tech"))
            actions.append(("Download from a URL", "download", "direct file or page media"))
        if kinds & {"url", "domain", "email", "username", "phone"}:
            actions.append(("Search a finding",    "search",   "feed any artifact into a SERP query"))
        if has_domains:
            actions.append(("Recon a domain",      "recon",    "WHOIS · DNS · TLS · subdomains"))
        if "username" in kinds:
            actions.append(("Enumerate a username","user-enum","Sherlock / Maigret"))
        if "email" in kinds:
            actions.append(("Enumerate an email",  "email-enum","Holehe · ~120 services"))
        if (kinds & {"email"}) or has_domains:
            actions.append(("Breach & leak check", "hibp",     "Have I Been Pwned"))
        actions.append(("Add a target manually",   "add",      "seed a URL/domain/email/username"))
        if not hub.is_empty():
            actions.append(("View all findings",   "view",     f"{len(hub)} total"))
            actions.append(("Clear findings",      "clear",    ""))
        actions.append(("Back to main menu",       "back",     ""))

        choice = select_menu("Next step", actions, default=actions[0][1])

        if choice in (None, "back"):
            break
        elif choice == "analyse":
            url = _pick_value(_kind_options(hub, "url"), "Pick a URL to analyse")
            if url:
                process_selected_url(url, ia_agent)
        elif choice == "download":
            _hub_download_pivot(hub)
        elif choice == "search":
            _hub_search_pivot(hub, ia_agent)
        elif choice == "recon":
            _hub_recon_pivot(hub)
        elif choice == "user-enum":
            _hub_username_pivot(hub)
        elif choice == "email-enum":
            _hub_email_pivot(hub)
        elif choice == "hibp":
            _hub_hibp_pivot(hub)
        elif choice == "add":
            _hub_add_target(hub)
        elif choice == "view":
            _render_findings_full(hub)
        elif choice == "clear":
            if confirm("Clear all findings?", default=False):
                hub.clear()
                print_info("Findings cleared.")


def _offer_hub(ia_agent=None) -> None:
    """After a producing tool finishes, drop into the Findings Hub if anything
    was discovered, so the user can chain onward instead of bouncing back to the
    main menu. A no-op when the pool is empty."""
    if not get_hub().is_empty():
        findings_hub_menu(ia_agent)


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

_MAIN_MENU_CHOICES = [
    ("Guided Search",          "guided",   "Name · Username · Email · Phone"),
    ("Direct Search",          "direct",   "Raw query or Google Dork"),
    ("AI Dork Generator",      "dork",     "LLM-assisted dork creation"),
    ("AI Query Planner",       "planner",  "ReAct-style multi-tool plan"),
    ("Findings Hub",           "hub",      "Pivot discovered URLs/domains/emails onward"),
    ("Reverse Image Lookup",   "reverse",  "TinEye · Bing · Yandex · manual URLs"),
    ("Web Technology Scan",    "tech",     "Tech stack fingerprinting"),
    ("Username Enumeration",   "user-enum","Sherlock · 400+ sites"),
    ("Email Enumeration",      "email-enum","Holehe · ~120 services"),
    ("Domain Recon",           "recon",    "WHOIS · DNS · TLS · headers · subdomains"),
    ("Breach & Leak Check",    "hibp",     "Have I Been Pwned: accounts · domains · passwords"),
    ("Load Saved Case",        "load",     "Resume a previous investigation"),
    ("Configure API Keys",     "config",   "Edit .env credentials"),
    ("Exit",                   "exit",     ""),
]


# The four HIBP menu options. The description column shows in the picker
# so users know at a glance whether they need an API key ("free" = no key needed).
_HIBP_CHOICES = [
    ("Check email",         "email",    "Breaches + pastes containing this address"),
    ("Check domain",        "domain",   "Breaches affecting a domain (free)"),
    ("Breach details",      "breach",   "Full metadata for one named breach"),
    ("Check password",      "password", "Pwned Passwords k-anonymity (free, safe)"),
    ("Back",                "back",     ""),
]


def _run_hibp_menu() -> None:
    """Sub-menu for Have I Been Pwned breach + leak checks.

    Loops until the user picks "Back" or presses Escape, so they can check
    multiple emails, domains, or passwords in one session without returning
    to the main menu each time. Lazy-imports analysis.hibp inside each branch
    so the module (and its ``requests`` dependency) only load when needed.
    """
    while True:
        header_bar("Breach & Leak Check", "Have I Been Pwned", glyph="🔒")
        action = select_menu(
            "Pick a HIBP lookup",
            _HIBP_CHOICES,
            default="email",
        )
        if action in (None, "back"):
            break  # User escaped or picked Back — return to the main menu

        if action == "email":
            # Full account check: breaches + optional pastes.
            # This is the most useful HIBP lookup for person OSINT.
            # Requires HIBP_API_KEY — if it's missing, analysis.hibp will
            # print an error message automatically.
            from analysis.hibp import check_account
            email = ask("Email address")
            if not email:
                print_error("Email cannot be empty.")
                continue
            include_pastes = confirm("Also check pastes?", default=True)
            check_account(email, include_pastes=include_pastes)
            # Pool the address so it can be pivoted into Holehe or a search next.
            get_hub().add_email(email, source="hibp")

        elif action == "domain":
            # Free endpoint — no key needed. Perfect for a quick company recon:
            # "Has example.com ever appeared in a HIBP breach?"
            from analysis.hibp import check_domain
            domain = ask("Domain (e.g. example.com)")
            if not domain:
                print_error("Domain cannot be empty.")
                continue
            check_domain(domain)
            # Pool the domain so it can be reconned or searched next.
            get_hub().add_domain(domain, source="hibp")

        elif action == "breach":
            # Drill into a single breach by its HIBP name (usually the company name).
            # Builds a key:value table then optionally renders the full description
            # in a panel — breach descriptions can be quite long (and colourful).
            from analysis.hibp import hibp_breach
            name = ask("Breach name (e.g. Adobe, LinkedIn)")
            if not name:
                print_error("Breach name cannot be empty.")
                continue
            info = hibp_breach(name)
            if not info:
                # HIBP returned 404 — name doesn't match any known breach.
                print_error(f"No record for '{name}'.")
                continue
            tbl = make_table(
                f"Breach: {info.get('Name')}",
                ("Field", THEME["PRIMARY"]),
                ("Value", "white"),
                show_lines=False,
            )
            tbl.add_row("Date",         str(info.get("BreachDate") or "?"))
            tbl.add_row("Domain",       str(info.get("Domain") or "?"))
            tbl.add_row("Accounts",     f"{int(info.get('PwnCount', 0)):,}")
            tbl.add_row("Verified",     "yes" if info.get("IsVerified") else "no")
            tbl.add_row("Sensitive",    "yes" if info.get("IsSensitive") else "no")
            tbl.add_row("Data classes", ", ".join(info.get("DataClasses") or []))
            console.print(tbl)
            desc = (info.get("Description") or "").strip()
            if desc:
                # HIBP breach descriptions are prose paragraphs explaining what happened.
                # Render in a cyan panel to visually separate narrative from tabular data.
                panel(desc, title="Description", border="cyan")

        elif action == "password":
            # k-anonymity Pwned Passwords check.
            # getpass suppresses terminal echo so the password never appears on screen.
            # Ctrl+C / Ctrl+D is caught gracefully — we just continue the menu loop
            # rather than blowing up with an unhandled exception.
            import getpass
            from analysis.hibp import check_password
            try:
                pw = getpass.getpass("  Password (hidden): ")
            except (KeyboardInterrupt, EOFError):
                # User changed their mind mid-prompt — that's fine, just loop back.
                print_warn("Cancelled.")
                continue
            if not pw:
                print_error("Password cannot be empty.")
                continue
            check_password(pw)

    # Any emails/domains checked above are now pooled — offer to pivot onward.
    _offer_hub()


_RECON_CHOICES = [
    ("Full recon (all tools)",      "full",       "WHOIS+DNS+TLS+headers+subdomains"),
    ("WHOIS",                       "whois",      "registrar · dates · contacts"),
    ("DNS records",                 "dns",        "A · AAAA · MX · NS · TXT · SOA · CAA"),
    ("Email security (SPF/DMARC)",  "email-sec",  "DKIM selector hints included"),
    ("TLS certificate",             "tls",        "subject · SAN · validity · cipher"),
    ("HTTP security headers",       "headers",    "HSTS · CSP · COOP · COEP · CORP"),
    ("Subdomains (crt.sh)",         "subs",       "passive CT-log enumeration"),
    ("Shodan host lookup",          "shodan",     "needs SHODAN_API_KEY"),
    ("Back",                        "back",       ""),
]


def _run_domain_recon() -> None:
    header_bar("Domain Recon", "Pick a primitive or run the full sweep", glyph="🛰")
    target = ask("Target domain or URL")
    if not target:
        print_error("Target cannot be empty.")
        return
    domain, url = _normalize_target(target)
    if not domain:
        print_error("Could not parse a domain from the input.")
        return

    # Seed the target domain so it's pivotable even if the user only runs one probe.
    hub = get_hub()
    hub.add_domain(domain, source="recon-input")

    while True:
        action = select_menu(
            f"Recon tool for {domain}",
            _RECON_CHOICES,
            default="full",
        )
        if action in (None, "back"):
            break
        # Each probe feeds its pivotable artifacts into the hub via ingest_recon,
        # which accepts a partial report dict and harvests only the keys present
        # (subdomains/TLS SANs → domains, A/AAAA → IPs, WHOIS emails → emails).
        if action == "full":
            hub.ingest_recon(domain_recon(domain), source="recon")
        elif action == "whois":
            hub.ingest_recon({"whois": whois_lookup(domain)}, source="recon")
        elif action == "dns":
            hub.ingest_recon({"dns": dns_records(domain)}, source="recon")
        elif action == "email-sec":
            email_security(domain)
        elif action == "tls":
            hub.ingest_recon({"tls": tls_certificate(domain)}, source="recon")
        elif action == "headers":
            http_security_headers(url or f"https://{domain}")
        elif action == "subs":
            hub.ingest_recon({"subdomains": subdomains_crtsh(domain)}, source="recon")
        elif action == "shodan":
            ip = _resolve_first_ip(domain)
            if ip:
                hub.add_ip(ip, source="recon")
                hub.ingest_recon({"shodan": shodan_host(ip)}, source="recon")
            else:
                print_error("Could not resolve target to an IP.")

    _offer_hub()


def _run_guided_search() -> None:
    header_bar("Guided Search", "Compose an AND-query from target attributes")
    full_name   = ask("Full name         (optional)")
    username    = ask("Username / handle (optional)")
    email       = ask("Email address     (optional)")
    phone       = ask("Phone number      (optional)")
    search_term = ask("General term      (optional)")

    # Each provided attribute becomes a quoted AND clause, e.g.
    # "Alice Smith" AND "aliceS" AND "alice@example.com"
    parts = []
    if full_name:    parts.append(f'"{full_name}"')
    if username:     parts.append(f'"{username}"')
    if email:        parts.append(f'"{email}"')
    if phone:        parts.append(f'"{phone}"')
    if search_term:  parts.append(f'"{search_term}"')

    if not parts:
        print_error("At least one search term is required.")
        return

    # Seed the typed attributes as findings so they're pivotable on their own
    # (e.g. run Holehe on the email, or enumerate the username) regardless of
    # what the search itself returns.
    hub = get_hub()
    if username: hub.add_username(username, source="guided")
    if email:    hub.add_email(email, source="guided")
    if phone:    hub.add_phone(phone, source="guided")

    query  = " AND ".join(parts)
    engine = _select_engine()

    if email or phone:
        print_info("PII detected — switching to deep extraction mode…")
        cli.actions.do_deep_search(query, engine, pages=1, start_page=1, lang="lang_es")
        _offer_hub()
    else:
        cli.actions.do_search(query, engine, pages=1, start_page=1,
                              lang="lang_es", interactive=False, ia_agent=None)
        if state.LAST_RESULTS:
            interactive_analysis_menu(state.LAST_RESULTS, ia_agent=None)


def _run_direct_search() -> None:
    header_bar("Direct Search", "Raw query or Google-style Dork")
    query = ask("Search query / dork")
    if not query:
        print_error("Query cannot be empty.")
        return
    engine = _select_engine()
    cli.actions.do_search(query, engine, pages=1, start_page=1,
                          lang="lang_es", interactive=False, ia_agent=None)
    if state.LAST_RESULTS:
        interactive_analysis_menu(state.LAST_RESULTS, ia_agent=None)


def _run_tech_scan() -> None:
    header_bar("Web Technology Scan", "Fingerprint the target's stack")
    url = ask("Target URL")
    if url:
        tech_scan(url)
        # Pool the scanned URL and its host so it can be analysed or reconned next.
        hub = get_hub()
        hub.add_url(url, source="tech-scan")
        hub.add_domain(url, source="tech-scan")
        _offer_hub()
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

    # Seed the queried handle, then pool every profile URL the enumerator finds
    # so the user can pivot straight into analysing/downloading from them.
    get_hub().add_username(handle, source="user-enum-input")
    results = username_enum(handle, backend=backend, timeout=timeout)
    get_hub().ingest_username_enum(results, source="user-enum")
    _offer_hub()


def _run_email_enum() -> None:
    header_bar("Email Enumeration", "Check ~120 services via Holehe")
    email = ask("Email address")
    if not email:
        print_error("Email cannot be empty.")
        return
    only_used = confirm(
        "Show only services where the email is registered?",
        default=True,
    )
    timeout_str = ask("Per-site timeout in seconds", default="10")
    try:
        timeout = max(3, int(timeout_str))
    except ValueError:
        timeout = 10

    # Seed the queried email, then pool the service domains where it is
    # registered so they become recon/search targets.
    get_hub().add_email(email, source="email-enum-input")
    results = email_enum(email, only_used=only_used, timeout=timeout)
    get_hub().ingest_email_enum(results, source="email-enum")
    _offer_hub()


def show_main_menu() -> None:
    """Root navigation menu for ScannUs."""
    while True:
        header_bar("ScannUs", "Advanced OSINT & Search Framework")
        hub = get_hub()
        status_footer([
            ("env",      ".env" if os.path.exists(".env") else "missing",
                         "on" if os.path.exists(".env") else "off"),
            ("case",     _current_case_label(),    "info"),
            ("findings", hub.summary_line(), "info" if not hub.is_empty() else "off"),
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
        elif choice == "planner":
            cli.actions.do_query_planner()
        elif choice == "hub":
            findings_hub_menu()
        elif choice == "reverse":
            header_bar("Reverse Image Lookup", "Yandex visual search")
            do_reverse_image_search()
        elif choice == "tech":
            _run_tech_scan()
        elif choice == "user-enum":
            _run_username_enum()
        elif choice == "email-enum":
            _run_email_enum()
        elif choice == "recon":
            _run_domain_recon()
        elif choice == "hibp":
            _run_hibp_menu()
        elif choice == "load":
            header_bar("Load Case", "Restore a saved investigation")
            ia_agent = select_ia_agent()
            if ia_agent and load_case():
                interactive_analysis_menu(state.LAST_RESULTS, ia_agent)
        elif choice == "config":
            header_bar("API Credentials", "Update .env file")
            env_config()
            openai_config()
