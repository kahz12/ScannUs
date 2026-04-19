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
# IBAN — ISO 13616 format + mod-97 checksum
# ---------------------------------------------------------------------------

# Per-country IBAN length map (partial — covers the most common jurisdictions).
_IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16,
    "BG": 22, "BH": 22, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28,
    "CZ": 24, "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24,
    "FI": 18, "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18,
    "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IQ": 23,
    "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32,
    "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22,
    "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15, "PK": 24,
    "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24,
    "SC": 31, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "ST": 25, "SV": 28,
    "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20,
}


def _iban_is_valid(candidate: str) -> bool:
    """Validates an IBAN string via ISO 13616 country-length + mod-97 checksum."""
    raw = re.sub(r"\s+", "", candidate).upper()
    if len(raw) < 15 or not raw[:2].isalpha() or not raw[2:4].isdigit():
        return False
    expected = _IBAN_LENGTHS.get(raw[:2])
    if expected and len(raw) != expected:
        return False
    # Rearrange: move the first four chars to the end, then map letters → digits.
    rearranged = raw[4:] + raw[:4]
    numeric = "".join(
        ch if ch.isdigit() else str(ord(ch) - 55) for ch in rearranged
    )
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def _extract_ibans(text: str) -> set[str]:
    """Finds IBAN candidates and returns only those that pass the checksum."""
    pattern = re.compile(
        r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,8}(?:[ ]?[A-Z0-9]{1,4})?)\b"
    )
    found: set[str] = set()
    for m in pattern.finditer(text):
        candidate = m.group(1)
        if _iban_is_valid(candidate):
            found.add(re.sub(r"\s+", "", candidate).upper())
    return found


# ---------------------------------------------------------------------------
# Credit cards — Luhn-verified
# ---------------------------------------------------------------------------

def _luhn_ok(number: str) -> bool:
    """Returns True if ``number`` (digits-only) passes the Luhn checksum."""
    total = 0
    reverse_digits = number[::-1]
    for i, ch in enumerate(reverse_digits):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _extract_credit_cards(text: str) -> set[str]:
    """
    Extracts credit/debit card numbers from text.

    Candidates are 13–19 digit sequences (with optional spaces or hyphens)
    that pass the Luhn checksum. Returns digit-only canonical forms.
    """
    pattern = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
    found: set[str] = set()
    for m in pattern.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            found.add(digits)
    return found


# ---------------------------------------------------------------------------
# Country-specific identifiers: CUIT (AR), DNI (ES/AR), RFC (MX)
# ---------------------------------------------------------------------------

def _cuit_is_valid(digits: str) -> bool:
    """Argentine CUIT/CUIL — 11 digits with mod-11 check digit."""
    if len(digits) != 11 or not digits.isdigit():
        return False
    weights = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    total = sum(int(d) * w for d, w in zip(digits[:10], weights))
    rem = total % 11
    check = 0 if rem == 0 else (11 - rem)
    if check == 10:
        check = 9
    return check == int(digits[-1])


def _extract_cuit(text: str) -> set[str]:
    """Extracts Argentine CUIT/CUIL identifiers in ``XX-XXXXXXXX-X`` form."""
    pattern = re.compile(r"\b(\d{2}[- ]?\d{8}[- ]?\d)\b")
    found: set[str] = set()
    for m in pattern.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if _cuit_is_valid(digits):
            found.add(f"{digits[:2]}-{digits[2:10]}-{digits[10]}")
    return found


def _dni_es_is_valid(candidate: str) -> bool:
    """Spanish DNI — 8 digits + letter from the mod-23 alphabet."""
    letters = "TRWAGMYFPDXBNJZSQVHLCKE"
    if len(candidate) != 9 or not candidate[:8].isdigit() or not candidate[8].isalpha():
        return False
    return candidate[8].upper() == letters[int(candidate[:8]) % 23]


def _extract_dni(text: str) -> set[str]:
    """
    Extracts DNI-style identifiers.

    - Spanish DNI: 8 digits + mod-23 check letter (validated).
    - Argentine DNI: 7–8 bare digits preceded by a ``DNI``/``D.N.I.`` marker.
    """
    found: set[str] = set()

    for m in re.finditer(r"\b(\d{8}[A-HJ-NP-TV-Z])\b", text, re.IGNORECASE):
        cand = m.group(1).upper()
        if _dni_es_is_valid(cand):
            found.add(cand)

    for m in re.finditer(
        r"\bD\.?N\.?I\.?[:\s-]*([0-9]{1,3}(?:[.\s][0-9]{3}){1,2}|\d{7,8})\b",
        text, re.IGNORECASE,
    ):
        digits = re.sub(r"\D", "", m.group(1))
        if 7 <= len(digits) <= 8:
            found.add(digits)

    return found


def _extract_rfc(text: str) -> set[str]:
    """
    Extracts Mexican RFC identifiers (persons and corporations).

    Format:
      - Person:      4 letters + 6 digits (YYMMDD) + 3 homoclave chars
      - Corporation: 3 letters + 6 digits (YYMMDD) + 3 homoclave chars
    """
    pattern = re.compile(
        r"\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b",
        re.IGNORECASE,
    )
    found: set[str] = set()
    for m in pattern.finditer(text):
        cand = m.group(1).upper()
        date_part = cand[-9:-3]
        try:
            month = int(date_part[2:4])
            day = int(date_part[4:6])
        except ValueError:
            continue
        if 1 <= month <= 12 and 1 <= day <= 31:
            found.add(cand)
    return found


# ---------------------------------------------------------------------------
# Optional Microsoft Presidio integration
# ---------------------------------------------------------------------------

try:
    from presidio_analyzer import AnalyzerEngine  # type: ignore
    _PRESIDIO = AnalyzerEngine()
    _HAS_PRESIDIO = True
except Exception:
    _PRESIDIO = None
    _HAS_PRESIDIO = False


def _extract_presidio_entities(text: str) -> dict[str, list[str]]:
    """
    Runs Microsoft Presidio (if installed) and returns a dict keyed by entity
    type with deduplicated match strings. Returns an empty dict if Presidio
    is not available or the analyzer fails.
    """
    if not _HAS_PRESIDIO or not text:
        return {}
    try:
        results = _PRESIDIO.analyze(text=text, language="en")
    except Exception:
        return {}

    grouped: dict[str, set[str]] = {}
    for r in results:
        grouped.setdefault(r.entity_type, set()).add(text[r.start:r.end])
    return {k: sorted(v) for k, v in grouped.items()}


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

    # --- IBAN (mod-97 validated) ---
    ibans = _extract_ibans(text)
    if ibans:
        extracted['ibans'] = sorted(ibans)

    # --- Credit cards (Luhn validated) ---
    cards = _extract_credit_cards(text)
    if cards:
        extracted['credit_cards'] = sorted(cards)

    # --- CUIT/CUIL (Argentina) ---
    cuits = _extract_cuit(text)
    if cuits:
        extracted['cuit'] = sorted(cuits)

    # --- DNI (Spain / Argentina) ---
    dnis = _extract_dni(text)
    if dnis:
        extracted['dni'] = sorted(dnis)

    # --- RFC (Mexico) ---
    rfcs = _extract_rfc(text)
    if rfcs:
        extracted['rfc'] = sorted(rfcs)

    # --- Optional: Microsoft Presidio entities ---
    presidio = _extract_presidio_entities(text)
    if presidio:
        extracted['presidio'] = presidio

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
