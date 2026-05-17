import requests
from search.engines.cache import search_cache

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

    def search(self, query, pages=1):
        """
        Executes a search query against the Brave web index.

        Args:
            query (str): Target search string/dork.
            pages (int): Number of result pages to fetch. Brave returns up to 20 results per request.

        Returns:
            list: Normalized result objects containing 'title', 'description', and 'link'.
        """
        final_results = []
        count = 20

        # --- In-session cache check ---
        cache_key = search_cache.make_key("brave", query, pages=pages)
        cached = search_cache.get(cache_key)
        if cached is not None:
            return cached

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key
        }

        for page in range(pages):
            # Brave API uses page-based offsets.
            # Page 1 corresponds to offset 0, Page 2 to offset 1, etc.
            # Note: Many subscription tiers limit the maximum offset (often to 9).
            
            params = {
                "q": query,
                "count": count,
                "offset": page
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
                    
            except Exception as e:
                raise RuntimeError(f"Brave Search API Error (page {page + 1}): {e}")

        search_cache.set(cache_key, final_results)
        return final_results
