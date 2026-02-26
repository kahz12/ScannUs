import os
from rich.table import Table
from cli.ui import console
from utils.results_parse import ResultsParser
from search.engines.duckduckgosearch import DuckDuckGoSearch
from search.engines.bravesearch import BraveSearch
from search.engines.googlesearch import GoogleSearch
from core import state
from analysis.web_analyzer import get_text_from_url
from search.smart_search import extract_information

def do_deep_search(query, engine, pages, start_page, lang):
    """
    Executes an intensive search operation across the specified engine. 
    Retrieves SERP results and recursively crawls each destination URL 
    to extract PII and sensitive identifiers (emails, phones, SQL leaks).
    """
    if not query:
        console.print("[bold red]Error: Query cannot be empty.[/bold red]")
        return

    console.print(f"Using search engine: [bold green]{engine}[/bold green]")
    console.print(f"Starting [bold magenta]Deep Search[/bold magenta] with query: [cyan]{query}[/cyan]")

    try:
        # Strategy pattern dispatch based on the target engine
        if engine.lower() == 'duckduckgo':
            search_engine = DuckDuckGoSearch()
            resultados = search_engine.search(query, pages=pages)
        elif engine.lower() == 'brave':
            BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
            if not BRAVE_API_KEY:
                console.print("[bold red]Error: BRAVE_API_KEY not found in .env.[/bold red]")
                return
            search_engine = BraveSearch(BRAVE_API_KEY)
            resultados = search_engine.search(query, pages=pages)
        else:
            API_KEY_GOOGLE = os.getenv("API_KEY_GOOGLE")
            SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")
            if not API_KEY_GOOGLE or not SEARCH_ENGINE_ID:
                console.print("[bold red]Error: API_KEY_GOOGLE or SEARCH_ENGINE_ID not found in .env for Google search.[/bold red]")
                return
            search_engine = GoogleSearch(API_KEY_GOOGLE, SEARCH_ENGINE_ID)
            resultados = search_engine.search(query, start_page=start_page, pages=pages, lang=lang)
    except Exception as e:
        console.print(f"[bold red]An error occurred during search: {e}[/bold red]")
        return
    
    console.print(f"Search finished. Found [bold yellow]{len(resultados)}[/bold yellow] results. Commencing data extraction...")
    
    all_extracted_data = {}
    
    # Sequential crawler loop for deep inspection of each result node
    for r in resultados:
        url = r.get('link')
        if not url: continue
        console.print(f"[yellow]Analyzing URL:[/yellow] {url}")
        
        # Isolate text payload and dispatch to the regex extraction engine
        text = get_text_from_url(url)
        if text:
            data = extract_information(text)
            if data:
                # Aggregate findings into the global case state
                for key, values in data.items():
                    if key not in all_extracted_data:
                        all_extracted_data[key] = set()
                    all_extracted_data[key].update(values)
                    
    console.print("\n[bold green]--- Deep Search Results ---[/bold green]")
    
    # Render the consolidated intelligence findings in a Rich table
    if all_extracted_data:
        table = Table(title="Extracted Information from Results", show_header=True, header_style="bold magenta")
        table.add_column("Data Type", style="cyan")
        table.add_column("Found Values", style="green")
        for key, values in all_extracted_data.items():
            table.add_row(key.replace('_', ' ').capitalize(), "\n".join(values))
        console.print(table)
    else:
        console.print("[yellow]No associated information found in the reviewed links.[/yellow]")

    # Persist search metadata in global runtime state
    state.CASO_ACTUAL["terminos"] = {"type": "deep", "value": query}
    state.ULTIMOS_RESULTADOS = resultados


def do_search(query, engine, pages, start_page, lang, interactive, ia_agent):
    """
    Standard search execution flow.
    Dispatches query to engine and optionally enters the interactive TUI mode.
    """
    if not query:
        console.print("[bold red]Error: Query cannot be empty.[/bold red]")
        return

    console.print(f"Using search engine: [bold green]{engine}[/bold green]")
    console.print(f"Searching for: [cyan]{query}[/cyan]")

    try:
        if engine.lower() == 'duckduckgo':
            search_engine = DuckDuckGoSearch()
            resultados = search_engine.search(query, pages=pages)
        elif engine.lower() == 'brave':
            BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
            if not BRAVE_API_KEY:
                console.print("[bold red]Error: BRAVE_API_KEY not found in .env.[/bold red]")
                return
            search_engine = BraveSearch(BRAVE_API_KEY)
            resultados = search_engine.search(query, pages=pages)
        else:
            API_KEY_GOOGLE = os.getenv("API_KEY_GOOGLE")
            SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")
            if not API_KEY_GOOGLE or not SEARCH_ENGINE_ID:
                console.print("[bold red]Error: API_KEY_GOOGLE or SEARCH_ENGINE_ID not found in .env for Google search.[/bold red]")
                return
            search_engine = GoogleSearch(API_KEY_GOOGLE, SEARCH_ENGINE_ID)
            resultados = search_engine.search(query, start_page=start_page, pages=pages, lang=lang)
    except Exception as e:
        console.print(f"[bold red]An error occurred during search: {e}[/bold red]")
        return
    
    console.print(f"Search complete. Found [bold yellow]{len(resultados)}[/bold yellow] results.")
    
    state.CASO_ACTUAL["terminos"] = {"type": "direct", "value": query}
    state.ULTIMOS_RESULTADOS = resultados
    
    # Dispatch to appropriate UI flow
    if interactive:
        if not ia_agent:
            console.print("[bold yellow]No AI agent selected. Interactive mode will have limited functionality.[/bold yellow]")
        from cli.menus import interactive_analysis_menu
        interactive_analysis_menu(resultados, ia_agent)
    else:
        # Standard table-based output for headless or non-interactive runs
        rparser = ResultsParser(resultados)
        console.print(rparser.to_table())

def do_generate_dork_ia():
    """
    NLP-driven Google Dork generation flow.
    Captures user intent and leverages the LLM to synthesize a complex search query.
    """
    from cli.menus import select_ia_agent
    ia_agent = select_ia_agent()
    if not ia_agent:
        return
    
    description = input("Enter description to generate the dork: ")
    if not description:
        console.print("[bold red]Description cannot be empty.[/bold red]")
        return

    console.print(f"Generating dork for: '{description}'", style="yellow")
    
    # Delegate inference to the AI component
    dork_generado = ia_agent.generate_gdork(description)
    
    if dork_generado:
        console.print("\n✅ Dork Generated:", style="bold green")
        console.print(dork_generado.strip())
        
        realizar_busqueda = input("Do you want to perform a search with this dork? (y/n): ").lower()
        if realizar_busqueda in ('y', 's'):
            motor = input("Which engine to use? (google/duckduckgo/brave) [duckduckgo]: ").lower() or "duckduckgo"
            do_search(query=dork_generado, engine=motor, pages=1, start_page=1, lang='lang_es', interactive=True, ia_agent=ia_agent)
    else:
        console.print("\n❌ Failed to generate dork.", style="bold red")
