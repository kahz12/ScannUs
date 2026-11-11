"""
analysis/hibp.py — Have I Been Pwned breach & paste lookups.

Answers two questions through the Have I Been Pwned (HIBP) service: in which
known breaches or pastes an email or domain appears, and how often a password
shows up in breach corpora.

Three classes of endpoint, all routed through the persistent SQLite cache:

  * Paid (needs ``HIBP_API_KEY``):
      - ``hibp_breached_account(email)``   — breaches a specific email appears in
      - ``hibp_pastes_for_account(email)`` — pastes containing the email

  * Free (no key required):
      - ``hibp_breaches_for_domain(domain)`` — breaches affecting a domain
      - ``hibp_breach(name)``                — detailed metadata for one breach

  * Pwned Passwords k-anonymity (free, separate host):
      - ``hibp_password_pwned(password)``      — k-anon count for a cleartext pw
      - ``hibp_password_pwned_hash(sha1_hex)`` — k-anon count for an SHA-1 hash

Design notes:
  - The plaintext password never leaves the process. It is hashed with SHA-1
    locally and only the first 5 hex chars go to
    ``api.pwnedpasswords.com/range/{prefix}``. The response is a list of
    ``SUFFIX:COUNT`` pairs; the rest of the hash is matched in memory and the
    count returned (0 = not seen in any known breach, which is not proof that
    the password is strong).
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

# HIBP rejects requests without a User-Agent and asks that it name the client,
# so every request identifies ScannUs.
_USER_AGENT = "ScannUs-OSINT-Framework"

# Per-request timeout in seconds. HIBP normally answers in well under a second;
# this only bounds a stalled connection.
_DEFAULT_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _api_key() -> str | None:
    """Return the configured HIBP API key, or None if absent.

    The key lives in the ``HIBP_API_KEY`` env var (populated from .env by
    ``core.config.env_config``). Paid endpoints gate on this; free ones don't.
    Surrounding whitespace is stripped, since keys are usually pasted in.
    """
    key = (os.getenv("HIBP_API_KEY") or "").strip()
    return key or None


def _headers(api_key: str | None = None) -> dict:
    """Build the HTTP headers dict for every HIBP request.

    Always includes User-Agent (required by HIBP) and a JSON Accept header.
    The ``hibp-api-key`` header is added only when a key is configured; the
    free endpoints ignore it, and an empty value would be sent for nothing.
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

    This is the single choke-point for the HIBP API in this module — the other
    functions call ``_get`` rather than ``requests`` directly, so a test only
    needs to replace ``requests.get``. The Pwned Passwords range endpoint has
    its own fetcher, :func:`_fetch_pwned_range`, because it returns plain text.

    Returns ``(status_code, body)`` where body is parsed JSON for 2xx, the
    raw text for non-2xx (so we can surface a useful message), or ``status=0``
    on transport failure.

    ``namespace`` selects the rate-limit bucket: the paid account/paste
    endpoints use ``hibp_account`` (~1.5 rps — HIBP throttles those), while
    the free catalog endpoints pass ``hibp_breach`` (~5 rps — Cloudflare-
    fronted and far more lenient). Requests are retried on transient HTTP
    failures (429/502/503/504) via :func:`core.throttle.retry_http_sync`, and
    ``Retry-After`` is honoured when present so we back off as much as HIBP
    wants us to.

    Failures are returned rather than raised so that one unreachable endpoint
    does not abort a menu session or a planner investigation; every caller
    checks the status instead.
    """
    def _once() -> tuple[int, Any, str | None]:
        try:
            r = requests.get(url, headers=_headers(api_key), timeout=timeout)
        except requests.RequestException as e:
            return 0, f"transport: {e}", None
        return r.status_code, r, r.headers.get("Retry-After")

    status, body = retry_http_sync(_once, namespace=namespace, max_retries=2)

    # body is the requests.Response (or the transport-failure string for status=0)
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
        # (this is documented HIBP API behaviour).
        return 404, []
    return status, body.text if hasattr(body, "text") else body


# ---------------------------------------------------------------------------
# Breached account / pastes — PAID
# ---------------------------------------------------------------------------
# These two endpoints require a paid HIBP API key (``HIBP_API_KEY``). HIBP
# keeps per-email lookups behind a key so the corpus cannot be harvested in
# bulk; without one, both functions report the missing key and return None.
# ---------------------------------------------------------------------------

def _fetch_breached_account(email: str, truncate: bool) -> list[dict] | None:
    """Raw network fetch for the /breachedaccount endpoint.

    ``truncate=True`` asks HIBP to return only breach names (much smaller
    payload — good for a quick yes/no check). ``False`` returns full metadata
    including data classes, descriptions, etc.

    This is the private uncached version; the public ``hibp_breached_account``
    wraps it with SQLite caching so a repeated lookup does not spend another
    rate-limited request.
    """
    key = _api_key()
    if not key:
        return None
    suffix = "?truncateResponse=true" if truncate else "?truncateResponse=false"
    url = f"{_HIBP_API}/breachedaccount/{quote(email, safe='')}{suffix}"
    # quote() turns '@' into '%40'; HIBP expects the address URL-encoded.
    status, body = _get(url, api_key=key)
    if status == 200 and isinstance(body, list):
        return body
    if status == 404:
        return []  # HIBP answers 404 when the email is in no breach
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
    containing dumps of credentials. A hit means the address appeared in a
    dump that was published openly.

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
        return []  # HIBP answers 404 when the email is in no paste
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
# These endpoints require no API key and return the public breach catalog:
# one entry per breach, with its date, size, data classes and verification
# status. They are cheaper to call, so they use the more lenient
# ``hibp_breach`` rate-limit bucket.
# ---------------------------------------------------------------------------

def _fetch_breaches_for_domain(domain: str) -> list[dict] | None:
    """Raw network fetch: all breaches associated with a domain.

    HIBP filters its catalog by domain, so e.g. "linkedin.com" returns only
    the LinkedIn breach(es), not every breach in existence.
    Private uncached version.

    Returns ``None`` when the request fails. The cache skips ``None``, so a
    failed lookup is never stored as a domain without breaches.
    """
    url = f"{_HIBP_API}/breaches?domain={quote(domain, safe='')}"
    status, body = _get(url, namespace="hibp_breach")
    if status == 200 and isinstance(body, list):
        return body
    if status == 404:
        return []  # HIBP's way of saying "no records"
    return None


def hibp_breaches_for_domain(domain: str) -> list[dict] | None:
    """Return breaches affecting a domain. No API key needed; cached 7d.

    7-day TTL is reasonable because breach metadata barely changes after
    initial ingestion — HIBP doesn't retroactively "un-breach" a company.

    Returns:
        * ``list`` (possibly empty) on success
        * ``None`` if the request failed
    """
    return cached_call(
        "hibp_breach",
        ["domain", domain.lower()],  # lowercase so "Adobe.com" == "adobe.com"
        lambda: _fetch_breaches_for_domain(domain),
    )


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

    Gives the full record of one breach: its description, the data classes
    that were exposed, whether HIBP has verified it, and how many accounts it
    holds (``PwnCount``). Returns None when the name is unknown or the
    request fails.
    """
    return cached_call(
        "hibp_breach",
        ["one", name.lower()],
        lambda: _fetch_breach(name),
    )


