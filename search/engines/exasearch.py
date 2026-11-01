from search.engines.api_query import (
    post_search, result_window, split_site_filters, warn_ignored_operators,
)
from search.engines.cache import search_cache

_BASE_URL = "https://api.exa.ai/search"

# Exa has no pagination. Its documented maximum is 100 results, but plans can
# set a lower limit and only Enterprise lists more than 25.
_MAX_RESULTS = 25
_PAGE_SIZE = 10

# Highlights carry no extra charge, unlike summaries.
_SNIPPET_CHARACTERS = 500

_REJECTIONS = {
    401: "Exa rejected EXA_API_KEY. Check the key in .env.",
    402: "Exa has no credit left. Check the balance at dashboard.exa.ai.",
    429: "Exa rate limit reached. Try again in a moment.",
}


class ExaSearch:
    """
    Client wrapper for the Exa Search API.
    Encapsulates authentication, request construction, and result normalization.
    """

    def __init__(self, api_key):
        """
        Initializes the ExaSearch service layer.

        Args:
            api_key (str): Exa API key, sent in the x-api-key header.
        """
        self.api_key = api_key

    def search(self, query, pages=1, start_page=1):
        """
        Executes a search query against the Exa index.

        Every call is one billed request, and each result above 10 adds a
        small charge, so asking for more pages costs slightly more.

        Args:
            query (str): Target search string. ``site:`` becomes a domain filter.
            pages (int): Number of pages, 10 results each, up to 25 results.
            start_page (int): First page to return (1-based).

        Returns:
            list: Normalized result objects containing 'title', 'description', and 'link'.

        Raises a runtime exception when the API fails, or when ``start_page``
        is past the last result ScannUs asks Exa for.
        """
        warn_ignored_operators("Exa", query)

        cache_key = search_cache.make_key("exa", query, pages=pages, start=start_page)
        cached = search_cache.get(cache_key)
        if cached is not None:
            return cached

        first, last = result_window("Exa", pages, start_page, _PAGE_SIZE, _MAX_RESULTS)
        text, included, excluded = split_site_filters(query)

        payload = {
            "query": text,
            "type": "auto",
            "numResults": last,
            "contents": {"highlights": {"maxCharacters": _SNIPPET_CHARACTERS}},
        }
        if included:
            payload["includeDomains"] = included
        if excluded:
            payload["excludeDomains"] = excluded

        headers = {"x-api-key": self.api_key}
        results = post_search("Exa", _BASE_URL, headers, payload, _REJECTIONS)

        final_results = [
            {
                "title": result.get("title") or result["url"],
                "description": " ".join(result.get("highlights") or []),
                "link": result["url"],
            }
            for result in results[first:last]
            if result.get("url")
        ]

        search_cache.set(cache_key, final_results)
        return final_results
