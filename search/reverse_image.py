from cli.ui import console
from search.smart_search import SmartSearch
from utils.results_parse import ResultsParser

def do_reverse_image_search():
    image_url = input("Ingrese la URL de la imagen para la búsqueda inversa: ")
    if not image_url:
        console.print("[bold red]La URL de la imagen no puede estar vacía.[/bold red]")
        return

    console.print(f"Realizando búsqueda inversa para la imagen: [cyan]{image_url}[/cyan]...")
    try:
        search_engine = SmartSearch() 
        results = search_engine.reverse_image_search(image_url)
        console.print(f"Búsqueda finalizada. Se encontraron [bold yellow]{len(results)}[/bold yellow] resultados.")
        rparser = ResultsParser(results)
        console.print(rparser.to_table())
    except Exception as e:
        console.print(f"[bold red]Ocurrió un error durante la búsqueda inversa: {e}[/bold red]")
