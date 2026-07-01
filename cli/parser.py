"""
cli/parser.py — Argument parser and styled help renderer for ScannUs CLI.

show_custom_help() renders each argparse group as its own Rich Panel (using the
shared THEME tokens for consistency with the TUI) and lists usage examples in a
two-column grid.
"""

import argparse
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns

from cli.ui import console, THEME


# ---------------------------------------------------------------------------
# Custom help renderer
# ---------------------------------------------------------------------------

def show_custom_help(parser: argparse.ArgumentParser) -> None:
    """
    Renders a structured, theme-consistent help screen using Rich.

    Each argparse group becomes its own Panel with a table of options.
    Common usage examples are shown in a two-column grid at the bottom.
    """
    console.print()
    console.print(
        Panel(
            f"[{THEME['DIM']}]Advanced OSINT search and analysis framework[/]",
            title=f"[{THEME['PRIMARY']}]⬡  ScannUs — Help[/]",
            subtitle=f"[{THEME['DIM']}]Use -i to enter interactive TUI mode[/]",
            border_style="bright_black",
            padding=(0, 2),
        )
    )
    console.print()

    # One styled panel per argument group
    for group in parser._action_groups:
        actions = [a for a in group._group_actions if a.option_strings]
        if not actions:
            continue

        tbl = Table(box=None, show_header=True, header_style=THEME["DIM"],
                    padding=(0, 1), border_style="bright_black")
        tbl.add_column("Flag",        style=THEME["PRIMARY"], no_wrap=True, min_width=22)
        tbl.add_column("Description", style="white")
        tbl.add_column("Value",       style=THEME["ACCENT"], no_wrap=True)

        for action in actions:
            opts     = ", ".join(action.option_strings)
            metavar  = action.metavar or ("FLAG" if action.nargs == 0 else "VALUE")
            tbl.add_row(opts, action.help or "", metavar)

        console.print(
            Panel(
                tbl,
                title=f"[{THEME['ACCENT']}]{group.title}[/]",
                border_style="bright_black",
                padding=(0, 1),
            )
        )

    # Usage examples in a two-column layout
    console.print()
    console.rule(f"[{THEME['PRIMARY']}]Usage Examples[/]")
    console.print()

    examples = [
        ("Basic search query",
         'python main.py -q "site:.gov filetype:pdf"'),
        ("Multi-engine with pagination",
         'python main.py -q "OSINT tools" --engine brave --pages 2'),
        ("AI Dork generation",
         'python main.py -gd "Find Excel price lists of tech companies"'),
        ("Guided multi-parameter search",
         'python main.py -n "John Doe" -u "jdoe88" --engine google'),
        ("Media scraper pipeline",
         'python main.py --media-scrape "https://example.com/gallery"'),
        ("Interactive TUI mode",
         'python main.py -i'),
        ("Deep extraction + Excel export",
         'python main.py -q "target@corp.com" --deep --excel results.xlsx'),
        ("Load saved case",
         'python main.py --load-case'),
        ("Domain recon (WHOIS+DNS+TLS+headers+subs)",
         'python main.py --recon example.com'),
        ("Breach lookup for an email",
         'python main.py --hibp-account target@example.com'),
        ("Pwned-password check (interactive)",
         'python main.py --hibp-password'),
    ]

    panels = []
    for title, cmd in examples:
        panels.append(
            Panel(
                f"[{THEME['LINK']}]{cmd}[/]",
                title=f"[{THEME['DIM']}]{title}[/]",
                border_style="bright_black",
                padding=(0, 1),
            )
        )

    # Render in a two-column Columns layout
    console.print(Columns(panels, equal=True, expand=True))
    console.print()


# ---------------------------------------------------------------------------
# Parser factory
# ---------------------------------------------------------------------------

