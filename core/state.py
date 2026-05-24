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
CURRENT_CASE = {"search_params": {}, "results": []}
