# Core system imports
import os
import re
import html
import argparse
from urllib.parse import urlparse

import phonenumbers

# Engine-specific imports
from search.engines.googlesearch import GoogleSearch
from core.logging_setup import get_logger

_log = get_logger(__name__)

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
# Phone number extraction helpers — backed by Google's libphonenumber
# ---------------------------------------------------------------------------

# Regions tried in addition to fully international (``+``-prefixed) numbers.
# Order matters only for picking which region's parser claims an ambiguous
# domestic number first; canonical E.164 deduplication handles overlaps.
_PHONE_REGIONS = ("US", "ES", "MX", "AR", "GB")


def _to_e164(num) -> str | None:
    """Return the E.164 canonical form of *num* if it is a valid number."""
    if not phonenumbers.is_valid_number(num):
        return None
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def _extract_phones_from_text(text: str) -> set[str]:
    """
    Extracts phone numbers from *text* using libphonenumber.

    Strategy:
      1. Scan for fully-international (``+CC…``) numbers via region ``ZZ``.
      2. Re-scan under a small set of common regions to catch domestically
         formatted numbers (``(555) 867-5309``, ``5558675309``,
         ``912 34 56 78`` …).
      3. Deduplicate by E.164 canonical form so the same number written in
         different styles is reported once. The human-readable form is the
         one originally written in the text.
    """
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
            seen_canonical[canonical] = text[match.start:match.end].strip()

    return set(seen_canonical.values())


def _extract_phones_from_html(text: str) -> set[str]:
    """
    Extracts phone numbers from ``href="tel:..."`` attributes in HTML source,
    validated via libphonenumber.
    """
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
# Leaked secrets — high-confidence token signatures
# ---------------------------------------------------------------------------
#
# Each pattern matches a token format whose prefix and length make false
# positives unlikely. We intentionally do NOT chase generic 32/40-char hex
# blobs — those flag every commit hash and content-addressed asset in the
# wild. The dict is keyed by output category; values are compiled regexes.

import base64 as _b64
import ipaddress as _ipaddr
import json as _json

_SECRET_PATTERNS: dict[str, "re.Pattern[str]"] = {
    # AWS — IAM long-lived (AKIA) and STS short-lived (ASIA) access keys
    "aws_access_keys": re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b"),
    # GitHub: classic PATs (ghp_/gho_/ghu_/ghs_/ghr_) and fine-grained (github_pat_…)
    "github_tokens": re.compile(
        r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{82})\b"
    ),
    # GitLab personal access token (modern 16+ prefix)
    "gitlab_tokens": re.compile(r"\b(glpat-[A-Za-z0-9_\-]{20,})\b"),
    # Slack — bot/user/app/refresh/legacy tokens
    "slack_tokens": re.compile(r"\b(xox[abprs]-[A-Za-z0-9\-]{10,})\b"),
    # Stripe — live and test secret/restricted/publishable keys
    "stripe_keys": re.compile(r"\b((?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,})\b"),
    # Google API key — always 39 chars, "AIza" prefix
    "google_api_keys": re.compile(r"\b(AIza[0-9A-Za-z_\-]{35})\b"),
    # Discord bot token — three base64-ish parts joined by dots
    "discord_tokens": re.compile(
        r"\b([MN][A-Za-z0-9_\-]{23}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,})\b"
    ),
    # Telegram bot token — bot_id:35-char secret
    "telegram_tokens": re.compile(r"\b(\d{8,10}:[A-Za-z0-9_\-]{35})\b"),
    # PEM-encoded private key (RSA, EC, DSA, OpenSSH, PKCS#8)
    "private_keys": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |)PRIVATE KEY-----"
    ),
}

# JWTs are validated structurally because the regex alone fires on any
# string starting with "eyJ" — we additionally require the header to decode
# to JSON containing an "alg" field.
_JWT_RE = re.compile(r"\b(eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,})\b")


def _looks_like_jwt(token: str) -> bool:
    """Return True if the token's header decodes to a JSON object with an ``alg`` field."""
    head = token.split(".", 1)[0]
    # base64url padding may be missing
    head_padded = head + "=" * (-len(head) % 4)
    try:
        decoded = _b64.urlsafe_b64decode(head_padded.encode("ascii"))
        payload = _json.loads(decoded)
    except Exception:
        return False
    return isinstance(payload, dict) and "alg" in payload


