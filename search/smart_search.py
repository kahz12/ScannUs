# Core system imports
import os
import re
import argparse
from urllib.parse import urlparse

# Engine-specific imports
from search.engines.googlesearch import GoogleSearch

# --- Information Extraction Functions ---

def extract_information(text):
    """
    Parses a text block to extract sensitive or high-interest OSINT patterns 
    using pre-defined regular expressions.
    
    Args:
        text (str): Raw input text to analyze.
        
    Returns:
        dict: Categorized extraction results (e.g., {"emails": [...], "phones": [...]}).
    """
    if not text:
        return {}
    
    # Heuristic-based regex patterns for common data leaks and PII
    patterns = {
        "emails": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        "phones": r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        "sql_errors": r'(SQL(ite)?|MySQL|PostgreSQL|Oracle)\s(error|exception|failed|denied)|(unclosed quotation mark|syntax error|invalid query)',
        "usernames": r'(user|username|login|usuario|nombre de usuario)[\s:=]+[\'"]?([a-zA-Z0-9._-]{3,})[\'"]?'
    }
    
    extracted_data = {}
    for key, pattern in patterns.items():
        # Set deduplication for overlapping matches
        unique_matches = set()
        for match in re.finditer(pattern, text, re.IGNORECASE):
            # Complex captures (usernames/sql_errors) extract the specific group payload
            if key in ["usernames", "sql_errors"]:
                found = next((g for g in match.groups() if g), None)
                if found:
                    unique_matches.add(found.strip())
            else:
                # Simple matches capture the entire matched string
                unique_matches.add(match.group(0).strip())
        
        if unique_matches:
            extracted_data[key] = list(unique_matches)
            
    return extracted_data

# --- Main Search Implementation ---

