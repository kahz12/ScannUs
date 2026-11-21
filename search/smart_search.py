"""
search/smart_search.py — Orchestration facade for PII/secret extraction,
evidence construction, LLM redaction, local directory search and Yandex
reverse-image scraping.

The low-level pattern extractors live in :mod:`search.extractors` and are
re-exported here so existing imports continue working unchanged.
"""

import argparse
import os
import re
from functools import lru_cache
from urllib.parse import urlparse

from cli.ui import print_warn
from core.logging_setup import get_logger
from search.extractors.evidence import (
    _PEM_BLOCK_RE,
    _WITHHELD_EXTRACTORS,
    _written_forms,
    build_evidence,
    category_confidence,
    flatten_extracted,
    iter_extracted,
    redact_for_model,
    redact_sensitive,
)
from search.extractors.pii import (
    _PHONE_REGIONS,
    _card_brand_ok,
    _col_id_kind,
    _cpf_is_valid,
    _cuit_is_valid,
    _decode_email_obfuscation,
    _dni_es_is_valid,
    _extract_col_id,
    _extract_cpf,
    _extract_credit_cards,
    _extract_cuit,
    _extract_dni,
    _extract_emails_from_html,
    _extract_emails_from_text,
    _extract_ibans,
    _extract_nit,
    _extract_phones_from_html,
    _extract_phones_from_text,
    _extract_rfc,
    _extract_sin,
    _extract_ssn,
    _has_context,
    _iban_is_valid,
    _luhn_ok,
    _nit_check_digit,
    _ssn_us_is_valid,
    _to_e164,
)
from search.extractors.secrets import (
    _b58_decode,
    _btc_base58check_ok,
    _eth_eip55_ok,
    _extract_btc,
    _extract_eth,
    _extract_ipv4,
    _extract_ipv6,
    _extract_mac,
    _extract_secrets,
    _looks_like_jwt,
)

_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Optional Microsoft Presidio integration
# ---------------------------------------------------------------------------

_PRESIDIO_ENTITIES = frozenset({"PERSON", "LOCATION"})


@lru_cache(maxsize=1)
def _get_presidio():
    """
    Returns the shared Presidio analyzer, or None when it cannot be used.

    Loading it pulls in spaCy and a large language model, so it happens on first
    use instead of at import time and commands that extract no PII start faster.
    """
    try:
        from presidio_analyzer import AnalyzerEngine  # type: ignore
        return AnalyzerEngine()
    except ImportError:
        return None
    except (Exception, SystemExit):
        # SystemExit: spaCy exits the process when it cannot get the model.
        _log.warning("Presidio could not start", exc_info=True)
        print_warn("Presidio could not start, so its entities are skipped. "
                   "Install its model with: python -m spacy download en_core_web_lg")
        return None


def _extract_presidio_entities(text: str) -> dict[str, list[str]]:
    """
    Runs Microsoft Presidio (if installed) and returns a dict keyed by entity
    type with deduplicated match strings.
    """
    if not text:
        return {}
    analyzer = _get_presidio()
    if analyzer is None:
        return {}
    try:
        results = analyzer.analyze(text=text, language="en")
    except Exception:
        return {}

    grouped: dict[str, set[str]] = {}
    for r in results:
        value = text[r.start:r.end].strip()
        if r.entity_type not in _PRESIDIO_ENTITIES:
            continue
        if r.entity_type == "PERSON" and len(value.split()) < 2:
            continue
        grouped.setdefault(r.entity_type, set()).add(value)
    return {k: sorted(v) for k, v in grouped.items()}


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------

_NOT_USERNAMES = frozenset({
    "none", "null", "true", "false", "undefined", "password", "name", "email",
})

_SQL_RE = re.compile(
    r"(SQL(ite)?|MySQL|PostgreSQL|Oracle)\s(error|exception|failed|denied)"
    r"|(unclosed quotation mark|syntax error|invalid query)",
    re.IGNORECASE,
)
_USER_RE = re.compile(
    r'\b(user|username|login|usuario|nombre de usuario)\s*[:=]\s*[\'"]?([a-zA-Z0-9._-]{3,})[\'"]?',
    re.IGNORECASE,
)


def extract_information(text: str) -> dict:
    """
    Parse a text/HTML block and extract PII, leaked secrets and OSINT patterns.

    Returns a dict mapping category names to deduplicated, sorted lists of
    found values.
    """
    if not text:
        return {}

    extracted: dict[str, list] = {}

    emails = _extract_emails_from_text(text) | _extract_emails_from_html(text)
    if emails:
        extracted["emails"] = sorted(emails)

    phones = _extract_phones_from_text(text) | _extract_phones_from_html(text)
    if phones:
        extracted["phones"] = sorted(phones)

    sql_hits = {m.group(0).strip() for m in _SQL_RE.finditer(text) if m.group(0).strip()}
    if sql_hits:
        extracted["sql_errors"] = sorted(sql_hits)

    usernames = {m.group(2).rstrip("._-") for m in _USER_RE.finditer(text)}
    usernames = {u for u in usernames if len(u) >= 3 and u.lower() not in _NOT_USERNAMES}
    if usernames:
        extracted["usernames"] = sorted(usernames)

    for key, fn in (
        ("ibans", _extract_ibans),
        ("credit_cards", _extract_credit_cards),
        ("cuit", _extract_cuit),
        ("dni", _extract_dni),
        ("rfc", _extract_rfc),
        ("ssn", _extract_ssn),
        ("cpf", _extract_cpf),
        ("sin", _extract_sin),
        ("col_id", _extract_col_id),
        ("nit", _extract_nit),
        ("btc_addresses", _extract_btc),
        ("eth_addresses", _extract_eth),
    ):
        vals = fn(text)
        if vals:
            extracted[key] = sorted(vals)

    for category, values in _extract_secrets(text).items():
        if values:
            extracted[category] = sorted(values)

    for key, fn in (
        ("ipv4", _extract_ipv4),
        ("ipv6", _extract_ipv6),
        ("mac_addresses", _extract_mac),
    ):
        vals = fn(text)
        if vals:
            extracted[key] = sorted(vals)

    presidio = _extract_presidio_entities(text)
    if presidio:
        extracted["presidio"] = presidio

    return extracted