def get_parser() -> argparse.ArgumentParser:
    """
    Builds and returns the configured ArgumentParser for ScannUs CLI.
    Arguments are grouped into logical sections for clarity in the help screen.
    """
    parser = argparse.ArgumentParser(
        description="ScannUs: Advanced OSINT Search Orchestrator.",
        add_help=False,  # Suppress default help — we use show_custom_help()
    )

    # ── Main ──────────────────────────────────────────────────────────────
    general = parser.add_argument_group("Main Options")
    general.add_argument("-h", "--help",        action="store_true",
                         help="Display this help screen.")
    general.add_argument("-q", "--query",       type=str,
                         help="Primary search string or Google Dork.")
    general.add_argument("-c", "--configure",   action="store_true",
                         help="Launch the .env API credential setup wizard.")
    general.add_argument("-i", "--interactive", action="store_true",
                         help="Enter the full interactive TUI investigation mode.")
    general.add_argument("--debug",             action="store_true",
                         help="Verbose debug logging to stderr + outputs/logs/scannus.log.")

    # ── Case management ───────────────────────────────────────────────────
    cases = parser.add_argument_group("Case Management")
    cases.add_argument("--load-case", action="store_true",
                       help="Restore session state from a previously saved case.")

    # ── Search parameters ─────────────────────────────────────────────────
    search = parser.add_argument_group("Search Parameters")
    search.add_argument("--engine",     type=str, default="duckduckgo", metavar="ENGINE",
                        help="Search engine: google | duckduckgo | brave  (default: duckduckgo).")
    search.add_argument("-n", "--name",     metavar="NAME",
                        help="Target's full legal name.")
    search.add_argument("-u", "--username", metavar="HANDLE",
                        help="Target's username or social handle.")
    search.add_argument("-b", "--search",   metavar="TERM",
                        help="Generic keyword or search topic.")
    search.add_argument("-e", "--email",    metavar="EMAIL",
                        help="Target's email address (triggers deep PII mode).")
    search.add_argument("-t", "--phone",    metavar="PHONE",
                        help="Target's phone number (triggers deep PII mode).")
    search.add_argument("--deep",           action="store_true",
                        help="Recursively analyse each result URL for PII.")
    search.add_argument("-rev", "--reverse", metavar="URL",
                        help="Multi-engine reverse image search "
                             "(TinEye → Bing → Yandex → manual URLs).")
    search.add_argument("--username-enum", metavar="HANDLE",
                        help="Enumerate accounts for a username via Sherlock/Maigret (400+ sites).")
    search.add_argument("--enum-backend", type=str, default="auto", metavar="ENGINE",
                        help="Username enumeration backend: auto | sherlock | maigret (default: auto).")
    search.add_argument("--email-enum", metavar="EMAIL",
                        help="Enumerate service registrations for an email via Holehe (~120 sites).")
    search.add_argument("--email-enum-all", action="store_true",
                        help="With --email-enum, include services where the email is NOT registered.")
    search.add_argument("--phone-osint", metavar="PHONE",
                        help="Number intelligence via libphonenumber: carrier, region, "
                             "line type, time zones + OSINT footprint (offline, keyless).")
    search.add_argument("--start-page",    type=int, default=1, metavar="N",
                        help="Starting SERP page index (default: 1).")
    search.add_argument("--pages",         type=int, default=1, metavar="N",
                        help="Number of result pages to retrieve (default: 1).")
    search.add_argument("--lang",          type=str, default="lang_es", metavar="CODE",
                        help="Language restrict code (default: lang_es).")

    # ── AI / NLP ──────────────────────────────────────────────────────────
    ia = parser.add_argument_group("AI & NLP Options")
    ia.add_argument("-gd", "--google-dorks", type=str, metavar='"DESCRIPTION"',
                    help="Generate a Google Dork from a natural-language description via LLM.")
    ia.add_argument("-p", "--plan", type=str, metavar='"GOAL"',
                    help="LLM-based OSINT planner: generate + execute a multi-step investigation.")

    # ── Media ─────────────────────────────────────────────────────────────
    media = parser.add_argument_group("Media Processing")
    media.add_argument("--media-scrape", type=str, metavar="URL",
                       help="Scrape and archive all media assets from a remote URL.")

    # ── Domain / Network OSINT ────────────────────────────────────────────
    domain = parser.add_argument_group("Domain & Network OSINT")
    domain.add_argument("--recon", type=str, metavar="DOMAIN|URL",
                        help="Full domain recon: WHOIS + DNS + TLS + headers + "
                             "subdomains (crt.sh) + optional Shodan.")

    # ── Breach & leak checks (HIBP) ───────────────────────────────────────
    # Four flags for Have I Been Pwned integration.
    # Two require a paid HIBP_API_KEY (account, pastes);
    # two are free (domain, breach metadata).
    # The password check uses k-anonymity so the plaintext is never sent anywhere
    # — which is why it's interactive (getpass) rather than a CLI argument;
    # you *really* don't want your password in shell history or process listings.
    hibp = parser.add_argument_group("Breach & Leak Checks (HIBP)")
    hibp.add_argument("--hibp-account", type=str, metavar="EMAIL",
                      help="List every Have I Been Pwned breach (and paste) "
                           "an email address appears in. Requires HIBP_API_KEY.")
    hibp.add_argument("--hibp-domain", type=str, metavar="DOMAIN",
                      help="List breaches affecting a domain (free endpoint).")
    hibp.add_argument("--hibp-breach", type=str, metavar="NAME",
                      help="Show detailed metadata for a single named breach.")
    hibp.add_argument("--hibp-password", action="store_true",
                      help="Interactively prompt for a password and check it "
                           "against Pwned Passwords via SHA-1 k-anonymity. "
                           "The plaintext never leaves the process.")

    # ── Cache management ──────────────────────────────────────────────────
    cache = parser.add_argument_group("Cache Management")
    cache.add_argument("--cache-stats", action="store_true",
                       help="Print persistent SQLite cache statistics and exit.")
    cache.add_argument("--cache-clear", type=str, nargs="?", const="__ALL__",
                       metavar="NAMESPACE",
                       help="Clear the persistent cache. Without an argument "
                            "wipes everything; with one (e.g. 'search', 'whois', "
                            "'dns', 'http_text', 'wayback') wipes just that "
                            "namespace.")

    # ── Export ────────────────────────────────────────────────────────────
    export = parser.add_argument_group("Export Options")
    export.add_argument("--json",     type=str, metavar="FILE.json",
                        help="Serialise results to a JSON file.")
    export.add_argument("--html",     type=str, metavar="FILE.html",
                        help="Generate a styled HTML report.")
    export.add_argument("--csv",      type=str, metavar="FILE.csv",
                        help="Export results to a flat CSV file.")
    export.add_argument("--excel",    type=str, metavar="FILE.xlsx",
                        help="Export results to a styled Excel workbook.")
    export.add_argument("--download", type=str, metavar="TYPES",
                        help="Batch-download file types from results (e.g. 'pdf,docx' or 'all').")
    export.add_argument("--metadata", action="store_true",
                        help="Extract metadata from downloaded files.")

    return parser
