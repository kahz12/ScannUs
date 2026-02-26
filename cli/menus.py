from urllib.parse import urlparse
from rich.table import Table
from cli.ui import console
from core import state
from core.case_manager import guardar_caso, cargar_caso
from core.config import env_config, openai_config
from core.ai_agent import IAAgent, GeminiGenerator, OpenAIGenerator
from search.reverse_image import do_reverse_image_search
from analysis.tech_scanner import tech_scan
from analysis.web_analyzer import get_text_from_url, summarize_text_with_ia, translate_and_analyze_with_ia, extract_entities_and_graph
from analysis.advanced_osint import take_screenshot, check_wayback_machine, get_dynamic_text_from_url
from search.smart_search import extract_information
from utils.file_download import FileDownload
from utils.media_downloader import download_media
from utils.results_parse import ResultsParser
import cli.actions
import os

def select_ia_agent():
    """
    Orchestrates the selection and initialization of the AI inference engine.
    Ensures the target provider (Gemini or OpenAI) has the required credentials 
    mapped in the local environment before instantiation.
    """
    respuesta = ""
    while respuesta.lower() not in ("ge", "op"):
        respuesta = input("Which AI model do you want to use? Gemini (ge) or OpenAI (op): ")
    
    if respuesta.lower() == "ge":
        if not os.getenv("GOOGLE_API_KEY_FOR_GEMINI"):
            console.print("[bold red]Error: GOOGLE_API_KEY_FOR_GEMINI not found in .env.[/bold red]")
            return None
        console.print("--- Using Gemini ---", style="bold green")
        return IAAgent(GeminiGenerator())
    elif respuesta.lower() == "op":
        if not os.getenv("OPENAI_API_KEY"):
            console.print("[bold yellow]OpenAI API Key is not configured.[/bold yellow]")
            openai_config()
        console.print("--- Using OpenAI ---", style="bold green")
        return IAAgent(OpenAIGenerator(model_name="gpt-4o"))
    return None

def process_selected_url(url, ia_agent):
    """
    TUI menu for deep analysis of a specific search result (URL).
    Provides access to text summarization, metadata extraction, tech stack scanning,
    Wayback Machine auditing, and AI-driven relationship mapping.
    """
    while True:
        console.print(f"\n--- Analyzing URL: [cyan]{url}[/cyan] ---", style="bold blue")
        console.print("Choose an action:")
        console.print("1. [green]Summarize[/green] content with AI")
        console.print("2. [green]Extract[/green] PII (emails, phones, etc.)")
        console.print("3. [green]Scan[/green] web technologies")
        console.print("4. [green]Download[/green] file (direct link only)")
        console.print("5. [green]Download Media[/green] (images/videos) from page")
        console.print("6. [magenta]Capture Screenshot[/magenta] (Headless)")
        console.print("7. [magenta]Verify history[/magenta] in Wayback Machine")
        console.print("8. [yellow]Deep Analysis[/yellow] with AI")
        console.print("9. [yellow]Entity Graph[/yellow] (Pyvis) via AI")
        console.print("10. [cyan]Deep Scraping[/cyan] (JS Rendering / Hidden Content)")
        console.print("0. [red]Return[/red] to main menu")
        action = input("> ").strip()

        if action == '1':
            if not ia_agent:
                console.print("[bold red]AI configuration is required for this action.[/bold red]")
                continue
            console.print("\n[yellow]Fetching and summarizing content...[/yellow]")
            page_text = get_text_from_url(url)
            if page_text:
                summary = summarize_text_with_ia(page_text, ia_agent)
                console.print("\n--- Summary ---", style="bold green")
                console.print(summary)
        
        elif action == '2':
            console.print("\n[yellow]Extracting information...[/yellow]")
            page_text = get_text_from_url(url)
            if page_text:
                extracted_data = extract_information(page_text)
                if extracted_data:
                    table = Table(title="Extracted Information", show_header=True, header_style="bold magenta")
                    table.add_column("Data Type", style="cyan")
                    table.add_column("Found Values", style="green")
                    for key, values in extracted_data.items():
                        table.add_row(key.replace('_', ' ').capitalize(), "\n".join(values))
                    console.print(table)
                else:
                    console.print("  [yellow]No extractable identifiers (emails, phones) found.[/yellow]")
        
        elif action == '3':
            tech_scan(url)

        elif action == '4':
            console.print("\n[yellow]Attempting download...[/yellow]")
            fdownloader = FileDownload()
            fdownloader.descargar_archivo_directo(url, extract_metadata=True)

        elif action == '5':
            console.print("\n[yellow]Starting media download pipeline...[/yellow]")
            try:
                domain = urlparse(url).netloc.replace('.', '_')
                zip_file_name = f"{domain}_media.zip"
                download_media(url, zip_file_name)
            except Exception as e:
                console.print(f"[bold red]Error during media download:[/bold red] {e}")

        elif action == '6':
            take_screenshot(url)
            
        elif action == '7':
            check_wayback_machine(url)
            
        elif action == '8':
            if not ia_agent:
                console.print("[bold red]AI configuration is required for this action.[/bold red]")
                continue
            console.print("\n[yellow]Fetching content for deep analysis...[/yellow]")
            page_text = get_text_from_url(url)
            if page_text:
                analysis = translate_and_analyze_with_ia(page_text, ia_agent)
                console.print("\n--- AI Analysis ---", style="bold green")
                console.print(analysis)
                
        elif action == '9':
            if not ia_agent:
                console.print("[bold red]AI configuration is required for this action.[/bold red]")
                continue
            console.print("\n[yellow]Extracting entities to build relationship graph...[/yellow]")
            page_text = get_text_from_url(url)
            if page_text:
                domain = urlparse(url).netloc.replace('.', '_')
                graph_file = f"graph_{domain}.html"
                result_file = extract_entities_and_graph(page_text, ia_agent, output_filename=graph_file)
                if result_file:
                    console.print(f"[bold green]Relationship graph generated:[/bold green] {result_file}")
                    
        elif action == '10':
            console.print("\n[yellow]Starting Deep Scraping (JS execution may take several seconds)...[/yellow]")
            page_text = get_dynamic_text_from_url(url)
            if page_text:
                console.print(f"\n[green]Scraping successful. Retrieved {len(page_text)} characters.[/green]")
                console.print("[cyan]Analyzing vital identifiers...[/cyan]")
                extracted_data = extract_information(page_text)
                if extracted_data:
                    table = Table(title="Extracted Information (Deep Scraping)", show_header=True, header_style="bold magenta")
                    table.add_column("Data Type", style="cyan")
                    table.add_column("Found Values", style="green")
                    for key, values in extracted_data.items():
                        table.add_row(key.replace('_', ' ').capitalize(), "\n".join(values))
                    console.print(table)
                else:
                    console.print("  [yellow]No extractable identifiers found in deep content.[/yellow]")
                
        elif action == '0':
            break
        else:
            console.print("[bold red]Invalid option.[/bold red]")


