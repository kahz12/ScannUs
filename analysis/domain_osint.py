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

The orchestrator ``domain_recon(target)`` runs the free, no-key tools in order
and prints a single consolidated report.
"""

from __future__ import annotations

import os
import re
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from cli.ui import (
    console, THEME,
    print_info, print_warn, print_error, print_success, make_table,
)


# ---------------------------------------------------------------------------
# Optional backends — resolved at import time
# ---------------------------------------------------------------------------

try:
    import dns.resolver           # type: ignore
    import dns.exception          # type: ignore
    _HAS_DNS = True
except Exception:
    _HAS_DNS = False

try:
    import whois                  # python-whois
    _HAS_WHOIS = True
except Exception:
    _HAS_WHOIS = False


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


def whois_lookup(domain: str) -> dict:
    """
    Performs a WHOIS lookup with persistent SQLite caching (TTL: 7d).
    Returns a normalised dict and renders a Rich table.
    """
    from core.cache import cached_call
    print_info(f"WHOIS · {domain}")
    info = cached_call("whois", [domain.lower()],
                       lambda: _whois_fetch(domain)) or {}
    if not info:
        return {}

    rows = [
        ("Registrar",      str(info["registrar"] or "—")),
        ("Created",        str(info["created"] or "—")),
        ("Expires",        str(info["expires"] or "—")),
        ("Updated",        str(info["updated"] or "—")),
        ("Org",            str(info["org"] or "—")),
        ("Country",        str(info["country"] or "—")),
        ("Name servers",   "\n".join(info["name_servers"]) or "—"),
        ("Status",         "\n".join(info["status"]) if isinstance(info["status"], list)
                           else (str(info["status"]) if info["status"] else "—")),
        ("Emails",         "\n".join(info["emails"]) if isinstance(info["emails"], list)
                           else (str(info["emails"]) if info["emails"] else "—")),
    ]
    tbl = make_table(
        f"WHOIS · {info['domain']}",
        ("Field", THEME["PRIMARY"]),
        ("Value", "white"),
        show_lines=False,
    )
    for k, v in rows:
        tbl.add_row(k, v)
    console.print(tbl)
    return info


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------

_DNS_TYPES = ("A", "AAAA", "MX", "NS", "TXT", "SOA", "CNAME", "CAA")


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


def dns_records(domain: str, types: tuple[str, ...] = _DNS_TYPES) -> dict[str, list[str]]:
    """
    Queries the most useful DNS record types for *domain* with persistent
    SQLite caching (TTL: 1h to honour real DNS TTLs).
    Returns a dict ``{type: [records]}``.
    """
    from core.cache import cached_call
    print_info(f"DNS · {domain}")
    key_parts = [domain.lower(), ",".join(types)]
    found = cached_call("dns", key_parts,
                        lambda: _dns_fetch(domain, types)) or {}

    if not found:
        print_warn("No DNS records returned.")
        return {}

    tbl = make_table(
        f"DNS Records · {domain}",
        ("Type",   THEME["PRIMARY"]),
        ("Value",  "white"),
        show_lines=True,
    )
    for rtype, values in found.items():
        tbl.add_row(rtype, "\n".join(values))
    console.print(tbl)
    return found


def email_security(domain: str) -> dict:
    """
    Inspects SPF, DMARC, and reports likely DKIM selectors found at common names.
    Returns ``{"spf": str|None, "dmarc": str|None, "dkim_selectors": [str]}``.
    """
    if not _HAS_DNS:
        print_warn("dnspython not installed — install with: pip install dnspython")
        return {}

    print_info(f"Email security · {domain}")

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

    dkim_selectors: list[str] = []
    for selector in ("default", "google", "selector1", "selector2", "k1", "mail"):
        if _txt(f"{selector}._domainkey.{domain}"):
            dkim_selectors.append(selector)

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

    return {"spf": spf, "dmarc": dmarc, "dkim_selectors": dkim_selectors}


# ---------------------------------------------------------------------------
# TLS certificate
# ---------------------------------------------------------------------------

def tls_certificate(host: str, port: int = 443, timeout: float = 8.0) -> dict:
    """
    Connects to ``host:port`` over TLS and returns parsed certificate info.
    """
    print_info(f"TLS · {host}:{port}")
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                cipher = ssock.cipher()
                version = ssock.version()
    except Exception as e:
        print_error(f"TLS handshake failed: {e}")
        return {}

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

    rows = [
        ("Subject",    subject or "—"),
        ("Issuer",     issuer or "—"),
        ("Valid from", not_before or "—"),
        ("Valid to",   not_after or "—"),
        ("Days left",  ("[red]expired[/red]" if (days_left is not None and days_left < 0)
                        else ("[yellow]" + str(days_left) + "[/yellow]" if (days_left is not None and days_left < 30)
                              else (str(days_left) if days_left is not None else "—")))),
        ("TLS",        f"{version}  {cipher[0]}" if cipher else (version or "—")),
        ("SAN",        "\n".join(sans) or "—"),
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

    return {
        "subject":    subject,
        "issuer":     issuer,
        "san":        sans,
        "not_before": not_before,
        "not_after":  not_after,
        "days_left":  days_left,
        "tls_version": version,
        "cipher":     cipher[0] if cipher else None,
    }


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


def http_security_headers(url: str) -> dict:
    """
    Fetches *url* (HEAD with GET fallback) and reports hardening headers.
    """
    print_info(f"HTTP headers · {url}")
    try:
        resp = requests.head(url, headers=_HEADERS, timeout=10, allow_redirects=True)
        if resp.status_code >= 400:
            resp = requests.get(url, headers=_HEADERS, timeout=10, allow_redirects=True, stream=True)
    except requests.exceptions.RequestException as e:
        print_error(f"HTTP request failed: {e}")
        return {}

    headers = {k: v for k, v in resp.headers.items()}
    tbl = make_table(
        f"Security Headers · {resp.url}  ({resp.status_code})",
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
        "url":      resp.url,
        "status":   resp.status_code,
        "present":  present,
        "missing":  missing,
        "score":    score,
        "server":   headers.get("Server"),
        "powered_by": headers.get("X-Powered-By"),
    }


# ---------------------------------------------------------------------------
# Subdomain enumeration — passive via crt.sh
# ---------------------------------------------------------------------------

def subdomains_crtsh(domain: str, timeout: float = 30.0,
                    include_wildcards: bool = False) -> list[str]:
    """
    Returns deduplicated subdomains observed in Certificate Transparency logs.
    """
    print_info(f"Subdomains · crt.sh lookup for *.{domain}")
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
        print_error(f"crt.sh request failed: {e}")
        return []
    except ValueError:
        print_error("crt.sh returned non-JSON (likely rate-limited).")
        return []

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

    found_sorted = sorted(found)
    tbl = make_table(
        f"Subdomains · *.{domain}  ({len(found_sorted)} unique)",
        ("Subdomain", THEME["PRIMARY"]),
        show_lines=False,
    )
    for sub in found_sorted[:200]:
        tbl.add_row(sub)
    console.print(tbl)
    if len(found_sorted) > 200:
        console.print(f"  [{THEME['DIM']}](+{len(found_sorted) - 200} more not shown)[/]")
    return found_sorted


# ---------------------------------------------------------------------------
# Shodan host lookup (optional, needs API key)
# ---------------------------------------------------------------------------

def shodan_host(ip: str) -> dict:
    """
    Queries Shodan for ``ip`` if ``SHODAN_API_KEY`` is set in the environment.
    Returns the raw host dict, or {} on failure / no key.
    """
    key = os.getenv("SHODAN_API_KEY")
    if not key:
        print_warn("SHODAN_API_KEY not set — skipping Shodan lookup.")
        return {}

    print_info(f"Shodan · {ip}")
    try:
        resp = requests.get(
            f"https://api.shodan.io/shodan/host/{ip}",
            params={"key": key},
            headers=_HEADERS,
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        print_error(f"Shodan request failed: {e}")
        return {}

    if resp.status_code == 404:
        print_warn("Shodan has no records for this IP.")
        return {}
    if resp.status_code != 200:
        print_error(f"Shodan returned {resp.status_code}: {resp.text[:120]}")
        return {}

    try:
        data = resp.json()
    except ValueError:
        print_error("Shodan returned non-JSON.")
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


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def domain_recon(target: str, include_shodan: bool | None = None) -> dict:
    """
    Runs the free, no-key tools in sequence and returns a consolidated dict.

    Order:
      1. WHOIS                — registrar, dates, contacts
      2. DNS                  — A/AAAA/MX/TXT/NS/SOA/CNAME/CAA
      3. Email security       — SPF + DMARC + DKIM hints
      4. TLS certificate      — cert, SANs, days left
      5. HTTP security headers — hardening posture
      6. Subdomains (crt.sh)  — passive enumeration
      7. Shodan (only if SHODAN_API_KEY set, or include_shodan=True)
    """
    domain, url = _normalize_target(target)
    if not domain:
        print_error("Target cannot be empty.")
        return {}

    console.print()
    console.rule(f"[{THEME['PRIMARY']}]Domain Recon · {domain}[/]", style=THEME["DIM"])
    console.print()

    report: dict = {"target": domain}

    report["whois"]            = whois_lookup(domain)
    console.print()
    report["dns"]              = dns_records(domain)
    console.print()
    report["email_security"]   = email_security(domain)
    console.print()
    report["tls"]              = tls_certificate(domain)
    console.print()
    report["headers"]          = http_security_headers(url or f"https://{domain}")
    console.print()
    report["subdomains"]       = subdomains_crtsh(domain)
    console.print()

    do_shodan = include_shodan if include_shodan is not None else bool(os.getenv("SHODAN_API_KEY"))
    if do_shodan:
        ip = _resolve_first_ip(domain)
        if ip:
            report["shodan"] = shodan_host(ip)
        else:
            print_warn("Could not resolve target to an IP — skipping Shodan.")

    print_success(f"Recon complete for {domain}.")
    return report
