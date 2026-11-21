"""
search/extractors/pii.py — Personal, financial and national ID extractors.

Includes:
  - Emails (plain, obfuscated, mailto: hrefs) with false-positive filtering
  - Phones (libphonenumber, international + domestic + tel: hrefs)
  - IBAN (ISO 13616 country lengths + mod-97)
  - Credit/debit cards (network prefix + Luhn + grouping/context)
  - National identifiers: AR CUIT/CUIL, ES/AR DNI, MX RFC, US SSN, BR CPF,
    CA SIN, Colombian CC/TI/CE and NIT
"""

import html
import re

import phonenumbers


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------

# Domains that are almost never real contact emails (false-positive heuristic)
_FP_EMAIL_DOMAINS = frozenset({
    "example.com", "example.org", "example.net", "test.com", "localhost",
    "domain.com", "email.com", "yoursite.com", "sentry.io",
})

# Top-level domains that are really file extensions, as in "logo@2x.png"
_ASSET_EXTENSIONS = frozenset({
    "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "css", "js", "map",
    "woff", "woff2", "ttf",
})

# Local-part patterns that indicate tooling / auto-generated addresses
_FP_EMAIL_LOCAL_RE = re.compile(
    r"^(noreply|no-reply|donotreply|mailer-daemon|postmaster|"
    r"webmaster|hostmaster|abuse|devnull|bounce|daemon|robot|bot|"
    r"\d+\.\d+\.\d+)$",          # version numbers like "1.2.3"
    re.IGNORECASE,
)


def _has_context(text: str, start: int, end: int, keywords: "re.Pattern[str]",
                 window: int = 40) -> bool:
    """Tells whether *keywords* appear close to ``text[start:end]``."""
    return bool(keywords.search(text[max(0, start - window):end + window]))


def _decode_email_obfuscation(text: str) -> str:
    """
    Decodes common anti-scraping obfuscation patterns in plain text so that
    the main email regex can capture them.

    Patterns handled:
    - HTML entities:  ``&#64;`` → ``@``, ``&#46;`` → ``.``
    - Bracketed tags: ``[at]``, ``(at)``, ``{at}`` → ``@``  (surrounding spaces consumed)
    - Spaced words:   ``user at domain dot com`` → ``user@domain.com``
    """
    text = html.unescape(text)

    # Bracketed/braced/parenthesised variants — consume surrounding whitespace too
    text = re.sub(r"\s*[\[\({]\s*at\s*[\]\)}]\s*", "@", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[\[\({]\s*dot\s*[\]\)}]\s*", ".", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[\[\({]\s*@\s*[\]\)}]\s*", "@", text, flags=re.IGNORECASE)

    # Space-surrounded "at" only when the domain side also uses obfuscated "dot",
    # so ordinary English prose ("available at acme.org") is not misread as an address.
    text = re.sub(
        r"(?<=\w)\s+at\s+(?=[\w-]+(?:\s+dot\s+[\w-]+)+)",
        "@", text, flags=re.IGNORECASE,
    )
    text = re.sub(r"(?<=\w)\s+dot\s+(?=\w)", ".", text, flags=re.IGNORECASE)

    # Final safety pass: remove stray spaces clinging to @ or .
    text = re.sub(r"\s*@\s*", "@", text)
    text = re.sub(r"(?<=\w)\s+\.\s+(?=\w)", ".", text)

    return text


_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9](?:[a-zA-Z0-9._%+\-]{0,62}[a-zA-Z0-9])?"       # local part
    r"@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"            # domain label
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*"     # subdomains
    r"\.[a-zA-Z]{2,63}",                                         # TLD
)


