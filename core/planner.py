"""
core/planner.py — ReAct query-planner primitives for the OSINT agent.

Contains the plan data model (:class:`PlanStep`, :class:`QueryPlan`), the
whitelist of read-only tools the planner may choose from (``TOOL_CATALOG``),
and the per-tool dispatchers that actually execute a step (``TOOL_DISPATCH``).

This module is intentionally decoupled from the LLM providers and from
:class:`~core.ai_agent.IAAgent`: every dispatcher receives the agent instance
as a parameter (``ia_agent``) rather than importing it, and all heavy /
circular-prone imports are done lazily inside each dispatcher.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Plan data model
# ---------------------------------------------------------------------------

@dataclass
class PlanStep:
    """One atomic step in an executable OSINT plan."""
    tool: str
    args: dict = field(default_factory=dict)
    rationale: str = ""
    expected: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PlanStep":
        return cls(
            tool=str(d.get("tool", "")).strip(),
            args=dict(d.get("args") or {}),
            rationale=str(d.get("rationale", "")).strip(),
            expected=str(d.get("expected", "")).strip(),
        )


@dataclass
class QueryPlan:
    """LLM-synthesised investigation plan for a natural-language goal."""
    goal: str
    summary: str = ""
    steps: list[PlanStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "goal":    self.goal,
            "summary": self.summary,
            "steps":   [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict, goal: str = "") -> "QueryPlan":
        steps_raw = d.get("steps") or []
        return cls(
            goal=d.get("goal") or goal or "",
            summary=str(d.get("summary", "")).strip(),
            steps=[PlanStep.from_dict(s) for s in steps_raw if isinstance(s, dict)],
        )


# Whitelisted, read-only OSINT tools the planner may choose from.
TOOL_CATALOG: dict[str, dict] = {
    "search": {
        "desc": "Run a SERP search and return the list of titles/URLs/snippets.",
        "args": {
            "query":  "str (required) — search string, Google-Dork operators welcome",
            "engine": "str — duckduckgo | google | brave (default: duckduckgo)",
            "pages":  "int — SERP pages to retrieve (default: 1)",
        },
    },
    "deep_search": {
        "desc": "Search, then crawl each URL and extract PII + leaked secrets "
                "(emails, phones, IBANs, credit cards, DNIs, CUITs, RFCs, SSNs, "
                "CPF, SIN, AWS/GitHub/Slack/Stripe/Google API keys, JWTs, "
                "private keys, BTC/ETH wallets, public IPs).",
        "args": {
            "query":  "str (required)",
            "engine": "str (default: duckduckgo)",
        },
    },
    "extract_pii": {
        "desc": "Fetch a single URL and extract identifiers + leaked secrets "
                "(emails, phones, IBANs, credit cards, DNIs, CUITs, RFCs, SSNs, "
                "CPF, SIN, AWS/GitHub/Slack/Stripe/Google API keys, JWTs, "
                "private keys, BTC/ETH wallets, public IPs).",
        "args": {"url": "str (required)"},
    },
    "tech_scan": {
        "desc": "Fingerprint the web-technology stack of a URL (CMS, frameworks, "
                "analytics, CDNs).",
        "args": {"url": "str (required)"},
    },
    "username_enum": {
        "desc": "Enumerate social-network accounts for a handle via Sherlock/Maigret "
                "(400+ sites).",
        "args": {
            "username": "str (required)",
            "backend":  "str — auto | sherlock | maigret (default: auto)",
        },
    },
    "email_enum": {
        # Complements hibp_account: HIBP says where an email LEAKED;
        # email_enum says where it's currently REGISTERED on live services.
        "desc": "Enumerate service registrations for an email via Holehe "
                "(~120 sites: Instagram, Twitter, Pinterest, Spotify, etc.). "
                "Complements hibp_account — HIBP surfaces leaks, email_enum "
                "surfaces current registrations.",
        "args": {
            "email":     "str (required)",
            "only_used": "bool — show only claimed accounts (default: true)",
        },
    },
    "phone_osint": {
        # Offline, keyless, instant — backed by libphonenumber metadata.
        "desc": "Resolve offline intelligence for a phone number via libphonenumber: "
                "validity, country/region, geographic location, carrier, time zones "
                "and line type (mobile/fixed/VoIP). Also returns an OSINT footprint "
                "(search dorks + lookup links). No network call, no API key.",
        "args": {
            "phone":  "str (required) — ideally E.164, e.g. +14155552671",
            "region": "str — optional ISO-3166 hint (e.g. US) for national-format numbers",
        },
    },
    "screenshot": {
        "desc": "Capture a full-page screenshot of a URL using a headless browser.",
        "args": {"url": "str (required)"},
    },
    "wayback": {
        "desc": "Look up the URL's history on the Wayback Machine (CDX timeline).",
        "args": {"url": "str (required)"},
    },
    "wayback_fetch": {
        "desc": "Fetch the raw archived content of a URL at a specific Wayback "
                "snapshot. Returns the visible text along with status/MIME/size.",
        "args": {
            "url":       "str (required)",
            "timestamp": "str — CDX timestamp or 'latest'|'earliest'|YYYY|YYYY-MM",
        },
    },
    "wayback_extract": {
        "desc": "Fetch a Wayback snapshot and run the full PII/secret extractor "
                "on it. Surfaces identifiers/credentials that may have been "
                "scrubbed from the live site.",
        "args": {
            "url":       "str (required)",
            "timestamp": "str — CDX timestamp or 'latest'|'earliest'|YYYY|YYYY-MM",
        },
    },
    "wayback_diff": {
        "desc": "Diff two Wayback snapshots of a URL by their visible text. "
                "Returns added/removed line counts plus a unified diff.",
        "args": {
            "url":  "str (required)",
            "ts_a": "str (required) — CDX timestamp or fuzzy spec",
            "ts_b": "str (required) — CDX timestamp or fuzzy spec",
        },
    },
    "summarize_url": {
        "desc": "Fetch a URL's main content and ask the LLM to summarise it.",
        "args": {"url": "str (required)"},
    },
    "domain_recon": {
        "desc": "Full domain recon: WHOIS + DNS + email auth + TLS + HTTP "
                "security headers + subdomains (crt.sh) [+ Shodan if key set].",
        "args": {"target": "str (required) — domain or URL"},
    },
    "whois": {
        "desc": "WHOIS lookup: registrar, creation/expiry dates, nameservers, contacts.",
        "args": {"domain": "str (required)"},
    },
    "dns_records": {
        "desc": "DNS records (A, AAAA, MX, NS, TXT, SOA, CNAME, CAA).",
        "args": {"domain": "str (required)"},
    },
    "tls_certificate": {
        "desc": "Inspect the TLS certificate of a host: subject, SANs, validity.",
        "args": {"host": "str (required)", "port": "int (default 443)"},
    },
    "http_security_headers": {
        "desc": "Report which HTTP hardening headers are present/missing on a URL.",
        "args": {"url": "str (required)"},
    },
    "subdomains": {
        "desc": "Passive subdomain enumeration via Certificate Transparency (crt.sh).",
        "args": {"domain": "str (required)"},
    },
    "reverse_image": {
        "desc": "Multi-engine reverse image search (TinEye API + Bing Visual "
                "Search API + Yandex scraping + manual lookup URLs). Every "
                "engine is independent; the manual-URL tier always returns.",
        "args": {
            "url":     "str (required) — public URL of the target image",
            "engines": "list[str] — optional whitelist: tineye | bing | yandex | manual",
        },
    },
    # --- HIBP tools ----------------------------------------------------------
    # Have I Been Pwned (hibp_*) tools give the planner breach-intelligence
    # superpowers. Two are paid (need HIBP_API_KEY), two are free. All results
    # are cached so the planner can call them repeatedly without hammering Troy.
    "hibp_account": {
        "desc": "Have I Been Pwned: list every breach (and optionally pastes) "
                "containing a target email address. Requires HIBP_API_KEY.",
        "args": {
            "email":          "str (required)",
            "include_pastes": "bool — default true",
        },
    },
    "hibp_domain": {
        # Free endpoint — no API key needed. Great for a quick first recon step
        # before deciding whether to invest in the paid per-account lookup.
        "desc": "Have I Been Pwned: list breaches affecting a domain. "
                "Free endpoint, no API key required.",
        "args": {"domain": "str (required)"},
    },
    "hibp_breach": {
        # Useful as a follow-up after hibp_account surfaces a breach name —
        # drill into the full metadata (data classes, verification status, etc.)
        # to understand *what* was stolen and calibrate risk.
        "desc": "Have I Been Pwned: detailed metadata for a single named "
                "breach (size, data classes, verified flag, description).",
        "args": {"name": "str (required) — e.g. 'Adobe', 'LinkedIn'"},
    },
    "hibp_password": {
        # k-anonymity means the plaintext never leaves the process — safe to use
        # in automated investigation plans. Prefer 'sha1' arg in plan steps
        # so the raw password doesn't appear in execution logs.
        "desc": "Pwned Passwords k-anonymity lookup: returns how many times "
                "a password has been seen across known breaches. The plaintext "
                "never leaves the process — only the first 5 chars of its "
                "SHA-1 are sent.",
        "args": {
            "password": "str — cleartext password (mutually exclusive with sha1)",
            "sha1":     "str — pre-computed 40-char SHA-1 hex (alternative)",
        },
    },
}


def _truncate(value: Any, limit: int = 220) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_catalog_for_prompt() -> str:
    """Human-readable tool catalog embedded into the planner prompt."""
    lines: list[str] = []
    for name, meta in TOOL_CATALOG.items():
        lines.append(f"- {name}: {meta['desc']}")
        for arg_name, arg_desc in meta["args"].items():
            lines.append(f"    · {arg_name}: {arg_desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool dispatchers — lazy imports to avoid circular deps at import-time
# ---------------------------------------------------------------------------

def _dispatch_search(args: dict, ia_agent) -> dict:
    from cli.actions import get_search_engine
    query = (args.get("query") or "").strip()
    if not query:
        return {"status": "error", "summary": "search: missing 'query'"}
    engine = (args.get("engine") or "duckduckgo").lower()
    try:
        pages = int(args.get("pages") or 1)
    except (TypeError, ValueError):
        pages = 1
    try:
        results = get_search_engine(engine, pages, 1, "lang_es", query)
    except Exception as e:
        return {"status": "error", "summary": f"search failed: {e}"}
    top = [r.get("title", "") for r in results[:5]]
    links = [r.get("link", "") for r in results[:5]]
    return {
        "status":  "ok",
        "summary": f"{len(results)} hits · top: " + " | ".join(_truncate(t, 60) for t in top),
        "data":    {"results": results, "top_links": links},
    }


def _dispatch_deep_search(args: dict, ia_agent) -> dict:
    from cli.actions import do_deep_search
    from core import state
    query = (args.get("query") or "").strip()
    if not query:
        return {"status": "error", "summary": "deep_search: missing 'query'"}
    engine = (args.get("engine") or "duckduckgo").lower()
    try:
        do_deep_search(query, engine, pages=1, start_page=1, lang="lang_es")
    except Exception as e:
        return {"status": "error", "summary": f"deep_search failed: {e}"}
    count = len(state.LAST_RESULTS or [])
    return {
        "status":  "ok",
        "summary": f"deep search over {count} URLs complete",
        "data":    {"count": count},
    }


def _dispatch_extract_pii(args: dict, ia_agent) -> dict:
    from analysis.web_analyzer import get_text_from_url
    from search.smart_search import extract_information
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "extract_pii: missing 'url'"}
    text = get_text_from_url(url)
    if not text:
        return {"status": "error", "summary": f"could not fetch {url}"}
    data = extract_information(text)
    if not data:
        return {"status": "ok", "summary": f"{url}: no identifiers found", "data": {}}
    counts = {k: len(v) for k, v in data.items()}
    return {
        "status":  "ok",
        "summary": "extracted: " + ", ".join(f"{k}×{n}" for k, n in counts.items()),
        "data":    {"by_category": data, "counts": counts},
    }


def _dispatch_tech_scan(args: dict, ia_agent) -> dict:
    from analysis.tech_scanner import tech_scan
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "tech_scan: missing 'url'"}
    try:
        tech_scan(url)
    except Exception as e:
        return {"status": "error", "summary": f"tech_scan failed: {e}"}
    return {"status": "ok", "summary": f"tech_scan executed for {url}", "data": {}}


def _dispatch_username_enum(args: dict, ia_agent) -> dict:
    from search.username_enum import username_enum
    from core.unified import from_username_enum
    username = (args.get("username") or "").strip()
    if not username:
        return {"status": "error", "summary": "username_enum: missing 'username'"}
    backend = (args.get("backend") or "auto").lower()
    try:
        results = username_enum(username, backend=backend)
    except Exception as e:
        return {"status": "error", "summary": f"username_enum failed: {e}"}
    if results is None:
        return {"status": "error",
                "summary": "username_enum: no backend installed or empty input"}
    records = from_username_enum(username, results)
    return {
        "status":  "ok",
        "summary": f"username_enum: {len(records)} claimed account(s) for @{username}",
        "data":    {"count": len(records), "records": records},
    }


def _dispatch_email_enum(args: dict, ia_agent) -> dict:
    from search.email_enum import email_enum, HOLEHE_AVAILABLE
    from core.unified import from_email_enum
    email = (args.get("email") or "").strip()
    if not email:
        return {"status": "error", "summary": "email_enum: missing 'email'"}
    if not HOLEHE_AVAILABLE:
        return {"status": "error",
                "summary": "email_enum: holehe not installed (pip install holehe)"}
    only_used = bool(args.get("only_used", True))
    try:
        results = email_enum(email, only_used=only_used)
    except Exception as e:
        return {"status": "error", "summary": f"email_enum failed: {e}"}
    if results is None:
        return {"status": "error", "summary": "email_enum: holehe unavailable"}
    records = from_email_enum(email, results)
    claimed = sum(1 for r in records if r["status"] == "claimed")
    return {
        "status":  "ok",
        "summary": f"email_enum: {claimed} service registration(s) found for {email}",
        "data":    {"claimed": claimed, "total": len(records), "records": records},
    }


def _dispatch_phone_osint(args: dict, ia_agent) -> dict:
    from search.phone_osint import phone_lookup
    from core.unified import from_phone_osint
    phone = (args.get("phone") or "").strip()
    if not phone:
        return {"status": "error", "summary": "phone_osint: missing 'phone'"}
    region = (args.get("region") or "").strip().upper() or None
    try:
        report = phone_lookup(phone, region=region)
    except Exception as e:
        return {"status": "error", "summary": f"phone_osint failed: {e}"}
    if report is None:
        return {"status": "error",
                "summary": f"phone_osint: could not parse '{phone}' as a number"}
    records = from_phone_osint(phone, report)
    validity = "valid" if report["valid"] else "invalid"
    return {
        "status":  "ok",
        "summary": (f"phone_osint: {report['e164']} is {validity} — "
                    f"{report.get('carrier') or 'unknown carrier'}, "
                    f"{report.get('location') or report.get('region_code') or '?'}, "
                    f"{report['line_type']}"),
        "data":    {"report": report, "records": records},
    }


def _dispatch_screenshot(args: dict, ia_agent) -> dict:
    from analysis.advanced_osint import take_screenshot
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "screenshot: missing 'url'"}
    try:
        take_screenshot(url)
    except Exception as e:
        return {"status": "error", "summary": f"screenshot failed: {e}"}
    return {"status": "ok", "summary": f"screenshot captured for {url}", "data": {}}


def _dispatch_wayback(args: dict, ia_agent) -> dict:
    from analysis.advanced_osint import check_wayback_machine
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "wayback: missing 'url'"}
    try:
        check_wayback_machine(url)
    except Exception as e:
        return {"status": "error", "summary": f"wayback failed: {e}"}
    return {"status": "ok", "summary": f"wayback lookup completed for {url}", "data": {}}


def _dispatch_domain_recon(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import domain_recon
    target = (args.get("target") or args.get("domain") or args.get("url") or "").strip()
    if not target:
        return {"status": "error", "summary": "domain_recon: missing 'target'"}
    try:
        report = domain_recon(target)
    except Exception as e:
        return {"status": "error", "summary": f"domain_recon failed: {e}"}
    subs = len(report.get("subdomains") or [])
    hdr  = (report.get("headers") or {}).get("score", "?")
    return {
        "status":  "ok",
        "summary": f"recon complete · {subs} subdomains · headers {hdr}",
        "data":    report,
    }


def _dispatch_whois(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import whois_lookup
    domain = (args.get("domain") or args.get("target") or "").strip()
    if not domain:
        return {"status": "error", "summary": "whois: missing 'domain'"}
    info = whois_lookup(domain)
    if not info:
        return {"status": "error", "summary": f"whois: no data for {domain}"}
    return {"status": "ok",
            "summary": f"whois {domain}: registrar={info.get('registrar') or '?'}, "
                       f"expires={info.get('expires') or '?'}",
            "data":    info}


def _dispatch_dns_records(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import dns_records
    domain = (args.get("domain") or args.get("target") or "").strip()
    if not domain:
        return {"status": "error", "summary": "dns_records: missing 'domain'"}
    rec = dns_records(domain)
    if not rec:
        return {"status": "error", "summary": f"dns: no records for {domain}"}
    summary = "dns " + ", ".join(f"{k}×{len(v)}" for k, v in rec.items())
    return {"status": "ok", "summary": summary, "data": rec}


def _dispatch_tls_certificate(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import tls_certificate
    host = (args.get("host") or args.get("domain") or "").strip()
    if not host:
        return {"status": "error", "summary": "tls_certificate: missing 'host'"}
    try:
        port = int(args.get("port") or 443)
    except (TypeError, ValueError):
        port = 443
    cert = tls_certificate(host, port=port)
    if not cert:
        return {"status": "error", "summary": f"tls: handshake failed for {host}:{port}"}
    return {"status":  "ok",
            "summary": f"tls {host}:{port} · expires in "
                       f"{cert.get('days_left')} days · {cert.get('tls_version')}",
            "data":    cert}


def _dispatch_http_security_headers(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import http_security_headers
    url = (args.get("url") or args.get("target") or "").strip()
    if not url:
        return {"status": "error", "summary": "http_security_headers: missing 'url'"}
    data = http_security_headers(url)
    if not data:
        return {"status": "error", "summary": f"headers: request failed for {url}"}
    return {"status":  "ok",
            "summary": f"headers {data.get('score')} present",
            "data":    data}


def _dispatch_subdomains(args: dict, ia_agent) -> dict:
    from analysis.domain_osint import subdomains_crtsh
    domain = (args.get("domain") or args.get("target") or "").strip()
    if not domain:
        return {"status": "error", "summary": "subdomains: missing 'domain'"}
    subs = subdomains_crtsh(domain)
    return {"status":  "ok",
            "summary": f"{len(subs)} subdomain(s) from crt.sh",
            "data":    {"subdomains": subs}}


def _dispatch_wayback_fetch(args: dict, ia_agent) -> dict:
    from analysis.advanced_osint import wayback_fetch_snapshot
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "wayback_fetch: missing 'url'"}
    ts = (args.get("timestamp") or "latest").strip()
    snap = wayback_fetch_snapshot(url, ts)
    if not snap:
        return {"status": "error", "summary": f"wayback_fetch: no snapshot for {url}"}
    return {
        "status":  "ok",
        "summary": f"snapshot {snap['date']} · {snap['mime']} · {snap['size']} bytes",
        "data":    {
            "timestamp":   snap["timestamp"],
            "date":        snap["date"],
            "archive_url": snap["archive_url"],
            "mime":        snap["mime"],
            "size":        snap["size"],
            "text":        _truncate(snap.get("text") or "", 4000),
        },
    }


def _dispatch_wayback_extract(args: dict, ia_agent) -> dict:
    from analysis.advanced_osint import wayback_extract_pii
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "wayback_extract: missing 'url'"}
    ts = (args.get("timestamp") or "latest").strip()
    result = wayback_extract_pii(url, ts)
    if not result:
        return {"status": "error",
                "summary": f"wayback_extract: no content for {url} @ {ts}"}
    counts = result.get("counts") or {}
    summary = ("extracted from " + result["date"] + ": " +
               (", ".join(f"{k}×{v}" for k, v in counts.items()) or "no identifiers"))
    return {"status": "ok", "summary": summary, "data": result}


def _dispatch_wayback_diff(args: dict, ia_agent) -> dict:
    from analysis.advanced_osint import wayback_diff
    url = (args.get("url") or "").strip()
    ts_a = (args.get("ts_a") or "").strip()
    ts_b = (args.get("ts_b") or "").strip()
    if not (url and ts_a and ts_b):
        return {"status": "error",
                "summary": "wayback_diff: requires 'url', 'ts_a', 'ts_b'"}
    result = wayback_diff(url, ts_a, ts_b)
    if not result:
        return {"status": "error",
                "summary": "wayback_diff: could not fetch one or both snapshots"}
    return {
        "status":  "ok",
        "summary": f"{result['date_a']} -> {result['date_b']}: "
                   f"+{result['added_count']} -{result['removed_count']}"
                   + (" (identical)" if result["identical"] else ""),
        "data":    result,
    }


def _dispatch_reverse_image(args: dict, ia_agent) -> dict:
    from search.reverse_image_engines import reverse_image_aggregate
    url = (args.get("url") or args.get("image_url") or "").strip()
    if not url:
        return {"status": "error", "summary": "reverse_image: missing 'url'"}
    engines = args.get("engines")
    if isinstance(engines, str):
        engines = [e.strip() for e in engines.split(",") if e.strip()]
    try:
        results = reverse_image_aggregate(url, engines=engines)
    except Exception as e:
        return {"status": "error", "summary": f"reverse_image failed: {e}"}
    by_engine: dict[str, int] = {}
    for r in results:
        by_engine[r.get("engine", "?")] = by_engine.get(r.get("engine", "?"), 0) + 1
    breakdown = ", ".join(f"{k}×{v}" for k, v in by_engine.items()) or "no results"
    return {
        "status":  "ok",
        "summary": f"reverse_image: {len(results)} entries ({breakdown})",
        "data":    {"results": results, "by_engine": by_engine},
    }


def _dispatch_summarize_url(args: dict, ia_agent) -> dict:
    from analysis.web_analyzer import get_text_from_url, summarize_text_with_ia
    url = (args.get("url") or "").strip()
    if not url:
        return {"status": "error", "summary": "summarize_url: missing 'url'"}
    if ia_agent is None:
        return {"status": "error", "summary": "summarize_url: no AI agent available"}
    text = get_text_from_url(url)
    if not text:
        return {"status": "error", "summary": f"could not fetch {url}"}
    try:
        summary = summarize_text_with_ia(text, ia_agent)
    except Exception as e:
        return {"status": "error", "summary": f"summarize failed: {e}"}
    return {"status": "ok", "summary": _truncate(summary, 240), "data": {"full": summary}}


def _dispatch_hibp_account(args: dict, ia_agent) -> dict:
    """AI plan dispatcher for the hibp_account tool.

    Validates args, calls the data + render functions, and packages
    the result into the standard {status, summary, data} shape that
    the ReAct executor expects. The ``include_pastes`` arg accepts
    truthy strings ("true", "yes", "1") as well as booleans because
    LLMs sometimes serialise booleans as strings. We handle both.
    """
    from analysis.hibp import (hibp_breached_account, hibp_pastes_for_account,
                               render_breached_account, render_pastes_for_account)
    from core.unified import from_hibp_breaches, from_hibp_pastes
    email = (args.get("email") or "").strip()
    if not email:
        # Can't look up an account with no email. Tell the planner to retry.
        return {"status": "error", "summary": "hibp_account: missing 'email'"}
    include_pastes = args.get("include_pastes", True)
    # Handle the case where the LLM passes "false" as a string instead of False.
    if isinstance(include_pastes, str):
        include_pastes = include_pastes.strip().lower() not in ("0", "false", "no", "")
    breaches = hibp_breached_account(email)
    if breaches is None:
        # None means the API key is absent or the request failed — not just "no results".
        return {"status": "error",
                "summary": "hibp_account: API key missing or request failed"}
    render_breached_account(email, breaches)
    pastes: list[dict] = []
    if include_pastes:
        pastes_raw = hibp_pastes_for_account(email)
        if pastes_raw is None:
            pastes_raw = []  # API key issue for pastes; breaches still valid above
        render_pastes_for_account(email, pastes_raw)
        pastes = pastes_raw
    records = from_hibp_breaches(email, breaches) + from_hibp_pastes(email, pastes)
    return {
        "status":  "ok",
        "summary": f"{email}: {len(breaches)} breach(es), {len(pastes)} paste(s)",
        "data":    {
            "email":        email,
            "breaches":     breaches,
            "pastes":       pastes,
            "breach_count": len(breaches),
            "paste_count":  len(pastes),
            "records":      records,
        },
    }


def _dispatch_hibp_domain(args: dict, ia_agent) -> dict:
    """AI plan dispatcher for the hibp_domain tool.

    The free HIBP domain endpoint, so no API key gating here.
    The planner can use this to check whether a target domain has
    ever suffered a recorded breach without needing credentials.
    """
    from analysis.hibp import hibp_breaches_for_domain, render_breaches_for_domain
    domain = (args.get("domain") or "").strip()
    if not domain:
        return {"status": "error", "summary": "hibp_domain: missing 'domain'"}
    breaches = hibp_breaches_for_domain(domain)
    render_breaches_for_domain(domain, breaches)
    return {
        "status":  "ok",
        "summary": f"{domain}: {len(breaches)} breach(es) recorded",
        "data":    {"domain": domain, "breaches": breaches},
    }


def _dispatch_hibp_breach(args: dict, ia_agent) -> dict:
    """AI plan dispatcher for the hibp_breach tool.

    Fetches the full metadata for a single named breach. Useful when
    the planner has spotted a breach name (e.g. from hibp_account results)
    and wants to understand what data classes were exposed before deciding
    the next investigation step.
    """
    from analysis.hibp import hibp_breach
    name = (args.get("name") or "").strip()
    if not name:
        return {"status": "error", "summary": "hibp_breach: missing 'name'"}
    info = hibp_breach(name)
    if not info:
        # 404 from HIBP — name doesn't match any known breach identifier
        return {"status": "error", "summary": f"hibp_breach: no record for '{name}'"}
    return {
        "status":  "ok",
        # Summary is concise for the ReAct log; full metadata lives in "data".
        "summary": (f"{info.get('Name')} ({info.get('BreachDate')}): "
                    f"{info.get('PwnCount', 0):,} accounts, "
                    f"data classes: {', '.join(info.get('DataClasses') or [])[:80]}"),
        "data":    info,
    }


def _dispatch_hibp_password(args: dict, ia_agent) -> dict:
    """AI plan dispatcher for the hibp_password tool.

    Accepts either a ``password`` (cleartext — will be hashed locally before
    any network call) or a pre-computed ``sha1`` hex string. The ``via`` field
    in the returned data records which path was taken, useful for audit logs.

    Reminder: this dispatcher should NOT be called with the user's actual
    password in a plan step that gets logged. Prefer the ``sha1`` arg in
    automated contexts where the hash can be computed upstream.
    """
    from analysis.hibp import (hibp_password_pwned, hibp_password_pwned_hash,
                               render_password_pwned)
    password = args.get("password") or ""
    sha1 = (args.get("sha1") or "").strip()
    if not (password or sha1):
        # Neither argument provided — tell the planner it needs one or the other.
        return {"status": "error",
                "summary": "hibp_password: provide either 'password' or 'sha1'"}
    # Prefer sha1 if supplied (avoids re-hashing and is safer in log contexts).
    count = (hibp_password_pwned_hash(sha1) if sha1
             else hibp_password_pwned(password))
    render_password_pwned(count)
    if count is None:
        return {"status": "error", "summary": "hibp_password: lookup failed"}
    return {
        "status":  "ok",
        "summary": (f"password seen {count:,} time(s) in HIBP corpus"
                    if count else "password not in any known HIBP breach"),
        "data":    {"count": count, "via": "sha1" if sha1 else "password"},
    }


TOOL_DISPATCH: dict[str, Callable[..., dict]] = {
    "search":                _dispatch_search,
    "deep_search":           _dispatch_deep_search,
    "extract_pii":           _dispatch_extract_pii,
    "tech_scan":             _dispatch_tech_scan,
    "username_enum":         _dispatch_username_enum,
    "email_enum":            _dispatch_email_enum,
    "phone_osint":           _dispatch_phone_osint,
    "screenshot":            _dispatch_screenshot,
    "wayback":               _dispatch_wayback,
    "wayback_fetch":         _dispatch_wayback_fetch,
    "wayback_extract":       _dispatch_wayback_extract,
    "wayback_diff":          _dispatch_wayback_diff,
    "summarize_url":         _dispatch_summarize_url,
    "domain_recon":          _dispatch_domain_recon,
    "whois":                 _dispatch_whois,
    "dns_records":           _dispatch_dns_records,
    "tls_certificate":       _dispatch_tls_certificate,
    "http_security_headers": _dispatch_http_security_headers,
    "subdomains":            _dispatch_subdomains,
    "reverse_image":         _dispatch_reverse_image,
    "hibp_account":          _dispatch_hibp_account,
    "hibp_domain":           _dispatch_hibp_domain,
    "hibp_breach":           _dispatch_hibp_breach,
    "hibp_password":         _dispatch_hibp_password,
}