# ---------------------------------------------------------------------------
# Pwned Passwords — FREE (k-anonymity)
# ---------------------------------------------------------------------------
# The lookup follows HIBP's k-anonymity model:
#   - the password is hashed with SHA-1 locally;
#   - only the first 5 hex characters of the hash (the prefix) are sent;
#   - the API returns every suffix:count pair that shares that prefix
#     (about 800, padded to a uniform size);
#   - the remaining 35 characters are matched in memory.
#
# The server therefore sees neither the password nor its full hash: a prefix
# is shared by roughly a million-th of the hash space, so it cannot be
# reversed to a single password.
# ---------------------------------------------------------------------------

def _fetch_pwned_range(prefix: str) -> str | None:
    """Fetch the SHA-1 range from the Pwned Passwords API.

    Returns the raw response body, one ``SUFFIX:COUNT`` pair per line:
        1E4C9B93F3F0682250B6CF8331B7EE68FD8:9999999
        AABBCC...:3
        ...

    The ``Add-Padding: true`` header asks HIBP to pad the response with
    zero-count entries to a uniform size, so the response length does not
    reveal how many real hashes share the prefix.

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

    Useful when the SHA-1 is already known, since nothing is re-hashed.
    The public ``hibp_password_pwned`` function calls this after hashing.

    The whole range response is cached under its 5-character prefix, so a
    later lookup of any hash that starts with the same prefix is answered
    from the cache without a request. Different passwords almost never share
    a prefix, so the cache mostly helps when the same password is checked
    again.

    Args:
        sha1_hex: The SHA-1 of the password as a 40-char hex string
                  (case-insensitive).

    Returns:
        The number of times the password has been seen across HIBP's corpus.
        ``0`` means the password is not in any known breach (still no guarantee
        of safety, but a good signal). ``None`` on transport failure.
    """
    # HIBP returns upper-case suffixes, so the hash is compared in upper case.
    s = sha1_hex.strip().upper()
    # Nothing is sent unless the input is exactly 40 hex characters.
    if len(s) != 40 or not all(c in "0123456789ABCDEF" for c in s):
        return None
    prefix, suffix = s[:5], s[5:]  # the prefix is sent; the suffix stays local
    body = cached_call(
        "hibp_password",
        ["range", prefix],
        lambda: _fetch_pwned_range(prefix),
    )
    if body is None:
        return None  # the request failed, so the answer is unknown
    for line in body.splitlines():
        # Each line is "<35-char suffix>:<count>". Counts reach the millions
        # for common passwords; the renderers add the thousands separators.
        parts = line.strip().split(":")
        if len(parts) >= 2 and parts[0].upper() == suffix:
            try:
                return int(parts[1])
            except ValueError:
                return 0  # an unreadable count is reported as not seen
    # The suffix is not in the range, so no known breach contains the password.
    return 0


