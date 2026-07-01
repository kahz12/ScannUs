"""
core/database.py — SQLite DAO for ScannUs investigation cases.

Persists named cases and exposes CRUD helpers. save_case() returns a conflict
signal when a case name already exists, so callers can offer an "overwrite?"
prompt rather than failing silently; update_case() performs that overwrite and
delete_case() removes a case by name.
"""

import sqlite3
import os
import json
from datetime import datetime, timezone
from cli.ui import console, THEME
from core.config import DIR_CASES


class DBManager:
    """
    Data Access Object mapped to a local SQLite instance.
    Manages serialisation and hydration of investigation case sessions.
    """

    def __init__(self, db_path: str = os.path.join(DIR_CASES, "cases.db")):
        self.db_path = db_path
        self._initialize_db()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _initialize_db(self) -> None:
        """Creates tables if they do not already exist (idempotent)."""
        try:
            with self._connect() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS cases (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        name       TEXT UNIQUE NOT NULL,
                        query_data TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS results (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        case_id   INTEGER,
                        result_id INTEGER,
                        title     TEXT,
                        description TEXT,
                        link      TEXT,
                        FOREIGN KEY (case_id) REFERENCES cases (id) ON DELETE CASCADE
                    );
                """)
        except Exception as e:
            console.print(f"  [{THEME['ERROR']}]✘[/]  DB init error: {e}")

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_case(self, name: str, current_case: dict) -> tuple[bool, str, bool]:
        """
        Persists a case to the database.

        Returns:
            (success, message, name_conflict)
            - name_conflict is True when the name already exists, so the
              caller can offer an 'overwrite?' prompt.
        """
        query_data = json.dumps(current_case.get("search_params", {}), ensure_ascii=False)
        results = current_case.get("results", [])

        try:
            with self._connect() as conn:
                try:
                    cursor = conn.execute(
                        "INSERT INTO cases (name, query_data) VALUES (?, ?)",
                        (name, query_data),
                    )
                    case_id = cursor.lastrowid
                except sqlite3.IntegrityError:
                    # UNIQUE constraint → duplicate name
                    return False, f"A case named '{name}' already exists.", True

                self._insert_results(conn, case_id, results)
                return True, f"Case '{name}' saved successfully.", False

        except Exception as e:
            return False, f"Error saving case: {e}", False

    def update_case(self, name: str, current_case: dict) -> tuple[bool, str]:
        """
        Overwrites an existing case (by name) with new data.
        All previous results for the case are deleted before re-inserting.

        Returns:
            (success, message)
        """
        query_data = json.dumps(current_case.get("search_params", {}), ensure_ascii=False)
        results = current_case.get("results", [])

        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM cases WHERE name = ?", (name,)
                ).fetchone()

                if not row:
                    return False, f"No case named '{name}' found."

                case_id = row[0]
                now = datetime.now(timezone.utc).isoformat()

                conn.execute(
                    "UPDATE cases SET query_data = ?, updated_at = ? WHERE id = ?",
                    (query_data, now, case_id),
                )
                conn.execute("DELETE FROM results WHERE case_id = ?", (case_id,))
                self._insert_results(conn, case_id, results)

            return True, f"Case '{name}' updated successfully."

        except Exception as e:
            return False, f"Error updating case: {e}"

    def delete_case(self, name: str) -> tuple[bool, str]:
        """
        Deletes a case (and all its results via CASCADE) from the database.

        Returns:
            (success, message)
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM cases WHERE name = ?", (name,)
                )
                if cursor.rowcount == 0:
                    return False, f"No case named '{name}' found."
            return True, f"Case '{name}' deleted."
        except Exception as e:
            return False, f"Error deleting case: {e}"

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_all_cases(self) -> list[tuple]:
        """Returns all cases as (id, name, created_at) tuples, newest first."""
        try:
            with self._connect() as conn:
                return conn.execute(
                    "SELECT id, name, created_at FROM cases ORDER BY created_at DESC"
                ).fetchall()
        except Exception as e:
            console.print(f"  [{THEME['ERROR']}]✘[/]  Error fetching cases: {e}")
            return []

    def get_case_by_id(self, case_id: int) -> dict | None:
        """
        Deep-fetches a case by ID, joining root metadata with its result nodes.

        Returns:
            dict with keys 'name', 'search_params', 'results', or None on failure.
        """
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row

                case_row = conn.execute(
                    "SELECT name, query_data FROM cases WHERE id = ?", (case_id,)
                ).fetchone()

                if not case_row:
                    return None

                result_rows = conn.execute(
                    "SELECT result_id, title, description, link "
                    "FROM results WHERE case_id = ? ORDER BY result_id ASC",
                    (case_id,),
                ).fetchall()

            search_params = json.loads(case_row["query_data"]) if case_row["query_data"] else {}
            results = [
                {
                    "id":          row["result_id"],
                    "title":       row["title"],
                    "description": row["description"],
                    "link":        row["link"],
                }
                for row in result_rows
            ]

            return {"name": case_row["name"], "search_params": search_params, "results": results}

        except Exception as e:
            console.print(f"  [{THEME['ERROR']}]✘[/]  Error loading case: {e}")
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _insert_results(self, conn: sqlite3.Connection,
                        case_id: int, results: list) -> None:
        """Batch-inserts result rows into the results table."""
        conn.executemany(
            "INSERT INTO results (case_id, result_id, title, description, link) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (case_id, r.get("id"), r.get("title"),
                 r.get("description"), r.get("link"))
                for r in results
            ],
        )
