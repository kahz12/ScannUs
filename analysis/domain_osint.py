"""
analysis/domain_osint.py — Domain and network OSINT primitives.

Covers the foundational reconnaissance surface that wasn't in the project before:

  - whois_lookup(domain)             registrar / dates / contacts / nameservers
  - dns_records(domain)              A, AAAA, MX, TXT, NS, SOA, CNAME, CAA
  - email_security(domain)           SPF + DMARC + DKIM hint
  - tls_certificate(host, port=443)  cert details, SANs, validity, days left
  - http_security_headers(url)       presence + assessment of hardening headers
  - subdomains_crtsh(domain)         passive subdomain enumeration via crt.sh
  - shodan_host(ip)                  optional, needs SHODAN_API_KEY

The orchestrator ``domain_recon(target)`` fans out every free, no-key probe
concurrently via ``asyncio.gather`` and renders the results in fixed order
after all probes have completed (deferred rendering — keeps output ordered
even though probes finish in arbitrary order). Sync entry points are
preserved so individual callers (CLI menu, AI Query Planner dispatchers) are
unaffected.
"""

from __future__ import annotations

import asyncio
import os
import re
import socket
import ssl
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from cli.ui import (
    console, THEME,
    print_info, print_warn, print_error, print_success, make_table,
)
from core.throttle import throttled, throttled_async


# ---------------------------------------------------------------------------
# Optional backends — resolved at import time
# ---------------------------------------------------------------------------

try:
    import dns.resolver           # type: ignore
    import dns.exception          # type: ignore
    import dns.asyncresolver      # type: ignore
    _HAS_DNS = True
except Exception:
    _HAS_DNS = False

try:
    import whois                  # python-whois
    _HAS_WHOIS = True
except Exception:
    _HAS_WHOIS = False

try:
    import aiohttp                # type: ignore
    _HAS_AIOHTTP = True
except Exception:
    _HAS_AIOHTTP = False


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}$",
    re.IGNORECASE,
)
_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def _normalize_target(raw: str) -> tuple[str, str | None]:
    """
    Normalises *raw* into ``(domain, scheme_url_or_None)``.

    Accepts URLs (``https://x.com/path``), bare domains (``x.com``), or
    domains with userinfo / port.  Returns ``(domain, "https://domain")`` for
    domain inputs so caller can hit it over HTTP if needed.
    """
    raw = (raw or "").strip()
    if not raw:
        return "", None
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        return host.lower(), raw
    # Strip path / port if user typed "x.com/y" or "x.com:8443"
    host = raw.split("/", 1)[0].split(":", 1)[0]
    return host.lower(), f"https://{host}"


def _resolve_first_ip(domain: str) -> str | None:
    """Returns the first IPv4 for *domain* via the system resolver, or None."""
    try:
        return socket.gethostbyname(domain)
    except OSError:
        return None


def _first_a(dns_data) -> str | None:
    """Extract the first A record from a dns_records() result, or None."""
    if isinstance(dns_data, dict):
        a = dns_data.get("A") or []
        if a:
            return a[0]
    return None


# ---------------------------------------------------------------------------
# WHOIS
# ---------------------------------------------------------------------------