def _extract_emails_from_text(text: str) -> set[str]:
    """
    Extracts email addresses from raw text, including obfuscated variants.
    Applies a false-positive filter to remove likely non-human addresses.
    """
    clean = _decode_email_obfuscation(text)

    found = set()
    for match in _EMAIL_RE.finditer(clean):
        addr = match.group(0).lower()
        local, _, domain = addr.partition("@")

        if domain in _FP_EMAIL_DOMAINS:
            continue
        if domain.rsplit(".", 1)[-1] in _ASSET_EXTENSIONS:
            continue
        if _FP_EMAIL_LOCAL_RE.match(local):
            continue
        if re.search(r"^\d+\.\d+", local):
            continue

        found.add(addr)
    return found


def _extract_emails_from_html(text: str) -> set[str]:
    """Extracts emails from ``href="mailto:..."`` attributes in HTML source."""
    found = set()
    for match in re.finditer(r'href=["\']mailto:([^"\'?\s]+)', text, re.IGNORECASE):
        addr = match.group(1).lower().strip()
        if "@" in addr:
            found.add(addr)
    return found


# ---------------------------------------------------------------------------
# Phone numbers — backed by Google's libphonenumber
# ---------------------------------------------------------------------------

_PHONE_REGIONS = ("US", "ES", "MX", "AR", "CO", "GB")

_PHONE_CONTEXT_RE = re.compile(
    r"\b(?:tel|tlf|tfno|phone|telephone|tel[eé]fono|mobile|m[oó]vil|cell|celular|"
    r"whatsapp|fax|call|llama|llamar|llamanos|contact|contacto)\b",
    re.IGNORECASE,
)


def _to_e164(num) -> str | None:
    """Return the E.164 canonical form of *num* if it is a valid number."""
    if not phonenumbers.is_valid_number(num):
        return None
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def _extract_phones_from_text(text: str) -> set[str]:
    """Extracts phone numbers from *text* using libphonenumber."""
    seen_canonical: dict[str, str] = {}

    for region in ("ZZ", *_PHONE_REGIONS):
        try:
            matches = phonenumbers.PhoneNumberMatcher(text, region)
        except Exception:
            continue
        for match in matches:
            canonical = _to_e164(match.number)
            if not canonical or canonical in seen_canonical:
                continue
            written = text[match.start:match.end].strip()
            if written.isdigit() and not _has_context(
                    text, match.start, match.end, _PHONE_CONTEXT_RE):
                continue
            seen_canonical[canonical] = written

    return set(seen_canonical.values())


def _extract_phones_from_html(text: str) -> set[str]:
    """Extracts phone numbers from ``href="tel:..."`` attributes in HTML source."""
    seen_canonical: dict[str, str] = {}

    for match in re.finditer(r'href=["\']tel:([^"\'?\s]+)', text, re.IGNORECASE):
        raw = match.group(1).strip()
        for region in ("ZZ", *_PHONE_REGIONS):
            try:
                num = phonenumbers.parse(raw, region)
            except phonenumbers.NumberParseException:
                continue
            canonical = _to_e164(num)
            if canonical:
                seen_canonical.setdefault(canonical, raw)
                break

    return set(seen_canonical.values())


# ---------------------------------------------------------------------------
# IBAN — ISO 13616 format + mod-97 checksum
# ---------------------------------------------------------------------------

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
# Credit cards — brand prefix + Luhn, plus formatting or context
# ---------------------------------------------------------------------------

_CARD_CONTEXT_RE = re.compile(
    r"\b(?:card|tarjeta|visa|mastercard|amex|american express|discover|cvv|cvc|"
    r"credit|debit|cr[eé]dito|d[eé]bito)\b|\b(?:0[1-9]|1[0-2])[/-]\d{2,4}\b",
    re.IGNORECASE,
)
_CARD_GROUPED_RE = re.compile(
    r"\d{4}(?:[ -]\d{4}){3}(?:[ -]\d{3})?|\d{4}[ -]\d{6}[ -]\d{4,5}"
)