def hibp_password_pwned(password: str) -> int | None:
    """
    K-anonymity check for a cleartext password.

    This is the user-facing function. It hashes the password with SHA-1
    locally, then delegates to ``hibp_password_pwned_hash``.

    The plaintext never leaves this process: ``hashlib.sha1`` runs locally and
    only ``sha1_hex[:5]`` hits the network.

    Args:
        password: The cleartext password to check.

    Returns:
        Number of breach occurrences (0 if clean), or ``None`` on failure.
    """
    if not password:
        # An empty password means nothing was entered, so no lookup is made.
        return None
    sha1_hex = hashlib.sha1(password.encode("utf-8")).hexdigest()
    return hibp_password_pwned_hash(sha1_hex)


# ---------------------------------------------------------------------------
# Renderers — Rich tables for human-facing CLI/menu paths
# ---------------------------------------------------------------------------
# These are kept apart from the network/cache layer above, so a caller such as
# the planner dispatcher can fetch the data, inspect it, and decide whether to
# print a table at all, instead of getting output as a side effect of the fetch.
# ---------------------------------------------------------------------------

def _fmt_int(n: Any) -> str:
    """Format a number with thousands separators (e.g. 152445165 → '152,445,165').

    Falls back to str(n) if the value isn't numeric, so an unexpected type in
    an HIBP response still renders instead of raising.
    """
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def render_breached_account(email: str, breaches: list[dict] | None) -> None:
    """Render the breaches a specific account appears in.

    Builds a Rich table with one row per breach: name, domain, date, account
    count, and which categories of data were stolen. An empty list prints a
    success line. ``None`` prints nothing, because the fetch function has
    already printed the reason (missing key or failed request).
    """
    if breaches is None:
        return
    if not breaches:
        print_success(f"{email}: no breaches found in HIBP.")
        return

    # One row per breach; the title carries the hit count.
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
    The table shows where the paste came from, its ID (so it can be looked
    up by hand), when it was posted, how many emails it holds, and its title.
    ``None`` prints nothing, because the fetch function has already printed
    the reason.
    """
    if pastes is None:
        return
    if not pastes:
        print_info(f"{email}: no pastes found in HIBP.")
        return

    tbl = make_table(
        f"Pastes for {email}  [{THEME['DIM']}]({len(pastes)})[/]",
        ("Source",  THEME["PRIMARY"]),  # e.g. "Pastebin", "GitHub"
        ("ID",      "white"),           # the paste's ID on that platform
        ("Date",    "white"),           # when it was posted (or ingested by HIBP)
        ("Emails",  THEME["ACCENT"]),   # number of emails in the paste
        ("Title",   "white"),           # the title given by whoever posted it
        show_lines=False,
    )
    for p in pastes:
        tbl.add_row(
            str(p.get("Source") or "?"),
            str(p.get("Id") or "?"),
            str(p.get("Date") or "?"),
            _fmt_int(p.get("EmailCount", 0)),
            str(p.get("Title") or "")[:50],  # keeps the table within a terminal width
        )
    console.print(tbl)


def render_breaches_for_domain(domain: str, breaches: list[dict] | None) -> None:
    """Render breaches affecting a domain (free endpoint).

    Lighter table than the account renderer — no paste column because the
    domain endpoint doesn't include paste data. Shows name, date, account
    count, and whether HIBP has verified the breach as authentic.
    "Unverified" breaches are still real data but may be incomplete or
    may contain fabricated entries mixed in with real ones.
    ``None`` means the lookup failed, which says nothing about the domain.
    """
    if breaches is None:
        print_error(f"{domain}: HIBP lookup failed (network or API problem).")
        return
    if not breaches:
        # Only breaches HIBP has catalogued count; an empty list does not mean
        # the domain was never breached.
        print_info(f"{domain}: no breaches recorded by HIBP.")
        return

    tbl = make_table(
        f"Breaches affecting {domain}  [{THEME['DIM']}]({len(breaches)})[/]",
        ("Name",     THEME["PRIMARY"]),
        ("Date",     "white"),
        ("Accounts", THEME["ACCENT"]),
        ("Verified", "white"),  # whether HIBP has confirmed the breach is genuine
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

    Four outcomes:
      - None:  the lookup failed (no connection, or an invalid hash).
      - 0:     the password is in no known breach corpus.
      - 1-9:   seen a few times — exposed, but not a commonly used password.
      - 10+:   a common password that attackers try first.

    The colour coding uses Rich styles from THEME for consistency with the
    rest of ScannUs output: green (success) / yellow (warn) / red (failure).
    """
    if count is None:
        print_error("Pwned Passwords lookup failed (network or invalid hash).")
        return
    if count == 0:
        print_success("Password not found in any known HIBP breach corpus.")
        return
    if count < 10:
        # A low count usually means one account on a breached site used it.
        print_warn(f"Password seen in HIBP corpus: {_fmt_int(count)} time(s) — change it.")
    else:
        # Ten or more sightings put it among the passwords that appear in
        # credential-stuffing lists ("password", "123456", "qwerty" are seen
        # millions of times).
        print_error(
            f"Password seen in HIBP corpus: {_fmt_int(count)} time(s) — "
            f"do NOT use it anywhere."
        )


