"""
core/case_manager.py — Save and load investigation sessions from SQLite.
Uses Rich console helpers for a consistent visual experience.
"""

from cli.ui import console, THEME, print_success, print_error, print_warn, print_info, make_table
from core import state
from core.database import DBManager
from core.findings import EVIDENCE_KINDS, get_hub


def case_snapshot() -> dict:
    """
    Returns the active case as it should be stored: its evidence plus the hub
    findings not already covered by it or by the search results, such as the
    subdomains and addresses that recon found.
    """
    case = state.CURRENT_CASE
    evidence = list(case.get("evidence") or [])
    links = {r.get("link") for r in case.get("results") or []}
    covered = {(EVIDENCE_KINDS.get(e["category"]), e["value"].lower()) for e in evidence}
    for finding in get_hub().all():
        if (finding.kind, finding.value.lower()) in covered or finding.value in links:
            continue
        evidence.append({
            "category":       finding.kind,
            "value":          finding.value,
            "confidence":     "",
            "source":         finding.label if finding.label.startswith("http") else "",
            "tool":           finding.source,
            "found_at":       finding.found_at,
            "content_sha256": "",
        })
    return {**case, "evidence": evidence}


def _has_content(case: dict) -> bool:
    return bool(case.get("results") or case.get("evidence") or case.get("investigation"))


def save_case_as(name: str) -> bool:
    """Saves the active case under *name* without prompting. Returns True on success."""
    case = case_snapshot()
    if not _has_content(case):
        print_warn("Nothing to save — the session has no results or findings.")
        return False
    success, message, _conflict = DBManager().save_case(name, case)
    (print_success if success else print_error)(message)
    return success


def save_case() -> None:
    """
    Prompts the user for a case name and persists the current session to the
    local SQLite database. If a case with the same name already exists, offers
    an overwrite prompt rather than silently failing or duplicating.
    """
    case = case_snapshot()
    if not _has_content(case):
        print_warn("No results to save — run a search first.")
        return

    case_name = console.input(
        f"  [{THEME['DIM']}]Case name (e.g. investigation_z):[/] [{THEME['INPUT']}]❯[/] "
    ).strip()

    if not case_name:
        print_error("Case name cannot be empty.")
        return

    db = DBManager()
    success, message, conflict = db.save_case(case_name, case)

    if success:
        print_success(message)
        return

    if conflict:
        # The name already exists in the DB — ask before overwriting so the
        # user doesn't accidentally clobber a previous investigation.
        confirm = console.input(
            f"  [{THEME['WARN']}]⚠[/]  Case '{case_name}' already exists. "
            f"Overwrite? (y/n) [{THEME['INPUT']}]❯[/] "
        ).strip().lower()

        if confirm == "y":
            ok, msg = db.update_case(case_name, case)
            if ok:
                print_success(msg)
            else:
                print_error(msg)
        else:
            print_info("Save cancelled.")
    else:
        print_error(message)


def load_case() -> bool:
    """
    Lists all saved cases in a Rich table, prompts the user to select one by
    number, and restores it into the global session state and the findings hub.

    Returns:
        True if a case was loaded successfully, False otherwise (no cases in
        the DB, invalid selection, missing data, or an empty case).
    """
    db = DBManager()
    saved_cases = db.get_all_cases()

    if not saved_cases:
        print_warn("No saved cases found — save a search session first (option 'save').")
        return False

    # Render the case list so the user can identify which number to enter.
    tbl = make_table(
        f"Saved Cases  [{THEME['DIM']}]({len(saved_cases)} total)[/]",
        ("#",       THEME["DIM"]),
        ("Name",    "bold white"),
        ("Created", THEME["DIM"]),
        show_lines=False,
    )
    for i, row in enumerate(saved_cases, 1):
        # Each row from get_all_cases() is (id, name, created_at).
        tbl.add_row(str(i), row[1], str(row[2]))

    console.print()
    console.print(tbl)

    choice = console.input(
        f"\n  [{THEME['DIM']}]Select case number to load:[/] [{THEME['INPUT']}]❯[/] "
    ).strip()

    if not choice.isdigit() or not (1 <= int(choice) <= len(saved_cases)):
        print_error(f"'{choice}' is not a valid selection.")
        return False

    case_idx  = int(choice) - 1
    case_id   = saved_cases[case_idx][0]
    case_name = saved_cases[case_idx][1]

    case_data = db.get_case_by_id(case_id)
    if not case_data:
        print_error("Could not load case data from the database.")
        return False

    # Restore the session globals so menus and the AI planner can pick up
    # from where the previous session left off.
    state.CURRENT_CASE  = case_data
    state.LAST_RESULTS  = state.CURRENT_CASE.get("results", [])

    if not _has_content(case_data):
        print_warn("The selected case exists but it is empty.")
        return False

    evidence = case_data.get("evidence", [])
    hub = get_hub()
    hub.ingest_results(state.LAST_RESULTS, source="case")
    hub.ingest_evidence(evidence)

    print_success(
        f"Case '[bold]{case_name}[/bold]' loaded — "
        f"{len(state.LAST_RESULTS)} results and {len(evidence)} findings available."
    )
    return True
