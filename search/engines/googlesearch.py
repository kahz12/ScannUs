# Import the `requests` library to make HTTP requests to the Google API.
import requests

class GoogleSearch:
    """
    Class that encapsulates the logic to interact with the Google Custom Search API.
    It allows performing automated searches, handling pagination, and formatting results.
    """

    def __init__(self, api_key, engine_id):
        """
        Initializes a new instance of GoogleSearch.

        Args:
            api_key (str): Your Google API key, required to authenticate requests.
            engine_id (str): Your Custom Search Engine ID (known as CX).
                             This ID tells Google which search configuration to use.
        """
        self.api_key = api_key
        self.engine_id = engine_id

    def search(self, query, start_page=1, pages=1, lang="lang_es"):
        """
        Performs a Google search using the provided parameters and handles pagination.

        Args:
            query (str): The search query or "dork" to send to Google.
            start_page (int): The result page to start from (defaults to 1).
            pages (int): Total number of result pages to fetch (defaults to 1).
                         Each page contains up to 10 results.
            lang (str): The language code for the search results.
                        Defaults to "lang_es" for Spanish.

        Returns:
            list: A list of dictionaries, where each dictionary represents a
                  formatted search result with title, description, and link.

        Raises:
            Exception: If a network error, an HTTP error (like 4xx or 5xx),
                       or an error decoding the JSON response occurs.
        """
        final_results = []  # List to accumulate results from all requested pages.
        results_per_page = 10  # The Google API returns a maximum of 10 results per page.

        # Iterate over the number of pages the user wants to fetch.
        for page in range(pages):
            # Calculate the start index for Google API pagination.
            # The API uses a 1-based index, not 0-based.
            # Example: for page 1, start=1; for page 2, start=11; for page 3, start=21.
            start_index = (start_page - 1) * results_per_page + 1 + (page * results_per_page)
            
            # Build the API URL with all necessary parameters.
            url = f"https://www.googleapis.com/customsearch/v1?key={self.api_key}&cx={self.engine_id}&q={query}&start={start_index}&lr={lang}"
            
            try:
                # Make the GET request to the Google API with a timeout to avoid hanging.
                response = requests.get(url, timeout=10)
                # Raise an exception if the response has an error status code (e.g., 403 Forbidden, 404 Not Found).
                response.raise_for_status()
                # Decode the JSON response into a Python dictionary.
                data = response.json()
                # Extract the list of results ('items') from the JSON. If it doesn't exist, return an empty list.
                results = data.get("items", [])
                # Format the results to extract only the relevant information.
                cresults = self.custom_results(results)
                # Append the formatted results of the current page to the final list.
                final_results.extend(cresults)
            except requests.exceptions.RequestException as e:
                # Handle network errors (e.g., DNS issues, connection refused).
                error_msg = f"Network or HTTP error fetching page {page + 1}: {e}"
                print(error_msg)
                raise Exception(error_msg)
            except ValueError as e:  # Catch JSON decoding errors.
                error_msg = f"Error decoding JSON for page {page + 1}: {e}"
                print(error_msg)
                raise Exception(error_msg)
                
        return final_results

    def custom_results(self, results):
        """
        Formats a list of raw API results to extract only the fields of interest.

        Args:
            results (list): The list of 'items' returned by the Google API.

        Returns:
            list: A list of dictionaries, each with the keys "title", "description", and "link".
        """
        custom_results = []
        # Iterate over each search result.
        for result in results:
            # Create a dictionary with the key information for each result.
            # `result.get(key, default_value)` is used to prevent errors if a key is missing.
            cresult = {
                "title": result.get("title"),
                "description": result.get("snippet"),  # 'snippet' is the description field in the Google API.
                "link": result.get("link")
            }
            custom_results.append(cresult)
        return custom_results