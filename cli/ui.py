"""
cli/ui.py — Design system for ScannUs.

Stack:
  - rich          — panels, tables, progress, status, banners
  - questionary   — arrow-key navigable menus (graceful fallback to numeric input)

All visual output and user interaction in ScannUs flows through this module
to ensure a single, consistent look and behaviour across every screen.
"""

import os
import sys
import textwrap
from typing import Iterable, Sequence

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.columns import Columns
from rich.padding import Padding
from rich.rule import Rule
from rich import box

# Optional dependency — arrow-key navigation. Falls back to numeric prompts
# when missing or when running in a non-interactive shell (CI, pipes, etc.).
try:
    import questionary
    from questionary import Style as _QStyle
    _HAS_QUESTIONARY = True
except ImportError:
    questionary = None
    _QStyle = None
    _HAS_QUESTIONARY = False


# ---------------------------------------------------------------------------
# Global console (single instance shared everywhere)
# ---------------------------------------------------------------------------

console = Console(highlight=False, soft_wrap=False)


# ---------------------------------------------------------------------------
# Theme tokens
# ---------------------------------------------------------------------------

THEME = {
    # Brand
    "PRIMARY"  : "bold cyan",
    "ACCENT"   : "bold magenta",
    "ACCENT_2" : "bold #00d7af",         # mint highlight
    # Status
    "SUCCESS"  : "bold green",
    "ERROR"    : "bold red",
    "WARN"     : "bold yellow",
    "INFO"     : "bold #5fafff",
    # Neutral
    "DIM"      : "grey62",
    "MUTED"    : "grey50",
    "BORDER"   : "grey30",
    # Interactive
    "LINK"     : "cyan underline",
    "INPUT"    : "bold cyan",
    "KEY"      : "bold #00d7ff",
    # Banner gradient (top → bottom)
    "BANNER_1" : "bold #00ffff",
    "BANNER_2" : "bold #00cfff",
    "BANNER_3" : "bold #009fff",
    "BANNER_4" : "bold #006fff",
    "BANNER_5" : "bold #003fff",
    "BANNER_6" : "bold #0000ff",
}

PROMPT_GLYPH   = "❯"
SUCCESS_GLYPH  = "✔"
ERROR_GLYPH    = "✘"
WARN_GLYPH     = "⚠"
INFO_GLYPH     = "›"
ARROW_GLYPH    = "→"
BULLET_GLYPH   = "•"
LOADING_GLYPH  = "◔"

PROMPT = f"[{THEME['INPUT']}]{PROMPT_GLYPH}[/] "

# questionary style — kept in sync with THEME for visual consistency
_Q_STYLE = _QStyle([
    ("qmark",       "fg:#00d7ff bold"),
    ("question",    "bold"),
    ("answer",      "fg:#5fafff bold"),
    ("pointer",     "fg:#ff5fd7 bold"),
    ("highlighted", "fg:#00d7ff bold"),
    ("selected",    "fg:#00d7af bold"),
    ("separator",   "fg:#5f5f5f"),
    ("instruction", "fg:#808080"),
    ("text",        ""),
    ("disabled",    "fg:#5f5f5f italic"),
]) if _HAS_QUESTIONARY else None


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------

def _interactive_tty() -> bool:
    """True when stdin/stdout are TTYs and questionary is available."""
    return _HAS_QUESTIONARY and sys.stdin.isatty() and sys.stdout.isatty()


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def ask(question: str = "", default: str = "") -> str:
    """
    Styled free-text prompt with optional default value (shown as a hint).
    Returns the trimmed string the user typed (or the default if empty).
    """
    suffix = f" [{THEME['DIM']}][{default}][/]" if default else ""
    label  = f"  {question}{suffix} {PROMPT}" if question else f"  {PROMPT}"
    answer = console.input(label).strip()
    return answer or default


def confirm(question: str, default: bool = False) -> bool:
    """
    Yes/No confirmation. Uses questionary when available; otherwise a styled
    [y/n] prompt that accepts y/yes/s/si and n/no.
    """
    if _interactive_tty():
        try:
            return bool(questionary.confirm(
                question, default=default, style=_Q_STYLE,
                qmark=PROMPT_GLYPH,
            ).ask())
        except (KeyboardInterrupt, EOFError):
            return False

    hint = "[Y/n]" if default else "[y/N]"
    raw = ask(f"{question} {hint}")
    if not raw:
        return default
    return raw.lower() in ("y", "yes", "s", "si", "sí")


