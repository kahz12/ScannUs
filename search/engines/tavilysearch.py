from search.engines.api_query import (
    post_search, result_window, split_site_filters, warn_ignored_operators,
)
from search.engines.cache import search_cache

_BASE_URL = "https://api.tavily.com/search"

# The API returns at most 20 results per request and has no pagination.
_MAX_RESULTS = 20
_PAGE_SIZE = 10

_REJECTIONS = {
    401: "Tavily rejected TAVILY_API_KEY. Check the key in .env.",
    429: "Tavily rate limit reached. Try again in a moment.",
    432: "Tavily plan limit reached. Credits renew every month.",
    433: "Tavily pay-as-you-go limit reached.",
}


class TavilySearch:
    """
    Client wrapper for the Tavily Search API.
    Encapsulates authentication, request construction, and result normalization.
    """

    def __init__(self, api_key):
        """
        Initializes the TavilySearch service layer.

        Args:
            api_key (str): Tavily API key, sent as a bearer token.
        """
        self.api_key = api_key

    def search(self, query, pages=1, start_page=1):
        """
        Executes a search query against the Tavily index.

        Every call spends one credit, however many pages it covers. Basic
        depth is used because advanced depth costs two credits.

        Args:
            query (str): Target search string. ``site:`` becomes a domain filter.
            pages (int): Number of pages, 10 results each, up to 20 results.
            start_page (int): First page to return (1-based).

        Returns:
            list: Normalized result objects containing 'title', 'description', and 'link'.

        Raises a runtime exception when the API fails, or when ``start_page``
        is past the last result Tavily serves.
        """
        warn_ignored_operators("Tavily", query)

        cache_key = search_cache.make_key("tavily", query, pages=pages, start=start_page)
        cached = search_cache.get(cache_key)
        if cached is not None:
            return cached

        first, last = result_window("Tavily", pages, start_page, _PAGE_SIZE, _MAX_RESULTS)
        text, included, excluded = split_site_filters(query)

        payload = {"query": text, "search_depth": "basic", "max_results": last}
        if included:
            payload["include_domains"] = included
        if excluded:
            payload["exclude_domains"] = excluded
        if '"' in text:
            payload["exact_match"] = True

        headers = {"Authorization": f"Bearer {self.api_key}"}
        results = post_search("Tavily", _BASE_URL, headers, payload, _REJECTIONS)

        final_results = [
            {
                "title": result.get("title") or result["url"],
                "description": result.get("content") or "",
                "link": result["url"],
            }
            for result in results[first:last]
            if result.get("url")
        ]

        search_cache.set(cache_key, final_results)
        return final_results
