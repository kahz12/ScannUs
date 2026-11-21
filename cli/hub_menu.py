"""
cli/hub_menu.py — Findings Hub sequential pivot TUI.

Reads the session-wide :class:`core.findings.FindingsHub` pool and offers the
natural next OSINT pivot for every discovered artifact type. Heavy tool modules
are imported lazily inside each pivot handler.
"""

from urllib.parse import urlparse

from cli.ui import (
    console, THEME,
    ask, confirm, select_menu,
    header_bar, status_footer,
    print_success, print_error, print_warn, print_info,
    make_table, run_guarded,
)
from core.findings import KINDS
from cli.results_menu import _MEDIA_CHOICES, _agent_label, process_selected_url


_HUB_KIND_LABEL = {
    "url": "URL", "domain": "Domain", "email": "Email",
    "username": "Username", "ip": "IP", "phone": "Phone",
}

_ENUM_BACKEND_CHOICES = [
    ("Auto-detect", "auto",     "prefer Sherlock if available"),
    ("Sherlock",    "sherlock", "pure-Python · works on Termux"),
    ("Maigret",     "maigret",  "3000+ sites · Linux/macOS only"),
]


def _kind_options(hub, kind: str) -> list[tuple[str, str]]:
    """Build ``(value, hint)`` pairs for every finding of *kind*, for a picker."""
    options = []
    for f in hub.of_kind(kind):
        hint = f.label or ""
        if f.source:
            hint = f"{hint} · {f.source}" if hint else f.source
        options.append((f.value, hint))
    return options


def _pick_value(options: list[tuple[str, str]], prompt: str) -> str | None:
    """Arrow-key picker over ``(value, hint)`` pairs."""
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
    """Pivot: turn any searchable finding into a SERP query."""
    from cli import actions as _actions
    from cli import menus as _menus
    options = []
    for kind in ("email", "username", "domain", "phone", "url"):
        for f in hub.of_kind(kind):
            options.append((f.value, f"{_HUB_KIND_LABEL[kind]} · {f.source or ''}"))
    value = _pick_value(options, "Pick a finding to search for")
    if not value:
        return
    engine = _menus._select_engine()
    query = f'"{value}"' if " " in value else value
    _actions.do_search(query, engine, pages=1, start_page=1,
                       interactive=False, ia_agent=ia_agent)
    print_info("Result URLs added to the hub — use “Analyse a URL” to act on them.")


def _hub_recon_pivot(hub) -> None:
    """Pivot: run full domain recon on a discovered domain."""
    from analysis.domain_osint import domain_recon
    domain = _pick_value(hub.candidate_domains(), "Pick a domain to recon")
    if not domain:
        return
    report = domain_recon(domain)
    added = hub.ingest_recon(report, source="recon")
    if added:
        print_info(f"{added} new finding(s) added to the hub.")


def _hub_username_pivot(hub) -> None:
    """Pivot: enumerate a discovered username across social sites."""
    from search.username_enum import username_enum
    handle = _pick_value(_kind_options(hub, "username"), "Pick a username to enumerate")
    if not handle:
        return
    backend = select_menu("Enumeration backend", _ENUM_BACKEND_CHOICES, default="auto") or "auto"
    results = username_enum(handle, backend=backend)
    added = hub.ingest_username_enum(results, source="user-enum")
    if added:
        print_info(f"{added} profile URL(s) added to the hub.")


def _hub_email_pivot(hub) -> None:
    """Pivot: enumerate a discovered email via Holehe."""
    from search.email_enum import email_enum
    email = _pick_value(_kind_options(hub, "email"), "Pick an email to enumerate")
    if not email:
        return
    only_used = confirm("Show only services where the email is registered?", default=True)
    results = email_enum(email, only_used=only_used)
    added = hub.ingest_email_enum(results, source="email-enum")
    if added:
        print_info(f"{added} service domain(s) added to the hub.")