def interactive_analysis_menu(resultados, ia_agent):
    """
    Main interactive loop for processing search results.
    Enables iterative analysis, mass data exports (Excel), media scraping,
    and investigation state persistence (Case Management).
    """
    state.ULTIMOS_RESULTADOS = resultados
    
    # Initialize session metadata if unpopulated
    if not state.CASO_ACTUAL["terminos"]:
        state.CASO_ACTUAL["terminos"] = {"type": "manual", "value": "N/A"}
    
    # Standardize result schema for internal state tracking
    formatted_results = []
    for i, r in enumerate(resultados):
        formatted_results.append({
            'id': i + 1, 'title': r.get('title', 'N/A'),
            'description': r.get('description', 'N/A'), 'link': r.get('link', 'N/A')
        })
    state.CASO_ACTUAL["resultados"] = formatted_results
    
    while True:
        table = Table(title="Search Results", show_header=True, header_style="bold green")
        table.add_column("ID", style="dim", width=4)
        table.add_column("Title", style="bold")
        table.add_column("Link", style="cyan")
        for res in state.CASO_ACTUAL["resultados"]:
            table.add_row(str(res['id']), res['title'], res['link'])
        console.print(table)

        console.print("\n[bold]Select an option:[/bold]")
        console.print(" - Enter the [cyan]ID number[/cyan] to analyze a specific result.")
        console.print(" - Type '[magenta]media[/magenta]' to batch-download media from results.")
        console.print(" - Type '[yellow]save[/yellow]' to persist current session to DB.")
        console.print(" - Type '[green]excel[/green]' to export session to Excel.")
        console.print(" - Type '[red]exit[/red]' to quit.")
        choice = input("\n> ").strip().lower()

        if choice in ('exit', 'salir'):
            break
        
        if choice in ('save', 'guardar'):
            guardar_caso()
            continue
            
        if choice == 'excel':
            archivo = input("Enter Excel filename (e.g., results.xlsx) [results.xlsx]: ").strip()
            if not archivo:
                archivo = "results.xlsx"
            if not archivo.endswith('.xlsx'):
                archivo += '.xlsx'
            rparser = ResultsParser(state.CASO_ACTUAL.get("resultados", []))
            rparser.exportar_excel(archivo)
            continue
            
        if choice == 'media':
            ids_str = input("Enter result IDs to download, separated by commas (e.g., 1, 3, 8): ")
            ids_to_download = [int(i.strip()) for i in ids_str.split(',') if i.strip().isdigit()]
            
            for index in ids_to_download:
                if 0 < index <= len(state.CASO_ACTUAL["resultados"]):
                    url = state.CASO_ACTUAL["resultados"][index - 1]['link']
                    console.print(f"\n[yellow]Starting media download for ID {index} ({url})...[/yellow]")
                    try:
                        domain = urlparse(url).netloc.replace('.', '_')
                        zip_file_name = f"{domain}_media.zip"
                        download_media(url, zip_file_name)
                    except Exception as e:
                        console.print(f"[bold red]Error during media download for ID {index}: {e}[/bold red]")
                else:
                    console.print(f"[bold red]ID '{index}' out of range. Skipping.[/bold red]")
            continue

        try:
            index = int(choice) - 1
            if 0 <= index < len(state.CASO_ACTUAL["resultados"]):
                selected_url = state.CASO_ACTUAL["resultados"][index]['link']
                process_selected_url(selected_url, ia_agent)
            else:
                console.print("[bold red]Index out of range. Please try again.[/bold red]")
        except ValueError:
            console.print("[bold red]Invalid input. Enter an ID, 'media', 'save', 'excel', or 'exit'.[/bold red]")

