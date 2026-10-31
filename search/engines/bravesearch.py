import requests

from cli.ui import print_warn
from search.engines.cache import search_cache

# Highest page offset the API accepts, so a query reaches ten pages at most.
_MAX_OFFSET = 9


class BraveSearch:
    """
    Client wrapper for the Brave Search API (V1).
    Encapsulates authentication, request construction, and result normalization.
    """

    def __init__(self, api_key):
        """
        Initializes the BraveSearch service layer.

        Args:
            api_key (str): X-Subscription-Token for Brave API authentication.
        """
        self.api_key = api_key
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    def search(self, query, pages=1, start_page=1):
        """
        Executes a search query against the Brave web index.

        Args:
            query (str): Target search string/dork.
            pages (int): Number of result pages to fetch. Brave returns up to 20 results per request.
            start_page (int): First page to fetch (1-based).

        Returns:
            list: Normalized result objects containing 'title', 'description', and 'link'.

        Raises a runtime exception when the API fails before any result was
        retrieved, or when ``start_page`` is past the last page Brave serves.
        """
        final_results = []
        count = 20

        # --- In-session cache check ---
        cache_key = search_cache.make_key("brave", query, pages=pages, start=start_page)
        cached = search_cache.get(cache_key)
        if cached is not None:
            return cached

        first_offset = start_page - 1
        if first_offset > _MAX_OFFSET:
            raise RuntimeError(f"Brave only serves {_MAX_OFFSET + 1} pages per query.")
        last_offset = first_offset + pages - 1
        if last_offset > _MAX_OFFSET:
            print_warn(f"Brave only serves {_MAX_OFFSET + 1} pages per query — "
                       f"stopping at page {_MAX_OFFSET + 1}.")
            last_offset = _MAX_OFFSET

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key
        }

        for offset in range(first_offset, last_offset + 1):
            # Brave API uses page-based offsets.
            # Page 1 corresponds to offset 0, Page 2 to offset 1, etc.

            params = {
                "q": query,
                "count": count,
                "offset": offset
            }


            try:
                response = requests.get(self.base_url, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                # Payload traversal: data -> web -> results (list)
                web_results = data.get("web", {}).get("results", [])
                
                for result in web_results:
                    # Map Brave response fields to internal ScannUs schema
                    final_results.append({
                        "title": result.get("title"),
                        "description": result.get("description"),
                        "link": result.get("url")
                    })

                # Every request spends paid credit, so stop once no page is left.
                if not data.get("query", {}).get("more_results_available"):
                    break

            except Exception as e:
                if not final_results:
                    raise RuntimeError(f"Brave Search API Error (page {offset + 1}): {e}")
                # Incomplete set: keep what was paid for, but leave it out of
                # the cache so a later run can fetch every page.
                print_warn(f"Brave failed on page {offset + 1} — returning "
                           f"the {len(final_results)} results found so far.")
                return final_results

        search_cache.set(cache_key, final_results)
        return final_results
