"""
analysis/hibp.py — Have I Been Pwned breach & paste lookups.

Welcome to the "Oh No, My Password Was 'password123'" module! 🔒
This integrates with Troy Hunt's legendary Have I Been Pwned service
to answer the eternal question: "Has my email / password been leaked
by some irresponsible company storing passwords in plain text?"
(Spoiler: probably yes.)

Three classes of endpoint, all routed through the persistent SQLite cache:

  * Paid (needs ``HIBP_API_KEY``):
      - ``hibp_breached_account(email)``   — breaches a specific email appears in
      - ``hibp_pastes_for_account(email)`` — pastes containing the email

  * Free (no key required):
      - ``hibp_breaches_for_domain(domain)`` — breaches affecting a domain
      - ``hibp_breach(name)``                — detailed metadata for one breach
      - ``hibp_all_breaches()``              — the global breach catalog

  * Pwned Passwords k-anonymity (free, separate host):
      - ``hibp_password_pwned(password)``      — k-anon count for a cleartext pw
      - ``hibp_password_pwned_hash(sha1_hex)`` — k-anon count for an SHA-1 hash

Design notes:
  - The plaintext password NEVER leaves the process. We SHA-1 it locally and
    send only the first 5 hex chars to ``api.pwnedpasswords.com/range/{prefix}``.
    The response is a list of ``SUFFIX:COUNT`` pairs; we match the rest of the
    hash in-memory and return the count (0 = safe / not in any known breach).
    Troy Hunt is clever — you learn your fate without revealing your secret.
  - Caching uses three namespaces (``hibp_account``, ``hibp_breach``,
    ``hibp_password``) with TTLs tuned in :mod:`core.cache`.
  - Renderers (``render_*``) are decoupled from the network layer so they can
    be reused by the AI dispatcher without printing twice.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any
from urllib.parse import quote

import requests

from cli.ui import (
    console, THEME,
    make_table, print_info, print_warn, print_error, print_success,
)
from core.cache import cached_call
from core.throttle import retry_http_sync


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The two HIBP API roots. The main API handles breaches/pastes/accounts;
# the separate pwnedpasswords host handles the k-anonymity range endpoint.
_HIBP_API     = "https://haveibeenpwned.com/api/v3"
_PWNED_PW_API = "https://api.pwnedpasswords.com/range"

# Be polite — HIBP asks for a descriptive UA on every request.
# "ScannUs-OSINT-Framework" is informative enough that Troy won't block us.
_USER_AGENT = "ScannUs-OSINT-Framework"

# How long to wait before giving up on HIBP. 15 seconds is generous;
# if the internet is slower than this you have bigger problems than leaked passwords.
_DEFAULT_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _api_key() -> str | None:
    """Return the configured HIBP API key, or None if absent.

    The key lives in the ``HIBP_API_KEY`` env var (populated from .env by
    ``core.config.env_config``). Paid endpoints gate on this; free ones don't.
    Strips whitespace so a copy-paste typo doesn't ruin your day.
    """
    key = (os.getenv("HIBP_API_KEY") or "").strip()
    return key or None


def _headers(api_key: str | None = None) -> dict:
    """Build the HTTP headers dict for every HIBP request.

    Always includes User-Agent (required by HIBP) and JSON Accept header.
    The secret sauce ``hibp-api-key`` header is added only when we have a key —
    free endpoints work without it, so no need to send an empty header
    and confuse Troy's servers.
    """
    h = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    if api_key:
        h["hibp-api-key"] = api_key
    return h


def _get(url: str, *, api_key: str | None = None,
         timeout: float = _DEFAULT_TIMEOUT,
         namespace: str = "hibp_account") -> tuple[int, Any]:
    """
    Perform a GET against HIBP and normalise the response.

    This is the single choke-point for all outbound HTTP in this module —
    everything else calls ``_get`` rather than talking to ``requests`` directly.
    That makes mocking in tests painless (replace ``requests.get``, done).

    Returns ``(status_code, body)`` where body is parsed JSON for 2xx, the
    raw text for non-2xx (so we can surface a useful error), or ``status=0``
    on transport failure.

    ``namespace`` selects the rate-limit bucket: the paid account/paste
    endpoints use ``hibp_account`` (~1.5 rps — HIBP throttles those), while
    the free catalog endpoints pass ``hibp_breach`` (~5 rps — Cloudflare-
    fronted and far more lenient). Requests are retried on transient HTTP
    errors (429/502/503/504) via :func:`core.throttle.retry_http_sync`, and
    ``Retry-After`` is honoured when present so we back off as much as HIBP
    wants us to.

    Why not raise on errors? Because OSINT tools should degrade gracefully —
    a network hiccup shouldn't abort a 30-step investigation plan.
    """
    def _once() -> tuple[int, Any, str | None]:
        try:
            r = requests.get(url, headers=_headers(api_key), timeout=timeout)
        except requests.RequestException as e:
            return 0, f"transport: {e}", None
        return r.status_code, r, r.headers.get("Retry-After")

    status, body = retry_http_sync(_once, namespace=namespace, max_retries=2)

    # body is the requests.Response (or the transport-error string for status=0)
    if status == 0:
        return 0, body if isinstance(body, str) else "transport failure"
    if status == 200:
        try:
            return 200, body.json()
        except ValueError:
            # HIBP occasionally returns plain text on 200 (very rare).
            return 200, body.text
    if status == 404:
        # HIBP uses 404 to mean "no records" — treat as a soft empty
        # (NOT a bug — this is documented HIBP API behaviour).
        return 404, []
    return status, body.text if hasattr(body, "text") else body


# ---------------------------------------------------------------------------
# Breached account / pastes — PAID
# ---------------------------------------------------------------------------
# These two endpoints require a paid HIBP API key (~$3.50/month as of 2024).
# Yes, you have to pay to find out which companies lost your data. The irony
# is not lost on us. But at least it keeps scrapers from harvesting the DB.
# ---------------------------------------------------------------------------

def _fetch_breached_account(email: str, truncate: bool) -> list[dict] | None:
    """Raw network fetch for the /breachedaccount endpoint.

    ``truncate=True`` asks HIBP to return only breach names (much smaller
    payload — good for a quick yes/no check). ``False`` returns full metadata
    including data classes, descriptions, etc.

    This is the private uncached version; the public ``hibp_breached_account``
    wraps it with SQLite caching so we don't hammer HIBP on every run.
    """
    key = _api_key()
    if not key:
        return None
    suffix = "?truncateResponse=true" if truncate else "?truncateResponse=false"
    url = f"{_HIBP_API}/breachedaccount/{quote(email, safe='')}{suffix}"
    # Note: quote() URL-encodes '@' -> '%40', which is correct and expected.
    status, body = _get(url, api_key=key)
    if status == 200 and isinstance(body, list):
        return body
    if status == 404:
        return []  # Happy path: no breaches found. Treat yourself to a coffee.
    return None


def hibp_breached_account(email: str, *,
                          truncate: bool = False) -> list[dict] | None:
    """
    Return the list of breaches an email appears in.

    Requires ``HIBP_API_KEY``. Cached for 12h in the ``hibp_account`` namespace.

    The cache key uses ``email.lower()`` so "USER@EXAMPLE.COM" and
    "user@example.com" share the same row — email addresses are case-insensitive
    in the local part for all practical purposes (even though RFC 5321 disagrees).

    Returns:
        * ``list`` (possibly empty) on success
        * ``None`` if the API key is missing or the request failed
    """
    if not _api_key():
        # Fail loudly rather than silently returning nothing — the user should
        # know they need to configure the key rather than thinking the email is clean.
        print_error("HIBP_API_KEY not configured — set it in .env (paid API).")
        return None
    return cached_call(
        "hibp_account",
        ["breaches", email.lower(), int(truncate)],
        lambda: _fetch_breached_account(email, truncate),
    )


def _fetch_pastes_for_account(email: str) -> list[dict] | None:
    """Raw network fetch for the /pasteaccount endpoint.

    Pastes are snippets posted to Pastebin, GitHub Gists, and similar sites
    containing dumps of credentials. Finding your email here means someone
    copy-pasted a breach dump somewhere public. Charming.

    Private uncached version — see ``hibp_pastes_for_account`` for the
    cached public API.
    """
    key = _api_key()
    if not key:
        return None
    url = f"{_HIBP_API}/pasteaccount/{quote(email, safe='')}"
    status, body = _get(url, api_key=key)
    if status == 200 and isinstance(body, list):
        return body
    if status == 404:
        return []  # No pastes. Your email is off Pastebin's radar. For now.
    return None


def hibp_pastes_for_account(email: str) -> list[dict] | None:
    """Return the list of pastes referencing an email. Paid; cached 12h.

    Shares the same ``hibp_account`` cache namespace as breach lookups
    since the cache key differs ("pastes" vs "breaches" prefix), so there's
    no collision between the two datasets.
    """
    if not _api_key():
        print_error("HIBP_API_KEY not configured — set it in .env (paid API).")
        return None
    return cached_call(
        "hibp_account",
        ["pastes", email.lower()],
        lambda: _fetch_pastes_for_account(email),
    )


# ---------------------------------------------------------------------------
# Breach catalog — FREE
# ---------------------------------------------------------------------------
# These endpoints require no API key and return publicly available breach
# metadata. Think of it as HIBP's "greatest hits" album, except the music
# is all the companies that failed to hash their passwords properly.
# ---------------------------------------------------------------------------

def _fetch_breaches_for_domain(domain: str) -> list[dict]:
    """Raw network fetch: all breaches associated with a domain.

    HIBP filters its catalog by domain, so e.g. "linkedin.com" returns only
    the LinkedIn breach(es), not every breach in existence.
    Private uncached version.
    """
    url = f"{_HIBP_API}/breaches?domain={quote(domain, safe='')}"
    status, body = _get(url, namespace="hibp_breach")
    if status == 200 and isinstance(body, list):
        return body
    return []  # On error, return empty rather than crashing


def hibp_breaches_for_domain(domain: str) -> list[dict]:
    """Return breaches affecting a domain. No API key needed; cached 7d.

    7-day TTL is reasonable because breach metadata barely changes after
    initial ingestion — HIBP doesn't retroactively "un-breach" a company.
    """
    return cached_call(
        "hibp_breach",
        ["domain", domain.lower()],  # lowercase so "Adobe.com" == "adobe.com"
        lambda: _fetch_breaches_for_domain(domain),
    ) or []


def _fetch_breach(name: str) -> dict | None:
    """Raw network fetch for a single named breach (e.g. "Adobe", "LinkedIn").

    The breach ``name`` is HIBP's internal identifier, not the human-readable
    title. Usually they match, but not always (e.g. "Collection1" is the name
    for a large compilation breach). Private uncached version.
    """
    url = f"{_HIBP_API}/breach/{quote(name, safe='')}"
    status, body = _get(url, namespace="hibp_breach")
    if status == 200 and isinstance(body, dict):
        return body
    return None


def hibp_breach(name: str) -> dict | None:
    """Return detailed metadata for a named breach. Free; cached 7d.

    Useful when you want the full story on a specific breach: its description,
    exactly which data classes were stolen, whether it's been verified, and
    crucially, how many accounts were caught in the blast radius.
    """
    return cached_call(
        "hibp_breach",
        ["one", name.lower()],
        lambda: _fetch_breach(name),
    )


def _fetch_all_breaches() -> list[dict]:
    """Raw network fetch for the entire HIBP breach catalog.

    This endpoint returns every breach ever ingested by HIBP. As of 2024 that's
    700+ breaches. Great for building dashboards; expensive on first call;
    hence the 7-day cache below. Private uncached version.
    """
    status, body = _get(f"{_HIBP_API}/breaches", namespace="hibp_breach")
    if status == 200 and isinstance(body, list):
        return body
    return []


def hibp_all_breaches() -> list[dict]:
    """Return the full HIBP breach catalog. Free; cached 7d.

    Cached under the key "catalog" so all callers share the same warm copy.
    If this returns an empty list, either HIBP is down or every company on
    the internet has magically started handling data responsibly (unlikely).
    """
    return cached_call(
        "hibp_breach",
        ["catalog"],
        _fetch_all_breaches,
    ) or []


# ---------------------------------------------------------------------------
# Pwned Passwords — FREE (k-anonymity)
# ---------------------------------------------------------------------------
# This is the clever bit. Troy Hunt's k-anonymity model means:
#   1. We SHA-1 the password locally.
#   2. We send only the first 5 hex characters (the "prefix") to the API.
#   3. The API returns ~800 suffix:count pairs that share that prefix.
#   4. We search for our suffix IN MEMORY.
#
# Result: the server never sees the password OR its full hash. It only sees
# 1/1,048,576 of the hash space — completely useless for reversing. Genius.
# ---------------------------------------------------------------------------

def _fetch_pwned_range(prefix: str) -> str | None:
    """Fetch the SHA-1 range from the Pwned Passwords API.

    Returns the raw response body, which is a bunch of lines like:
        1E4C9B93F3F0682250B6CF8331B7EE68FD8:9999999
        AABBCC...:3
        ...

    The ``Add-Padding: true`` header asks HIBP to pad the response to a
    fixed size (~800 entries) so traffic analysis can't reveal whether
    a specific prefix exists in the corpus. Extra privacy! 🎉

    Rate-limited and retried via the shared ``hibp_password`` bucket
    (default ~10 rps — the k-anon endpoint is a permissive CDN).
    Private uncached version — the public caller wraps it in cached_call.
    """
    url = f"{_PWNED_PW_API}/{prefix}"

    def _once() -> tuple[int, Any, str | None]:
        try:
            r = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT, "Add-Padding": "true"},
                timeout=_DEFAULT_TIMEOUT,
            )
        except requests.RequestException as e:
            return 0, f"transport: {e}", None
        return r.status_code, r, r.headers.get("Retry-After")

    status, body = retry_http_sync(_once, namespace="hibp_password", max_retries=2)
    if status == 200 and hasattr(body, "text"):
        return body.text
    return None


def hibp_password_pwned_hash(sha1_hex: str) -> int | None:
    """
    K-anonymity lookup for an already-computed SHA-1 password hash.

    Use this when you already have the SHA-1 and don't want to re-hash.
    The public ``hibp_password_pwned`` function calls this after hashing.

    How the cache works here: the entire range response (~800 entries) is
    cached under the 5-char prefix. Future lookups for ANY password sharing
    that prefix (e.g. "password", "password1", "pa55word") all hit the same
    cached blob — great cache efficiency for common prefix spaces.

    Args:
        sha1_hex: The SHA-1 of the password as a 40-char hex string
                  (case-insensitive).

    Returns:
        The number of times the password has been seen across HIBP's corpus.
        ``0`` means the password is not in any known breach (still no guarantee
        of safety, but a good signal). ``None`` on transport failure.
    """
    # Normalise to uppercase — HIBP suffixes are uppercase and we compare them.
    s = sha1_hex.strip().upper()
    # Validate before sending anything: must be exactly 40 valid hex chars.
    if len(s) != 40 or not all(c in "0123456789ABCDEF" for c in s):
        return None  # Not a valid SHA-1 — caller passed garbage, return None
    prefix, suffix = s[:5], s[5:]  # Split: send prefix, match suffix locally
    body = cached_call(
        "hibp_password",
        ["range", prefix],
        lambda: _fetch_pwned_range(prefix),
    )
    if body is None:
        return None  # Network failure; we can't tell if it's compromised
    for line in body.splitlines():
        # Each line: "<35-char suffix>:<count>"
        # The count can be large (billions for "123456"); format it elsewhere.
        parts = line.strip().split(":")
        if len(parts) >= 2 and parts[0].upper() == suffix:
            try:
                return int(parts[1])
            except ValueError:
                return 0  # Malformed line from the API; treat as count=0
    # Password not found in the range — it hasn't been seen in any known breach.
    return 0


def hibp_password_pwned(password: str) -> int | None:
    """
    K-anonymity check for a cleartext password.

    This is the user-facing function. It hashes the password with SHA-1
    locally, then delegates to ``hibp_password_pwned_hash``.

    THE PLAINTEXT NEVER LEAVES THIS PROCESS. For real. Look at the code —
    ``hashlib.sha1`` runs locally, only ``sha1_hex[:5]`` hits the network.
    You can verify this by running a packet sniffer while calling it. Go ahead.

    Args:
        password: The cleartext password to check. Please don't log this anywhere.

    Returns:
        Number of breach occurrences (0 if clean), or ``None`` on failure.
    """
    if not password:
        # Empty string would technically work, but let's not encourage checking
        # whether the empty string is a popular password (it is, sadly).
        return None
    sha1_hex = hashlib.sha1(password.encode("utf-8")).hexdigest()
    return hibp_password_pwned_hash(sha1_hex)


# ---------------------------------------------------------------------------
# Renderers — Rich tables for human-facing CLI/menu paths
# ---------------------------------------------------------------------------
# These are deliberately separated from the network/cache layer above.
# Why? So the AI dispatcher can call the data functions, check the result,
# and decide whether to render — without the data function side-effectfully
# blasting a table to stdout mid-plan. Separation of concerns FTW.
# ---------------------------------------------------------------------------

def _fmt_int(n: Any) -> str:
    """Format a number with thousands separators (e.g. 152445165 → '152,445,165').

    Falls back to str(n) if the value isn't numeric — defensive against
    HIBP API changes that might someday return a string where we expect an int.
    """
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def render_breached_account(email: str, breaches: list[dict] | None) -> None:
    """Render the breaches a specific account appears in.

    Builds a Rich table with one row per breach: name, domain, date, account
    count, and which categories of data were stolen. If the list is empty,
    prints a reassuring success message. If it's None, assumes the caller
    already printed the relevant error and stays silent.
    """
    if breaches is None:
        return  # caller already explained why (missing key, network error, etc.)
    if not breaches:
        # Great news! The email hasn't been caught in any known breach.
        # (Or they signed up for everything under an alias. Smart.)
        print_success(f"{email}: no breaches found in HIBP.")
        return

    # Build the table with one row per breach entry.
    # The title shows the hit count so it's visible at a glance.
    tbl = make_table(
        f"Breaches for {email}  [{THEME['DIM']}]({len(breaches)} hit"
        f"{'s' if len(breaches) != 1 else ''})[/]",
        ("Name",       THEME["PRIMARY"]),
        ("Domain",     THEME["LINK"]),
        ("Date",       "white"),
        ("Accounts",   THEME["ACCENT"]),
        ("Data",       "white"),
        show_lines=True,  # lines between rows improve readability for long lists
    )
    for b in breaches:
        data_classes = b.get("DataClasses") or []
        tbl.add_row(
            str(b.get("Name") or b.get("Title") or "?"),
            str(b.get("Domain") or "?"),
            str(b.get("BreachDate") or "?"),
            _fmt_int(b.get("PwnCount", 0)),
            # Cap the data-classes string at 80 chars to keep the table readable;
            # append ellipsis if truncated so the user knows there's more.
            ", ".join(data_classes)[:80] + ("…" if sum(len(s) for s in data_classes) > 80 else ""),
        )
    console.print(tbl)


def render_pastes_for_account(email: str, pastes: list[dict] | None) -> None:
    """Render the pastes a specific account appears in.

    Pastes are typically Pastebin / GitHub Gist / similar dumps.
    The table shows where the paste came from, its ID (so you can look
    it up manually), when it was posted, how many emails are in it,
    and the title (usually something ominous like "combolist_2021").
    """
    if pastes is None:
        return  # Likely API key issue — silently bail, caller handled it
    if not pastes:
        # No pastes! Your email hasn't been copy-pasted into any dark corners of the web.
        print_info(f"{email}: no pastes found in HIBP.")
        return

    tbl = make_table(
        f"Pastes for {email}  [{THEME['DIM']}]({len(pastes)})[/]",
        ("Source",  THEME["PRIMARY"]),  # e.g. "Pastebin", "GitHub"
        ("ID",      "white"),           # the paste's unique ID on that platform
        ("Date",    "white"),           # when it was posted (or ingested by HIBP)
        ("Emails",  THEME["ACCENT"]),   # total emails in that paste dump
        ("Title",   "white"),           # usually unintentionally funny or ominous
        show_lines=False,
    )
    for p in pastes:
        tbl.add_row(
            str(p.get("Source") or "?"),
            str(p.get("Id") or "?"),
            str(p.get("Date") or "?"),
            _fmt_int(p.get("EmailCount", 0)),
            str(p.get("Title") or "")[:50],  # 50 chars is plenty for a title
        )
    console.print(tbl)


def render_breaches_for_domain(domain: str, breaches: list[dict]) -> None:
    """Render breaches affecting a domain (free endpoint).

    Lighter table than the account renderer — no paste column because the
    domain endpoint doesn't include paste data. Shows name, date, account
    count, and whether HIBP has verified the breach as authentic.
    "Unverified" breaches are still real data but may be incomplete or
    may contain fabricated entries mixed in with real ones.
    """
    if not breaches:
        # Domain is clean! Either they have great security or haven't been
        # discovered yet. Optimistically assume the former.
        print_info(f"{domain}: no breaches recorded by HIBP.")
        return

    tbl = make_table(
        f"Breaches affecting {domain}  [{THEME['DIM']}]({len(breaches)})[/]",
        ("Name",     THEME["PRIMARY"]),
        ("Date",     "white"),
        ("Accounts", THEME["ACCENT"]),
        ("Verified", "white"),  # HIBP's stamp of authenticity
        show_lines=False,
    )
    for b in breaches:
        tbl.add_row(
            str(b.get("Name") or "?"),
            str(b.get("BreachDate") or "?"),
            _fmt_int(b.get("PwnCount", 0)),
            "yes" if b.get("IsVerified") else "no",
        )
    console.print(tbl)


def render_password_pwned(count: int | None) -> None:
    """Render the result of a Pwned Passwords lookup.

    Three possible outcomes:
      - None:    Transport failure (can't connect to pwnedpasswords.com).
      - 0:       Password not found — green light, but pick a better one anyway.
      - 1-9:     Rare occurrence — still compromised, change it.
      - 10+:     Very common password — abandon all hope. Change it everywhere.

    The colour coding uses Rich styles from THEME for consistency with the
    rest of ScannUs output: green (success) / yellow (warn) / red (error).
    """
    if count is None:
        print_error("Pwned Passwords lookup failed (network or invalid hash).")
        return
    if count == 0:
        # Not in the corpus. You're probably using a passphrase or a password
        # manager. Either way, good job — have a gold star. ⭐
        print_success("Password not found in any known HIBP breach corpus.")
        return
    if count < 10:
        # Technically compromised but rare. Someone probably used it once in 2009
        # in a forum that got breached. Still: change it. Don't be that person.
        print_warn(f"Password seen in HIBP corpus: {_fmt_int(count)} time(s) — change it.")
    else:
        # Seen 10+ times means this is a genuinely popular bad password.
        # "password", "123456", "qwerty", "abc123" all live here in the millions.
        # Red alert. Change it. Use a password manager. Enable MFA. The works.
        print_error(
            f"Password seen in HIBP corpus: {_fmt_int(count)} time(s) — "
            f"do NOT use it anywhere."
        )


# ---------------------------------------------------------------------------
# Convenience wrappers used by CLI + menus + AI dispatchers
# ---------------------------------------------------------------------------
# These three functions are the "batteries included" API:
# fetch + render in one call, returning a dict for callers that want
# the data programmatically (e.g. the AI planner, JSON export).
# ---------------------------------------------------------------------------

def check_account(email: str, *, include_pastes: bool = True) -> dict:
    """
    Run the full account check (breaches + optional pastes) and render.

    This is the one-stop shop for "has this email been pwned?"
    It fetches both breaches and pastes (if requested), renders each table
    to the terminal, and returns a clean dict for programmatic consumers.

    The ``include_pastes`` flag lets callers skip the paste lookup (e.g.
    if the user only cares about breaches, or wants to save an API call).

    Returns a serialisable dict suitable for JSON export / case storage:
      {"email", "breaches": [...], "pastes": [...] | None,
       "breach_count", "paste_count", "checked_at"}
    """
    breaches = hibp_breached_account(email)
    render_breached_account(email, breaches)
    pastes = None
    if include_pastes:
        pastes = hibp_pastes_for_account(email)
        render_pastes_for_account(email, pastes)
    return {
        "email":        email,
        "breaches":     breaches or [],
        "pastes":       pastes or [],
        "breach_count": len(breaches or []),
        "paste_count":  len(pastes or []),
        "checked_at":   time.time(),  # unix timestamp for "when was this checked"
    }


def check_domain(domain: str) -> list[dict]:
    """Run the free domain breach lookup and render.

    Thin wrapper around ``hibp_breaches_for_domain`` + ``render_breaches_for_domain``.
    Returns the raw list so callers can inspect or export the data.
    No API key needed — great for a quick domain hygiene check.
    """
    breaches = hibp_breaches_for_domain(domain)
    render_breaches_for_domain(domain, breaches)
    return breaches


def check_password(password: str) -> int | None:
    """Run the k-anonymity password lookup and render.

    Thin wrapper that hashes, queries, and renders in one call.
    Returns the raw count so callers can make programmatic decisions
    (e.g. the AI dispatcher uses this to summarise findings).

    Remember: the plaintext password is NOT stored or logged anywhere in
    this call chain. It hashes and evaporates. 🔥
    """
    count = hibp_password_pwned(password)
    render_password_pwned(count)
    return count
