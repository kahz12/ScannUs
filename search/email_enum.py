"""
search/email_enum.py — Email-to-service enumeration via Holehe.

Holehe probes ~120 services (Instagram, Twitter, Pinterest, Spotify, …) using
their password-reset flows to detect whether a target email is registered,
*without sending any email to the address*. It is the email-side counterpart
to Sherlock/Maigret (which enumerate usernames).

Where this fits in the ScannUs OSINT chain:
  - HIBP tells you where an email has been **leaked** (breach corpus).
  - email_enum tells you where the email is currently **registered** (live
    services). The two are complementary, not redundant.

Backend invocation: subprocess against the ``holehe`` CLI, mirroring the
pattern in :mod:`search.username_enum` for consistency. Results are
unified into a stable schema, rendered as a Rich table, persisted as a
JSON report to ``DIR_REPORTS``, and cached in the persistent SQLite cache
under the ``email_enum`` namespace (12h TTL) so repeat investigations on
the same address are instant.

Public API:
  enumerate_email(email, only_used=True, timeout=10) -> list[dict]
  email_enum(email, only_used=True, timeout=10, save_json=True) -> list[dict] | None
"""

import os
import csv
import json
import shutil
import subprocess
import tempfile

from cli.ui import (
    console, THEME,
    print_info, print_warn, print_error, print_success, make_table,
)
from core.config import DIR_REPORTS
from core.cache import cached_call
from core.throttle import throttled


# ---------------------------------------------------------------------------
# Backend detection (resolved at import time)
# ---------------------------------------------------------------------------

_HOLEHE_BIN = shutil.which("holehe")
HOLEHE_AVAILABLE = _HOLEHE_BIN is not None


# Holehe CSV columns (from holehe/core.py argparse + module output keys):
#   name · domain · rateLimit · error · exists · emailrecovery · phoneNumber · others
# The "exists" field is the string "True" / "False".
_FOUND_VALUES = {"true", "1", "yes"}


# ---------------------------------------------------------------------------
# Holehe backend
# ---------------------------------------------------------------------------

