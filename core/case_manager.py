from core import state
from core.database import DBManager
from cli.ui import console

def guardar_caso():
    if not state.CASO_ACTUAL["resultados"]:
        console.print("[bold red]No hay resultados para guardar.[/bold red]")
        return
    
    nombre_caso = input("Ingrese un nombre para el caso (ej: investigacion_z): ")
    if not nombre_caso:
        console.print("[bold red]El nombre del caso no puede estar vacío.[/bold red]")
        return
        
    db = DBManager()
    success, message = db.save_case(nombre_caso, state.CASO_ACTUAL)
    
    if success:
        console.print(f"[bold green]{message}[/bold green]")
    else:
        console.print(f"[bold red]{message}[/bold red]")

def cargar_caso():
    """Loads a session and returns True if successful, False otherwise."""
    db = DBManager()
    casos = db.get_all_cases()
    
    if not casos:
        console.print("[bold red]No hay casos guardados para cargar.[/bold red]")
        return False

    console.print("[bold yellow]Casos guardados:[/bold yellow]")
    for i, caso in enumerate(casos):
        console.print(f"  [cyan]{i+1}.[/cyan] {caso[1]} (Creado: {caso[2]})")
    
    choice = input("Seleccione el número del caso a cargar: ")
    if choice.isdigit() and 1 <= int(choice) <= len(casos):
        case_idx = int(choice) - 1
        case_id = casos[case_idx][0]
        case_name = casos[case_idx][1]
        
        datos_caso = db.get_case_by_id(case_id)
        if not datos_caso:
            console.print("[bold red]Error al cargar los datos del caso.[/bold red]")
            return False
            
        state.CASO_ACTUAL = datos_caso
        state.ULTIMOS_RESULTADOS = state.CASO_ACTUAL.get("resultados", [])
        
        if not state.ULTIMOS_RESULTADOS:
            console.print("[bold red]El caso cargado no contiene resultados.[/bold red]")
            return False

        console.print(f"Caso '{case_name}' cargado. Mostrando menú de análisis.")
        return True
    else:
        console.print("[bold red]Selección no válida.[/bold red]")
        return False
