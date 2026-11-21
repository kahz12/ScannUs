"""
search/extractors/evidence.py — Evidence records, confidence & LLM redaction.
"""

import hashlib
import re
from datetime import datetime, timezone

from search.extractors.pii import (
    _extract_col_id,
    _extract_cpf,
    _extract_credit_cards,
    _extract_cuit,
    _extract_dni,
    _extract_ibans,
    _extract_nit,
    _extract_rfc,
    _extract_sin,
    _extract_ssn,
)
from search.extractors.secrets import (
    _extract_btc,
    _extract_eth,
    _extract_mac,
    _extract_secrets,
)


# Categories that rest on format alone. Everything else has a checksum or a
# vendor prefix behind it, and Presidio entities are statistical guesses.
_MEDIUM_CONFIDENCE = frozenset({
    "phones", "usernames", "ipv4", "ipv6", "mac_addresses", "ssn", "rfc", "sql_errors",
    "col_id", "nit",
})


def category_confidence(category: str) -> str:
    """Returns how far a value of *category* can be trusted: high, medium or low."""
    if category.startswith("presidio_"):
        return "low"
    return "medium" if category in _MEDIUM_CONFIDENCE else "high"


def iter_extracted(data: dict):
    """
    Yields ``(category, value)`` pairs from an :func:`extract_information` result.

    Presidio entities are nested by type, so they come out flattened under
    categories such as ``presidio_person``.
    """
    for category, values in data.items():
        if isinstance(values, dict):
            for entity, entity_values in values.items():
                for value in entity_values:
                    yield f"{category}_{entity.lower()}", value
        else:
            for value in values:
                yield category, value


def flatten_extracted(data: dict) -> dict[str, list[str]]:
    """Groups an :func:`extract_information` result as ``category -> values``."""
    grouped: dict[str, list[str]] = {}
    for category, value in iter_extracted(data):
        grouped.setdefault(category, []).append(value)
    return grouped


def build_evidence(data: dict, text: str, source: str, tool: str) -> list[dict]:
    """
    Turns an :func:`extract_information` result into evidence records.

    Returns one dict per value with ``category``, ``value``, ``confidence``,
    ``source``, ``tool``, ``found_at`` (UTC) and ``content_sha256``.
    """
    found_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    content_sha256 = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
    return [
        {
            "category":       category,
            "value":          value,
            "confidence":     category_confidence(category),
            "source":         source,
            "tool":           tool,
            "found_at":       found_at,
            "content_sha256": content_sha256,
        }
        for category, value in iter_extracted(data)
    ]


# ---------------------------------------------------------------------------
# Withholding sensitive values from AI providers
# ---------------------------------------------------------------------------

_WITHHELD_EXTRACTORS = {
    "credit_cards": _extract_credit_cards,
    "ibans":        _extract_ibans,
    "cuit":         _extract_cuit,
    "dni":          _extract_dni,
    "rfc":          _extract_rfc,
    "ssn":          _extract_ssn,
    "cpf":          _extract_cpf,
    "sin":          _extract_sin,
    "col_id":       _extract_col_id,
    "nit":          _extract_nit,
}
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
    re.DOTALL,
)


def _written_forms(value: str) -> "re.Pattern[str]":
    """Matches *value* in text whatever spaces, dots, commas or dashes split it."""
    body = r"[\s.,\-/]{0,2}".join(re.escape(c) for c in value if c.isalnum())
    return re.compile(rf"(?<![0-9A-Za-z]){body}(?![0-9A-Za-z])", re.IGNORECASE)


def redact_sensitive(text: str) -> str:
    """
    Replaces card numbers, bank accounts, national IDs, crypto wallets, MACs
    and leaked secrets in *text* with ``[withheld: <category>]`` before sending
    text to an AI provider.
    """
    if not text:
        return text
    text = _PEM_BLOCK_RE.sub("[withheld: private_keys]", text)
    for category, values in _extract_secrets(text).items():
        for value in sorted(values, key=len, reverse=True):
            text = text.replace(value, f"[withheld: {category}]")
    for category, extract in (("btc_addresses", _extract_btc), ("eth_addresses", _extract_eth)):
        for value in sorted(extract(text), key=len, reverse=True):
            text = text.replace(value, f"[withheld: {category}]")
    for mac in sorted(_extract_mac(text), key=len, reverse=True):
        mac_re = re.compile(r"\b" + re.escape(mac).replace(":", "[:-]") + r"\b", re.IGNORECASE)
        text = mac_re.sub("[withheld: mac_addresses]", text)
    for category, extract in _WITHHELD_EXTRACTORS.items():
        for value in sorted(extract(text), key=len, reverse=True):
            target = value.split()[-1] if category == "col_id" else value
            text = _written_forms(target).sub(f"[withheld: {category}]", text)
    return text


def redact_for_model(value):
    """Applies :func:`redact_sensitive` to every string in nested lists and dicts."""
    if isinstance(value, str):
        return redact_sensitive(value)
    if isinstance(value, list):
        return [redact_for_model(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_model(item) for item in value)
    if isinstance(value, dict):
        return {key: redact_for_model(item) for key, item in value.items()}
    return value
