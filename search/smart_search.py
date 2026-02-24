# Necessary imports
import os
import re
import argparse
from urllib.parse import urlparse

# Local module imports
# Assumes 'googlesearch' is a local module containing the GoogleSearch class.
from search.engines.googlesearch import GoogleSearch

# --- Information Extraction Functions ---

def extract_information(text):
    """
    Parses a text block to extract sensitive or interesting information using regular expressions.
    
    Args:
        text (str): The text to analyze.
        
    Returns:
        dict: A dictionary where the keys are the information types (e.g. "emails")
              and the values are lists of the found matches.
    """
    if not text:
        return {}
    
    # Define regex patterns for each type of information to extract.
    patterns = {
        "emails": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        "telefonos": r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        "sql_errors": r'(SQL(ite)?|MySQL|PostgreSQL|Oracle)\s(error|exception|failed|denied)|(unclosed quotation mark|syntax error|invalid query)',
        "usernames": r'(user|username|login|usuario|nombre de usuario)[\s:=]+[\'"]?([a-zA-Z0-9._-]{3,})[\'"]?'
    }
    
    extracted_data = {}
    for key, pattern in patterns.items():
        # Use a set to store unique matches and avoid duplicates.
        unique_matches = set()
        # Iterate over all matches found in the text.
        for match in re.finditer(pattern, text, re.IGNORECASE):
            # For usernames and SQL errors, capture groups may vary.
            # Look for the first non-null group.
            if key in ["usernames", "sql_errors"]:
                found = next((g for g in match.groups() if g), None)
                if found:
                    unique_matches.add(found.strip())
            else:
                # For other patterns, take the full match.
                unique_matches.add(match.group(0).strip())
        
        if unique_matches:
            extracted_data[key] = list(unique_matches)
            
    return extracted_data

# --- Main Search Class ---

