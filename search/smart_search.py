# Core system imports
import os
import re
import html
import argparse
from urllib.parse import urlparse

# Engine-specific imports
from search.engines.googlesearch import GoogleSearch

# ---------------------------------------------------------------------------
# PII Extraction — Helpers
# ---------------------------------------------------------------------------

# Domains that are almost never real contact emails (false-positive heuristic)
_FP_EMAIL_DOMAINS = frozenset({
    'example.com', 'example.org', 'example.net', 'test.com', 'localhost',
    'domain.com', 'email.com', 'yoursite.com', 'sentry.io',
})

# Local-part patterns that indicate tooling / auto-generated addresses
_FP_EMAIL_LOCAL_RE = re.compile(
    r'^(noreply|no-reply|donotreply|mailer-daemon|postmaster|'
    r'webmaster|hostmaster|abuse|devnull|bounce|daemon|robot|bot|'
    r'\d+\.\d+\.\d+)$',          # version numbers like "1.2.3"
    re.IGNORECASE
)

# Normalise obfuscated email text BEFORE running the main regex.
# Handles: [at], (at), " at ", [dot], (dot), " dot ", HTML entities like &#64;
def _decode_email_obfuscation(text: str) -> str:
    """
    Decodes common anti-scraping obfuscation patterns in plain text so that
    the main email regex can capture them.

    Patterns handled:
    - HTML entities:  ``&#64;`` → ``@``, ``&#46;`` → ``.``
    - Bracketed tags: ``[at]``, ``(at)``, ``{at}`` → ``@``  (surrounding spaces consumed)
    - Spaced words:   `` at `` → ``@``, `` dot `` → ``.``
    """
    # Decode HTML entities first (e.g. &#64; → @)
    text = html.unescape(text)

    # Bracketed/braced/parenthesised variants — consume surrounding whitespace too
    # e.g. "user [at] domain" → "user@domain"
    text = re.sub(r'\s*[\[\({]\s*at\s*[\]\)}]\s*', '@', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*[\[\({]\s*dot\s*[\]\)}]\s*', '.', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*[\[\({]\s*@\s*[\]\)}]\s*', '@', text, flags=re.IGNORECASE)

    # Space-surrounded keyword variants between word characters
    # e.g. "user at domain dot com" → "user@domain.com"
    text = re.sub(r'(?<=\w)\s+at\s+(?=\w)', '@', text, flags=re.IGNORECASE)
    text = re.sub(r'(?<=\w)\s+dot\s+(?=\w)', '.', text, flags=re.IGNORECASE)

    # Final safety pass: remove stray spaces that may still cling to @ or .
    # (handles edge cases like "user @ domain . com")
    text = re.sub(r'\s*@\s*', '@', text)
    text = re.sub(r'(?<=\w)\s+\.\s+(?=\w)', '.', text)

    return text



def _extract_emails_from_text(text: str) -> set[str]:
    """
    Extracts email addresses from raw text, including obfuscated variants.
    Applies a false-positive filter to remove likely non-human addresses.

    Returns a set of lowercase, deduplicated email strings.
    """
    # Decode obfuscation first so the regex works on clean text
    clean = _decode_email_obfuscation(text)

    # RFC-5321-inspired pattern — supports subdomains and long TLDs (e.g. .travel)
    EMAIL_RE = re.compile(
        r'[a-zA-Z0-9](?:[a-zA-Z0-9._%+\-]{0,62}[a-zA-Z0-9])?'   # local part
        r'@'
        r'[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'        # domain label
        r'(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*' # subdomains
        r'\.[a-zA-Z]{2,63}',                                        # TLD (up to 63 chars)
    )

    found = set()
    for match in EMAIL_RE.finditer(clean):
        addr = match.group(0).lower()
        local, _, domain = addr.partition('@')

        # Filter: domain in known false-positive list
        if domain in _FP_EMAIL_DOMAINS:
            continue
        # Filter: local part matches bot/tooling patterns
        if _FP_EMAIL_LOCAL_RE.match(local):
            continue
        # Filter: local part looks like a file path or semantic version
        if re.search(r'^\d+\.\d+', local):
            continue

        found.add(addr)
    return found


def _extract_emails_from_html(text: str) -> set[str]:
    """
    Extracts emails from ``href="mailto:..."`` attributes in HTML source.
    Complements the text-based extractor for pages that encode emails only
    in anchor tags without displaying them in visible content.
    """
    found = set()
    for match in re.finditer(r'href=["\']mailto:([^"\'?\s]+)', text, re.IGNORECASE):
        addr = match.group(1).lower().strip()
        if '@' in addr:
            found.add(addr)
    return found