def _extract_secrets(text: str) -> dict[str, set[str]]:
    """
    Scan *text* for leaked-token signatures and return a dict keyed by token
    category, mapping to a set of matched strings.

    Strategy:
      - Each regex is anchored by a vendor-specific prefix (e.g. ``AKIA``,
        ``ghp_``, ``AIza``) to suppress noise.
      - JWTs are post-filtered by structurally decoding the header.
      - Output categories are independent — a single line may surface in
        several (e.g. a stripped key embedded inside an env-style file).
    """
    found: dict[str, set[str]] = {}
    for category, rx in _SECRET_PATTERNS.items():
        for m in rx.finditer(text):
            value = m.group(1) if m.groups() else m.group(0)
            found.setdefault(category, set()).add(value.strip())

    jwts = {m.group(1) for m in _JWT_RE.finditer(text) if _looks_like_jwt(m.group(1))}
    if jwts:
        found["jwt_tokens"] = jwts
    return found


# ---------------------------------------------------------------------------
# Cryptocurrency wallet addresses
# ---------------------------------------------------------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def _b58_decode(s: str) -> bytes | None:
    """Decode a base58-encoded string. Returns None if any character is invalid."""
    num = 0
    for ch in s:
        if ch not in _B58_INDEX:
            return None
        num = num * 58 + _B58_INDEX[ch]
    # Restore leading-zero bytes encoded as leading '1's in base58
    n_pad = len(s) - len(s.lstrip("1"))
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * n_pad + body


def _btc_base58check_ok(addr: str) -> bool:
    """Validate a P2PKH/P2SH Bitcoin address via base58check (double-SHA256 checksum)."""
    import hashlib
    raw = _b58_decode(addr)
    if raw is None or len(raw) != 25:
        return False
    payload, checksum = raw[:-4], raw[-4:]
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] == checksum


def _extract_btc(text: str) -> set[str]:
    """
    Extract Bitcoin addresses (P2PKH/P2SH via base58check, Bech32 by prefix shape).
    Bech32 is matched structurally only — full checksum validation would require
    pulling in a dependency for a single feature.
    """
    found: set[str] = set()
    for m in re.finditer(r"\b([13][1-9A-HJ-NP-Za-km-z]{25,34})\b", text):
        cand = m.group(1)
        if _btc_base58check_ok(cand):
            found.add(cand)
    for m in re.finditer(r"\b(bc1[02-9ac-hj-np-z]{6,87})\b", text):
        found.add(m.group(1))
    return found


def _eth_eip55_ok(addr: str) -> bool:
    """
    Validate an Ethereum address's EIP-55 mixed-case checksum.
    All-lowercase or all-uppercase addresses pass through (no checksum to verify).
    Mixed-case addresses are rejected when pycryptodome is available and the
    Keccak-256 checksum doesn't match; structurally accepted if it isn't.
    """
    body = addr[2:]
    if body == body.lower() or body == body.upper():
        return True  # no checksum applied — accept structurally
    # Keccak-256 of the lowercase hex string
    try:
        from Crypto.Hash import keccak  # type: ignore
        h = keccak.new(digest_bits=256)
        h.update(body.lower().encode("ascii"))
        digest = h.hexdigest()
    except Exception:
        # No keccak available — fall back to structural acceptance
        return True
    for i, ch in enumerate(body):
        if ch.isalpha():
            should_upper = int(digest[i], 16) >= 8
            if should_upper != ch.isupper():
                return False
    return True


def _extract_eth(text: str) -> set[str]:
    """Extract Ethereum addresses (``0x`` + 40 hex chars), EIP-55 checked when mixed-case."""
    found: set[str] = set()
    for m in re.finditer(r"\b(0x[a-fA-F0-9]{40})\b", text):
        cand = m.group(1)
        if _eth_eip55_ok(cand):
            found.add(cand)
    return found


# ---------------------------------------------------------------------------
# Additional national identifiers: US SSN, BR CPF, CA SIN
# ---------------------------------------------------------------------------

def _ssn_us_is_valid(area: str, group: str, serial: str) -> bool:
    """US SSN structural validity: rejects reserved ranges (000/666/9xx area, 00 group, 0000 serial)."""
    if area in ("000", "666") or area.startswith("9"):
        return False
    if group == "00" or serial == "0000":
        return False
    return True


def _extract_ssn(text: str) -> set[str]:
    """Extract US SSNs (``###-##-####`` only — bare-digit form is too noisy)."""
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


# ---------------------------------------------------------------------------
# Network identifiers: public IPv4, IPv6, MAC
# ---------------------------------------------------------------------------

def _extract_ipv4(text: str) -> set[str]:
    """Extract public IPv4 addresses (filters RFC1918, loopback, link-local, multicast, reserved)."""
    found: set[str] = set()
    for m in re.finditer(r"\b((?:\d{1,3}\.){3}\d{1,3})\b", text):
        try:
            ip = _ipaddr.IPv4Address(m.group(1))
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast \
                or ip.is_reserved or ip.is_unspecified:
            continue
        found.add(str(ip))
    return found


