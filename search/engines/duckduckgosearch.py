import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote

class DuckDuckGoSearch:
    """
    Class to perform searches and extract results from DuckDuckGo
    via web scraping of its HTML version.
    """

    def __init__(self):
        """
        Initializes the DuckDuckGo search engine.
        """
        self.base_url = "https://html.duckduckgo.com/html/"

    def search(self, query, pages=1):
        """
        Performs a search on DuckDuckGo.

        Args:
            query (str): The search query.
            pages (int): DuckDuckGo (HTML version) does not have traditional pagination, 
                         so this parameter is ignored, but kept for compatibility.

        Returns:
            list: A list of dictionaries with results (title, description, link).
        """
        final_results = []
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        
        params = {
            'q': query
        }

        try:
            response = requests.post(self.base_url, headers=headers, data=params, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all result containers
            results_container = soup.find_all('div', {'class': 'result'})

            for container in results_container:
                title_element = container.find('h2', {'class': 'result__title'})
                link_element = container.find('a', {'class': 'result__a'})
                snippet_element = container.find('a', {'class': 'result__snippet'})

                if title_element and link_element and snippet_element:
                    title = title_element.get_text(strip=True)
            
                    # The link in DDG is in the format /url?q=URL&...
                    raw_link = link_element['href']
                    # Extract the real URL from the 'q' parameter
                    parsed_link = self.clean_link(raw_link)
                    
                    snippet = snippet_element.get_text(strip=True)

                    if title and parsed_link and snippet:
                        final_results.append({
                            "title": title,
                            "description": snippet,
                            "link": parsed_link
                        })

        except requests.exceptions.RequestException as e:
            print(f"Network error searching DuckDuckGo: {e}")
        except Exception as e:
            print(f"An unexpected error occurred processing DuckDuckGo: {e}")
            
        return final_results

    def clean_link(self, raw_link):
        """
        Cleans the DuckDuckGo redirection link to get the final destination URL.
        Example: /l/?kh=-1&uddg=https%3A%2F%2Fwww.ejemplo.com
        """
        if raw_link.startswith("/l/"):
            # Look for the 'uddg=' parameter containing the real URL
            param = 'uddg='
            try:
                start_index = raw_link.index(param) + len(param)
                # Decode the URL (e.g. %3A -> :)
                url = unquote(raw_link[start_index:])
                return url
            except ValueError:
                return None # If 'uddg=' is not found
        return raw_link


if __name__ == '__main__':
    # Usage example
    ddg = DuckDuckGoSearch()
    search_results = ddg.search("python web scraping")
    if search_results:
        for i, res in enumerate(search_results, 1):
            print(f"--- Resultado {i} ---")
            print(f"Título: {res['title']}")
            print(f"Descripción: {res['description']}")
            print(f"Enlace: {res['link']}")
            print()
    else:
        print("No se encontraron resultados.")
