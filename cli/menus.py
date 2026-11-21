"""
cli/menus.py — Root interactive TUI menus and AI provider picker for ScannUs.

The URL/results browser lives in :mod:`cli.results_menu` and the Findings Hub
pivot loop in :mod:`cli.hub_menu`; both are re-exported here so callers can
continue importing the menu surface from ``cli.menus``.

Heavy analysis/scraping/export dependencies are imported lazily inside each
runner so starting the CLI stays fast.
"""

import os

from cli.ui import (
    console, THEME,
    ask, confirm, select_menu,
    header_bar, status_footer, panel,
    print_success, print_error, print_warn, print_info,
    make_table, run_guarded,
)
from cli.results_menu import (
    PAGE_SIZE,
    _MEDIA_CHOICES,
    _URL_ACTION_CHOICES,
    _agent_label,
    _current_case_label,
    _record_evidence,
    _render_results_page,
    _run_wayback_menu,
    _show_evidence,
    interactive_analysis_menu,
    process_selected_url,
)
from cli.hub_menu import (
    _ENUM_BACKEND_CHOICES,
    _offer_hub,
    _phone_footprint_followup,
    findings_hub_menu,
)
from core import state
from core.findings import get_hub
from core.case_manager import delete_case_prompt, load_case
from core.config import env_config, has_env_file, openai_config


# ---------------------------------------------------------------------------
# Common selection helpers
# ---------------------------------------------------------------------------

_ENGINE_CHOICES = [
    ("DuckDuckGo",  "duckduckgo", "privacy-friendly · default"),
    ("Brave",       "brave",      "independent index · API key"),
    ("Tavily",      "tavily",     "free monthly credits · API key"),
    ("Exa",         "exa",        "semantic search · free monthly credit · API key"),
]


def _select_engine(default: str = "duckduckgo") -> str:
    """Arrow-key engine picker with safe fallback."""
    return select_menu(
        "Select search engine",
        _ENGINE_CHOICES,
        default=default,
    ) or default


# ---------------------------------------------------------------------------
# AI agent selection
# ---------------------------------------------------------------------------