# ---------------------------------------------------------------------------
# Local file analysis + Yandex reverse-image Selenium backend
# ---------------------------------------------------------------------------

class SmartSearch:
    """Orchestrator for local file analysis and automated Reverse Image Search."""

    def __init__(self, dir_path=None):
        self.dir_path = dir_path
        self.files = self._read_files() if self.dir_path else {}

    def _read_files(self):
        files = {}
        if not os.path.isdir(self.dir_path):
            print(f"Error: The path '{self.dir_path}' is not a valid directory.")
            return files
        for filename in os.listdir(self.dir_path):
            file_path = os.path.join(self.dir_path, filename)
            if os.path.isfile(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        files[filename] = f.read()
                except Exception as e:
                    print(f"Error reading file {file_path}: {e}")
        return files

    def regex_search(self, regex):
        results_by_file = {}
        for filename, text in self.files.items():
            matches = re.findall(regex, text, re.IGNORECASE)
            if matches:
                results_by_file[filename] = matches
        return results_by_file

    def extract_from_files(self):
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

    def reverse_image_search(self, image_url):
        """Yandex reverse image search via headless Firefox Selenium."""
        try:
            from selenium import webdriver
            from selenium.webdriver.firefox.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.firefox.service import Service
        except ImportError:
            return []

        options = Options()
        options.add_argument("--headless")

        service = None
        termux_gecko = "/data/data/com.termux/files/usr/bin/geckodriver"
        if os.path.exists(termux_gecko):
            service = Service(executable_path=termux_gecko)

        driver = None
        try:
            driver = (webdriver.Firefox(options=options, service=service)
                      if service else webdriver.Firefox(options=options))
            search_url = f"https://yandex.com/images/search?rpt=imageview&url={image_url}"
            driver.get(search_url)
            WebDriverWait(driver, 40).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.CbirSites-Item"))
            )
            results = []
            for container in driver.find_elements(By.CSS_SELECTOR, "li.CbirSites-Item"):
                try:
                    title = container.find_element(
                        By.CSS_SELECTOR, "div.CbirSites-ItemTitle").text
                    link = container.find_element(
                        By.CSS_SELECTOR, "a.CbirSites-ItemLink").get_attribute("href")
                    if link and title:
                        results.append({
                            "title":       title,
                            "link":        link,
                            "description": f"Source: {urlparse(link).netloc}",
                        })
                except Exception:
                    continue
            return results
        except Exception:
            return []
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    _log.debug("selenium driver.quit() failed during cleanup", exc_info=True)


__all__ = [
    "SmartSearch",
    "extract_information",
    "iter_extracted",
    "flatten_extracted",
    "build_evidence",
    "category_confidence",
    "redact_sensitive",
    "redact_for_model",
    "_PHONE_REGIONS",
    "_PEM_BLOCK_RE",
    "_WITHHELD_EXTRACTORS",
    "_written_forms",
    "_card_brand_ok",
    "_col_id_kind",
    "_cpf_is_valid",
    "_cuit_is_valid",
    "_decode_email_obfuscation",
    "_dni_es_is_valid",
    "_extract_col_id",
    "_extract_cpf",
    "_extract_credit_cards",
    "_extract_cuit",
    "_extract_dni",
    "_extract_emails_from_html",
    "_extract_emails_from_text",
    "_extract_ibans",
    "_extract_nit",
    "_extract_phones_from_html",
    "_extract_phones_from_text",
    "_extract_rfc",
    "_extract_sin",
    "_extract_ssn",
    "_has_context",
    "_iban_is_valid",
    "_luhn_ok",
    "_nit_check_digit",
    "_ssn_us_is_valid",
    "_to_e164",
    "_b58_decode",
    "_btc_base58check_ok",
    "_eth_eip55_ok",
    "_extract_btc",
    "_extract_eth",
    "_extract_ipv4",
    "_extract_ipv6",
    "_extract_mac",
    "_extract_secrets",
    "_looks_like_jwt",
    "_get_presidio",
    "_extract_presidio_entities",
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SmartSearch Standalone Utility - Local and Remote Intelligence Extraction.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-d", "--dir_path", type=str, help="Directory target for local analysis.")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-r", "--regex", type=str, help="Custom regex for local search.")
    group.add_argument("-e", "--extract", action="store_true", help="Batch extract sensitive patterns.")
    group.add_argument("--reverse-image", type=str, help="Target image URL for reverse search.")

    args = parser.parse_args()

    if args.reverse_image:
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
