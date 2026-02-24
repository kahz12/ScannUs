import requests
import json
import os

class BraveSearch:
    """
    Class to perform searches using the Brave Search API.
    Requires a valid API Key.
    """

    def __init__(self, api_key):
        """
        Initializes the BraveSearch instance.

        Args:
            api_key (str): Your Brave Search API key.
        """
        self.api_key = api_key
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    def search(self, query, pages=1):
        """
        Performs a search on Brave Search.

        Args:
            query (str): The search query.
            pages (int): Number of result pages (Brave allows up to 20 results per request,
                         but complex pagination. We simplify by iterating offset).

        Returns:
            list: List of dictionaries with results (title, description, link).
        """
        final_results = []
        # The Brave Search API default returns 20 results depending on the plan,
        # but the maximum 'count' parameter is 20.
        count = 20
        
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key
        }

        for page in range(pages):
            # The Brave API uses offset-based pagination (0, 1, 2...).
            # The 'offset' parameter indicates the number of result pages to skip (not item count).
            # For example: page 1 -> offset=0, page 2 -> offset=1.
            # Note: The maximum offset limit is typically 9 in standard plans.
            
            params = {
                "q": query,
                "count": count,
                "offset": page # 0 for the first page, 1 for the second...
            }
            
            try:
                response = requests.get(self.base_url, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                # Brave response structure:
                # { "web": { "results": [ ... ] } }
                
                web_results = data.get("web", {}).get("results", [])
                
                for result in web_results:
                    # Brave result keys: 'title', 'url' (link), 'description'
                    final_results.append({
                        "title": result.get("title"),
                        "description": result.get("description"),
                        "link": result.get("url")
                    })
                    
            except Exception as e:
                print(f"Error en búsqueda con Brave (página {page+1}): {e}")
                break
                
        return final_results