@throttled(namespace="holehe")
def _run_holehe(email: str, only_used: bool, timeout: int) -> list[dict]:
    """Run holehe and return a unified list of result dicts.

    Holehe's ``-C/--csv`` flag dumps the CSV into the process cwd with no
    way to override the path, so we run inside a temp directory and scan
    it for the produced file.

    Rate-limited via the shared ``holehe`` token bucket. Note this sits
    *inside* ``cached_call`` (see ``enumerate_email``), so a cache hit skips
    the bucket entirely — only real subprocess launches are throttled.
    """
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [_HOLEHE_BIN, email, "--csv", "--no-color", "--no-clear",
               "--timeout", str(timeout)]
        if only_used:
            cmd.append("--only-used")

        try:
            subprocess.run(
                cmd,
                capture_output=True, text=True,
                cwd=tmp,
                timeout=max(timeout * 40, 1200),
                check=False,
            )
        except subprocess.TimeoutExpired:
            print_error("Holehe execution timed out.")
            return []
        except FileNotFoundError:
            print_error("Holehe binary disappeared mid-run.")
            return []

        # Holehe names the file after the email (e.g. "user@example.com.csv");
        # the exact format has shifted across releases, so just scan the dir.
        csv_path = None
        for fn in os.listdir(tmp):
            if fn.endswith(".csv"):
                csv_path = os.path.join(tmp, fn)
                break
        if not csv_path or not os.path.isfile(csv_path):
            return []

        results: list[dict] = []
        with open(csv_path, newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                exists_raw = (row.get("exists") or "").strip().lower()
                claimed = exists_raw in _FOUND_VALUES
                if only_used and not claimed:
                    continue

                # Normalise to the same shape as username_enum so downstream
                # callers can treat "service presence" results uniformly.
                results.append({
                    "service":        row.get("name") or "?",
                    "domain":         row.get("domain") or "",
                    "email":          email,
                    "status":         "claimed" if claimed else "available",
                    "email_recovery": (row.get("emailrecovery") or "").strip(),
                    "phone_number":   (row.get("phoneNumber") or "").strip(),
                    "rate_limited":   (row.get("rateLimit") or "").strip().lower()
                                      in _FOUND_VALUES,
                    "error":          (row.get("error") or "").strip().lower()
                                      in _FOUND_VALUES,
                    "others":         (row.get("others") or "").strip(),
                })
        return results


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_results_json(email: str, results: list[dict]) -> str | None:
    """Persist results to ``DIR_REPORTS``; returns the saved path or None."""
    if not results:
        return None
    os.makedirs(DIR_REPORTS, exist_ok=True)
    safe_name = "".join(c if c.isalnum() else "_" for c in email)
    path = os.path.join(DIR_REPORTS, f"email_{safe_name}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "email":   email,
                    "backend": "holehe",
                    "count":   len(results),
                    "results": results,
                },
                f, indent=2, ensure_ascii=False,
            )
        return path
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enumerate_email(email: str, only_used: bool = True,
                    timeout: int = 10) -> list[dict]:
    """Enumerate ``email`` across services using Holehe.

    Args:
        email:     Address to look up.
        only_used: If True, only return services where the email is claimed.
        timeout:   Per-site request timeout (seconds, passed to holehe).

    Returns:
        List of result dicts (possibly empty). Empty if Holehe is missing.
    """
    if not email or not email.strip():
        return []
    if not HOLEHE_AVAILABLE:
        return []

    email = email.strip()

    def _produce() -> list[dict]:
        print_info(
            f"Running holehe on '{email}' (per-site timeout {timeout}s)…"
        )
        return _run_holehe(email, only_used=only_used, timeout=timeout)

    # Cache by (email, only_used). The 12h TTL is configured via the
    # ``email_enum`` entry in core.cache.DEFAULT_TTL; passing ttl=None lets
    # cached_call resolve it from the namespace defaults.
    return cached_call(
        "email_enum", [email, "used" if only_used else "all"], _produce,
    ) or []


def email_enum(email: str, only_used: bool = True, timeout: int = 10,
               save_json: bool = True) -> list[dict] | None:
    """Run Holehe and render a Rich table + optionally persist a JSON report.

    Returns the result list (possibly empty), or ``None`` if Holehe is not
    installed (a friendly install hint is printed in that case).
    """
    if not email or not email.strip():
        print_error("Email cannot be empty.")
        return None

    if not HOLEHE_AVAILABLE:
        print_error(
            "Holehe is not installed. Install it with:\n"
            "    pip install holehe"
        )
        return None

    results = enumerate_email(email, only_used=only_used, timeout=timeout)

    if not results:
        print_warn(
            f"No service registrations found for '{email}'."
            if only_used else
            f"Holehe returned no results for '{email}'."
        )
        return results

    results_sorted = sorted(results, key=lambda r: r["service"].lower())

    tbl = make_table(
        f"Email Enumeration  [{THEME['DIM']}]{email} · via holehe[/]",
        ("Service", THEME["PRIMARY"]),
        ("Domain",  THEME["LINK"]),
        ("Status",  "green"),
        ("Recovery hint", THEME["DIM"]),
        show_lines=False,
    )
    for r in results_sorted:
        recovery = r["email_recovery"] or r["phone_number"] or ""
        tbl.add_row(r["service"], r["domain"], r["status"], recovery)

    claimed = sum(1 for r in results_sorted if r["status"] == "claimed")
    console.print()
    console.print(tbl)
    console.print(
        f"  [{THEME['DIM']}]Total: {claimed} claimed · "
        f"{len(results_sorted)} entries · backend: holehe[/]"
    )

    if save_json:
        path = _save_results_json(email.strip(), results_sorted)
        if path:
            print_success(f"Results saved → {path}")

    return results_sorted
