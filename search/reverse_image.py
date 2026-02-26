from cli.ui import console
from search.smart_search import SmartSearch
from utils.results_parse import ResultsParser

def do_reverse_image_search():
    """
    Executes a reverse image search operation.
    Captures a target image URL via STDIN, dispatches it to the SmartSearch 
    automation module (Selenium/Yandex), and renders the results in a TUI table.
    """
    image_url = input("Enter the image URL for reverse search: ")
    if not image_url:
        console.print("[bold red]Image URL cannot be empty.[/bold red]")
        return

    console.print(f"Performing reverse image search for image: [cyan]{image_url}[/cyan]...")
    try:
        # Instantiate the unified search orchestrator
        search_engine = SmartSearch() 
        # Block until the headless automation driver returns the result set
        results = search_engine.reverse_image_search(image_url)
        console.print(f"Search complete. Found [bold yellow]{len(results)}[/bold yellow] results.")
        
        # Format the raw dictionary list into a Rich console table for display
        rparser = ResultsParser(results)
        console.print(rparser.to_table())
    except Exception as e:
        console.print(f"[bold red]An error occurred during reverse image search: {e}[/bold red]")