class SmartSearch:
    """
    Class encapsulating the logic to perform smart searches, either in
    local files or via web search engines like Google.
    Also includes reverse image search functionality.
    """
    def __init__(self, dir_path=None, api_key=None, engine_id=None):
        """
        Initializes the SmartSearch class.
        
        Args:
            dir_path (str, optional): Path to the directory for local searches.
            api_key (str, optional): API key for the Google search engine.
            engine_id (str, optional): Custom Search Engine ID for Google.
        """
        self.dir_path = dir_path
        # Read files from the directory if one is provided.
        self.files = self._read_files() if self.dir_path else {}
        # Initialize Google Search engine if credentials are provided.
        self.google_search_engine = GoogleSearch(api_key, engine_id) if api_key and engine_id else None

    def _read_files(self):
        """
        Reads all files in a directory and stores their content.
        (Currently not used in the main application flow, but available).
        """
        files = {}
        if not os.path.isdir(self.dir_path):
            print(f"Error: La ruta '{self.dir_path}' no es un directorio válido.")
            return files
        for archivo in os.listdir(self.dir_path):
            file_path = os.path.join(self.dir_path, archivo)
            if os.path.isfile(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        files[archivo] = f.read()
                except Exception as e:
                    print(f"Error al leer el archivo {file_path}: {e}")
        return files

    def regex_search(self, regex):
        """
        Performs a search with a regular expression on the loaded local files.
        (Currently not used in the main flow).
        """
        coincidencias = {}
        for file, text in self.files.items():
            matches = re.findall(regex, text, re.IGNORECASE)
            if matches:
                coincidencias[file] = matches
        return coincidencias

    def extract_from_files(self):
        """
        Extracts information (emails, phones, etc.) from the loaded local files.
        (Currently not used in the main flow).
        """
        all_extracted_data = {}
        for file, text in self.files.items():
            print(f"\n--- Analizando fichero: {file} ---")
            extracted_data = extract_information(text)
            if extracted_data:
                all_extracted_data[file] = extracted_data
                for key, values in extracted_data.items():
                    print(f"  -> {key.replace('_', ' ').capitalize()}:")
                    for value in values:
                        print(f"     - {value}")
            else:
                print("  No se encontró información relevante.")
        return all_extracted_data

    def search_google(self, query, pages=1):
        """
        Performs a Google search using the custom search engine.
        
        Args:
            query (str): The search query.
            pages (int): The number of result pages to fetch.
            
        Returns:
            list: A list of search results.
        """
        if not self.google_search_engine:
            raise Exception("Google Search is not initialized. Provide an API key and engine ID.")
        return self.google_search_engine.search(query, pages=pages)

    def reverse_image_search(self, image_url):
        """
        Performs a reverse image search using Yandex Images via Selenium.
        This method automates a browser in headless mode to perform the search.
        
        Args:
            image_url (str): The URL of the image to search for.
            
        Returns:
            list: A list of dictionaries with the results (title, link, description).
        """
        # Specific Selenium imports, done here so they are only loaded if this function is used.
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.firefox.service import Service

        # Configure Firefox options to run in headless mode.
        options = Options()
        options.add_argument("--headless")
        
        # Path to the browser driver (geckodriver for Firefox).
        # This path is hardcoded for a specific Termux environment.
        geckodriver_path = "/data/data/com.termux/files/usr/bin/geckodriver"
        service = Service(executable_path=geckodriver_path)

        driver = None
        try:
            print("[bold yellow]Iniciando Firefox en modo headless para Yandex...[/bold yellow]")
            driver = webdriver.Firefox(options=options, service=service)
            
            # Build the Yandex search URL for reverse image search.
            search_url = f"https://yandex.com/images/search?rpt=imageview&url={image_url}"
            driver.get(search_url)

            print("[bold yellow]Esperando a que la página de resultados de Yandex cargue...[/bold yellow]")
            # Explicit wait to give the page time to fully load (up to 40 seconds).
            wait = WebDriverWait(driver, 40)

            # Wait until the results container appears, which indicates search is done.
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "li.CbirSites-Item")))

            results = []
            # Find all elements containing a search result.
            result_containers = driver.find_elements(By.CSS_SELECTOR, "li.CbirSites-Item")

            print(f"[bold green]Se encontraron {len(result_containers)} posibles resultados en Yandex. Procesando...[/bold green]")

            for container in result_containers:
                try:
                    # Extract title and link for each result.
                    title_element = container.find_element(By.CSS_SELECTOR, "div.CbirSites-ItemTitle")
                    link_element = container.find_element(By.CSS_SELECTOR, "a.CbirSites-ItemLink")
                    
                    title = title_element.text
                    link = link_element.get_attribute('href')
                    
                    if link and title:
                        results.append({
                            "title": title,
                            "link": link,
                            "description": f"Fuente: {urlparse(link).netloc}"
                        })
                except Exception:
                    # If there's an error with an individual result, skip and continue.
                    continue
            
            return results

        except Exception as e:
            # If a generic error occurs during the scraping process...
            if driver:
                # ...save a screenshot and HTML for debugging.
                driver.save_screenshot("debug_yandex.png")
                with open("debug_yandex.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print("[bold red]Error durante la búsqueda con Yandex. Se han guardado 'debug_yandex.png' y 'debug_yandex.html' para análisis.[/bold red]")
            
            # Raise an exception so the caller knows the search failed.
            raise Exception(f"Error with Selenium/Yandex: {e}")
        finally:
            # Ensure the browser closes properly, even if errors occur.
            if driver:
                driver.quit()

# --- Main Execution Block (for testing and using as standalone script) ---
if __name__ == "__main__":
    # Configure the argument parser for when the script is run directly.
    parser = argparse.ArgumentParser(
        description="Herramienta para realizar búsquedas en ficheros locales o en la web.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-d", "--dir_path", type=str, help="Ruta al directorio para búsquedas locales.")
    
    # Mutually exclusive group: only one option can be used at a time.
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-r", "--regex", type=str, help="Expresión regular para búsqueda local.")
    group.add_argument("-e", "--extract", action="store_true", help="Extrae información predefinida de ficheros locales.")
    group.add_argument("-g", "--google", type=str, help="Término de búsqueda para Google.")
    group.add_argument("--reverse-image", type=str, help="URL de una imagen para búsqueda inversa.")
    
    parser.add_argument("-p", "--pages", type=int, default=1, help="Número de páginas para la búsqueda en Google.")

    args = parser.parse_args()

    # Logic to handle provided arguments.
    if args.google:
        from dotenv import load_dotenv
        # Load environment variables from a .env file in the parent directory.
        load_dotenv(dotenv_path='../.env')
        api_key = os.getenv("API_KEY_GOOGLE")
        engine_id = os.getenv("SEARCH_ENGINE_ID")
        if not api_key or not engine_id:
            print("Error: Se requieren las variables API_KEY_GOOGLE y SEARCH_ENGINE_ID en el fichero .env.")
        else:
            searcher = SmartSearch(api_key=api_key, engine_id=engine_id)
            resultados = searcher.search_google(args.google, pages=args.pages)
            print("\nResultados de la búsqueda en Google:")
            for r in resultados:
                print(f"\n- Título: {r['title']}\n  Descripción: {r['description']}\n  Enlace: {r['link']}")
    
    elif args.reverse_image:
        searcher = SmartSearch()
        resultados = searcher.reverse_image_search(args.reverse_image)
        print("\nResultados de la búsqueda inversa de imagen:")
        for r in resultados:
            print(f"\n- Título: {r['title']}\n  Fuente: {r['description']}\n  Enlace: {r['link']}")

    elif args.dir_path:
        searcher = SmartSearch(dir_path=args.dir_path)
        if args.regex:
            resultados = searcher.regex_search(args.regex)
            print("\nResultados de la búsqueda con Regex:")
            for file, results in resultados.items():
                print(f"\n--- {file} ---")
                for r in results:
                    print(f"  - {r}")
        if args.extract:
            searcher.extract_from_files()
    else:
        # If local search arguments are used without specifying a directory.
        if args.regex or args.extract:
            print("Debe proporcionar una ruta de directorio con -d para búsquedas locales.")
