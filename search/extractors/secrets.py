"""
search/extractors/secrets.py — Leaked credentials, crypto wallets & network IDs.

Includes:
  - Prefix-anchored vendor secrets (AWS, GitHub, GitLab, Slack, Stripe, Google,
    Discord, Telegram, PEM private keys) + structurally validated JWTs
  - Cryptocurrency addresses: Bitcoin (Base58Check + Bech32), Ethereum (EIP-55)
  - Public network identifiers: IPv4 (filtering private/version noise), IPv6, MAC
"""

import base64
import hashlib
import ipaddress
import json
import re


# ---------------------------------------------------------------------------
# Leaked secrets — high-confidence token signatures
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: dict[str, "re.Pattern[str]"] = {
    "aws_access_keys": re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b"),
    "github_tokens": re.compile(
        r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{82})\b"
    ),
    "gitlab_tokens": re.compile(r"\b(glpat-[A-Za-z0-9_\-]{20,})\b"),
    "slack_tokens": re.compile(r"\b(xox[abprs]-[A-Za-z0-9\-]{10,})\b"),
    "stripe_keys": re.compile(r"\b((?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,})\b"),
    "google_api_keys": re.compile(r"\b(AIza[0-9A-Za-z_\-]{35})\b"),
    "discord_tokens": re.compile(
        r"\b([MN][A-Za-z0-9_\-]{23}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,})\b"
    ),
    "telegram_tokens": re.compile(r"\b(\d{8,10}:[A-Za-z0-9_\-]{35})\b"),
    "private_keys": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |)PRIVATE KEY-----"
    ),
}

_JWT_RE = re.compile(r"\b(eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,})\b")


def _looks_like_jwt(token: str) -> bool:
    """Return True if the token's header decodes to a JSON object with an ``alg`` field."""
    head = token.split(".", 1)[0]
    head_padded = head + "=" * (-len(head) % 4)
    try:
        decoded = base64.urlsafe_b64decode(head_padded.encode("ascii"))
        payload = json.loads(decoded)
    except Exception:
        return False
    return isinstance(payload, dict) and "alg" in payload


def _extract_secrets(text: str) -> dict[str, set[str]]:
    """Scan *text* for leaked-token signatures and return ``{category: {values}}``."""
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
    n_pad = len(s) - len(s.lstrip("1"))
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * n_pad + body


def _btc_base58check_ok(addr: str) -> bool:
    """Validate a P2PKH/P2SH Bitcoin address via base58check (double-SHA256)."""
    raw = _b58_decode(addr)
    if raw is None or len(raw) != 25:
        return False
    payload, checksum = raw[:-4], raw[-4:]
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] == checksum


def _extract_btc(text: str) -> set[str]:
    """Extract Bitcoin addresses (P2PKH/P2SH via base58check, Bech32 structurally)."""
    found: set[str] = set()
    for m in re.finditer(r"\b([13][1-9A-HJ-NP-Za-km-z]{25,34})\b", text):
        cand = m.group(1)
        if _btc_base58check_ok(cand):
            found.add(cand)
    for m in re.finditer(r"\b(bc1[02-9ac-hj-np-z]{6,87})\b", text):
        found.add(m.group(1))
    return found


def _eth_eip55_ok(addr: str) -> bool:
    """Validate an Ethereum address's EIP-55 mixed-case checksum."""
    body = addr[2:]
    if body == body.lower() or body == body.upper():
        return True
    try:
        from Crypto.Hash import keccak  # type: ignore
        h = keccak.new(digest_bits=256)
        h.update(body.lower().encode("ascii"))
        digest = h.hexdigest()
    except Exception:
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
# Network identifiers: public IPv4, IPv6, MAC
# ---------------------------------------------------------------------------

_VERSION_PREFIX_RE = re.compile(
    r"\b(?:version|ver|build|release|firmware)[\s:=v.]*$"
    r"|\b(?:chrome|chromium|firefox|safari|edg|edge|opera|android)/$",
    re.IGNORECASE,
)


def _extract_ipv4(text: str) -> set[str]:
    """Extract public IPv4 addresses (filtering private/reserved/version numbers)."""
    found: set[str] = set()
    for m in re.finditer(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(?!\.?\d)", text):
        if _VERSION_PREFIX_RE.search(text[max(0, m.start() - 20):m.start()]):
            continue
        try:
            ip = ipaddress.IPv4Address(m.group(1))
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast \
                or ip.is_reserved or ip.is_unspecified:
            continue
        found.add(str(ip))
    return found


def _extract_ipv6(text: str) -> set[str]:
    """Extract public IPv6 addresses."""
    found: set[str] = set()
    for m in re.finditer(r"(?<![0-9A-Fa-f:])([0-9A-Fa-f:]{4,})(?![0-9A-Fa-f:])", text):
        cand = m.group(1)
        if cand.count(":") < 2:
            continue
        try:
            ip = ipaddress.IPv6Address(cand)
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
