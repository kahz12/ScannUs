"""
core/unified.py — Cross-tool result schema for "identifier presence" lookups.

Three tools in this project answer variants of the same question — "where
does this identifier (username / email) appear?" — but each returns its
own shape:

  * ``search.username_enum``    → per-site rows from Sherlock/Maigret
                                    ({site, url, http_status, ...})
  * ``search.email_enum``       → per-service rows from Holehe
                                    ({service, domain, exists, ...})
  * ``analysis.hibp.hibp_breached_account`` → per-breach metadata
                                    ({Name, Domain, BreachDate, ...})

Without a common shape, the AI Query Planner can't trivially correlate
findings ("the email leaked at LinkedIn AND the username is claimed on
LinkedIn → strong identity link"). The :class:`UnifiedRecord` schema
gives every per-target finding the same five fields:

  ``identifier``      — the queried string (e.g. ``"alice@example.com"``)
  ``identifier_type`` — ``email`` | ``username`` | ``domain`` | ``phone`` | ``ip``
  ``service``         — where the finding came from (LinkedIn, Spotify, …)
  ``status``          — ``claimed`` | ``available`` | ``leaked`` | ``rate_limited`` | ``error``
  ``evidence``        — tool-specific extra context (dict, may be empty)

The three ``from_*`` converters here are the canonical entry points;
new tools should add their own converter rather than emitting unified
records inline (keeps the conversion logic centralised and testable).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Literal

# These are *just* documentation — Python doesn't enforce Literal types at
# runtime. The dispatchers and the AI prompt both reference these names.
IdentifierType = Literal["email", "username", "domain", "phone", "ip"]
Status = Literal["claimed", "available", "leaked", "rate_limited", "error",
                 "valid", "invalid"]


@dataclass
class UnifiedRecord:
    """One cross-tool finding. Serialise via :meth:`to_dict` for JSON / planner."""

    identifier: str
    identifier_type: str
    service: str
    status: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Converters — one per source tool
# ---------------------------------------------------------------------------

def from_username_enum(username: str,
                       results: list[dict] | None) -> list[dict]:
    """
    Convert Sherlock/Maigret rows to unified records.

    ``search.username_enum.enumerate_username`` already filters to claimed
    accounts, so every record here has status=``claimed``. The original
    URL, HTTP status, and response time are preserved under ``evidence``.
    """
    out: list[dict] = []
    for r in results or []:
        out.append(UnifiedRecord(
            identifier=username,
            identifier_type="username",
            service=str(r.get("site") or "?"),
            status="claimed",
            evidence={
                "url":           r.get("url") or "",
                "http_status":   str(r.get("http_status") or ""),
                "response_time": str(r.get("response_time") or ""),
            },
        ).to_dict())
    return out


def from_email_enum(email: str,
                    results: list[dict] | None) -> list[dict]:
    """
    Convert Holehe rows to unified records.

    Status priority: ``error`` > ``rate_limited`` > ``claimed`` > ``available``.
    That order reflects which condition is most actionable for downstream
    analysis (an error is worth knowing about; a claimed account is
    actionable; an "available" hint is just the absence of a signal).
    """
    out: list[dict] = []
    for r in results or []:
        if r.get("error"):
            status = "error"
        elif r.get("rate_limited"):
            status = "rate_limited"
        elif r.get("status") == "claimed":
            status = "claimed"
        else:
            status = "available"
        out.append(UnifiedRecord(
            identifier=email,
            identifier_type="email",
            service=str(r.get("service") or "?"),
            status=status,
            evidence={
                "domain":         r.get("domain") or "",
                "email_recovery": r.get("email_recovery") or "",
                "phone_number":   r.get("phone_number") or "",
                "others":         r.get("others") or "",
            },
        ).to_dict())
    return out


def from_phone_osint(phone: str, report: dict | None) -> list[dict]:
    """
    Convert a :func:`search.phone_osint.phone_lookup` report into a single
    unified record. ``status`` is ``valid``/``invalid``; the offline metadata
    (carrier, location, line type, time zones, region) is kept under
    ``evidence`` so the planner can correlate it with other identifiers.
    """
    if not report:
        return []
    return [UnifiedRecord(
        identifier=report.get("e164") or phone,
        identifier_type="phone",
        service="phone_intel",
        status="valid" if report.get("valid") else "invalid",
        evidence={
            "carrier":     report.get("carrier") or "",
            "location":    report.get("location") or "",
            "line_type":   report.get("line_type") or "",
            "region_code": report.get("region_code") or "",
            "timezones":   list(report.get("timezones") or []),
            "country_code": report.get("country_code") or 0,
        },
    ).to_dict()]


def from_hibp_breaches(email: str,
                       breaches: list[dict] | None) -> list[dict]:
    """
    Convert HIBP breach hits to unified records.

    Each breach becomes one record with status=``leaked``; the rich
    breach metadata (date, account count, data classes, verified flag)
    is preserved in ``evidence``. Pastes are handled by
    :func:`from_hibp_pastes` separately so the AI planner can treat
    "leaked in a structured breach" and "leaked in a public paste"
    distinctly when it wants to.
    """
    out: list[dict] = []
    for b in breaches or []:
        out.append(UnifiedRecord(
            identifier=email,
            identifier_type="email",
            service=str(b.get("Name") or b.get("Title") or "?"),
            status="leaked",
            evidence={
                "domain":       b.get("Domain") or "",
                "breach_date":  b.get("BreachDate") or "",
                "pwn_count":    b.get("PwnCount") or 0,
                "data_classes": list(b.get("DataClasses") or []),
                "verified":     bool(b.get("IsVerified")),
                "source":       "hibp_breach",
            },
        ).to_dict())
    return out


def from_hibp_pastes(email: str,
                     pastes: list[dict] | None) -> list[dict]:
    """
    Convert HIBP paste hits to unified records (status=``leaked``).
    Source recorded in ``evidence.source`` as ``"hibp_paste"`` so callers
    can distinguish from structured breaches.
    """
    out: list[dict] = []
    for p in pastes or []:
        source_name = str(p.get("Source") or "paste")
        out.append(UnifiedRecord(
            identifier=email,
            identifier_type="email",
            service=source_name,
            status="leaked",
            evidence={
                "paste_id":    str(p.get("Id") or ""),
                "paste_title": str(p.get("Title") or ""),
                "date":        str(p.get("Date") or ""),
                "email_count": p.get("EmailCount") or 0,
                "source":      "hibp_paste",
            },
        ).to_dict())
    return out


# ---------------------------------------------------------------------------
# Aggregation helpers — used by the AI planner to correlate across tools
# ---------------------------------------------------------------------------

def by_service(records: list[dict]) -> dict[str, list[dict]]:
    """
    Group records by ``service`` (lowercased) so the planner can see at a
    glance whether the same upstream appears under multiple identifiers
    (e.g. username claimed on LinkedIn *and* email leaked in LinkedIn breach
    → identity-link signal).
    """
    out: dict[str, list[dict]] = {}
    for r in records or []:
        key = str(r.get("service") or "").lower()
        out.setdefault(key, []).append(r)
    return out


def by_identifier(records: list[dict]) -> dict[str, list[dict]]:
    """Group by ``identifier`` — useful when multiple targets are in play."""
    out: dict[str, list[dict]] = {}
    for r in records or []:
        out.setdefault(str(r.get("identifier") or ""), []).append(r)
    return out
