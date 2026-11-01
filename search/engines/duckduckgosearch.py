"""
search/engines/duckduckgosearch.py — DuckDuckGo HTML-endpoint scraper
with real pagination.

DuckDuckGo's ``html.duckduckgo.com`` endpoint accepts an ``s`` (start)
parameter that controls the result offset.  Each response also embeds a
hidden form pointing at the next page, so we can either step incrementally
(``s=0, 30, 60, …``) or follow the form's own ``s``.  We do the simple
incremental version, which is enough for OSINT-style pagination.
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote

from cli.ui import print_warn
from search.engines.cache import search_cache


_BASE_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# DuckDuckGo's HTML endpoint returns approximately this many results per page.
_PAGE_OFFSET_STEP = 30

# Asset path of the captcha DuckDuckGo serves when it suspects a bot.
_CHALLENGE_MARKER = "assets/anomaly/"


class SearchBlockedError(RuntimeError):
    """DuckDuckGo refused the search with its anti-bot check."""


def _is_challenge(response: requests.Response) -> bool:
    """
    Tells whether a page without results is DuckDuckGo's anti-bot captcha.

    The captcha normally arrives as HTTP 202, which ``raise_for_status()`` lets
    through. Call this only for pages that yielded no results, so a search
    that merely mentions the marker is never mistaken for a block.
    """
    return response.status_code == 202 or _CHALLENGE_MARKER in response.text


class DuckDuckGoSearch:
    """
    Search engine implementation for DuckDuckGo (HTML endpoint).

    Pagination is driven by the ``s`` (start-offset) form parameter.  The
    scraper iterates ``pages`` times, advancing the offset by
    ``_PAGE_OFFSET_STEP`` per request, and stops early if a page yields no
    new results.
    """

    def __init__(self):
        self.base_url = _BASE_URL

    def search(self, query: str, pages: int = 1, start_page: int = 1) -> list[dict]:
        """
        Executes a search query against DuckDuckGo.

        Args:
            query:      The search string.
            pages:      Number of result pages to retrieve (default 1, ~30 per page).
            start_page: First page to retrieve (1-based).

        Returns:
            Normalised list of result dictionaries (title, description, link).

        Raises this module's blocked-search exception when DuckDuckGo blocks
        the search before any result was retrieved, and a runtime exception on
        a network failure.
        """
        pages = max(1, int(pages))
        first_page = max(1, int(start_page)) - 1
        cache_key = search_cache.make_key("duckduckgo", query, pages=pages, start=first_page + 1)
        cached = search_cache.get(cache_key)
        if cached is not None:
            return cached

        final_results: list[dict] = []
        seen_links: set[str] = set()

        with requests.Session() as session:
            session.headers.update(_HEADERS)
            for page in range(first_page, first_page + pages):
                offset = page * _PAGE_OFFSET_STEP
                params = {"q": query}
                if offset:
                    params["s"] = str(offset)
                    params["dc"] = str(offset)

                try:
                    response = session.post(self.base_url, data=params, timeout=10)
                    response.raise_for_status()
                except requests.exceptions.RequestException as e:
                    raise RuntimeError(
                        f"Network error searching DuckDuckGo (page {page + 1}): {e}"
                    )

                page_results = self._parse_results(response.text)
                if not page_results:
                    if _is_challenge(response):
                        if not final_results:
                            raise SearchBlockedError(
                                "DuckDuckGo blocked this search with its anti-bot check. "
                                "Wait a few minutes, or add a Brave, Tavily or Exa key "
                                "to .env to search with that engine instead."
                            )
                        # Incomplete set: keep it, but leave it out of the cache
                        # so a later run can fetch every page.
                        print_warn(f"DuckDuckGo blocked page {page + 1} — returning "
                                   f"the {len(final_results)} results found so far.")
                        return final_results
                    # No more pages with content — stop early.
                    break

                new_count = 0
                for r in page_results:
                    if r["link"] in seen_links:
                        continue
                    seen_links.add(r["link"])
                    final_results.append(r)
                    new_count += 1

                # If a page returns only duplicates, further paging is pointless.
                if new_count == 0:
                    break

        search_cache.set(cache_key, final_results)
        return final_results

    def _parse_results(self, html: str) -> list[dict]:
        """Extracts a single result page into the normalised dict shape."""
        soup = BeautifulSoup(html, "html.parser")
        results: list[dict] = []

        for container in soup.find_all("div", {"class": "result"}):
            title_el   = container.find("h2", {"class": "result__title"})
            link_el    = container.find("a",  {"class": "result__a"})
            snippet_el = container.find("a",  {"class": "result__snippet"})

            if not (title_el and link_el and snippet_el):
                continue

            title = title_el.get_text(strip=True)
            parsed_link = self.clean_link(link_el["href"])
            snippet = snippet_el.get_text(strip=True)

            if title and parsed_link and snippet:
                results.append({
                    "title":       title,
                    "description": snippet,
                    "link":        parsed_link,
                })

        return results

    def clean_link(self, raw_link: str) -> str | None:
        """
        Sanitises DuckDuckGo redirector links to the canonical destination URL.
        Example: ``/l/?kh=-1&uddg=https%3A%2F%2Fwww.example.com`` → the URL.
        """
        if raw_link.startswith("/l/"):
            param = "uddg="
            try:
                start_index = raw_link.index(param) + len(param)
                # Stop at the next '&' so trailing tracker params (kh=, rut=, …)
                # are not glued onto the decoded destination URL.
                tail = raw_link[start_index:].split("&", 1)[0]
                return unquote(tail)
            except ValueError:
                return None
        return raw_link


if __name__ == "__main__":
    ddg = DuckDuckGoSearch()
    for i, res in enumerate(ddg.search("python web scraping", pages=2), 1):
        print(f"--- Result {i} ---")
        print(f"Title:       {res['title']}")
        print(f"Description: {res['description']}")
        print(f"Link:        {res['link']}\n")
