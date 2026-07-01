"""
search/phone_osint.py — Phone-number intelligence via libphonenumber.

Given a phone number, this resolves everything that can be known *offline* from
Google's libphonenumber metadata — validity, country/region, geographic
description, carrier, time zones and line type — and then generates an OSINT
**footprint**: ready-to-run search dorks (across the number's different written
forms) plus a couple of direct number-lookup links. It is the phone-side
counterpart to Sherlock/Maigret (usernames) and Holehe (emails), and it closes
the last gap in the Findings Hub, where ``phone`` was the only artifact kind
with no dedicated tool.

Where this fits in the ScannUs OSINT chain::

    phone → [footprint dork] → search → [result URLs] → analyse / download

Unlike :mod:`search.username_enum` and :mod:`search.email_enum`, this tool does
**no network I/O** — libphonenumber bundles its own metadata, so a lookup is
deterministic and instant. There is therefore deliberately *no* persistent
cache and *no* throttle around it (both exist purely to tame network calls);
the footprint entries are generated strings, not live probes. Running a
footprint dork goes through :func:`cli.actions.do_search`, which already pools
the resulting URLs into the hub.

Public API:
  phone_lookup(phone, region=None) -> dict | None
  phone_osint(phone, region=None, save_json=True) -> dict | None
"""

import os
import json
from urllib.parse import quote_plus

import phonenumbers
from phonenumbers import carrier, geocoder, timezone, PhoneNumberType

from cli.ui import (
    console, THEME,
    print_warn, print_error, print_success, make_table,
)
from core.config import DIR_REPORTS
# Reuse the same region fallback set the PII extractor uses, so a domestically
# formatted number parses identically here and in search.smart_search.
from search.smart_search import _PHONE_REGIONS


# Human-readable labels for libphonenumber's PhoneNumberType enum.
_LINE_TYPE_LABELS = {
    PhoneNumberType.FIXED_LINE:           "fixed line",
    PhoneNumberType.MOBILE:               "mobile",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed line or mobile",
    PhoneNumberType.TOLL_FREE:            "toll free",
    PhoneNumberType.PREMIUM_RATE:         "premium rate",
    PhoneNumberType.SHARED_COST:          "shared cost",
    PhoneNumberType.VOIP:                 "VoIP",
    PhoneNumberType.PERSONAL_NUMBER:      "personal number",
    PhoneNumberType.PAGER:                "pager",
    PhoneNumberType.UAN:                  "UAN",
    PhoneNumberType.VOICEMAIL:            "voicemail",
    PhoneNumberType.UNKNOWN:              "unknown",
}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse(phone: str, region: str | None):
    """Parse *phone* into a libphonenumber object.

    Tries the caller-supplied *region* first (and ``None`` for ``+``-prefixed
    international numbers), then falls back across the common regions used by
    the PII extractor so a domestically formatted number still resolves.
    Returns the parsed number or ``None`` if nothing claims it.
    """
    candidates = [region] if region else [None, *_PHONE_REGIONS]
    for reg in candidates:
        try:
            num = phonenumbers.parse(phone, reg)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_possible_number(num):
            return num
    # Last resort: return whatever the first attempt parsed (even if not
    # "possible"), so callers can still report a country code.
    for reg in candidates:
        try:
            return phonenumbers.parse(phone, reg)
        except phonenumbers.NumberParseException:
            continue
    return None


# ---------------------------------------------------------------------------
# Footprint generation (offline — produces queries/links, runs nothing)
# ---------------------------------------------------------------------------

def _build_footprint(e164: str, national: str, region_code: str) -> list[dict]:
    """Generate OSINT pivots for a number.

    Each entry is ``{"label", "kind", "value"}`` where ``kind`` is:
      - ``"search"`` → ``value`` is a query string to feed into a SERP search
        (the TUI runs it via :func:`cli.actions.do_search`).
      - ``"link"``   → ``value`` is a URL to a number-lookup service.
    """
    forms = [f'"{f}"' for f in dict.fromkeys([e164, national]) if f]
    dork = " OR ".join(forms)
    digits = "".join(ch for ch in e164 if ch.isdigit())

    footprint: list[dict] = []
    if dork:
        footprint.append({"label": "Exact-match web search", "kind": "search", "value": dork})
        footprint.append({"label": "Social mentions search",
                          "kind": "search",
                          "value": f'{dork} (site:facebook.com OR site:twitter.com OR site:instagram.com)'})
    if region_code:
        footprint.append({
            "label": "Truecaller lookup",
            "kind": "link",
            "value": f"https://www.truecaller.com/search/{region_code.lower()}/{digits}",
        })
    if digits:
        footprint.append({
            "label": "WhatsApp account check (wa.me)",
            "kind": "link",
            "value": f"https://wa.me/{digits}",
        })
        footprint.append({
            "label": "Sync.me lookup",
            "kind": "link",
            "value": f"https://sync.me/search/?number={quote_plus('+' + digits)}",
        })
    return footprint