def _extract_ipv6(text: str) -> set[str]:
    """Extract public IPv6 addresses. Uses the stdlib validator on candidates with ``:``."""
    found: set[str] = set()
    # Coarse pre-filter — at least three colons and only IPv6-legal chars
    for m in re.finditer(r"(?<![0-9A-Fa-f:])([0-9A-Fa-f:]{4,})(?![0-9A-Fa-f:])", text):
        cand = m.group(1)
        if cand.count(":") < 2:
            continue
        try:
            ip = _ipaddr.IPv6Address(cand)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast \
                or ip.is_reserved or ip.is_unspecified:
            continue
        found.add(str(ip))
    return found


def _extract_mac(text: str) -> set[str]:
    """Extract MAC addresses (``XX:XX:XX:XX:XX:XX`` or ``XX-XX-XX-XX-XX-XX``)."""
    found: set[str] = set()
    for m in re.finditer(r"\b((?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2})\b", text):
        found.add(m.group(1).lower().replace("-", ":"))
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
    Parse a text/HTML block and extract PII and OSINT-relevant patterns.

    Handling per category:
    - Emails: decodes common obfuscation, supports long TLDs, filters likely
      false positives, and also reads mailto: hrefs.
    - Phones: parses international and domestic formats via libphonenumber,
      deduplicated by E.164 canonical form; also reads tel: hrefs.
    - HTML:   mailto:/tel: attributes are extracted alongside visible text.
    - Also: SQL-error signatures, usernames, national IDs, financial and crypto
      identifiers, leaked secrets, and public network addresses.

    Args:
        text: Raw input text (may contain HTML markup).

    Returns:
        dict mapping category names to deduplicated, sorted lists of found values.
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

    # --- SQL Errors ---
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

    # --- Usernames ---
    # The pattern includes Spanish-language field labels ("usuario", "nombre de
    # usuario") because scraped target content may be in Spanish — these are
    # search keywords applied to external data, not Spanish identifiers in our code.
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

    # --- SSN (United States) ---
    ssns = _extract_ssn(text)
    if ssns:
        extracted['ssn'] = sorted(ssns)

    # --- CPF (Brazil) ---
    cpfs = _extract_cpf(text)
    if cpfs:
        extracted['cpf'] = sorted(cpfs)

    # --- SIN (Canada) ---
    sins = _extract_sin(text)
    if sins:
        extracted['sin'] = sorted(sins)

    # --- Crypto wallets ---
    btcs = _extract_btc(text)
    if btcs:
        extracted['btc_addresses'] = sorted(btcs)
    eths = _extract_eth(text)
    if eths:
        extracted['eth_addresses'] = sorted(eths)

    # --- Leaked tokens / API keys ---
    for category, values in _extract_secrets(text).items():
        if values:
            extracted[category] = sorted(values)

    # --- Network identifiers (public scope only) ---
    ipv4 = _extract_ipv4(text)
    if ipv4:
        extracted['ipv4'] = sorted(ipv4)
    ipv6 = _extract_ipv6(text)
    if ipv6:
        extracted['ipv6'] = sorted(ipv6)
    macs = _extract_mac(text)
    if macs:
        extracted['mac_addresses'] = sorted(macs)

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
        for filename in os.listdir(self.dir_path):
            file_path = os.path.join(self.dir_path, filename)
            if os.path.isfile(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        files[filename] = f.read()
                except Exception as e:
                    print(f"Error reading file {file_path}: {e}")
        return files

    def regex_search(self, regex):
        """
        Executes an arbitrary regex search against the in-memory file cache.

        Args:
            regex (str): Regular expression pattern to match against each file's text.

        Returns:
            dict: Mapping of filename → list of matched strings for every file
                  that contains at least one match. Empty dict if no hits.
        """
        results_by_file = {}
        for filename, text in self.files.items():
            matches = re.findall(regex, text, re.IGNORECASE)
            if matches:
                results_by_file[filename] = matches
        return results_by_file

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
        Yandex reverse image search via Selenium (one of several engines —
        see ``search.reverse_image_engines`` for the orchestrated fallback chain).

        Returns ``[]`` on any failure (missing browser, geckodriver not found,
        selector drift, network error) so callers can compose this with other
        engines without exception handling.
        """
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

        # Resolve geckodriver: prefer PATH (Linux/Windows primary targets),
        # fall back to the Termux absolute path only if it actually exists.
        service: "Service | None" = None
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
