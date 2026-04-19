"""
search/reverse_image.py — Reverse image search via Yandex / SmartSearch.

Improvements:
  - Replaced input() with console.input() so the ❯ prompt renders correctly
  - Replaced bare console.print() strings with Rich theme helpers
  - Added a spinner while the headless browser is running
"""

from cli.ui import console, THEME, print_info, print_error, print_warn
from search.smart_search import SmartSearch
from utils.results_parse import ResultsParser


def do_reverse_image_search(image_url: str | None = None) -> None:
    """
    Runs a Yandex reverse image search via Selenium and renders results.
    Prompts for the URL if not supplied (e.g. when launched from the TUI).
    """
    if not image_url:
        image_url = console.input(
            f"  [{THEME['DIM']}]Image URL for reverse search:[/] [{THEME['INPUT']}]❯[/] "
        ).strip()

    if not image_url:
        print_error("Image URL cannot be empty.")
        return

    print_info(f"Starting reverse image search for: {image_url}")

    try:
        search_engine = SmartSearch()

        with console.status(
            f"[{THEME['PRIMARY']}]Running headless browser (Yandex)…[/]",
            spinner="dots2",
        ):
            results = search_engine.reverse_image_search(image_url)

        if not results:
            print_warn("No results found for this image.")
            return

        console.print(
            f"  [{THEME['SUCCESS']}]✔[/]  {len(results)} result(s) found."
        )
        rparser = ResultsParser(results)
        console.print(rparser.to_table())

    except Exception as e:
        print_error(f"Reverse image search failed: {e}")
