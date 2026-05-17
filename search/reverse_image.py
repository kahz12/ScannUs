"""
search/reverse_image.py — Multi-engine reverse image search entry point.

Replaces the old Yandex-only flow with a tiered fallback chain (TinEye API,
Bing Visual Search API, Yandex via Selenium, manual lookup URLs). Each
engine is independent and silently skipped when its prerequisite is missing,
so the user always receives at least the manual-lookup URL tier.
"""

from cli.ui import console, THEME, print_info, print_error, print_warn
from search.reverse_image_engines import reverse_image_aggregate
from utils.results_parse import ResultsParser


def do_reverse_image_search(image_url: str | None = None) -> None:
    """
    Run the full reverse-image fallback chain and render the aggregated
    results. Prompts for the URL if not supplied (e.g. when launched from
    the TUI).
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
        with console.status(
            f"[{THEME['PRIMARY']}]Querying TinEye → Bing → Yandex → manual URLs…[/]",
            spinner="dots2",
        ):
            results = reverse_image_aggregate(image_url)

        if not results:
            print_warn("No results found across any engine.")
            return

        # Tally per-engine hits so the user can see which tier produced what
        by_engine: dict[str, int] = {}
        for r in results:
            by_engine[r.get("engine", "?")] = by_engine.get(r.get("engine", "?"), 0) + 1
        breakdown = ", ".join(f"{eng}×{n}" for eng, n in by_engine.items())

        console.print(
            f"  [{THEME['SUCCESS']}]✔[/]  {len(results)} result(s) "
            f"[{THEME['DIM']}]({breakdown})[/]"
        )
        rparser = ResultsParser(results)
        console.print(rparser.to_table())

    except Exception as e:
        print_error(f"Reverse image search failed: {e}")
