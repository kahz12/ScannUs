"""
core/findings.py — Session-wide "findings hub": a shared pool of typed OSINT
artifacts that every tool feeds and every tool can pivot from.

This module is what makes the interactive CLI *sequential*. Regardless of which
tool produced it, any discovered artifact (a URL, domain, email, username, IP,
or phone) is normalised into a uniform :class:`Finding` record and dropped into
one process-wide pool. The continuation menu in :func:`cli.menus.findings_hub_menu`
then reads that pool to offer the natural next step, so chains compose freely:

    dork → search → [result URLs] → analyse → [extracted emails] → Holehe / HIBP
    recon → [subdomains] → search → [URLs] → download
    username-enum → [profile URLs] → analyse → download

Like :data:`core.state.LAST_RESULTS`, the pool is intentionally session-only —
nothing here is persisted to disk. Deduplication is by ``(kind, value)`` with a
case-insensitive value, so the same artifact surfaced by two different tools is
stored once while remembering the tool that first produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


# The artifact kinds the hub understands. Each maps to one or more pivots in
# the continuation menu (see cli.menus.findings_hub_menu):
#   url       → analyse (download · media · PII · screenshot · wayback · tech)
#   domain    → recon · search · HIBP-domain
#   email     → Holehe enumerate · HIBP-account · search
#   username  → Sherlock/Maigret enumerate · search
#   ip        → shown for context; searchable
#   phone     → searchable
KINDS = ("url", "domain", "email", "username", "ip", "phone")

# Human-readable plural labels, used for the summary line and overview table.
_KIND_LABELS = {
    "url":      "URLs",
    "domain":   "domains",
    "email":    "emails",
    "username": "usernames",
    "ip":       "IPs",
    "phone":    "phones",
}


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _host_from_url(url: str) -> str:
    """
    Extract the bare hostname from a URL or host-ish string.

    Tolerant of inputs that omit a scheme (``example.com/path``) by prepending
    a ``//`` so :func:`urllib.parse.urlparse` treats the leading token as the
    network location rather than a path. Strips userinfo, port, a trailing dot,
    and a leading ``www.`` so the same site dedupes to one domain.
    """
    if not url:
        return ""
    try:
        netloc = urlparse(url if "://" in url else f"//{url}").netloc
    except ValueError:
        return ""
    host = netloc.split("@")[-1].split(":")[0].strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _normalize(kind: str, value: str) -> str:
    """
    Canonicalise *value* for its *kind* so dedup is reliable.

    - ``domain`` → strip scheme/path/port, lowercase, drop ``www.``/trailing dot.
    - ``email``  → lowercase (addresses are case-insensitive in practice).
    - everything else → whitespace-trimmed, preserved verbatim (URLs keep their
      path/query; usernames keep their casing for display).
    """
    value = (value or "").strip()
    if not value:
        return ""
    if kind == "domain":
        value = _host_from_url(value)
    elif kind == "email":
        value = value.lower()
    return value


# ---------------------------------------------------------------------------
# Finding record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    """One normalised artifact in the hub.

    Attributes:
        kind:   One of :data:`KINDS`.
        value:  The artifact itself (URL, domain, email, …), already normalised.
        source: Short label of the tool that first produced it (e.g. ``"search"``,
                ``"recon:tls-san"``) — shown as a hint in pivot pickers.
        label:  Optional human-friendly note (e.g. a result title or site name).
    """
    kind: str
    value: str
    source: str = ""
    label: str = ""


# ---------------------------------------------------------------------------
# The hub
# ---------------------------------------------------------------------------

class FindingsHub:
    """Process-wide, deduplicated pool of :class:`Finding` records.

    Insertion order is preserved (it doubles as discovery order). Dedup keys on
    ``(kind, value.lower())`` so an artifact seen by several tools is kept once,
    crediting the first tool that found it.
    """

    def __init__(self) -> None:
        self._items: list[Finding] = []
        self._seen: set[tuple[str, str]] = set()

    # -- core mutation ------------------------------------------------------

    def add(self, kind: str, value: str, *, source: str = "", label: str = "") -> bool:
        """Add one artifact. Returns True if it was new, False if a duplicate
        (or the kind is unknown / the value normalises to empty)."""
        if kind not in KINDS:
            return False
        norm = _normalize(kind, value)
        if not norm:
            return False
        key = (kind, norm.lower())
        if key in self._seen:
            return False
        self._seen.add(key)
        self._items.append(Finding(kind=kind, value=norm, source=source, label=label))
        return True

    # Thin, intention-revealing wrappers around add() for the common kinds.
    def add_url(self, value: str, **kw) -> bool:       return self.add("url", value, **kw)
    def add_domain(self, value: str, **kw) -> bool:    return self.add("domain", value, **kw)
    def add_email(self, value: str, **kw) -> bool:     return self.add("email", value, **kw)
    def add_username(self, value: str, **kw) -> bool:  return self.add("username", value, **kw)
    def add_ip(self, value: str, **kw) -> bool:        return self.add("ip", value, **kw)
    def add_phone(self, value: str, **kw) -> bool:     return self.add("phone", value, **kw)

    # -- bulk ingestion from each producer's native output shape -----------

    def ingest_results(self, results: list, source: str = "search") -> int:
        """Ingest URLs from a list of SERP result dicts (``{title, link, …}``).

        Only the ``link`` is pooled (as a ``url``); the site domain is derived
        on demand by :meth:`candidate_domains`, so a 50-result page does not
        flood the pool with 50 domain entries.
        """
        n = 0
        for r in results or []:
            if not isinstance(r, dict):
                continue
            link = (r.get("link") or "").strip()
            if link:
                n += self.add_url(link, source=source, label=(r.get("title") or "")[:60])
        return n

    def ingest_pii(self, data: dict, source: str = "pii") -> int:
        """Ingest the pivotable subset of an :func:`search.smart_search.extract_information`
        result: emails, usernames, IPv4/IPv6 and phone numbers. Non-pivotable
        categories (cards, IBANs, secrets, …) are deliberately skipped."""
        if not isinstance(data, dict):
            return 0
        n = 0
        for e in data.get("emails") or []:
            n += self.add_email(e, source=source)
        for u in data.get("usernames") or []:
            n += self.add_username(u, source=source)
        for ip in (data.get("ipv4") or []) + (data.get("ipv6") or []):
            n += self.add_ip(ip, source=source)
        for p in data.get("phones") or []:
            n += self.add_phone(p, source=source)
        return n

    def ingest_recon(self, report: dict, source: str = "recon") -> int:
        """Ingest pivotable artifacts from an :func:`analysis.domain_osint.domain_recon`
        report: crt.sh subdomains and TLS SANs (domains), WHOIS contact emails,
        resolved A/AAAA records (IPs), and Shodan hostnames (domains)."""
        if not isinstance(report, dict):
            return 0
        n = 0
        for sub in report.get("subdomains") or []:
            n += self.add_domain(sub, source=source, label="subdomain")

        whois = report.get("whois") or {}
        emails = whois.get("emails")
        if isinstance(emails, str):
            emails = [emails]
        for e in emails or []:
            n += self.add_email(e, source=f"{source}:whois")

        tls = report.get("tls") or {}
        for san in tls.get("san") or []:
            n += self.add_domain(san, source=f"{source}:tls-san")

        dns = report.get("dns") or {}
        for ip in (dns.get("A") or []) + (dns.get("AAAA") or []):
            n += self.add_ip(ip, source=f"{source}:dns")

        shodan = report.get("shodan") or {}
        for host in shodan.get("hostnames") or []:
            n += self.add_domain(host, source=f"{source}:shodan")
        return n

    def ingest_username_enum(self, results: list, source: str = "user-enum") -> int:
        """Ingest profile URLs from a Sherlock/Maigret result list (each row has
        ``site``/``url``)."""
        n = 0
        for r in results or []:
            if not isinstance(r, dict):
                continue
            url = (r.get("url") or "").strip()
            if url:
                n += self.add_url(url, source=source, label=r.get("site", ""))
        return n

    def ingest_email_enum(self, results: list, source: str = "email-enum") -> int:
        """Ingest service domains from a Holehe result list (each row has
        ``service``/``domain``)."""
        n = 0
        for r in results or []:
            if not isinstance(r, dict):
                continue
            dom = (r.get("domain") or "").strip()
            if dom:
                n += self.add_domain(dom, source=source, label=r.get("service", ""))
        return n

    # -- queries used by the continuation menu ------------------------------

    def of_kind(self, kind: str) -> list[Finding]:
        """All findings of a given kind, in discovery order."""
        return [f for f in self._items if f.kind == kind]

    def candidate_domains(self) -> list[tuple[str, str]]:
        """Domains worth a recon pivot: explicit ``domain`` findings *plus* the
        host of every ``url`` finding. Returns ``(domain, source)`` pairs,
        deduped (first source wins) and sorted alphabetically."""
        seen: dict[str, str] = {}
        for f in self.of_kind("domain"):
            seen.setdefault(f.value, f.source or "finding")
        for f in self.of_kind("url"):
            host = _host_from_url(f.value)
            if host:
                seen.setdefault(host, f"url:{f.source}" if f.source else "url")
        return sorted(seen.items())

    def kinds_present(self) -> set[str]:
        """The set of kinds that currently have at least one finding."""
        return {f.kind for f in self._items}

    def counts(self) -> dict[str, int]:
        """Map of ``kind → count`` for kinds that are present."""
        out: dict[str, int] = {}
        for f in self._items:
            out[f.kind] = out.get(f.kind, 0) + 1
        return out

    def summary_line(self) -> str:
        """One-line summary like ``"3 URLs · 2 domains · 1 email"`` (or
        ``"empty"``), ordered by :data:`KINDS`."""
        c = self.counts()
        if not c:
            return "empty"
        return " · ".join(f"{c[k]} {_KIND_LABELS[k]}" for k in KINDS if c.get(k))

    def all(self) -> list[Finding]:
        """A shallow copy of every finding, in discovery order."""
        return list(self._items)

    def is_empty(self) -> bool:
        return not self._items

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        """Drop every finding (e.g. when starting a fresh investigation)."""
        self._items.clear()
        self._seen.clear()


# Process-wide singleton. Callers should go through get_hub() rather than
# importing this name directly, so the indirection stays swappable in tests.
_HUB = FindingsHub()


def get_hub() -> FindingsHub:
    """Return the process-wide :class:`FindingsHub` singleton."""
    return _HUB