def select_menu(
    title: str,
    choices: Sequence[tuple],
    *,
    instruction: str = "↑/↓ to move · Enter to select",
    default: str | None = None,
) -> str | None:
    """
    Arrow-key navigable menu.

    Args:
        title:       Heading shown above the choices.
        choices:     Iterable of ``(label, value)`` or ``(label, value, hint)``.
        instruction: Hint text shown next to the prompt.
        default:     Pre-selected value.

    Returns:
        The ``value`` of the chosen entry, or None if the user cancelled.
    """
    normalised: list[tuple[str, str, str]] = []
    for choice in choices:
        if len(choice) == 2:
            label, value = choice
            hint = ""
        else:
            label, value, hint = choice[0], choice[1], choice[2]
        normalised.append((str(label), str(value), str(hint)))

    if _interactive_tty():
        return _select_questionary(title, normalised, instruction, default)
    return _select_numeric(title, normalised, default)


def _select_questionary(title, normalised, instruction, default):
    q_choices = []
    default_choice = None
    for label, value, hint in normalised:
        text = f"{label}    [{hint}]" if hint else label
        ch = questionary.Choice(title=text, value=value)
        q_choices.append(ch)
        if default is not None and value == default:
            default_choice = ch

    console.print()
    console.print(f"  [{THEME['PRIMARY']}]{title}[/]")
    try:
        return questionary.select(
            "",
            choices=q_choices,
            default=default_choice,
            style=_Q_STYLE,
            qmark=PROMPT_GLYPH,
            instruction=instruction,
            use_indicator=True,
            use_shortcuts=False,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None


def _select_numeric(title, normalised, default):
    """Fallback when questionary is unavailable or running non-interactively."""
    console.print()
    console.print(Panel.fit(
        _build_choice_table(normalised, default),
        title=f"[{THEME['PRIMARY']}]{title}[/]",
        border_style=THEME["BORDER"],
        padding=(0, 2),
    ))
    while True:
        raw = ask("Selection")
        if not raw and default is not None:
            return default
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(normalised):
                return normalised[idx][1]
        # Allow value-based input too
        for _, value, _ in normalised:
            if raw == value:
                return value
        print_warn("Enter a number from the list.")


def _build_choice_table(normalised, default):
    tbl = Table(box=None, show_header=False, padding=(0, 2))
    tbl.add_column("#",     style=THEME["KEY"], width=3, no_wrap=True)
    tbl.add_column("Label", style="bold white",          no_wrap=True)
    tbl.add_column("Hint",  style=THEME["DIM"],          no_wrap=False)
    for i, (label, value, hint) in enumerate(normalised, 1):
        marker = "•" if (default is not None and value == default) else " "
        tbl.add_row(f"{i}{marker}", label, hint)
    return tbl


# ---------------------------------------------------------------------------
# Status messages
# ---------------------------------------------------------------------------

def print_success(msg: str) -> None:
    console.print(f"  [{THEME['SUCCESS']}]{SUCCESS_GLYPH}[/]  {msg}")

def print_error(msg: str) -> None:
    console.print(f"  [{THEME['ERROR']}]{ERROR_GLYPH}[/]  {msg}")

def print_warn(msg: str) -> None:
    console.print(f"  [{THEME['WARN']}]{WARN_GLYPH}[/]  {msg}")

def print_info(msg: str) -> None:
    console.print(f"  [{THEME['INFO']}]{INFO_GLYPH}[/]  {msg}")

def print_section(title: str, subtitle: str = "") -> None:
    """Visual separator with a centred title and optional subtitle."""
    console.print()
    if subtitle:
        text = Text()
        text.append(title, style=THEME["PRIMARY"])
        text.append("   ")
        text.append(subtitle, style=THEME["DIM"])
        console.rule(text)
    else:
        console.rule(f"[{THEME['PRIMARY']}]{title}[/]")
    console.print()


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def header_bar(title: str, subtitle: str = "", glyph: str = "⬡") -> None:
    """
    Renders the screen-level title bar. One per screen — sets context so the
    user always knows where they are in the app.
    """
    text = Text()
    text.append(f" {glyph}  ", style=THEME["ACCENT"])
    text.append(title, style=THEME["PRIMARY"])
    if subtitle:
        text.append("   ")
        text.append(subtitle, style=THEME["DIM"])
    console.print()
    console.print(Panel(
        text,
        border_style=THEME["BORDER"],
        padding=(0, 1),
        box=box.HEAVY,
    ))


def status_footer(items: Sequence[tuple[str, str, str]]) -> None:
    """
    Bottom status strip. Each item is ``(label, value, style_token)`` where
    style_token is one of ``"on"``, ``"off"``, ``"info"``.
    """
    parts: list[str] = []
    for label, value, kind in items:
        if kind == "on":
            badge = f"[{THEME['SUCCESS']}]●[/]"
            value_style = THEME["SUCCESS"]
        elif kind == "off":
            badge = f"[{THEME['MUTED']}]○[/]"
            value_style = THEME["MUTED"]
        else:
            badge = f"[{THEME['INFO']}]◆[/]"
            value_style = THEME["INFO"]
        parts.append(
            f"{badge} [{THEME['DIM']}]{label}[/] [{value_style}]{value}[/]"
        )
    if not parts:
        return
    line = f"  {f'   {BULLET_GLYPH}   '.join(parts)}"
    console.print(Padding(Text.from_markup(line), (0, 0)))


def panel(content, title: str = "", subtitle: str = "",
          border: str = None, padding: tuple = (1, 2)) -> None:
    """Themed Rich Panel wrapper for consistent styling across the app."""
    console.print(Panel(
        content,
        title=f"[{THEME['PRIMARY']}]{title}[/]" if title else None,
        subtitle=f"[{THEME['DIM']}]{subtitle}[/]" if subtitle else None,
        border_style=border or THEME["BORDER"],
        padding=padding,
        box=box.ROUNDED,
    ))


# ---------------------------------------------------------------------------
# Table factory
# ---------------------------------------------------------------------------

def make_table(title: str = "", *columns, show_lines: bool = False) -> Table:
    """
    Pre-styled Rich Table.

    Args:
        title:      Optional table title.
        *columns:   Tuples of ``(header, style)`` pairs or plain strings.
        show_lines: Whether to draw row dividers.
    """
    tbl = Table(
        title=title or None,
        box=box.ROUNDED,
        header_style=THEME["PRIMARY"],
        title_style=THEME["ACCENT"],
        show_lines=show_lines,
        border_style=THEME["BORDER"],
        padding=(0, 1),
    )
    for col in columns:
        if isinstance(col, tuple):
            header = col[0]
            style  = col[1] if len(col) > 1 else "white"
            tbl.add_column(header, style=style, no_wrap=False)
        else:
            tbl.add_column(col)
    return tbl


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------

_BANNER_LINES = [
    r"   _____                         _   _   _    _  ____",
    r"  / ____|                       | \ | | | |  | |/ ___|",
    r" | (___   ___ __ _ _ __  _ __   |  \| | | |  | |\___ \ ",
    r"  \___ \ / __/ _` | '_ \| '_ \  | . ` | | |  | | ___) |",
    r"  ____) | (_| (_| | | | | | | | | |\  | | |__| |/ ___/ ",
    r" |_____/ \___\__,_|_| |_|_| |_| |_| \_|  \____/|_____|",
]


def _gradient_banner() -> Text:
    """Builds the gradient-coloured ASCII banner."""
    palette = [
        THEME["BANNER_1"], THEME["BANNER_2"], THEME["BANNER_3"],
        THEME["BANNER_4"], THEME["BANNER_5"], THEME["BANNER_6"],
    ]
    text = Text()
    for line, style in zip(_BANNER_LINES, palette):
        text.append(line + "\n", style=style)
    return text


def print_startup_banner(google_api_key_found: bool) -> None:
    """
    Renders the startup screen: gradient banner, tagline, init steps,
    and an environment-status footer.
    """
    banner = _gradient_banner()
    tagline = Text()
    tagline.append("\n  Advanced OSINT & Search Analysis Framework", style=THEME["DIM"])
    tagline.append("   ")
    tagline.append("v1.0", style=THEME["ACCENT_2"])

    body = Group(Align.center(banner), Align.center(tagline))

    console.print()
    console.print(Panel(
        body,
        border_style=THEME["BORDER"],
        padding=(1, 2),
        box=box.HEAVY,
        subtitle=f"[{THEME['DIM']}]press Ctrl+C anywhere to abort[/]",
    ))
    console.print()

    # Init sequence
    import time
    steps = [
        ("Resolving environment variables",  0.20),
        ("Verifying output directory tree",  0.18),
        ("Loading API credentials",          0.18),
    ]
    with console.status(
        f"[{THEME['PRIMARY']}]Initializing ScannUs…[/]",
        spinner="dots2", spinner_style="cyan",
    ) as status:
        for label, delay in steps:
            status.update(f"[{THEME['DIM']}]{label}…[/]")
            time.sleep(delay)

    # Capability footer
    status_footer([
        ("env",       "loaded",                          "on"),
        ("Gemini",    "configured" if google_api_key_found else "not set",
                      "on" if google_api_key_found else "off"),
        ("backend",   _detect_username_backend(),         "info"),
    ])
    console.print()
    console.print(Rule(style=THEME["BORDER"]))
    console.print()


def _detect_username_backend() -> str:
    import shutil
    if shutil.which("sherlock"):
        return "Sherlock"
    if shutil.which("maigret"):
        return "Maigret"
    return "none"
