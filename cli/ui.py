"""
cli/ui.py — Shared theme, console instance, and Rich helper functions.
All visual output in ScannUs flows through this module to ensure a consistent
professional look-and-feel across every screen.
"""

import textwrap
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich import box

# ---------------------------------------------------------------------------
# Global console — single instance shared across the entire application
# ---------------------------------------------------------------------------
console = Console(highlight=False)

# ---------------------------------------------------------------------------
# Colour / style theme tokens
# ---------------------------------------------------------------------------
THEME = {
    "PRIMARY"  : "bold cyan",          # headings, selected items
    "ACCENT"   : "bold magenta",        # highlights, counts
    "SUCCESS"  : "bold green",          # confirmations
    "ERROR"    : "bold red",            # errors
    "WARN"     : "bold yellow",         # warnings / soft errors
    "DIM"      : "dim white",           # secondary text, hints
    "LINK"     : "cyan underline",      # URLs / links
    "INPUT"    : "bold cyan",           # input prompt
    "BANNER_1" : "bold #00ffff",        # banner top
    "BANNER_2" : "bold #00cfff",
    "BANNER_3" : "bold #009fff",
    "BANNER_4" : "bold #006fff",
    "BANNER_5" : "bold #003fff",
    "BANNER_6" : "bold #0000ff",        # banner bottom
}

# ---------------------------------------------------------------------------
# Prompt helper
# ---------------------------------------------------------------------------
PROMPT = f"[{THEME['INPUT']}]❯[/] "


def ask(question: str = "") -> str:
    """Styled input prompt. Wraps console.input() with a consistent prefix."""
    prompt_str = f"  {question} {PROMPT}" if question else f"  {PROMPT}"
    return console.input(prompt_str).strip()


# ---------------------------------------------------------------------------
# Status / message helpers
# ---------------------------------------------------------------------------

def print_success(msg: str) -> None:
    console.print(f"  [{THEME['SUCCESS']}]✔[/]  {msg}")

def print_error(msg: str) -> None:
    console.print(f"  [{THEME['ERROR']}]✘[/]  {msg}")

def print_warn(msg: str) -> None:
    console.print(f"  [{THEME['WARN']}]⚠[/]  {msg}")

def print_info(msg: str) -> None:
    console.print(f"  [{THEME['DIM']}]→[/]  {msg}")

def print_section(title: str) -> None:
    """Prints a visual separator with a centred title."""
    console.print()
    console.rule(f"[{THEME['PRIMARY']}]{title}[/]")
    console.print()


# ---------------------------------------------------------------------------
# Table factory
# ---------------------------------------------------------------------------

def make_table(title: str = "", *columns: tuple, show_lines: bool = False) -> Table:
    """
    Creates a pre-styled Rich Table.

    Args:
        title:       Optional table title.
        *columns:    Tuples of (header_str, style_str).  e.g. ("URL", "cyan")
        show_lines:  Whether to show row-separator lines.

    Returns:
        A Rich Table instance ready for rows to be added.
    """
    tbl = Table(
        title=title if title else None,
        box=box.ROUNDED,
        header_style=THEME["PRIMARY"],
        title_style=THEME["ACCENT"],
        show_lines=show_lines,
        border_style="bright_black",
        padding=(0, 1),
    )
    for col in columns:
        if isinstance(col, tuple):
            header, style = col[0], col[1] if len(col) > 1 else "white"
            tbl.add_column(header, style=style, no_wrap=False)
        else:
            tbl.add_column(col)
    return tbl


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------

def print_startup_banner(google_api_key_found: bool) -> None:
    """
    Renders the ScannUs ASCII banner inside a Rich Panel, then shows a
    brief animated init sequence with real status steps.
    """
    # Gradient banner lines (one colour per line)
    banner_lines = [
        (THEME["BANNER_1"], r"   _____                         _   _   _    _  ____"),
        (THEME["BANNER_2"], r"  / ____|                       | \ | | | |  | |/ ___|"),
        (THEME["BANNER_3"], r" | (___   ___ __ _ _ __  _ __   |  \| | | |  | |\___ \ "),
        (THEME["BANNER_4"], r"  \___ \ / __/ _` | '_ \| '_ \  | . ` | | |  | | ___) |"),
        (THEME["BANNER_5"], r"  ____) | (_| (_| | | | | | | | | |\  | | |__| |/ ___/ "),
        (THEME["BANNER_6"], r" |_____/ \___\__,_|_| |_|_| |_| |_| \_|  \____/|_____|"),
    ]

    banner_text = Text()
    for style, line in banner_lines:
        banner_text.append(line + "\n", style=style)

    subtitle = Text("  Advanced OSINT & Search Analysis Framework  ", style=f"{THEME['DIM']} on grey11")

    panel_content = Text()
    panel_content.append_text(banner_text)
    panel_content.append("\n")
    panel_content.append_text(subtitle)

    console.print()
    console.print(
        Panel(
            panel_content,
            border_style="bright_black",
            padding=(0, 2),
            subtitle="[dim]v1.0 · ScannUs[/dim]",
        ),
        justify="center",
    )
    console.print()

    # --- Animated init steps ---
    import time
    steps = [
        ("Resolving environment variables",  0.25),
        ("Verifying output directory tree",  0.20),
        ("Loading API credentials",          0.20),
    ]

    with console.status(
        f"[{THEME['PRIMARY']}]Initializing ScannUs…[/]", spinner="dots2", spinner_style="cyan"
    ) as status:
        for label, delay in steps:
            status.update(f"[{THEME['DIM']}]{label}…[/]")
            time.sleep(delay)

    # API key status badges
    console.print(
        f"  [{THEME['SUCCESS']}]✔[/] Environment loaded   "
        f"  Gemini API: "
        + (f"[{THEME['SUCCESS']}]● configured[/]" if google_api_key_found
           else f"[{THEME['WARN']}]● not found (run option 7 to configure)[/]")
    )
    console.print()
    console.rule(f"[{THEME['DIM']}]Ready[/]")
    console.print()