class SmartSearch:
    """
    Orchestrator for multi-vector searches, supporting local file analysis, 
    SERP (Search Engine Results Page) scraping via Google, and automated 
    Reverse Image Search.
    """
    def __init__(self, dir_path=None, api_key=None, engine_id=None):
        """
        Initializes the search context.
        
        Args:
            dir_path (str, optional): Root directory for local file scraping.
            api_key (str, optional): Google API credential for cloud search.
            engine_id (str, optional): Google CX ID for custom search targeting.
        """
        self.dir_path = dir_path
        # Populate file cache if a valid directory is provided
        self.files = self._read_files() if self.dir_path else {}
        # Strategy pattern initialization for the Google Search engine
        self.google_search_engine = GoogleSearch(api_key, engine_id) if api_key and engine_id else None

    def _read_files(self):
        """
        Walks the provided directory and reads contents into memory.
        (Utility method for local-first analysis).
        """
        files = {}
        if not os.path.isdir(self.dir_path):
            print(f"Error: The path '{self.dir_path}' is not a valid directory.")
            return files
        for archivo in os.listdir(self.dir_path):
            file_path = os.path.join(self.dir_path, archivo)
            if os.path.isfile(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        files[archivo] = f.read()
                except Exception as e:
                    print(f"Error reading file {file_path}: {e}")
        return files

    def regex_search(self, regex):
        """
        Executes an arbitrary regex search against the local file cache.
        """
        coincidencias = {}
        for file, text in self.files.items():
            matches = re.findall(regex, text, re.IGNORECASE)
            if matches:
                coincidencias[file] = matches
        return coincidencias

    def extract_from_files(self):
        """
        Automated extractor loop for PII/Sensitive data in local files.
        """
        all_extracted_data = {}
        for file, text in self.files.items():
            print(f"\n--- Analyzing file: {file} ---")
            extracted_data = extract_information(text)
            if extracted_data:
                all_extracted_data[file] = extracted_data
                for key, values in extracted_data.items():
                    print(f"  -> {key.replace('_', ' ').capitalize()}:")
                    for value in values:
                        print(f"     - {value}")
            else:
                print("  No relevant information found.")
        return all_extracted_data

    def search_google(self, query, pages=1):
        """
        Proxies the search request to the Google Custom Search instance.
        """
        if not self.google_search_engine:
            raise Exception("Google Search is not initialized. Provide an API key and engine ID.")
        return self.google_search_engine.search(query, pages=pages)

    def reverse_image_search(self, image_url):
        """
        Performs an automated reverse image search using Yandex Images via Selenium.
        Orchestrates a headless browser to bypass dynamic rendering requirements.
        
        Args:
            image_url (str): Remote URL of the target image payload.
            
        Returns:
            list: Parsed result objects (title, link, description).
        """
        # Latent Selenium imports to minimize startup overhead for non-image tasks
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.firefox.service import Service

        options = Options()
        options.add_argument("--headless")
        
        # Geckodriver path specifically mapped for Termux environments
        geckodriver_path = "/data/data/com.termux/files/usr/bin/geckodriver"
        service = Service(executable_path=geckodriver_path)

        driver = None
        try:
            print("[bold yellow]Starting Firefox in headless mode for Yandex search...[/bold yellow]")
            driver = webdriver.Firefox(options=options, service=service)
            
            # Construct the direct rpt (report) URL for Yandex image view
            search_url = f"https://yandex.com/images/search?rpt=imageview&url={image_url}"
            driver.get(search_url)

            print("[bold yellow]Waiting for Yandex results page to render...[/bold yellow]")
            # Aggressive timeout for high-latency or bot-throttled environments
            wait = WebDriverWait(driver, 40)

            # Polling for the results list container
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "li.CbirSites-Item")))

            results = []
            # Scrape each result container item
            result_containers = driver.find_elements(By.CSS_SELECTOR, "li.CbirSites-Item")

            print(f"[bold green]Found {len(result_containers)} potential results on Yandex. Processing...[/bold green]")

            for container in result_containers:
                try:
                    title_element = container.find_element(By.CSS_SELECTOR, "div.CbirSites-ItemTitle")
                    link_element = container.find_element(By.CSS_SELECTOR, "a.CbirSites-ItemLink")
                    
                    title = title_element.text
                    link = link_element.get_attribute('href')
                    
                    if link and title:
                        results.append({
                            "title": title,
                            "link": link,
                            "description": f"Source: {urlparse(link).netloc}"
                        })
                except Exception:
                    # Silently skip malformed or dynamic result nodes
                    continue
            
            return results

        except Exception as e:
            # Persistent state dump for post-mortem debugging of scraping failures
            if driver:
                driver.save_screenshot("debug_yandex.png")
                with open("debug_yandex.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print("[bold red]Error during Yandex search. 'debug_yandex.png' and 'debug_yandex.html' saved for analysis.[/bold red]")
            
            raise Exception(f"Selenium/Yandex automation failure: {e}")
        finally:
            # Critical: Ensure process group teardown to prevent zombie browser instances
            if driver:
                driver.quit()

# --- Testing / CLI Standalone Utility ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SmartSearch Standalone Utility - Local and Remote Intelligence Extraction.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-d", "--dir_path", type=str, help="Directory target for local analysis.")
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-r", "--regex", type=str, help="Custom regex for local search.")
    group.add_argument("-e", "--extract", action="store_true", help="Batch extract sensitive patterns.")
    group.add_argument("-g", "--google", type=str, help="Execute Google search query.")
    group.add_argument("--reverse-image", type=str, help="Target image URL for reverse search.")
    
    parser.add_argument("-p", "--pages", type=int, default=1, help="SERP pagination depth.")

    args = parser.parse_args()

    if args.google:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path='../.env')
        api_key = os.getenv("API_KEY_GOOGLE")
        engine_id = os.getenv("SEARCH_ENGINE_ID")
        if not api_key or not engine_id:
            print("Error: API_KEY_GOOGLE and SEARCH_ENGINE_ID required in .env configuration.")
        else:
            searcher = SmartSearch(api_key=api_key, engine_id=engine_id)
            resultados = searcher.search_google(args.google, pages=args.pages)
            print("\nGoogle Search Results:")
            for r in resultados:
                print(f"\n- Title: {r['title']}\n  Description: {r['description']}\n  Link: {r['link']}")
    
    elif args.reverse_image:
        searcher = SmartSearch()
        resultados = searcher.reverse_image_search(args.reverse_image)
        print("\nReverse Image Search Results:")
        for r in resultados:
            print(f"\n- Title: {r['title']}\n  Source: {r['description']}\n  Link: {r['link']}")

    elif args.dir_path:
        searcher = SmartSearch(dir_path=args.dir_path)
        if args.regex:
            resultados = searcher.regex_search(args.regex)
            print("\nRegex Match Results:")
            for file, results in resultados.items():
                print(f"\n--- {file} ---")
                for r in results:
                    print(f"  - {r}")
        if args.extract:
            searcher.extract_from_files()
    else:
        if args.regex or args.extract:
            print("A target directory (-d) is required for local analysis operations.")
