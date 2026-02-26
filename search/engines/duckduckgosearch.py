import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
from search.engines.cache import search_cache

class DuckDuckGoSearch:
    """
    Search engine implementation for DuckDuckGo.
    Utilizes BeautifulSoup to scrape the HTML-only version (non-JS) of DDG.
    """

    def __init__(self):
        """
        Initializes the DuckDuckGo scraper configuration.
        """
        self.base_url = "https://html.duckduckgo.com/html/"

    def search(self, query, pages=1):
        """
        Executes a search query against DuckDuckGo.

        Args:
            query (str): The search string.
            pages (int): Parameter maintained for interface parity across engines; 
                         DDG's HTML version has non-standard pagination and is capped here to 1.

        Returns:
            list: Normalized list of result dictionaries (title, description, link).
        """
        final_results = []

        # --- In-session cache check ---
        cache_key = search_cache.make_key("duckduckgo", query, pages=pages)
        cached = search_cache.get(cache_key)
        if cached is not None:
            return cached

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        
        params = {
            'q': query
        }

        try:
            # The HTML version requires a POST request with the 'q' parameter in the body
            response = requests.post(self.base_url, headers=headers, data=params, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Locate all top-level result containers in the DOM
            results_container = soup.find_all('div', {'class': 'result'})

            for container in results_container:
                title_element = container.find('h2', {'class': 'result__title'})
                link_element = container.find('a', {'class': 'result__a'})
                snippet_element = container.find('a', {'class': 'result__snippet'})

                if title_element and link_element and snippet_element:
                    title = title_element.get_text(strip=True)
            
                    # DDG obfuscates destination URLs behind a tracker/redirector
                    raw_link = link_element['href']
                    # Extract the canonical URL from the 'uddg' query parameter
                    parsed_link = self.clean_link(raw_link)
                    
                    snippet = snippet_element.get_text(strip=True)

                    if title and parsed_link and snippet:
                        final_results.append({
                            "title": title,
                            "description": snippet,
                            "link": parsed_link
                        })

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Network error searching DuckDuckGo: {e}")
        except Exception as e:
            raise RuntimeError(f"Unexpected DOM processing error on DuckDuckGo: {e}")

        search_cache.set(cache_key, final_results)
        return final_results

    def clean_link(self, raw_link):
        """
        Sanitizes DuckDuckGo redirection links to extract the destination URL.
        Example: /l/?kh=-1&uddg=https%3A%2F%2Fwww.example.com
        """
        if raw_link.startswith("/l/"):
            # Target the 'uddg=' substring which contains the encoded destination
            param = 'uddg='
            try:
                start_index = raw_link.index(param) + len(param)
                # Percent-decode the extracted string
                url = unquote(raw_link[start_index:])
                return url
            except ValueError:
                return None
        return raw_link


if __name__ == '__main__':
    # Bootstrap check for the DDG scraper
    ddg = DuckDuckGoSearch()
    search_results = ddg.search("python web scraping")
    if search_results:
        for i, res in enumerate(search_results, 1):
            print(f"--- Result {i} ---")
            print(f"Title: {res['title']}")
            print(f"Description: {res['description']}")
            print(f"Link: {res['link']}")
            print()
    else:
        print("No results found.")