def _card_brand_ok(digits: str) -> bool:
    """Checks the issuer prefix and length of the main card networks."""
    length = len(digits)
    two, three, four = int(digits[:2]), int(digits[:3]), int(digits[:4])
    if digits[0] == "4":                                # Visa
        return length in (16, 19)
    if 51 <= two <= 55 or 2221 <= four <= 2720:         # Mastercard
        return length == 16
    if two in (34, 37):                                 # American Express
        return length == 15
    if four == 6011 or two == 65 or 644 <= three <= 649:  # Discover
        return length in (16, 19)
    if 300 <= three <= 305 or two in (36, 38):          # Diners Club
        return length == 14
    if 3528 <= four <= 3589:                            # JCB
        return length in (16, 19)
    if two == 62:                                       # UnionPay
        return 16 <= length <= 19
    return False


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
    """Extracts credit/debit card numbers from text."""
    pattern = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
    found: set[str] = set()
    for m in pattern.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if not (13 <= len(digits) <= 19 and _card_brand_ok(digits) and _luhn_ok(digits)):
            continue
        if _CARD_GROUPED_RE.fullmatch(m.group(0)) or _has_context(
                text, m.start(), m.end(), _CARD_CONTEXT_RE):
            found.add(digits)
    return found


# ---------------------------------------------------------------------------
# Country-specific identifiers: CUIT (AR), DNI (ES/AR), RFC (MX)
# ---------------------------------------------------------------------------

_CUIT_PREFIXES = frozenset({"20", "23", "24", "25", "26", "27", "30", "33", "34"})
_CUIT_CONTEXT_RE = re.compile(r"\b(?:cuit|cuil)\b", re.IGNORECASE)


def _cuit_is_valid(digits: str) -> bool:
    """Argentine CUIT/CUIL — 11 digits, a known type prefix, and a mod-11 check digit."""
    if len(digits) != 11 or not digits.isdigit() or digits[:2] not in _CUIT_PREFIXES:
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
    pattern = re.compile(r"(?<![\d+])(\d{2}[- ]?\d{8}[- ]?\d)(?!\d)")
    found: set[str] = set()
    for m in pattern.finditer(text):
        written = m.group(1)
        digits = re.sub(r"\D", "", written)
        if not _cuit_is_valid(digits):
            continue
        if written != digits or _has_context(text, m.start(), m.end(), _CUIT_CONTEXT_RE):
            found.add(f"{digits[:2]}-{digits[2:10]}-{digits[10]}")
    return found


def _dni_es_is_valid(candidate: str) -> bool:
    """Spanish DNI — 8 digits + letter from the mod-23 alphabet."""
    letters = "TRWAGMYFPDXBNJZSQVHLCKE"
    if len(candidate) != 9 or not candidate[:8].isdigit() or not candidate[8].isalpha():
        return False
    return candidate[8].upper() == letters[int(candidate[:8]) % 23]


def _extract_dni(text: str) -> set[str]:
    """Extracts Spanish (validated) and Argentine (labelled) DNI identifiers."""
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
    """Extracts Mexican RFC identifiers (persons and corporations)."""
    pattern = re.compile(r"\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE)
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
# Colombian identifiers: CC, TI, CE and NIT
# ---------------------------------------------------------------------------

_COL_NUMBER = r"(?P<number>\d{1,3}(?:[., ]\d{3}){1,3}|\d{6,11})(?!\d)"
_COL_NUMBER_PREFIX = r"\s*(?:(?i:n(?:o|ro|[°º]|[úu]mero))\.?\s*)?[:#-]?\s*"
_COL_ID_RE = re.compile(
    r"(?P<label>(?i:c[ée]dula\s+de\s+extranjer[íi]a|tarjeta\s+de\s+identidad"
    r"|c[ée]dula(?:\s+de\s+ciudadan[íi]a)?|\bc\.\s?c\.|\bt\.\s?i\.|\bc\.\s?e\.)"
    r"|\b(?:CC|TI|CE)\b)"
    + _COL_NUMBER_PREFIX + _COL_NUMBER
)
_NIT_RE = re.compile(
    r"\b(?i:nit)\b" + _COL_NUMBER_PREFIX
    + r"(?P<number>\d{1,3}(?:[.,]\d{3}){1,3}|\d{6,10})(?:\s*-\s*(?P<dv>\d))?(?!\d)"
)
_NIT_WEIGHTS = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)


