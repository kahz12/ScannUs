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

    def search(self, query: str, pages: int = 1) -> list[dict]:
        """
        Executes a search query against DuckDuckGo.

        Args:
            query: The search string.
            pages: Number of result pages to retrieve (default 1, ~30 per page).

        Returns:
            Normalised list of result dictionaries (title, description, link).
        """
        pages = max(1, int(pages))
        cache_key = search_cache.make_key("duckduckgo", query, pages=pages)
        cached = search_cache.get(cache_key)
        if cached is not None:
            return cached

        final_results: list[dict] = []
        seen_links: set[str] = set()

        with requests.Session() as session:
            session.headers.update(_HEADERS)
            for page in range(pages):
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