def _first(value):
    """python-whois returns scalars or lists depending on the TLD — normalise."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _whois_fetch(domain: str) -> dict:
    """Uncached WHOIS fetch + normalisation. Returns ``{}`` on failure."""
    if not _HAS_WHOIS:
        print_warn("python-whois not installed — install with: pip install python-whois")
        return {}
    try:
        raw = whois.whois(domain)
    except Exception as e:
        print_error(f"WHOIS lookup failed: {e}")
        return {}
    if not raw or not getattr(raw, "domain_name", None):
        print_warn("No WHOIS data returned — the registry may block public queries.")
        return {}
    return {
        "domain":       _first(raw.get("domain_name")) or domain,
        "registrar":    _first(raw.get("registrar")),
        "created":      _first(raw.get("creation_date")),
        "expires":      _first(raw.get("expiration_date")),
        "updated":      _first(raw.get("updated_date")),
        "name_servers": sorted({n.lower() for n in (raw.get("name_servers") or []) if n}),
        "status":       sorted({s for s in (raw.get("status") or []) if s})
                        if isinstance(raw.get("status"), list) else raw.get("status"),
        "emails":       sorted({e for e in (raw.get("emails") or []) if e})
                        if isinstance(raw.get("emails"), list) else raw.get("emails"),
        "country":      _first(raw.get("country")),
        "org":          _first(raw.get("org")) or _first(raw.get("registrant_name")),
    }


def _render_whois_body(info: dict) -> None:
    """Render the WHOIS table only — no print_info header (caller prints it)."""
    if not info:
        return
    rows = [
        ("Registrar",      str(info.get("registrar") or "—")),
        ("Created",        str(info.get("created") or "—")),
        ("Expires",        str(info.get("expires") or "—")),
        ("Updated",        str(info.get("updated") or "—")),
        ("Org",            str(info.get("org") or "—")),
        ("Country",        str(info.get("country") or "—")),
        ("Name servers",   "\n".join(info.get("name_servers") or []) or "—"),
        ("Status",         "\n".join(info["status"]) if isinstance(info.get("status"), list)
                           else (str(info.get("status")) if info.get("status") else "—")),
        ("Emails",         "\n".join(info["emails"]) if isinstance(info.get("emails"), list)
                           else (str(info.get("emails")) if info.get("emails") else "—")),
    ]
    tbl = make_table(
        f"WHOIS · {info.get('domain') or '?'}",
        ("Field", THEME["PRIMARY"]),
        ("Value", "white"),
        show_lines=False,
    )
    for k, v in rows:
        tbl.add_row(k, v)
    console.print(tbl)


def whois_lookup(domain: str) -> dict:
    """
    Performs a WHOIS lookup with persistent SQLite caching (TTL: 7d).
    Returns a normalised dict and renders a Rich table.
    """
    from core.cache import cached_call
    print_info(f"WHOIS · {domain}")
    info = cached_call("whois", [domain.lower()],
                       lambda: _whois_fetch(domain)) or {}
    _render_whois_body(info)
    return info


async def _whois_lookup_async(domain: str) -> dict:
    """Async WHOIS fetcher (cache-aware, no rendering). For the orchestrator."""
    from core.cache import get_cache
    cache = get_cache()
    key = cache.make_key(domain.lower())
    hit = cache.get("whois", key)
    if hit is not None:
        return hit
    info = await asyncio.to_thread(_whois_fetch, domain)
    if info:
        cache.set("whois", key, info)
    return info or {}


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------

_DNS_TYPES = ("A", "AAAA", "MX", "NS", "TXT", "SOA", "CNAME", "CAA")

# Per-record-type TTLs (seconds). The "dns" cache namespace stores one row
# per (domain, rtype) so volatile records (A/AAAA behind load balancers) and
# stable records (NS, SOA, MX, CAA) can each be cached at the right cadence.
_DNS_TYPE_TTL: dict[str, int] = {
    "A":     1  * 60 * 60,        # 1h  — IPs rotate with LBs / CDN steering
    "AAAA":  1  * 60 * 60,        # 1h
    "CNAME": 1  * 60 * 60,        # 1h  — moves with infra changes
    "TXT":   3  * 60 * 60,        # 3h  — verification tokens change occasionally
    "MX":    24 * 60 * 60,        # 24h — mail infra rarely flips
    "NS":    24 * 60 * 60,        # 24h — delegation almost never changes
    "SOA":   24 * 60 * 60,        # 24h — serials bump, but ttls in the rrset
                                  #       are still fine to cache for a day
    "CAA":   24 * 60 * 60,        # 24h — changes only on cert-provider switches
}


def _dns_fetch(domain: str, types: tuple[str, ...]) -> dict[str, list[str]]:
    """Uncached DNS resolution. Returns a dict ``{type: [records]}``."""
    if not _HAS_DNS:
        print_warn("dnspython not installed — install with: pip install dnspython")
        return {}
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 6.0
    resolver.timeout = 3.0
    found: dict[str, list[str]] = {}
    for rtype in types:
        try:
            answers = resolver.resolve(domain, rtype)
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            continue
        except dns.exception.DNSException as e:
            print_warn(f"  {rtype}: {e}")
            continue
        rows = [rdata.to_text().strip().strip('"') for rdata in answers]
        if rows:
            found[rtype] = rows
    return found


async def _dns_fetch_async(domain: str,
                           types: tuple[str, ...]) -> dict[str, list[str]]:
    """
    Async DNS resolution — fans out per-record-type queries concurrently.
    Returns a dict ``{type: [records]}``. Same exceptions as the sync version
    are caught and treated as "no records for that type".
    """
    if not _HAS_DNS:
        return {}
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = 6.0
    resolver.timeout = 3.0

    async def _one(rtype: str) -> tuple[str, list[str]]:
        try:
            answers = await resolver.resolve(domain, rtype)
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            return rtype, []
        except dns.exception.DNSException:
            return rtype, []
        return rtype, [rdata.to_text().strip().strip('"') for rdata in answers]

    pairs = await asyncio.gather(*[_one(t) for t in types])
    return {rt: rows for rt, rows in pairs if rows}


def _render_dns_body(domain: str, found: dict[str, list[str]]) -> None:
    """Render the DNS table only — no print_info header."""
    if not found:
        print_warn("No DNS records returned.")
        return
    tbl = make_table(
        f"DNS Records · {domain}",
        ("Type",   THEME["PRIMARY"]),
        ("Value",  "white"),
        show_lines=True,
    )
    for rtype, values in found.items():
        tbl.add_row(rtype, "\n".join(values))
    console.print(tbl)


def _dns_cache_lookup(types: tuple[str, ...],
                      domain: str) -> tuple[dict[str, list[str]], list[str]]:
    """
    Per-record-type cache probe. Returns ``(hits, misses)`` where ``hits``
    is the partial result dict already populated from cache and ``misses``
    is the list of record types that still need to be fetched.

    Empty-list cache entries (e.g. "this domain has no MX records") are
    honoured — they count as hits but do not appear in the returned dict.
    """
    from core.cache import get_cache
    cache = get_cache()
    hits: dict[str, list[str]] = {}
    misses: list[str] = []
    for rtype in types:
        key = cache.make_key(domain.lower(), rtype)
        cached = cache.get("dns", key)
        if cached is None:
            misses.append(rtype)
            continue
        if cached:
            hits[rtype] = cached
    return hits, misses


def _dns_cache_store(domain: str, fresh: dict[str, list[str]],
                     fetched_types: list[str]) -> None:
    """Persist freshly-fetched DNS results with per-type TTLs."""
    from core.cache import get_cache
    cache = get_cache()
    for rtype in fetched_types:
        rows = fresh.get(rtype, [])
        ttl = _DNS_TYPE_TTL.get(rtype, 60 * 60)
        cache.set("dns", cache.make_key(domain.lower(), rtype), rows, ttl=ttl)


def dns_records(domain: str, types: tuple[str, ...] = _DNS_TYPES) -> dict[str, list[str]]:
    """
    Queries the most useful DNS record types for *domain* with persistent
    SQLite caching. Each record type is cached independently with a TTL
    appropriate to its volatility (see ``_DNS_TYPE_TTL``).

    Returns a dict ``{type: [records]}``.
    """
    print_info(f"DNS · {domain}")
    found, misses = _dns_cache_lookup(types, domain)
    if misses:
        fresh = _dns_fetch(domain, tuple(misses))
        _dns_cache_store(domain, fresh, misses)
        for rtype in misses:
            rows = fresh.get(rtype, [])
            if rows:
                found[rtype] = rows
    _render_dns_body(domain, found)
    return found


async def _dns_records_async(domain: str,
                             types: tuple[str, ...] = _DNS_TYPES) -> dict[str, list[str]]:
    """Async DNS fetcher (per-type cache-aware, no rendering)."""
    found, misses = _dns_cache_lookup(types, domain)
    if misses:
        fresh = await _dns_fetch_async(domain, tuple(misses))
        _dns_cache_store(domain, fresh, misses)
        for rtype in misses:
            rows = fresh.get(rtype, [])
            if rows:
                found[rtype] = rows
    return found


# ---------------------------------------------------------------------------
# Email security (SPF / DMARC / DKIM hints)
# ---------------------------------------------------------------------------

_DKIM_SELECTORS = ("default", "google", "selector1", "selector2", "k1", "mail")


def _email_security_fetch(domain: str) -> dict:
    """Uncached SPF/DMARC/DKIM lookup. Returns ``{}`` if dnspython missing."""
    if not _HAS_DNS:
        return {}

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 6.0
    resolver.timeout = 3.0

    def _txt(name: str) -> list[str]:
        try:
            answers = resolver.resolve(name, "TXT")
        except Exception:
            return []
        out = []
        for rdata in answers:
            chunks = [b.decode(errors="ignore") if isinstance(b, bytes) else str(b)
                      for b in rdata.strings] if hasattr(rdata, "strings") else [rdata.to_text()]
            out.append("".join(chunks).strip('"'))
        return out

    spf = next((r for r in _txt(domain) if r.lower().startswith("v=spf1")), None)
    dmarc = next((r for r in _txt(f"_dmarc.{domain}") if r.lower().startswith("v=dmarc1")), None)
    dkim_selectors = [s for s in _DKIM_SELECTORS if _txt(f"{s}._domainkey.{domain}")]
    return {"spf": spf, "dmarc": dmarc, "dkim_selectors": dkim_selectors}


async def _email_security_fetch_async(domain: str) -> dict:
    """
    Async SPF/DMARC/DKIM lookup — runs all 8 TXT queries (1 SPF + 1 DMARC +
    6 DKIM selectors) concurrently.
    """
    if not _HAS_DNS:
        return {}

    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = 6.0
    resolver.timeout = 3.0

    async def _txt(name: str) -> list[str]:
        try:
            answers = await resolver.resolve(name, "TXT")
        except Exception:
            return []
        out = []
        for rdata in answers:
            chunks = [b.decode(errors="ignore") if isinstance(b, bytes) else str(b)
                      for b in rdata.strings] if hasattr(rdata, "strings") else [rdata.to_text()]
            out.append("".join(chunks).strip('"'))
        return out

    queries = [_txt(domain), _txt(f"_dmarc.{domain}")] + \
              [_txt(f"{s}._domainkey.{domain}") for s in _DKIM_SELECTORS]
    results = await asyncio.gather(*queries)

    spf = next((r for r in results[0] if r.lower().startswith("v=spf1")), None)
    dmarc = next((r for r in results[1] if r.lower().startswith("v=dmarc1")), None)
    dkim_selectors = [s for s, found in zip(_DKIM_SELECTORS, results[2:]) if found]
    return {"spf": spf, "dmarc": dmarc, "dkim_selectors": dkim_selectors}


def _render_email_security_body(domain: str, info: dict) -> None:
    """Render the email-auth table only — no print_info header."""
    if not info:
        return
    spf = info.get("spf")
    dmarc = info.get("dmarc")
    dkim_selectors = info.get("dkim_selectors") or []
    rows = [
        ("SPF",   spf or "[red]missing[/red]"),
        ("DMARC", dmarc or "[red]missing[/red]"),
        ("DKIM",  ", ".join(dkim_selectors) if dkim_selectors
                  else "[yellow]no common selectors found[/yellow]"),
    ]
    tbl = make_table(
        f"Email Authentication · {domain}",
        ("Mechanism", THEME["PRIMARY"]),
        ("Record",    "white"),
        show_lines=True,
    )
    for k, v in rows:
        tbl.add_row(k, v)
    console.print(tbl)


def email_security(domain: str) -> dict:
    """
    Inspects SPF, DMARC, and reports likely DKIM selectors found at common names.
    Returns ``{"spf": str|None, "dmarc": str|None, "dkim_selectors": [str]}``.
    """
    if not _HAS_DNS:
        print_warn("dnspython not installed — install with: pip install dnspython")
        return {}
    print_info(f"Email security · {domain}")
    info = _email_security_fetch(domain)
    _render_email_security_body(domain, info)
    return info


# ---------------------------------------------------------------------------
# TLS certificate
# ---------------------------------------------------------------------------

def _tls_fetch(host: str, port: int = 443, timeout: float = 8.0) -> dict:
    """
    Connects to ``host:port`` over TLS and returns parsed certificate info.
    On failure returns ``{"_error": str}``.
    """
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                cipher = ssock.cipher()
                version = ssock.version()
    except Exception as e:
        return {"_error": str(e)}

    def _dn(seq):
        return ", ".join(f"{k}={v}" for t in (seq or []) for k, v in t)

    subject = _dn(cert.get("subject"))
    issuer  = _dn(cert.get("issuer"))
    sans = [v for t, v in cert.get("subjectAltName", []) if t == "DNS"]
    not_before = cert.get("notBefore")
    not_after  = cert.get("notAfter")

    days_left = None
    try:
        exp = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days_left = (exp - datetime.now(timezone.utc)).days
    except (TypeError, ValueError):
        pass

    return {
        "subject":     subject,
        "issuer":      issuer,
        "san":         sans,
        "not_before":  not_before,
        "not_after":   not_after,
        "days_left":   days_left,
        "tls_version": version,
        "cipher":      cipher[0] if cipher else None,
    }


def _render_tls_body(host: str, port: int, info: dict) -> None:
    """Render the TLS table only — no print_info header."""
    if not info:
        return
    if "_error" in info:
        print_error(f"TLS handshake failed: {info['_error']}")
        return
    days_left = info.get("days_left")
    if days_left is not None and days_left < 0:
        days_cell = "[red]expired[/red]"
    elif days_left is not None and days_left < 30:
        days_cell = f"[yellow]{days_left}[/yellow]"
    elif days_left is not None:
        days_cell = str(days_left)
    else:
        days_cell = "—"

    version = info.get("tls_version") or "—"
    cipher = info.get("cipher")
    rows = [
        ("Subject",    info.get("subject") or "—"),
        ("Issuer",     info.get("issuer") or "—"),
        ("Valid from", info.get("not_before") or "—"),
        ("Valid to",   info.get("not_after") or "—"),
        ("Days left",  days_cell),
        ("TLS",        f"{version}  {cipher}" if cipher else version),
        ("SAN",        "\n".join(info.get("san") or []) or "—"),
    ]
    tbl = make_table(
        f"TLS Certificate · {host}:{port}",
        ("Field", THEME["PRIMARY"]),
        ("Value", "white"),
        show_lines=False,
    )
    for k, v in rows:
        tbl.add_row(k, v)
    console.print(tbl)


def tls_certificate(host: str, port: int = 443, timeout: float = 8.0) -> dict:
    """
    Connects to ``host:port`` over TLS and returns parsed certificate info.
    """
    print_info(f"TLS · {host}:{port}")
    info = _tls_fetch(host, port, timeout)
    _render_tls_body(host, port, info)
    if "_error" in info:
        return {}
    return info


# ---------------------------------------------------------------------------
# HTTP security headers
# ---------------------------------------------------------------------------

_SECURITY_HEADERS = {
    "Strict-Transport-Security": "HSTS — forces HTTPS in browsers",
    "Content-Security-Policy":   "CSP — restricts script/asset sources",
    "X-Frame-Options":           "Click-jacking protection (legacy; CSP frame-ancestors preferred)",
    "X-Content-Type-Options":    "Blocks MIME-sniffing (expect: nosniff)",
    "Referrer-Policy":           "Controls Referer leakage",
    "Permissions-Policy":        "Restricts powerful browser APIs",
    "Cross-Origin-Opener-Policy":   "Isolates browsing context",
    "Cross-Origin-Embedder-Policy": "Required for SharedArrayBuffer / cross-origin isolation",
    "Cross-Origin-Resource-Policy": "Restricts cross-origin embedding of the response",
}


def _http_headers_fetch(url: str) -> dict:
    """
    Sync HEAD-with-GET-fallback fetch. Returns ``{url, status, headers}`` or
    ``{"_error": str}`` on failure.
    """
    try:
        resp = requests.head(url, headers=_HEADERS, timeout=10, allow_redirects=True)
        if resp.status_code >= 400:
            resp = requests.get(url, headers=_HEADERS, timeout=10,
                                allow_redirects=True, stream=True)
    except requests.exceptions.RequestException as e:
        return {"_error": str(e)}
    return {"url": str(resp.url), "status": resp.status_code,
            "headers": dict(resp.headers)}


async def _http_headers_fetch_async(url: str) -> dict:
    """Async HEAD-with-GET-fallback via aiohttp; falls back to a thread if missing."""
    if not _HAS_AIOHTTP:
        return await asyncio.to_thread(_http_headers_fetch, url)
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(headers=_HEADERS, timeout=timeout) as sess:
            async with sess.head(url, allow_redirects=True) as resp:
                if resp.status >= 400:
                    async with sess.get(url, allow_redirects=True) as resp2:
                        return {
                            "url":     str(resp2.url),
                            "status":  resp2.status,
                            "headers": dict(resp2.headers),
                        }
                return {
                    "url":     str(resp.url),
                    "status":  resp.status,
                    "headers": dict(resp.headers),
                }
    except aiohttp.ClientError as e:
        return {"_error": str(e)}
    except asyncio.TimeoutError:
        return {"_error": "timeout"}


def _render_http_headers_body(raw: dict) -> dict:
    """
    Render the security-headers table only — no print_info header.
    Returns the normalised summary dict (present/missing/score…) the same
    way the sync wrapper used to.
    """
    if not raw or "_error" in (raw or {}):
        if raw and "_error" in raw:
            print_error(f"HTTP request failed: {raw['_error']}")
        return {}

    headers = raw.get("headers") or {}
    tbl = make_table(
        f"Security Headers · {raw.get('url')}  ({raw.get('status')})",
        ("Header",  THEME["PRIMARY"]),
        ("Status",  "white"),
        ("Value",   THEME["DIM"]),
        show_lines=True,
    )
    present, missing = {}, []
    for header, purpose in _SECURITY_HEADERS.items():
        value = headers.get(header) or headers.get(header.lower())
        if value:
            present[header] = value
            tbl.add_row(header, "[green]present[/green]", value[:120])
        else:
            missing.append(header)
            tbl.add_row(header, "[red]missing[/red]",
                        f"[{THEME['DIM']}]{purpose}[/]")
    console.print(tbl)
    score = f"{len(present)}/{len(_SECURITY_HEADERS)}"
    print_info(f"Security score: {score} headers present.")
    return {
        "url":        raw.get("url"),
        "status":     raw.get("status"),
        "present":    present,
        "missing":    missing,
        "score":      score,
        "server":     headers.get("Server"),
        "powered_by": headers.get("X-Powered-By"),
    }


def http_security_headers(url: str) -> dict:
    """
    Fetches *url* (HEAD with GET fallback) and reports hardening headers.
    """
    print_info(f"HTTP headers · {url}")
    raw = _http_headers_fetch(url)
    return _render_http_headers_body(raw)


# ---------------------------------------------------------------------------
# Subdomain enumeration — passive via crt.sh
# ---------------------------------------------------------------------------

def _crtsh_parse(entries, domain: str, include_wildcards: bool) -> list[str]:
    """Filter/normalise crt.sh JSON response into a sorted subdomain list."""
    found: set[str] = set()
    for entry in entries or []:
        names = (entry.get("name_value") or "").split("\n")
        for name in names:
            name = name.strip().lower()
            if not name:
                continue
            if not include_wildcards and name.startswith("*."):
                name = name[2:]
            if name == domain or name.endswith(f".{domain}"):
                found.add(name)
    return sorted(found)


def _crtsh_fetch(domain: str, timeout: float = 30.0,
                 include_wildcards: bool = False) -> dict:
    """Sync crt.sh fetch. Returns ``{"subdomains": [...]}`` or ``{"_error": str}``."""
    try:
        resp = requests.get(
            "https://crt.sh/",
            params={"q": f"%.{domain}", "output": "json"},
            headers=_HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
        entries = resp.json()
    except requests.exceptions.RequestException as e:
        return {"_error": str(e), "subdomains": []}
    except ValueError:
        return {"_error": "non-JSON (likely rate-limited)", "subdomains": []}
    return {"subdomains": _crtsh_parse(entries, domain, include_wildcards)}


async def _crtsh_fetch_async(domain: str, timeout: float = 30.0,
                             include_wildcards: bool = False) -> dict:
    """
    Async crt.sh fetch via aiohttp; falls back to a thread if missing.

    Rate-limited and retried via the shared ``crtsh`` bucket (default 0.5 rps
    + 2 retries on 502/503). crt.sh frequently 502s under load, so the
    retry loop materially improves dossier completeness.
    """
    if not _HAS_AIOHTTP:
        return await asyncio.to_thread(_crtsh_fetch, domain, timeout, include_wildcards)
    from core.throttle import retry_http_async

    t = aiohttp.ClientTimeout(total=timeout)

    async def _once() -> tuple[int, Any, str | None]:
        try:
            sess = aiohttp.ClientSession(headers=_HEADERS, timeout=t)
            async with sess:
                async with sess.get(
                    "https://crt.sh/",
                    params={"q": f"%.{domain}", "output": "json"},
                ) as resp:
                    text = await resp.text()
                    return resp.status, text, resp.headers.get("Retry-After")
        except aiohttp.ClientError as e:
            return 0, f"transport: {e}", None
        except asyncio.TimeoutError:
            return 0, "transport: timeout", None

    status, body = await retry_http_async(_once, namespace="crtsh", max_retries=2)

    if status != 200:
        if status == 0:
            return {"_error": body if isinstance(body, str) else "transport", "subdomains": []}
        return {"_error": f"HTTP {status}", "subdomains": []}
    try:
        import json as _json
        entries = _json.loads(body) if isinstance(body, str) else body
    except (ValueError, TypeError):
        return {"_error": "non-JSON (likely rate-limited)", "subdomains": []}
    return {"subdomains": _crtsh_parse(entries, domain, include_wildcards)}


def _render_subdomains_body(domain: str, raw: dict) -> list[str]:
    """Render the subdomains table only — no print_info header. Returns the list."""
    if "_error" in (raw or {}):
        print_error(f"crt.sh request failed: {raw['_error']}")
        return []
    subs = (raw or {}).get("subdomains") or []
    tbl = make_table(
        f"Subdomains · *.{domain}  ({len(subs)} unique)",
        ("Subdomain", THEME["PRIMARY"]),
        show_lines=False,
    )
    for sub in subs[:200]:
        tbl.add_row(sub)
    console.print(tbl)
    if len(subs) > 200:
        console.print(f"  [{THEME['DIM']}](+{len(subs) - 200} more not shown)[/]")
    return subs


def subdomains_crtsh(domain: str, timeout: float = 30.0,
                    include_wildcards: bool = False) -> list[str]:
    """
    Returns deduplicated subdomains observed in Certificate Transparency logs.
    """
    print_info(f"Subdomains · crt.sh lookup for *.{domain}")
    raw = _crtsh_fetch(domain, timeout, include_wildcards)
    return _render_subdomains_body(domain, raw)


# ---------------------------------------------------------------------------
# Shodan host lookup (optional, needs API key)
# ---------------------------------------------------------------------------

@throttled(namespace="shodan")
def _shodan_fetch(ip: str) -> dict:
    """Sync Shodan fetch. Returns the raw API dict, or ``{"_error": ...}``.

    Rate-limited via the shared ``shodan`` bucket (Shodan's free tier is
    ~1 rps and 429s on violation, so the bucket keeps us under the line).
    """
    key = os.getenv("SHODAN_API_KEY")
    if not key:
        return {"_error": "no_key"}
    try:
        resp = requests.get(
            f"https://api.shodan.io/shodan/host/{ip}",
            params={"key": key},
            headers=_HEADERS,
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return {"_error": str(e)}
    if resp.status_code == 404:
        return {"_error": "404"}
    if resp.status_code != 200:
        return {"_error": f"{resp.status_code}: {resp.text[:120]}"}
    try:
        return resp.json()
    except ValueError:
        return {"_error": "non-JSON"}


@throttled_async(namespace="shodan")
async def _shodan_fetch_async(ip: str) -> dict:
    """Async Shodan fetch via aiohttp; falls back to a thread if missing.

    Shares the ``shodan`` bucket with the sync fetcher. The no-aiohttp
    fallback calls ``_shodan_fetch.__wrapped__`` (the *undecorated* sync
    fetch) so this path consumes exactly one token, not two.
    """
    key = os.getenv("SHODAN_API_KEY")
    if not key:
        return {"_error": "no_key"}
    if not _HAS_AIOHTTP:
        return await asyncio.to_thread(_shodan_fetch.__wrapped__, ip)
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(headers=_HEADERS, timeout=timeout) as sess:
            async with sess.get(
                f"https://api.shodan.io/shodan/host/{ip}",
                params={"key": key},
            ) as resp:
                if resp.status == 404:
                    return {"_error": "404"}
                if resp.status != 200:
                    text = await resp.text()
                    return {"_error": f"{resp.status}: {text[:120]}"}
                try:
                    return await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    return {"_error": "non-JSON"}
    except aiohttp.ClientError as e:
        return {"_error": str(e)}
    except asyncio.TimeoutError:
        return {"_error": "timeout"}


def _render_shodan_body(ip: str, data: dict) -> dict:
    """Render the Shodan table only — no print_info header. Returns the data dict."""
    err = (data or {}).get("_error") if isinstance(data, dict) else None
    if err == "no_key":
        print_warn("SHODAN_API_KEY not set — skipping Shodan lookup.")
        return {}
    if err == "404":
        print_warn("Shodan has no records for this IP.")
        return {}
    if err:
        print_error(f"Shodan: {err}")
        return {}
    rows = [
        ("Org",     data.get("org") or "—"),
        ("ISP",     data.get("isp") or "—"),
        ("ASN",     data.get("asn") or "—"),
        ("Country", data.get("country_name") or data.get("country_code") or "—"),
        ("OS",      data.get("os") or "—"),
        ("Ports",   ", ".join(str(p) for p in (data.get("ports") or [])) or "—"),
        ("Hostnames", "\n".join(data.get("hostnames") or []) or "—"),
        ("Tags",    ", ".join(data.get("tags") or []) or "—"),
        ("Vulns",   ", ".join(sorted((data.get("vulns") or []))) or "—"),
        ("Last update", data.get("last_update") or "—"),
    ]
    tbl = make_table(
        f"Shodan · {ip}",
        ("Field", THEME["PRIMARY"]),
        ("Value", "white"),
        show_lines=False,
    )
    for k, v in rows:
        tbl.add_row(k, str(v))
    console.print(tbl)
    return data


def shodan_host(ip: str) -> dict:
    """
    Queries Shodan for ``ip`` if ``SHODAN_API_KEY`` is set in the environment.
    Returns the raw host dict, or {} on failure / no key.
    """
    print_info(f"Shodan · {ip}")
    data = _shodan_fetch(ip)
    return _render_shodan_body(ip, data)


# ---------------------------------------------------------------------------
# Orchestrator (async fan-out, deferred rendering)
# ---------------------------------------------------------------------------

async def _domain_recon_async(target: str, include_shodan: bool | None) -> dict:
    """
    Concurrent fan-out: fire all six independent probes in parallel via
    ``asyncio.gather``, then render the results in fixed order (WHOIS → DNS
    → email-auth → TLS → headers → subdomains → optional Shodan).
    """
    domain, url = _normalize_target(target)
    if not domain:
        print_error("Target cannot be empty.")
        return {}

    final_url = url or f"https://{domain}"

    console.print()
    console.rule(f"[{THEME['PRIMARY']}]Domain Recon · {domain}[/]", style=THEME["DIM"])
    console.print()
    print_info("Probing WHOIS, DNS, email auth, TLS, headers, and crt.sh in parallel…")
    console.print()

    whois_r, dns_r, mail_r, tls_r, hdr_r, sub_r = await asyncio.gather(
        _whois_lookup_async(domain),
        _dns_records_async(domain),
        _email_security_fetch_async(domain),
        asyncio.to_thread(_tls_fetch, domain, 443, 8.0),
        _http_headers_fetch_async(final_url),
        _crtsh_fetch_async(domain),
        return_exceptions=True,
    )

    report: dict = {"target": domain}

    # 1. WHOIS
    print_info(f"WHOIS · {domain}")
    if isinstance(whois_r, BaseException):
        print_error(f"WHOIS failed: {whois_r}")
        report["whois"] = {}
    else:
        info = whois_r if isinstance(whois_r, dict) else {}
        _render_whois_body(info)
        report["whois"] = info
    console.print()

    # 2. DNS
    print_info(f"DNS · {domain}")
    if isinstance(dns_r, BaseException):
        print_error(f"DNS failed: {dns_r}")
        report["dns"] = {}
    else:
        found = dns_r if isinstance(dns_r, dict) else {}
        _render_dns_body(domain, found)
        report["dns"] = found
    console.print()

    # 3. Email security
    print_info(f"Email security · {domain}")
    if isinstance(mail_r, BaseException):
        print_error(f"Email security failed: {mail_r}")
        report["email_security"] = {}
    elif not _HAS_DNS:
        print_warn("dnspython not installed — install with: pip install dnspython")
        report["email_security"] = {}
    else:
        info = mail_r if isinstance(mail_r, dict) else {}
        _render_email_security_body(domain, info)
        report["email_security"] = info
    console.print()

    # 4. TLS
    print_info(f"TLS · {domain}:443")
    if isinstance(tls_r, BaseException):
        print_error(f"TLS failed: {tls_r}")
        report["tls"] = {}
    else:
        info = tls_r if isinstance(tls_r, dict) else {}
        _render_tls_body(domain, 443, info)
        report["tls"] = {} if "_error" in info else info
    console.print()

    # 5. HTTP headers
    print_info(f"HTTP headers · {final_url}")
    if isinstance(hdr_r, BaseException):
        print_error(f"HTTP headers failed: {hdr_r}")
        report["headers"] = {}
    else:
        raw = hdr_r if isinstance(hdr_r, dict) else {}
        report["headers"] = _render_http_headers_body(raw)
    console.print()

    # 6. Subdomains (crt.sh)
    print_info(f"Subdomains · crt.sh lookup for *.{domain}")
    if isinstance(sub_r, BaseException):
        print_error(f"crt.sh failed: {sub_r}")
        report["subdomains"] = []
    else:
        raw = sub_r if isinstance(sub_r, dict) else {"subdomains": []}
        report["subdomains"] = _render_subdomains_body(domain, raw)
    console.print()

    # 7. Shodan (optional) — piggy-backs on the A record from step 2.
    do_shodan = include_shodan if include_shodan is not None else bool(os.getenv("SHODAN_API_KEY"))
    if do_shodan:
        ip = _first_a(report["dns"]) or await asyncio.to_thread(_resolve_first_ip, domain)
        if ip:
            print_info(f"Shodan · {ip}")
            shodan_data = await _shodan_fetch_async(ip)
            report["shodan"] = _render_shodan_body(ip, shodan_data)
        else:
            print_warn("Could not resolve target to an IP — skipping Shodan.")

    print_success(f"Recon complete for {domain}.")
    return report


def domain_recon(target: str, include_shodan: bool | None = None) -> dict:
    """
    Runs the free, no-key probes concurrently and returns a consolidated dict.

    Probes (run in parallel):
      - WHOIS                — registrar, dates, contacts
      - DNS                  — A/AAAA/MX/TXT/NS/SOA/CNAME/CAA
      - Email security       — SPF + DMARC + DKIM hints
      - TLS certificate      — cert, SANs, days left
      - HTTP security headers — hardening posture
      - Subdomains (crt.sh)  — passive enumeration

    Then (sequentially, because it needs the resolved IP):
      - Shodan (only if SHODAN_API_KEY set, or include_shodan=True)

    Output ordering is preserved via deferred rendering: probes run
    concurrently, but Rich tables are printed in fixed order after all
    fetches complete.
    """
    return asyncio.run(_domain_recon_async(target, include_shodan))
