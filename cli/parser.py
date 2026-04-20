"""
cli/parser.py — Argument parser and styled help renderer for ScannUs CLI.

Improvements:
  - Uses shared THEME tokens for visual consistency with the TUI
  - Help table rendered inside a Rich Panel per argument group
  - Examples section uses a styled two-column grid
"""

import argparse
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from rich import box

from cli.ui import console, THEME, make_table


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

    # ── Case management ───────────────────────────────────────────────────
    cases = parser.add_argument_group("Case Management")
    cases.add_argument("--load-case", action="store_true",
                       help="Restore session state from a previously saved case.")

    # ── Search parameters ─────────────────────────────────────────────────
    search = parser.add_argument_group("Search Parameters")
    search.add_argument("--engine",     type=str, default="duckduckgo", metavar="ENGINE",
                        help="Search engine: google | duckduckgo | brave  (default: duckduckgo).")
    search.add_argument("-n", "--nombre",   metavar="NAME",
                        help="Target's full legal name.")
    search.add_argument("-u", "--usuario",  metavar="HANDLE",
                        help="Target's username or social handle.")
    search.add_argument("-b", "--buscar",   metavar="TERM",
                        help="Generic keyword or search topic.")
    search.add_argument("-e", "--email",    metavar="EMAIL",
                        help="Target's email address (triggers deep PII mode).")
    search.add_argument("-t", "--telefono", metavar="PHONE",
                        help="Target's phone number (triggers deep PII mode).")
    search.add_argument("--deep",           action="store_true",
                        help="Recursively analyse each result URL for PII.")
    search.add_argument("-rev", "--reverse", metavar="URL",
                        help="Image URL to submit for Yandex reverse image search.")
    search.add_argument("--username-enum", metavar="HANDLE",
                        help="Enumerate accounts for a username via Sherlock/Maigret (400+ sites).")
    search.add_argument("--enum-backend", type=str, default="auto", metavar="ENGINE",
                        help="Username enumeration backend: auto | sherlock | maigret (default: auto).")
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

    # ── Media ─────────────────────────────────────────────────────────────
    media = parser.add_argument_group("Media Processing")
    media.add_argument("--media-scrape", type=str, metavar="URL",
                       help="Scrape and archive all media assets from a remote URL.")

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