# ---------------------------------------------------------------------------
# Phone number extraction helpers
# ---------------------------------------------------------------------------

def _normalize_phone(digits: str) -> str | None:
    """
    Strips all non-digit characters from a phone candidate and returns a
    canonical string only if the digit count is plausible (7–15 digits per
    ITU-T E.164).  Returns ``None`` for implausible counts.
    """
    d = re.sub(r'\D', '', digits)
    return d if 7 <= len(d) <= 15 else None


def _extract_phones_from_text(text: str) -> set[str]:
    """
    Extracts phone numbers from text using a broad international pattern,
    then normalises each candidate to its digit string for deduplication.

    Handles:
    - International prefix  ``+1``, ``+57``, ``+34``, …
    - Common separators     spaces, hyphens, dots, parentheses
    - North-American        ``(555) 867-5309``, ``555.867.5309``
    - European              ``+34 912 34 56 78``, ``+44 20 7946 0958``
    - Local 7-digit         ``867-5309``
    """
    PHONE_RE = re.compile(
        r'''
        (?:(?:\+|00)            # International prefix (+ or 00)
           [\d\s\-\.]{1,4})?   # Country code (up to 4 digits with separators)
        (?:[\(\[]?\d{2,4}[\)\]]?   # Area code (with optional parentheses)
           [\s\-\.]?)?
        \d{3,4}                  # Exchange number
        [\s\-\.]
        \d{3,4}                  # Subscriber number segment 1
        (?:[\s\-\.]\d{2,4})?     # Optional extra segment (European numbers)
        ''',
        re.VERBOSE,
    )

    seen_digits: set[str] = set()
    results: set[str] = set()

    for match in PHONE_RE.finditer(text):
        raw = match.group(0).strip()
        normalised = _normalize_phone(raw)
        if normalised and normalised not in seen_digits:
            seen_digits.add(normalised)
            # Store the human-readable form (trimmed), not the raw digit string
            results.add(raw)

    return results


def _extract_phones_from_html(text: str) -> set[str]:
    """
    Extracts phone numbers from ``href="tel:..."`` attributes in HTML source.
    """
    found: set[str] = set()
    for match in re.finditer(r'href=["\']tel:([^"\'?\s]+)', text, re.IGNORECASE):
        number = match.group(1).strip()
        norm = _normalize_phone(number)
        if norm:
            found.add(number)
    return found


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------

def extract_information(text: str) -> dict:
    """
    Parses a text/HTML block to extract PII and OSINT-relevant patterns.

    Improvements over the previous version:
    - Emails: obfuscation decoding, long TLD support, false-positive filter
    - Phones: international formats, multi-separator support, normalised dedup
    - HTML:   mailto:/tel: attribute extraction in addition to visible text
    - Misc:   SQL error and username patterns unchanged

    Args:
        text: Raw input text (may contain HTML markup).

    Returns:
        dict mapping category names to deduplicated lists of found values.
    """
    if not text:
        return {}

    extracted: dict[str, list] = {}

    # --- Emails ---
    emails = _extract_emails_from_text(text) | _extract_emails_from_html(text)
    if emails:
        extracted['emails'] = sorted(emails)

    # --- Phone numbers ---
    phones = _extract_phones_from_text(text) | _extract_phones_from_html(text)
    if phones:
        extracted['phones'] = sorted(phones)

    # --- SQL Errors (unchanged) ---
    SQL_RE = re.compile(
        r'(SQL(ite)?|MySQL|PostgreSQL|Oracle)\s(error|exception|failed|denied)'
        r'|(unclosed quotation mark|syntax error|invalid query)',
        re.IGNORECASE,
    )
    sql_hits = {
        next((g for g in m.groups() if g), None)
        for m in SQL_RE.finditer(text)
    }
    sql_hits.discard(None)
    if sql_hits:
        extracted['sql_errors'] = sorted(sql_hits)

    # --- Usernames (unchanged pattern) ---
    USER_RE = re.compile(
        r'(user|username|login|usuario|nombre de usuario)[\s:=]+[\'"]?([a-zA-Z0-9._-]{3,})[\'"]?',
        re.IGNORECASE,
    )
    usernames = {
        m.group(2).strip()
        for m in USER_RE.finditer(text)
        if m.group(2)
    }
    if usernames:
        extracted['usernames'] = sorted(usernames)

    return extracted


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
