from core import state
from core.database import DBManager
from cli.ui import console

def guardar_caso():
    """
    Saves the current active session state into the local SQLite database.
    Prompts the user for a semantic case name before committing.
    """
    if not state.CASO_ACTUAL["resultados"]:
        console.print("[bold red]No results found to save.[/bold red]")
        return
    
    nombre_caso = input("Enter a name for the case (e.g., investigation_z): ")
    if not nombre_caso:
        console.print("[bold red]Case name cannot be empty.[/bold red]")
        return
        
    db = DBManager()
    success, message = db.save_case(nombre_caso, state.CASO_ACTUAL)
    
    if success:
        console.print(f"[bold green]{message}[/bold green]")
    else:
        console.print(f"[bold red]{message}[/bold red]")

def cargar_caso():
    """
    Fetches available cases from the local DB, prompts the user to select one,
    and mounts it into the global state payload.

    Returns:
        bool: True if a case was successfully loaded into global state, False otherwise.
    """
    db = DBManager()
    casos = db.get_all_cases()
    
    if not casos:
        console.print("[bold red]No saved cases found to load.[/bold red]")
        return False

    console.print("[bold yellow]Saved cases:[/bold yellow]")
    for i, caso in enumerate(casos):
        console.print(f"  [cyan]{i+1}.[/cyan] {caso[1]} (Created: {caso[2]})")
    
    choice = input("Select the case number to load: ")
    if choice.isdigit() and 1 <= int(choice) <= len(casos):
        case_idx = int(choice) - 1
        case_id = casos[case_idx][0]
        case_name = casos[case_idx][1]
        
        datos_caso = db.get_case_by_id(case_id)
        if not datos_caso:
            console.print("[bold red]Error loading case data.[/bold red]")
            return False
            
        # Hydrate the global runtime state variables with the serialized DB payload
        state.CASO_ACTUAL = datos_caso
        state.ULTIMOS_RESULTADOS = state.CASO_ACTUAL.get("resultados", [])
        
        if not state.ULTIMOS_RESULTADOS:
            console.print("[bold red]The loaded case contains no results.[/bold red]")
            return False

        console.print(f"Case '{case_name}' loaded. Displaying analysis menu.")
        return True
    else:
        console.print("[bold red]Invalid selection.[/bold red]")
        return False
