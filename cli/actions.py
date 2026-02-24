import os
from cli.ui import console
from utils.results_parse import ResultsParser
from search.engines.duckduckgosearch import DuckDuckGoSearch
from search.engines.bravesearch import BraveSearch
from search.engines.googlesearch import GoogleSearch
from core import state

def do_search(query, engine, pages, start_page, lang, interactive, ia_agent):
    if not query:
        console.print("[bold red]Error: La consulta no puede estar vacía.[/bold red]")
        return

    console.print(f"Usando el motor de búsqueda: [bold green]{engine}[/bold green]")
    console.print(f"Buscando con la consulta: [cyan]{query}[/cyan]")

    try:
        if engine.lower() == 'duckduckgo':
            search_engine = DuckDuckGoSearch()
            resultados = search_engine.search(query, pages=pages)
        elif engine.lower() == 'brave':
            BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
            if not BRAVE_API_KEY:
                console.print("[bold red]Error: BRAVE_API_KEY no se encuentra en .env.[/bold red]")
                return
            search_engine = BraveSearch(BRAVE_API_KEY)
            resultados = search_engine.search(query, pages=pages)
        else:
            API_KEY_GOOGLE = os.getenv("API_KEY_GOOGLE")
            SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")
            if not API_KEY_GOOGLE or not SEARCH_ENGINE_ID:
                console.print("[bold red]Error: API_KEY_GOOGLE o SEARCH_ENGINE_ID no se encuentran en .env para la búsqueda con Google.[/bold red]")
                return
            search_engine = GoogleSearch(API_KEY_GOOGLE, SEARCH_ENGINE_ID)
            resultados = search_engine.search(query, start_page=start_page, pages=pages, lang=lang)
    except Exception as e:
        console.print(f"[bold red]Ocurrió un error durante la búsqueda: {e}[/bold red]")
        return
    
    console.print(f"Búsqueda finalizada. Se encontraron [bold yellow]{len(resultados)}[/bold yellow] resultados.")
    state.CASO_ACTUAL["terminos"] = {"tipo": "directo", "valor": query}
    state.ULTIMOS_RESULTADOS = resultados
    
    if interactive:
        if not ia_agent:
            console.print("[bold yellow]No se seleccionó un agente de IA. El modo interactivo tendrá funcionalidades limitadas.[/bold yellow]")
        from cli.menus import interactive_analysis_menu
        interactive_analysis_menu(resultados, ia_agent)
    else:
        rparser = ResultsParser(resultados)
        console.print(rparser.to_table())

def do_generate_dork_ia():
    from cli.menus import select_ia_agent
    ia_agent = select_ia_agent()
    if not ia_agent:
        return
    
    description = input("Ingrese la descripción para generar el dork: ")
    if not description:
        console.print("[bold red]La descripción no puede estar vacía.[/bold red]")
        return

    console.print(f"Generando dork para la descripción: '{description}'", style="yellow")
    dork_generado = ia_agent.generate_gdork(description)
    if dork_generado:
        console.print("\n✅ Dork Generado:", style="bold green")
        console.print(dork_generado.strip())
        
        realizar_busqueda = input("¿Desea realizar la búsqueda con este dork? (s/n): ").lower()
        if realizar_busqueda == 's':
            motor = input("¿Qué motor usar? (google/duckduckgo/brave) [duckduckgo]: ").lower() or "duckduckgo"
            do_search(query=dork_generado, engine=motor, pages=1, start_page=1, lang='lang_es', interactive=True, ia_agent=ia_agent)
    else:
        console.print("\n❌ No se pudo generar el dork.", style="bold red")