def select_ia_agent():
    """Arrow-key picker for the AI provider, returning an initialised IAAgent."""
    from core.ai_agent import (
        IAAgent, GeminiGenerator, OpenAIGenerator,
        AnthropicGenerator, OllamaGenerator,
    )
    header_bar("AI Provider", "Pick the LLM used for summarisation and dorking")

    gemini_model = os.getenv("GEMINI_MODEL") or GeminiGenerator.DEFAULT_MODEL
    openai_model = os.getenv("OPENAI_MODEL") or OpenAIGenerator.DEFAULT_MODEL
    claude_model = os.getenv("ANTHROPIC_MODEL") or AnthropicGenerator.DEFAULT_MODEL
    choice = select_menu(
        "Select AI provider",
        [
            ("Google Gemini",     "ge",     f"{gemini_model} · free tier"),
            ("OpenAI",            "op",     f"{openai_model} · paid"),
            ("Anthropic Claude",  "claude", f"{claude_model} · paid"),
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
        print_success(f"OpenAI selected ({openai_model}).")
        return IAAgent(OpenAIGenerator())

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
# Main menu & tool runners
# ---------------------------------------------------------------------------

_MAIN_MENU_CHOICES = [
    ("Guided Search",          "guided",     "Name · Username · Email · Phone"),
    ("Direct Search",          "direct",     "Raw query or dork"),
    ("AI Dork Generator",      "dork",       "LLM-assisted dork creation"),
    ("AI Query Planner",       "planner",    "ReAct-style multi-tool plan"),
    ("Findings Hub",           "hub",        "Pivot discovered URLs/domains/emails onward"),
    ("Reverse Image Lookup",   "reverse",    "TinEye · Bing · Yandex · manual URLs"),
    ("Web Technology Scan",    "tech",       "Tech stack fingerprinting"),
    ("Username Enumeration",   "user-enum",  "Sherlock · 400+ sites"),
    ("Email Enumeration",      "email-enum", "Holehe · ~120 services"),
    ("Phone Intelligence",     "phone-osint","Carrier · region · line type · footprint"),
    ("Domain Recon",           "recon",      "WHOIS · DNS · TLS · headers · subdomains"),
    ("Breach & Leak Check",    "hibp",       "Have I Been Pwned: accounts · domains · passwords"),
    ("Load Saved Case",        "load",       "Resume a previous investigation"),
    ("Delete Saved Case",      "del-case",   "Remove a saved investigation from SQLite"),
    ("Configure API Keys",     "config",     "Edit .env credentials"),
    ("Exit",                   "exit",       ""),
]

_HIBP_CHOICES = [
    ("Check email",         "email",    "Breaches + pastes containing this address"),
    ("Check domain",        "domain",   "Breaches affecting a domain (free)"),
    ("Breach details",      "breach",   "Full metadata for one named breach"),
    ("Check password",      "password", "Pwned Passwords k-anonymity (free, safe)"),
    ("Back",                "back",     ""),
]


def _run_hibp_menu() -> None:
    """Sub-menu for Have I Been Pwned breach + leak checks."""
    while True:
        header_bar("Breach & Leak Check", "Have I Been Pwned", glyph="🔒")
        action = select_menu("Pick a HIBP lookup", _HIBP_CHOICES, default="email")
        if action in (None, "back"):
            break

        if action == "email":
            from analysis.hibp import check_account
            email = ask("Email address")
            if not email:
                print_error("Email cannot be empty.")
                continue
            include_pastes = confirm("Also check pastes?", default=True)
            check_account(email, include_pastes=include_pastes)
            get_hub().add_email(email, source="hibp")

        elif action == "domain":
            from analysis.hibp import check_domain
            domain = ask("Domain (e.g. example.com)")
            if not domain:
                print_error("Domain cannot be empty.")
                continue
            check_domain(domain)
            get_hub().add_domain(domain, source="hibp")

        elif action == "breach":
            from analysis.hibp import hibp_breach
            name = ask("Breach name (e.g. Adobe, LinkedIn)")
            if not name:
                print_error("Breach name cannot be empty.")
                continue
            info = hibp_breach(name)
            if not info:
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
                panel(desc, title="Description", border="cyan")

        elif action == "password":
            import getpass
            from analysis.hibp import check_password
            try:
                pw = getpass.getpass("  Password (hidden): ")
            except (KeyboardInterrupt, EOFError):
                print_warn("Cancelled.")
                continue
            if not pw:
                print_error("Password cannot be empty.")
                continue
            check_password(pw)

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
    from analysis.domain_osint import (
        domain_recon,
        whois_lookup, dns_records, email_security,
        tls_certificate, http_security_headers,
        subdomains_crtsh, shodan_host, _normalize_target, _resolve_first_ip,
    )
    header_bar("Domain Recon", "Pick a primitive or run the full sweep", glyph="🛰")
    target = ask("Target domain or URL")
    if not target:
        print_error("Target cannot be empty.")
        return
    domain, url = _normalize_target(target)
    if not domain:
        print_error("Could not parse a domain from the input.")
        return

    hub = get_hub()
    hub.add_domain(domain, source="recon-input")

    while True:
        action = select_menu(f"Recon tool for {domain}", _RECON_CHOICES, default="full")
        if action in (None, "back"):
            break
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
    import cli.actions
    header_bar("Guided Search", "Compose an AND-query from target attributes")
    full_name   = ask("Full name         (optional)")
    username    = ask("Username / handle (optional)")
    email       = ask("Email address     (optional)")
    phone       = ask("Phone number      (optional)")
    search_term = ask("General term      (optional)")

    parts = []
    if full_name:    parts.append(f'"{full_name}"')
    if username:     parts.append(f'"{username}"')
    if email:        parts.append(f'"{email}"')
    if phone:        parts.append(f'"{phone}"')
    if search_term:  parts.append(f'"{search_term}"')

    if not parts:
        print_error("At least one search term is required.")
        return

    hub = get_hub()
    if username: hub.add_username(username, source="guided")
    if email:    hub.add_email(email, source="guided")
    if phone:    hub.add_phone(phone, source="guided")

    query  = " AND ".join(parts)
    engine = _select_engine()

    if email or phone:
        print_info("PII detected — switching to deep extraction mode…")
        cli.actions.do_deep_search(query, engine, pages=1, start_page=1)
        _offer_hub()
    else:
        cli.actions.do_search(query, engine, pages=1, start_page=1,
                              interactive=False, ia_agent=None)
        if state.LAST_RESULTS:
            interactive_analysis_menu(state.LAST_RESULTS, ia_agent=None)


def _run_direct_search() -> None:
    import cli.actions
    header_bar("Direct Search", "Raw query or dork")
    query = ask("Search query / dork")
    if not query:
        print_error("Query cannot be empty.")
        return
    engine = _select_engine()
    cli.actions.do_search(query, engine, pages=1, start_page=1,
                          interactive=False, ia_agent=None)
    if state.LAST_RESULTS:
        interactive_analysis_menu(state.LAST_RESULTS, ia_agent=None)


def _run_tech_scan() -> None:
    from analysis.tech_scanner import tech_scan
    header_bar("Web Technology Scan", "Fingerprint the target's stack")
    url = ask("Target URL")
    if url:
        tech_scan(url)
        hub = get_hub()
        hub.add_url(url, source="tech-scan")
        hub.add_domain(url, source="tech-scan")
        _offer_hub()
    else:
        print_error("URL cannot be empty.")


def _run_username_enum() -> None:
    from search.username_enum import username_enum
    header_bar("Username Enumeration", "Check 400+ social networks")
    handle = ask("Username / handle")
    if not handle:
        print_error("Username cannot be empty.")
        return
    backend = select_menu("Enumeration backend", _ENUM_BACKEND_CHOICES, default="auto") or "auto"
    timeout_str = ask("Per-site timeout in seconds", default="20")
    try:
        timeout = max(5, int(timeout_str))
    except ValueError:
        timeout = 20

    get_hub().add_username(handle, source="user-enum-input")
    results = username_enum(handle, backend=backend, timeout=timeout)
    get_hub().ingest_username_enum(results, source="user-enum")
    _offer_hub()


def _run_email_enum() -> None:
    from search.email_enum import email_enum
    header_bar("Email Enumeration", "Check ~120 services via Holehe")
    email = ask("Email address")
    if not email:
        print_error("Email cannot be empty.")
        return
    only_used = confirm("Show only services where the email is registered?", default=True)

    get_hub().add_email(email, source="email-enum-input")
    results = email_enum(email, only_used=only_used)
    get_hub().ingest_email_enum(results, source="email-enum")
    _offer_hub()


def _run_phone_osint() -> None:
    from search.phone_osint import phone_osint
    header_bar("Phone Intelligence", "Carrier · region · line type · OSINT footprint")
    phone = ask("Phone number  (international format preferred, e.g. +14155552671)")
    if not phone:
        print_error("Phone number cannot be empty.")
        return
    region = (ask("Region hint  (ISO-3166, optional, e.g. US)", default="") or "").strip().upper() or None

    get_hub().add_phone(phone, source="phone-osint-input")
    report = phone_osint(phone, region=region)
    if report:
        _phone_footprint_followup(report)
    _offer_hub()


def show_main_menu() -> None:
    """Root navigation menu for ScannUs."""
    while True:
        header_bar("ScannUs", "Advanced OSINT & Search Framework")
        hub = get_hub()
        env_present = has_env_file()
        status_footer([
            ("env",      ".env" if env_present else "missing",
                         "on" if env_present else "off"),
            ("case",     _current_case_label(),    "info"),
            ("findings", hub.summary_line(), "info" if not hub.is_empty() else "off"),
        ])

        choice = select_menu("Main menu", _MAIN_MENU_CHOICES, default="guided")

        if choice in (None, "exit"):
            console.print()
            panel(
                f"[{THEME['SUCCESS']}]Session closed. Stay curious.[/]",
                border="green",
                padding=(0, 4),
            )
            break

        labels = {value: label for label, value, *_ in _MAIN_MENU_CHOICES}
        run_guarded(_run_main_choice, choice, label=labels.get(choice, choice))


def _run_main_choice(choice: str) -> None:
    """Runs the tool picked in the main menu."""
    if choice == "guided":
        _run_guided_search()
    elif choice == "direct":
        _run_direct_search()
    elif choice == "dork":
        import cli.actions
        header_bar("AI Dork Generator", "Turn a natural-language brief into a dork")
        cli.actions.do_generate_dork_ia()
    elif choice == "planner":
        import cli.actions
        cli.actions.do_query_planner()
    elif choice == "hub":
        findings_hub_menu()
    elif choice == "reverse":
        from search.reverse_image import do_reverse_image_search
        header_bar("Reverse Image Lookup", "TinEye · Bing · Yandex · manual URLs")
        if do_reverse_image_search():
            _offer_hub()
    elif choice == "tech":
        _run_tech_scan()
    elif choice == "user-enum":
        _run_username_enum()
    elif choice == "email-enum":
        _run_email_enum()
    elif choice == "phone-osint":
        _run_phone_osint()
    elif choice == "recon":
        _run_domain_recon()
    elif choice == "hibp":
        _run_hibp_menu()
    elif choice == "load":
        header_bar("Load Case", "Restore a saved investigation")
        ia_agent = select_ia_agent()
        if ia_agent and load_case():
            interactive_analysis_menu(state.LAST_RESULTS, ia_agent)
    elif choice == "del-case":
        header_bar("Delete Case", "Remove a saved investigation")
        delete_case_prompt()
    elif choice == "config":
        header_bar("API Credentials", "Update .env file")
        env_config()
        openai_config()


__all__ = [
    "PAGE_SIZE",
    "_ENGINE_CHOICES",
    "_ENUM_BACKEND_CHOICES",
    "_MEDIA_CHOICES",
    "_URL_ACTION_CHOICES",
    "_agent_label",
    "_offer_hub",
    "_record_evidence",
    "_render_results_page",
    "_run_wayback_menu",
    "_show_evidence",
    "findings_hub_menu",
    "get_hub",
    "interactive_analysis_menu",
    "process_selected_url",
    "select_ia_agent",
    "show_main_menu",
]