def show_main_menu():
    """
    Root navigation menu for ScannUs.
    Coordinates the primary workflows: search, image lookup, case loading, and configuration.
    """
    while True:
        console.rule("[bold green]ScannUs Main Menu[/bold green]")
        console.print("1. [cyan]Guided Search[/cyan] (by Name, Username, Email...)")
        console.print("2. [cyan]Direct Search[/cyan] (Raw Google Dork)")
        console.print("3. [yellow]AI Dork Generator[/yellow]")
        console.print("4. [magenta]Reverse Image Lookup[/magenta]")
        console.print("5. [blue]Web Technology Analysis[/blue]")
        console.print("6. [green]Load Saved Case[/green]")
        console.print("7. [red]Configure API Keys[/red]")
        console.print("8. [bold red]Exit[/bold red]")
        console.rule()
        
        choice = input("> ").strip()

        if choice == '1':
            console.print("[bold cyan]--- Guided Search ---[/bold cyan]")
            nombre = input("Full Name (optional): ")
            usuario = input("Username/Handle (optional): ")
            email = input("Email address (optional): ")
            telefono = input("Phone number (optional): ")
            buscar = input("General search term (optional): ")
            
            # Aggregate search fragments into a Boolean AND query
            guided_parts = []
            if nombre: guided_parts.append(f'"{nombre}"')
            if usuario: guided_parts.append(f'"{usuario}"')
            if email: guided_parts.append(f'"{email}"')
            if telefono: guided_parts.append(f'"{telefono}"')
            if buscar: guided_parts.append(f'"{buscar}"')
            
            if not guided_parts:
                console.print("[bold red]At least one search term is required.[/bold red]")
                continue
            
            query = " AND ".join(guided_parts)
            engine = input("Search engine (google/duckduckgo/brave) [duckduckgo]: ").lower() or "duckduckgo"
            
            # Auto-trigger deep analysis if specific PII is targetted
            if email or telefono:
                console.print("[yellow]Starting deep search to extract associated data points...[/yellow]")
                cli.actions.do_deep_search(query, engine, pages=1, start_page=1, lang='lang_es')
            else:
                interactive_mode = input("Enable interactive analysis mode? (y/n) [y]: ").lower() or 'y'
                ia_agent = None
                if interactive_mode in ('y', 's'):
                    ia_agent = select_ia_agent()
                cli.actions.do_search(query, engine, pages=1, start_page=1, lang='lang_es', interactive=(interactive_mode in ('y', 's')), ia_agent=ia_agent)

        elif choice == '2':
            console.print("[bold cyan]--- Direct Search ---[/bold cyan]")
            query = input("Enter your search dork: ")
            if not query:
                console.print("[bold red]Query cannot be empty.[/bold red]")
                continue
            
            engine = input("Search engine (google/duckduckgo/brave) [duckduckgo]: ").lower() or "duckduckgo"
            interactive_mode = input("Enable interactive analysis mode? (y/n) [y]: ").lower() or 'y'
            
            ia_agent = None
            if interactive_mode in ('y', 's'):
                ia_agent = select_ia_agent()
                
            cli.actions.do_search(query, engine, pages=1, start_page=1, lang='lang_es', interactive=(interactive_mode in ('y', 's')), ia_agent=ia_agent)

        elif choice == '3':
            cli.actions.do_generate_dork_ia()

        elif choice == '4':
            do_reverse_image_search()

        elif choice == '5':
            url = input("Enter URL to analyze: ")
            if url:
                tech_scan(url)
                
        elif choice == '6':
            ia_agent = select_ia_agent()
            if ia_agent:
                if cargar_caso():
                    interactive_analysis_menu(state.ULTIMOS_RESULTADOS, ia_agent)
                    
        elif choice == '7':
            env_config()
            openai_config()
            
        elif choice == '8':
            console.print("[bold green]Goodbye![/bold green]")
            break
        else:
            console.print("[bold red]Invalid option. Please try again.[/bold red]")