def _phone_footprint_followup(report: dict, ia_agent=None) -> None:
    """Offer the generated footprint pivots from a phone report."""
    from cli import actions as _actions
    from cli import menus as _menus
    fps = report.get("footprint") or []
    if not fps:
        return
    while True:
        choices = [
            (fp["label"], str(i), "search dork" if fp["kind"] == "search" else "lookup link")
            for i, fp in enumerate(fps)
        ]
        choices.append(("Done", "__done__", ""))
        pick = select_menu("Run a footprint pivot?", choices, default="__done__")
        if pick in (None, "__done__"):
            return
        fp = fps[int(pick)]
        if fp["kind"] == "search":
            engine = _menus._select_engine()
            _actions.do_search(fp["value"], engine, pages=1, start_page=1,
                               interactive=False, ia_agent=ia_agent)
            print_info("Result URLs added to the hub — use “Analyse a URL” to act on them.")
        else:
            _menus.get_hub().add_url(fp["value"], source="phone-footprint", label=fp["label"])
            print_info(f"{fp['label']}: {fp['value']}  (added to hub)")


def _hub_phone_pivot(hub) -> None:
    """Pivot: run offline number intelligence on a discovered phone."""
    from search.phone_osint import phone_osint
    phone = _pick_value(_kind_options(hub, "phone"), "Pick a phone to investigate")
    if not phone:
        return
    report = phone_osint(phone)
    if report:
        _phone_footprint_followup(report)


def _hub_hibp_pivot(hub) -> None:
    """Pivot: breach/leak check against a discovered email or domain."""
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
    """Pivot: download a direct file or scrape page media from a discovered URL."""
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
        from utils.file_download import FileDownload
        print_info("Attempting direct download…")
        FileDownload().download_file_direct(url, extract_metadata=True)
    elif mode == "media":
        from utils.media_downloader import download_media
        media_type = select_menu("Media type", _MEDIA_CHOICES, default="all") or "all"
        use_selenium = confirm("Use Selenium for JavaScript-rendered pages?", default=False)
        domain = urlparse(url).netloc.replace(".", "_")
        try:
            download_media(url, f"{domain}_{media_type}_media.zip",
                           media_type=media_type, use_selenium=use_selenium)
        except Exception as e:
            print_error(str(e))


def _hub_add_target(hub) -> None:
    """Seed a finding by hand so a chain can start from any value."""
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
    """Findings Hub — the sequential pivot loop."""
    from cli import menus as _menus
    hub = _menus.get_hub()
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

        actions: list[tuple[str, str, str]] = []
        if hub.of_kind("url"):
            actions.append(("Analyse a URL",        "analyse",     "download · PII · media · wayback · tech"))
            actions.append(("Download from a URL",  "download",    "direct file or page media"))
        if kinds & {"url", "domain", "email", "username", "phone"}:
            actions.append(("Search a finding",     "search",      "feed any artifact into a SERP query"))
        if has_domains:
            actions.append(("Recon a domain",       "recon",       "WHOIS · DNS · TLS · subdomains"))
        if "username" in kinds:
            actions.append(("Enumerate a username", "user-enum",   "Sherlock / Maigret"))
        if "email" in kinds:
            actions.append(("Enumerate an email",   "email-enum",  "Holehe · ~120 services"))
        if "phone" in kinds:
            actions.append(("Phone intelligence",   "phone-osint", "validity · carrier · region · footprint"))
        if (kinds & {"email"}) or has_domains:
            actions.append(("Breach & leak check",  "hibp",        "Have I Been Pwned"))
        actions.append(("Add a target manually",    "add",         "seed a URL/domain/email/username"))
        if not hub.is_empty():
            actions.append(("View all findings",    "view",        f"{len(hub)} total"))
            actions.append(("Clear findings",       "clear",       ""))
        actions.append(("Back to main menu",        "back",        ""))

        choice = select_menu("Next step", actions, default=actions[0][1])

        if choice in (None, "back"):
            break
        labels = {value: label for label, value, _ in actions}
        run_guarded(_run_hub_choice, choice, hub, ia_agent, label=labels.get(choice, choice))


def _run_hub_choice(choice: str, hub, ia_agent) -> None:
    """Runs the pivot picked in the Findings Hub."""
    if choice == "analyse":
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
    elif choice == "phone-osint":
        _hub_phone_pivot(hub)
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
    """After a producing tool finishes, drop into the Findings Hub if anything was discovered."""
    from cli import menus as _menus
    if not _menus.get_hub().is_empty():
        findings_hub_menu(ia_agent)
