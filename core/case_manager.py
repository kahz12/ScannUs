"""
core/case_manager.py — Save and load investigation sessions from SQLite.
Uses Rich console helpers for a consistent visual experience.
"""

from rich.panel import Panel
from cli.ui import console, THEME, print_success, print_error, print_warn, print_info, make_table
from core import state
from core.database import DBManager


def guardar_caso() -> None:
    """
    Saves the current session into the local SQLite database.
    If a case with the same name already exists, prompts the user to overwrite.
    """
    if not state.CASO_ACTUAL.get("resultados"):
        print_warn("No results to save — run a search first.")
        return

    nombre_caso = console.input(
        f"  [{THEME['DIM']}]Case name (e.g. investigation_z):[/] [{THEME['INPUT']}]❯[/] "
    ).strip()

    if not nombre_caso:
        print_error("Case name cannot be empty.")
        return

    db = DBManager()
    success, message, conflict = db.save_case(nombre_caso, state.CASO_ACTUAL)

    if success:
        print_success(message)
        return

    if conflict:
        # Name already exists — offer to overwrite
        confirm = console.input(
            f"  [{THEME['WARN']}]⚠[/]  Case '{nombre_caso}' already exists. "
            f"Overwrite? (y/n) [{THEME['INPUT']}]❯[/] "
        ).strip().lower()

        if confirm in ("y", "s"):
            ok, msg = db.update_case(nombre_caso, state.CASO_ACTUAL)
            if ok:
                print_success(msg)
            else:
                print_error(msg)
        else:
            print_info("Save cancelled.")
    else:
        print_error(message)



def cargar_caso() -> bool:
    """
    Lists all saved cases in a Rich table, prompts the user to select one,
    and loads it into global state.

    Returns:
        True if a case was loaded successfully, False otherwise.
    """
    db = DBManager()
    casos = db.get_all_cases()

    if not casos:
        print_warn("No saved cases found — save a search session first (option 'save').")
        return False

    # Render saved cases as a styled table
    tbl = make_table(
        f"Saved Cases  [{THEME['DIM']}]({len(casos)} total)[/]",
        ("#",    THEME["DIM"]),
        ("Name", "bold white"),
        ("Created", THEME["DIM"]),
        show_lines=False,
    )
    for i, caso in enumerate(casos, 1):
        # caso → (id, name, created_at)
        tbl.add_row(str(i), caso[1], str(caso[2]))

    console.print()
    console.print(tbl)

    choice = console.input(
        f"\n  [{THEME['DIM']}]Select case number to load:[/] [{THEME['INPUT']}]❯[/] "
    ).strip()

    if not choice.isdigit() or not (1 <= int(choice) <= len(casos)):
        print_error(f"'{choice}' is not a valid selection.")
        return False

    case_idx  = int(choice) - 1
    case_id   = casos[case_idx][0]
    case_name = casos[case_idx][1]

    datos_caso = db.get_case_by_id(case_id)
    if not datos_caso:
        print_error("Could not load case data from the database.")
        return False

    state.CASO_ACTUAL       = datos_caso
    state.ULTIMOS_RESULTADOS = state.CASO_ACTUAL.get("resultados", [])

    if not state.ULTIMOS_RESULTADOS:
        print_warn("The selected case exists but contains no results.")
        return False

    print_success(
        f"Case '[bold]{case_name}[/bold]' loaded — "
        f"{len(state.ULTIMOS_RESULTADOS)} results available."
    )
    return True
