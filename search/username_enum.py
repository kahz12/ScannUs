"""
search/username_enum.py — Username enumeration across hundreds of social sites.

Integrates Sherlock and/or Maigret as subprocess backends:
  - Sherlock  — fast, ~400 well-maintained sites
  - Maigret   — Sherlock fork covering ~3,000 sites + richer metadata

Either backend is auto-selected based on availability. Both produce a unified
result schema so downstream consumers don't need to know which engine ran.

Some sites answer "found" for any handle of a given shape; with Sherlock, ten
sites claim a made-up handle that contains a dot. Each lookup therefore also
runs on a made-up handle of the same shape (see :func:`_control_handle`), and
a site that claims that handle as well is left out of the results, since its
answer says nothing about the real one.

Public API:
  enumerate_username(username, backend="auto", timeout=20) -> list[dict]
  username_enum(username, backend="auto", timeout=20, save_json=True) -> list[dict] | None
"""

import os
import csv
import json
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

from cli.ui import (
    console, THEME,
    print_info, print_warn, print_error, print_success, make_table,
)
from core.config import DIR_REPORTS
from core.throttle import throttled


# ---------------------------------------------------------------------------
# Backend detection (resolved at import time)
# ---------------------------------------------------------------------------

_VENV_BIN = os.path.dirname(sys.executable)
_SHERLOCK_BIN = shutil.which("sherlock") or shutil.which("sherlock", path=_VENV_BIN)
_MAIGRET_BIN  = shutil.which("maigret") or shutil.which("maigret", path=_VENV_BIN)


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

# Maigret's "available" means the handle is not registered on the site.
_MAIGRET_FOUND_STATUSES = {"claimed", "found"}


def _maigret_status(info: dict) -> str:
    """
    Reads the check status of one site in a Maigret JSON report, lowercased.

    Maigret 0.6 writes ``status`` as the check result object
    (``{"status": "Claimed", "url": ..., "ids": ...}``); older releases wrote
    the bare string.
    """
    status = info.get("status")
    if isinstance(status, dict):
        status = status.get("status")
    return str(status or "").lower()


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
            if not isinstance(info, dict):
                continue
            status_raw = _maigret_status(info)
            if status_raw and status_raw not in _MAIGRET_FOUND_STATUSES:
                continue
            nested = info["status"] if isinstance(info.get("status"), dict) else {}
            url = info.get("url_user") or info.get("url") or nested.get("url") or ""
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
# Control handle — sites that claim any handle of a given shape
# ---------------------------------------------------------------------------

# A made-up handle shorter than this is likely to be a real account on the
# busier sites, and would then remove true hits, so short handles run alone.
_MIN_CONTROL_CHARS = 5


def _control_handle(username: str) -> str | None:
    """
    Builds a made-up handle with the shape of *username*: the same length,
    separators such as ``.``, ``_`` and ``-`` in the same places, a digit
    wherever *username* has a digit and a letter of the same case elsewhere.

    It is derived from *username*, so the same handle always gets the same
    control. Returns None when *username* has fewer than
    ``_MIN_CONTROL_CHARS`` letters and digits.
    """
    if sum(ch.isalnum() for ch in username) < _MIN_CONTROL_CHARS:
        return None
    rng = random.Random(f"scannus-control:{username}")
    while True:
        control = "".join(
            rng.choice("0123456789") if ch.isdigit()
            else rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") if ch.isupper()
            else rng.choice("abcdefghijklmnopqrstuvwxyz") if ch.isalpha()
            else ch
            for ch in username
        )
        if control.lower() != username.lower():
            return control


def _lookup(backend: str, handle: str, timeout: int) -> list[dict]:
    """Runs one backend on one handle."""
    if backend == "sherlock":
        return _run_sherlock(handle, timeout)
    return _run_maigret(handle, timeout)


def _enumerate(username: str, backend: str,
               timeout: int) -> tuple[list[dict], list[str], str | None]:
    """
    Looks up *username* and its control handle in parallel.

    Returns:
        The rows for the sites that did not claim the control handle, the
        names of the sites left out, and the control handle (None when the
        handle is too short to have one).
    """
    control = _control_handle(username)
    print_info(
        f"Running {backend} on '{username}'"
        + (f" and on the made-up handle '{control}'" if control else "")
        + f" (per-site timeout {timeout}s)…"
    )
    if control is None:
        return _lookup(backend, username, timeout), [], None

    with ThreadPoolExecutor(max_workers=2) as pool:
        real = pool.submit(_lookup, backend, username, timeout)
        made_up = pool.submit(_lookup, backend, control, timeout)
        rows, control_rows = real.result(), made_up.result()

    claim_anything = {r["site"] for r in control_rows}
    kept = [r for r in rows if r["site"] not in claim_anything]
    left_out = sorted({r["site"] for r in rows} & claim_anything, key=str.lower)
    return kept, left_out, control


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enumerate_username(username: str, backend: str = "auto",
                       timeout: int = 20) -> list[dict]:
    """
    Enumerates ``username`` across social sites using the selected backend.

    Sites that also claim a made-up handle of the same shape are left out
    (see the module docstring).

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

    return _enumerate(username.strip(), chosen, timeout)[0]


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

    results, left_out, control = _enumerate(username.strip(), chosen, timeout)
    if left_out:
        print_info(
            f"Left out {len(left_out)} site(s) that also claimed the made-up "
            f"handle '{control}': {', '.join(left_out)}"
        )

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