def _col_id_kind(label: str) -> str:
    """Names the document a label introduces: CC, TI or CE."""
    compact = re.sub(r"[\s.]", "", label).lower()
    if "extranjer" in compact or compact == "ce":
        return "CE"
    if "tarjeta" in compact or compact == "ti":
        return "TI"
    return "CC"


def _extract_col_id(text: str) -> set[str]:
    """Extracts Colombian personal documents as ``"<kind> <digits>"`` (CC, TI, CE)."""
    found: set[str] = set()
    for m in _COL_ID_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group("number"))
        if 6 <= len(digits) <= 11:
            found.add(f"{_col_id_kind(m.group('label'))} {digits}")
    return found


def _nit_check_digit(digits: str) -> int:
    """The DIAN mod-11 verification digit of a NIT."""
    total = sum(int(d) * w for d, w in zip(reversed(digits), _NIT_WEIGHTS))
    rem = total % 11
    return rem if rem < 2 else 11 - rem


def _extract_nit(text: str) -> set[str]:
    """Extracts Colombian NITs after a ``NIT`` label, checking DIAN mod-11 when present."""
    found: set[str] = set()
    for m in _NIT_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group("number"))
        if not 6 <= len(digits) <= 10:
            continue
        dv = m.group("dv")
        if dv is None:
            found.add(digits)
        elif int(dv) == _nit_check_digit(digits):
            found.add(f"{digits}-{dv}")
    return found


# ---------------------------------------------------------------------------
# Additional national identifiers: US SSN, BR CPF, CA SIN
# ---------------------------------------------------------------------------

def _ssn_us_is_valid(area: str, group: str, serial: str) -> bool:
    """US SSN structural validity: rejects reserved ranges."""
    if area in ("000", "666") or area.startswith("9"):
        return False
    if group == "00" or serial == "0000":
        return False
    return True


def _extract_ssn(text: str) -> set[str]:
    """Extract US SSNs (``###-##-####`` only)."""
    found: set[str] = set()
    for m in re.finditer(r"\b(\d{3})-(\d{2})-(\d{4})\b", text):
        area, group, serial = m.groups()
        if _ssn_us_is_valid(area, group, serial):
            found.add(f"{area}-{group}-{serial}")
    return found


def _cpf_is_valid(digits: str) -> bool:
    """Brazilian CPF — 11 digits with two mod-11 check digits."""
    if len(digits) != 11 or not digits.isdigit() or digits == digits[0] * 11:
        return False
    for length in (9, 10):
        total = sum(int(digits[i]) * (length + 1 - i) for i in range(length))
        rem = (total * 10) % 11
        check = 0 if rem == 10 else rem
        if check != int(digits[length]):
            return False
    return True


def _extract_cpf(text: str) -> set[str]:
    """Extract Brazilian CPF identifiers in ``###.###.###-##`` form."""
    found: set[str] = set()
    for m in re.finditer(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b", text):
        digits = re.sub(r"\D", "", m.group(1))
        if _cpf_is_valid(digits):
            found.add(m.group(1))
    return found


def _extract_sin(text: str) -> set[str]:
    """Extract Canadian SINs (``###-###-###``) — validated via Luhn checksum."""
    found: set[str] = set()
    for m in re.finditer(r"\b(\d{3}-\d{3}-\d{3})\b", text):
        digits = re.sub(r"\D", "", m.group(1))
        if _luhn_ok(digits):
            found.add(m.group(1))
    return found
