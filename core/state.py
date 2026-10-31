# Global mutable runtime state singleton.
# This module is a transient in-memory store for the active session. It exists
# so that CLI menus and AI dispatchers can share search results without passing
# large data structures through every call frame.
#
# Nothing here is persisted on its own — callers must explicitly save to the DB
# via core.case_manager.save_case() if they want the session to survive restart.

# LAST_RESULTS — flat list of the most recently returned search result dicts.
# Reset on each new search; read by menus and the AI planner for post-processing.
LAST_RESULTS = []

# CURRENT_CASE — structured dict for the active investigation session.
#   "search_params": dict  — the query, engine, and other parameters used to
#                            produce the current result set. Serialised to the
#                            "query_data" column when the case is saved to the DB.
#   "results":       list  — the result objects accumulated this session.
#                            Persisted to the "results" table on save.
#   "evidence":      list  — values found this session, each with its origin.
#                            See search.smart_search.build_evidence for the fields.
#   "investigation": dict  — goal, steps and report of the last planner run.
CURRENT_CASE = {"search_params": {}, "results": [], "evidence": [], "investigation": None}


def add_results(results: list[dict]) -> None:
    """Adds search results to the active case, skipping links it already holds."""
    case_results = CURRENT_CASE.setdefault("results", [])
    known = {r.get("link") for r in case_results}
    for r in results:
        link = r.get("link") or "N/A"
        if link in known:
            continue
        known.add(link)
        case_results.append({
            "id":          len(case_results) + 1,
            "title":       r.get("title", "N/A"),
            "description": r.get("description", "N/A"),
            "link":        link,
        })


def add_evidence(records: list[dict]) -> int:
    """
    Adds evidence records to the active case and returns how many were new.

    The same value from the same source counts once, while the same value on
    two pages stays as two records, because each page is separate evidence.
    """
    evidence = CURRENT_CASE.setdefault("evidence", [])
    known = {(e["category"], e["value"], e["source"]) for e in evidence}
    added = 0
    for record in records:
        key = (record["category"], record["value"], record["source"])
        if key not in known:
            known.add(key)
            evidence.append(record)
            added += 1
    return added
