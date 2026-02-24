import sqlite3
import os
import json
from datetime import datetime
from rich.console import Console
from core.config import DIR_CASES

console = Console()

class DBManager:
    """
    Class to manage the storage and retrieval of cases
    using a SQLite database.
    """
    def __init__(self, db_path=os.path.join(DIR_CASES, "cases.db")):
        self.db_path = db_path
        self._initialize_db()

    def _initialize_db(self):
        """Initializes the database by creating necessary tables if they do not exist."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Cases table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    query_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Results table associated with a case
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
            console.print(f"[bold red]Error al inicializar la base de datos:[/bold red] {e}")

    def save_case(self, name, current_case):
        """
        Saves a case and its results into the database.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Insert the case
            query_data_str = json.dumps(current_case.get("terminos", {}), ensure_ascii=False)
            
            try:
                cursor.execute(
                    "INSERT INTO cases (name, query_data) VALUES (?, ?)", 
                    (name, query_data_str)
                )
                case_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                conn.close()
                return False, f"Ya existe un caso con el nombre '{name}'."
            
            # Insert the results
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
            
            conn.commit()
            conn.close()
            return True, f"Caso '{name}' guardado exitosamente."
        except Exception as e:
            return False, f"Error al guardar el caso: {e}"

    def get_all_cases(self):
        """
        Retrieves a list of all saved cases.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, created_at FROM cases ORDER BY created_at DESC")
            cases = cursor.fetchall()
            conn.close()
            return cases
        except Exception as e:
            console.print(f"[bold red]Error al obtener la lista de casos:[/bold red] {e}")
            return []

    def get_case_by_id(self, case_id):
        """
        Retrieves a complete case (search data and results) by its ID.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get case data
            cursor.execute("SELECT name, query_data FROM cases WHERE id = ?", (case_id,))
            case_row = cursor.fetchone()
            
            if not case_row:
                conn.close()
                return None
            
            # Get results
            cursor.execute("SELECT result_id, title, description, link FROM results WHERE case_id = ? ORDER BY result_id ASC", (case_id,))
            result_rows = cursor.fetchall()
            conn.close()
            
            terminos = json.loads(case_row['query_data']) if case_row['query_data'] else {}
            resultados = []
            
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
            console.print(f"[bold red]Error al cargar el caso:[/bold red] {e}")
            return None