# ---------------------------------------------------------------------------
# Convenience wrappers used by CLI + menus + AI dispatchers
# ---------------------------------------------------------------------------
# Each wrapper fetches and renders in one call and returns the data, for the
# command-line flags, the menus and the planner. Breach metadata by name has
# no wrapper: main.py and the menus render it as a key:value list themselves.
# ---------------------------------------------------------------------------

def check_account(email: str, *, include_pastes: bool = True) -> dict:
    """
    Run the full account check (breaches + optional pastes) and render.

    Fetches the breaches and, if requested, the pastes for one email, renders
    each table, and returns the data. ``include_pastes=False`` skips the paste
    lookup and its rate-limited request.

    Returns a serialisable dict suitable for JSON export / case storage:
      {"email", "checked", "breaches": [...], "pastes": [...],
       "breach_count", "paste_count", "checked_at"}

    ``pastes`` is an empty list when pastes were skipped or could not be
    fetched. ``checked`` is False when the breach lookup could not run, for
    example without an API key, so an empty breach list is not mistaken for a
    clean account. ``checked_at`` is a Unix timestamp.
    """
    breaches = hibp_breached_account(email)
    render_breached_account(email, breaches)
    pastes = None
    if include_pastes:
        pastes = hibp_pastes_for_account(email)
        render_pastes_for_account(email, pastes)
    return {
        "email":        email,
        "checked":      breaches is not None,
        "breaches":     breaches or [],
        "pastes":       pastes or [],
        "breach_count": len(breaches or []),
        "paste_count":  len(pastes or []),
        "checked_at":   time.time(),
    }


def check_domain(domain: str) -> list[dict] | None:
    """Run the free domain breach lookup and render.

    Thin wrapper around ``hibp_breaches_for_domain`` + ``render_breaches_for_domain``.
    Returns the raw list so callers can inspect or export the data, or ``None``
    when the lookup failed, so an empty list always means HIBP has no breach
    for the domain. Needs no API key.
    """
    breaches = hibp_breaches_for_domain(domain)
    render_breaches_for_domain(domain, breaches)
    return breaches


def check_password(password: str) -> int | None:
    """Run the k-anonymity password lookup and render.

    Thin wrapper that hashes, queries, and renders in one call, and returns the
    count from :func:`hibp_password_pwned` (``None`` when the lookup failed).
    The plaintext password is not stored or logged anywhere in this call chain.
    """
    count = hibp_password_pwned(password)
    render_password_pwned(count)
    return count
