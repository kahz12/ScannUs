"""
search/username_enum.py — Username enumeration across hundreds of social sites.

Integrates Sherlock and/or Maigret as subprocess backends:
  - Sherlock  — fast, ~400 well-maintained sites
  - Maigret   — Sherlock fork covering ~3,000 sites + richer metadata

Either backend is auto-selected based on availability. Both produce a unified
result schema so downstream consumers don't need to know which engine ran.

Public API:
  enumerate_username(username, backend="auto", timeout=20) -> list[dict]
  username_enum(username, backend="auto", timeout=20, save_json=True) -> None
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
from core.throttle import throttled


# ---------------------------------------------------------------------------
# Backend detection (resolved at import time)
# ---------------------------------------------------------------------------

_SHERLOCK_BIN = shutil.which("sherlock")
_MAIGRET_BIN  = shutil.which("maigret")


def _backend_available(name: str) -> bool:
    if name == "sherlock":
        return _SHERLOCK_BIN is not None
    if name == "maigret":
        return _MAIGRET_BIN is not None
    return False


def _select_backend(preference: str) -> str | None:
    """Returns the backend name to use, or None if no candidate is installed."""
    pref = (preference or "auto").lower()
    if pref == "auto":
        if _SHERLOCK_BIN:
            return "sherlock"
        if _MAIGRET_BIN:
            return "maigret"
        return None
    return pref if _backend_available(pref) else None


# ---------------------------------------------------------------------------
# Sherlock backend
# ---------------------------------------------------------------------------

@throttled(namespace="sherlock")
def _run_sherlock(username: str, timeout: int = 20) -> list[dict]:
    """
    Runs Sherlock with CSV output and returns claimed accounts.

    Each result dict has: site, url, status, http_status, response_time.

    Rate-limited via the shared ``sherlock`` token bucket so rapid
    back-to-back launches (e.g. an agent loop) get spaced out; a single
    interactive call never waits.
    """
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            _SHERLOCK_BIN, username,
            "--csv",
            "--folderoutput", tmp,
            "--timeout", str(timeout),
            "--print-found",
        ]
        try:
            subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=max(timeout * 30, 600), check=False,
            )
        except subprocess.TimeoutExpired:
            print_error("Sherlock execution timed out.")
            return []
        except FileNotFoundError:
            print_error("Sherlock binary disappeared mid-run.")
            return []

        csv_path = os.path.join(tmp, f"{username}.csv")
        if not os.path.exists(csv_path):
            # Fall back: scan dir for any csv produced by Sherlock.
            for fn in os.listdir(tmp):
                if fn.endswith(".csv"):
                    csv_path = os.path.join(tmp, fn)
                    break
        if not os.path.isfile(csv_path):
            return []

        results: list[dict] = []
        with open(csv_path, newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                exists = (row.get("exists") or "").strip().lower()
                if exists != "claimed":
                    continue
                results.append({
                    "site":          row.get("name") or row.get("site") or "?",
                    "url":           row.get("url_user") or "",
                    "status":        "found",
                    "http_status":   row.get("http_status") or "",
                    "response_time": row.get("response_time_s") or "",
                })
        return results


# ---------------------------------------------------------------------------
# Maigret backend
# ---------------------------------------------------------------------------

_MAIGRET_FOUND_STATUSES = {"claimed", "found", "available"}


@throttled(namespace="maigret")
def _run_maigret(username: str, timeout: int = 20) -> list[dict]:
    """
    Runs Maigret with simple-JSON output and returns claimed accounts.

    Each result dict has: site, url, status, http_status, response_time.

    Rate-limited via the shared ``maigret`` token bucket (gentler than
    Sherlock's — Maigret's ~3000-site sweep is far heavier).
    """
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            _MAIGRET_BIN, username,
            "--json", "simple",
            "--folderoutput", tmp,
            "--no-progressbar",
            "--timeout", str(timeout),
        ]
        try:
            subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=max(timeout * 60, 1800), check=False,
            )
        except subprocess.TimeoutExpired:
            print_error("Maigret execution timed out.")
            return []
        except FileNotFoundError:
            print_error("Maigret binary disappeared mid-run.")
            return []

        json_path = os.path.join(tmp, f"report_{username}_simple.json")
        if not os.path.exists(json_path):
            # Maigret has used different naming conventions across versions.
            for fn in os.listdir(tmp):
                if fn.endswith(".json"):
                    json_path = os.path.join(tmp, fn)
                    break
        if not os.path.isfile(json_path):
            return []

        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []

        results: list[dict] = []
        for site, info in (data or {}).items():
            info = info or {}
            status_raw = (info.get("status") or "").lower()
            if status_raw and status_raw not in _MAIGRET_FOUND_STATUSES:
                continue
            url = info.get("url_user") or info.get("url") or ""
            if not url:
                continue
            results.append({
                "site":          site,
                "url":           url,
                "status":        "found",
                "http_status":   str(info.get("http_status") or ""),
                "response_time": str(info.get("response_time") or ""),
            })
        return results


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_results_json(username: str, backend: str,
                       results: list[dict]) -> str | None:
    """Persists results to ``DIR_REPORTS``; returns the saved path or None."""
    if not results:
        return None
    os.makedirs(DIR_REPORTS, exist_ok=True)
    safe_name = "".join(c for c in username if c.isalnum() or c in ("-", "_"))
    path = os.path.join(DIR_REPORTS, f"username_{safe_name}_{backend}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "username": username,
                    "backend":  backend,
                    "count":    len(results),
                    "results":  results,
                },
                f, indent=2, ensure_ascii=False,
            )
        return path
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enumerate_username(username: str, backend: str = "auto",
                       timeout: int = 20) -> list[dict]:
    """
    Enumerates ``username`` across social sites using the selected backend.

    Args:
        username: Handle to look up.
        backend:  ``"auto"``, ``"sherlock"`` or ``"maigret"``.
        timeout:  Per-site request timeout in seconds.

    Returns:
        List of result dicts. Empty list if no backend is installed or no
        accounts were claimed.
    """
    if not username or not username.strip():
        return []

    chosen = _select_backend(backend)
    if chosen is None:
        return []

    print_info(
        f"Running {chosen} on '{username}' (per-site timeout {timeout}s)…"
    )
    if chosen == "sherlock":
        return _run_sherlock(username.strip(), timeout)
    return _run_maigret(username.strip(), timeout)


def username_enum(username: str, backend: str = "auto",
                  timeout: int = 20, save_json: bool = True) -> list[dict] | None:
    """
    Enumerates a username across social sites and renders the result as a
    Rich table, optionally persisting the JSON report to ``outputs/reports``.

    Args:
        username:  Handle to look up.
        backend:   ``"auto"``, ``"sherlock"`` or ``"maigret"``.
        timeout:   Per-site request timeout (seconds).
        save_json: Persist results as JSON under ``DIR_REPORTS``.

    Returns:
        Sorted list of result dicts (possibly empty) so AI dispatchers and
        other programmatic callers can consume the data. ``None`` is
        returned only when the input is empty or no backend is installed
        (an explanatory message is printed in both cases).
    """
    if not username or not username.strip():
        print_error("Username cannot be empty.")
        return None

    chosen = _select_backend(backend)
    if chosen is None:
        if (backend or "auto").lower() == "auto":
            print_error(
                "No enumeration backend available. Install one of:\n"
                "    pip install sherlock-project\n"
                "    pip install maigret"
            )
        else:
            print_error(f"Backend '{backend}' is not installed.")
        return None

    results = enumerate_username(username, backend=chosen, timeout=timeout)

    if not results:
        print_warn(f"No accounts found for '{username}' via {chosen}.")
        return []

    results_sorted = sorted(results, key=lambda r: r["site"].lower())

    tbl = make_table(
        f"Username Enumeration  [{THEME['DIM']}]{username} · via {chosen}[/]",
        ("Site",   THEME["PRIMARY"]),
        ("URL",    THEME["LINK"]),
        ("Status", "green"),
        show_lines=False,
    )
    for r in results_sorted:
        tbl.add_row(r["site"], r["url"], r["status"])

    console.print()
    console.print(tbl)
    console.print(
        f"  [{THEME['DIM']}]Total: {len(results)} hit(s) · backend: {chosen}[/]"
    )

    if save_json:
        path = _save_results_json(username.strip(), chosen, results_sorted)
        if path:
            print_success(f"Results saved → {path}")

    return results_sorted