# ---------------------------------------------------------------------------
# Core lookup (pure, offline)
# ---------------------------------------------------------------------------

def phone_lookup(phone: str, region: str | None = None) -> dict | None:
    """Resolve offline intelligence for *phone*.

    Args:
        phone:  The number, ideally in international ``+CC…`` form.
        region: Optional ISO-3166 region hint (e.g. ``"US"``) for numbers
                written in national format.

    Returns:
        A report dict (see module docstring for the schema), or ``None`` if the
        input is empty or completely unparseable.
    """
    if not phone or not phone.strip():
        return None
    phone = phone.strip()

    num = _parse(phone, region)
    if num is None:
        return None

    valid = phonenumbers.is_valid_number(num)
    region_code = phonenumbers.region_code_for_number(num) or ""

    e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    international = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    national = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)
    rfc3966 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.RFC3966)

    return {
        "input":        phone,
        "valid":        valid,
        "possible":     phonenumbers.is_possible_number(num),
        "e164":         e164,
        "international": international,
        "national":     national,
        "rfc3966":      rfc3966,
        "country_code": num.country_code,
        "region_code":  region_code,
        "location":     geocoder.description_for_number(num, "en") or "",
        "carrier":      carrier.name_for_number(num, "en") or "",
        "timezones":    list(timezone.time_zones_for_number(num)),
        "line_type":    _LINE_TYPE_LABELS.get(
                            phonenumbers.number_type(num), "unknown"),
        "footprint":    _build_footprint(e164, national, region_code),
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_report_json(report: dict) -> str | None:
    """Persist *report* to ``DIR_REPORTS``; returns the saved path or None."""
    os.makedirs(DIR_REPORTS, exist_ok=True)
    safe_name = "".join(c if c.isalnum() else "_" for c in report.get("input", "phone"))
    path = os.path.join(DIR_REPORTS, f"phone_{safe_name}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return path
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Rendering + public entry point
# ---------------------------------------------------------------------------

def phone_osint(phone: str, region: str | None = None,
                save_json: bool = True) -> dict | None:
    """Look up *phone*, render a Rich report, and optionally persist JSON.

    Returns the report dict, or ``None`` if the number could not be parsed at
    all (a friendly message is printed in that case).
    """
    if not phone or not phone.strip():
        print_error("Phone number cannot be empty.")
        return None

    report = phone_lookup(phone, region=region)
    if report is None:
        print_error(f"Could not parse '{phone.strip()}' as a phone number. "
                    "Try international format, e.g. +14155552671.")
        return None

    if not report["valid"]:
        print_warn(
            f"'{report['input']}' is not a valid number"
            f"{' (parsed as +%s, region %s)' % (report['country_code'], report['region_code']) if report['region_code'] else ''}"
            " — showing best-effort metadata."
        )

    # Core metadata table.
    tbl = make_table(
        f"Phone Intelligence  [{THEME['DIM']}]{report['input']} · via libphonenumber[/]",
        ("Field", THEME["PRIMARY"]),
        ("Value", "white"),
        show_lines=False,
    )
    tbl.add_row("Valid",        "[green]yes[/]" if report["valid"] else "[red]no[/]")
    tbl.add_row("E.164",        report["e164"])
    tbl.add_row("International", report["international"])
    tbl.add_row("National",     report["national"])
    tbl.add_row("Country code", f"+{report['country_code']}")
    tbl.add_row("Region",       report["region_code"] or "—")
    tbl.add_row("Location",     report["location"] or "—")
    tbl.add_row("Carrier",      report["carrier"] or "—")
    tbl.add_row("Line type",    report["line_type"])
    tbl.add_row("Time zones",   ", ".join(report["timezones"]) or "—")
    console.print()
    console.print(tbl)

    # Footprint: generated pivots the user can run next.
    if report["footprint"]:
        ftbl = make_table(
            f"OSINT Footprint  [{THEME['DIM']}]search dorks · lookup links[/]",
            ("#",     THEME["DIM"]),
            ("Pivot", THEME["PRIMARY"]),
            ("Kind",  THEME["ACCENT"]),
            ("Query / URL", THEME["LINK"]),
            show_lines=False,
        )
        for i, fp in enumerate(report["footprint"], 1):
            ftbl.add_row(str(i), fp["label"], fp["kind"], fp["value"])
        console.print()
        console.print(ftbl)

    if save_json:
        path = _save_report_json(report)
        if path:
            print_success(f"Report saved → {path}")

    return report
