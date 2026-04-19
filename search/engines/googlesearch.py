import requests
from search.engines.cache import search_cache

class GoogleSearch:
    """
    Client wrapper for the Google Custom Search JSON API (V1).
    Handles authenticated request construction, recursive pagination, and 
    normalization of the JSON payload.
    """

    def __init__(self, api_key, engine_id):
        """
        Initializes the Google Search service layer.

        Args:
            api_key (str): Google Cloud Platform API Key with Custom Search enabled.
            engine_id (str): Programmable Search Engine ID (CX).
        """
        self.api_key = api_key
        self.engine_id = engine_id

    def search(self, query, start_page=1, pages=1, lang="lang_es"):
        """
        Executes a search query against the Google Custom Search index.

        Args:
            query (str): The search string or complex Google Dork.
            start_page (int): The initial page index (1-based) to start fetching from.
            pages (int): The number of sequential pages to retrieve.
                         Note: Each page fetch costs 1 API quota unit.
            lang (str): Language restrict parameter (e.g., "lang_en", "lang_es").

        Returns:
            list: A list of normalized result dictionaries (title, description, link).

        Raises:
            Exception: On network failure, non-200 HTTP status, or malformed JSON responses.
        """
        final_results = []
        results_per_page = 10

        # --- In-session cache check ---
        cache_key = search_cache.make_key("google", query, pages=pages,
                                          start=start_page, lang=lang)
        cached = search_cache.get(cache_key)
        if cached is not None:
            return cached

        base_url = "https://www.googleapis.com/customsearch/v1"

        for page in range(pages):
            # Calculate the 'start' query parameter.
            # It represents the 1-based index of the first result to return.
            # Page 1 = start 1, Page 2 = start 11, etc.
            start_index = (start_page - 1) * results_per_page + 1 + (page * results_per_page)

            params = {
                "key":   self.api_key,
                "cx":    self.engine_id,
                "q":     query,
                "start": start_index,
                "lr":    lang,
            }

            try:
                response = requests.get(base_url, params=params, timeout=10)
                # Ensure we catch 4xx/5xx errors (e.g., quota exceeded, invalid API key)
                response.raise_for_status()
                
                data = response.json()
                
                # 'items' is only present if results were found for the specific index range
                results = data.get("items", [])
                
                # Transform the verbose API items into our internal lean schema
                cresults = self.custom_results(results)
                final_results.extend(cresults)
                
            except requests.exceptions.RequestException as e:
                raise Exception(f"Network or HTTP error fetching page {page + 1}: {e}")
            except ValueError as e:
                raise Exception(f"Error decoding JSON for page {page + 1}: {e}")

        search_cache.set(cache_key, final_results)
        return final_results

    def custom_results(self, results):
        """
        Normalizes raw API result objects into the standard ScannUs result schema.

        Args:
            results (list): Raw 'items' array from the Google Search API response.

        Returns:
            list: List of dictionaries with sanitized 'title', 'description', and 'link' keys.
        """
        custom_results = []
        for result in results:
            cresult = {
                "title": result.get("title"),
                # Google uses 'snippet' for the descriptive text block
                "description": result.get("snippet"),
                "link": result.get("link")
            }
            custom_results.append(cresult)
        return custom_results
