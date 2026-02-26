import sqlite3
import os
import json
from datetime import datetime
from rich.console import Console
from core.config import DIR_CASES

console = Console()

class DBManager:
    """
    Data Access Object (DAO) mapped to a local SQLite instance.
    Handles serialization and hydration of structured 'cases' 
    (search sessions, collected nodes, queries), ensuring data persistence across runs.
    """
    def __init__(self, db_path=os.path.join(DIR_CASES, "cases.db")):
        self.db_path = db_path
        self._initialize_db()

    def _initialize_db(self):
        """
        Bootstrap method. Verifies and creates the internal schema constraints.
        Safe to call multiple times as it uses IF NOT EXISTS.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Master 'cases' table. Stores high-level query metadata.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    query_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Dependent 'results' table mapped back to 'cases' via foreign key.
            # CASCADE ensures clean teardowns if a parent case is deleted.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id INTEGER,
                    result_id INTEGER,
                    title TEXT,
                    description TEXT,
                    link TEXT,
                    FOREIGN KEY (case_id) REFERENCES cases (id) ON DELETE CASCADE
                )
            ''')
            
            conn.commit()
            conn.close()
        except Exception as e:
            console.print(f"[bold red]Error initializing the database:[/bold red] {e}")

    def save_case(self, name, current_case):
        """
        Commits an active state dictionary payload to the database.
        Includes rollback/conflict catching for overlapping case names.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Serialize the complex query dictionary into a flat JSON string for storage
            query_data_str = json.dumps(current_case.get("terminos", {}), ensure_ascii=False)
            
            try:
                # Attempt to insert the root case node
                cursor.execute(
                    "INSERT INTO cases (name, query_data) VALUES (?, ?)", 
                    (name, query_data_str)
                )
                case_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                # Catch UNIQUE constraint failures cleanly (duplicate case names)
                conn.close()
                return False, f"A case with the name '{name}' already exists."
            
            # Batch process the corresponding child result nodes
            resultados = current_case.get("resultados", [])
            for res in resultados:
                cursor.execute(
                    """
                    INSERT INTO results (case_id, result_id, title, description, link)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        case_id,
                        res.get('id'),
                        res.get('title'),
                        res.get('description'),
                        res.get('link')
                    )
                )
            
            # Commit the transaction block
            conn.commit()
            conn.close()
            return True, f"Case '{name}' saved successfully."
        except Exception as e:
            return False, f"Error saving the case: {e}"

    def get_all_cases(self):
        """
        Queries and returns a flat array of all persisted case metadata, sorted chronologically.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, created_at FROM cases ORDER BY created_at DESC")
            cases = cursor.fetchall()
            conn.close()
            return cases
        except Exception as e:
            console.print(f"[bold red]Error retrieving the list of cases:[/bold red] {e}")
            return []

    def get_case_by_id(self, case_id):
        """
        Performs a deep fetch of a specific case, joining the root metadata with 
        all its associated result nodes, and reconstituting the Python dictionary state.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            # Row factory enables dictionary-like column access
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Fetch root metadata
            cursor.execute("SELECT name, query_data FROM cases WHERE id = ?", (case_id,))
            case_row = cursor.fetchone()
            
            if not case_row:
                conn.close()
                return None
            
            # Fetch the associated leaf nodes
            cursor.execute("SELECT result_id, title, description, link FROM results WHERE case_id = ? ORDER BY result_id ASC", (case_id,))
            result_rows = cursor.fetchall()
            conn.close()
            
            # Deserialize the query JSON
            terminos = json.loads(case_row['query_data']) if case_row['query_data'] else {}
            resultados = []
            
            # Reconstruct the results array
            for row in result_rows:
                resultados.append({
                    'id': row['result_id'],
                    'title': row['title'],
                    'description': row['description'],
                    'link': row['link']
                })
                
            return {
                "name": case_row['name'],
                "terminos": terminos,
                "resultados": resultados
            }
        except Exception as e:
            console.print(f"[bold red]Error loading the case:[/bold red] {e}")
            return None
