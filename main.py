import sys
import argparse
import os

from core.config import load_environment, env_config, openai_config, init_directories
from cli.ui import console, print_startup_banner
from cli.parser import get_parser, show_custom_help
from cli.menus import show_main_menu, select_ia_agent
from search.reverse_image import do_reverse_image_search
from core.case_manager import cargar_caso
from utils.file_download import FileDownload
from utils.media_downloader import download_media
from utils.results_parse import ResultsParser
from core import state

def main():
    """
    Main entry point for the ScannUs application.
    Bootstraps the environment, parses CLI arguments, and dispatches to the correct module.
    """
    # Initialize workspace scaffold and required directory structure
    init_directories()
    
    # Load environment variables (API keys, etc.) and verify core requirements
    google_api_key_found = load_environment()
    print_startup_banner(bool(google_api_key_found))
    
    parser = get_parser()

    # Intercept custom help flag to render the rich-formatted help screen
    if '-h' in sys.argv or '--help' in sys.argv:
        show_custom_help(parser)
        sys.exit(0)
    
    # Drop into interactive TUI if no command-line arguments are provided
    if len(sys.argv) == 1:
        show_main_menu()
        sys.exit(0)

    args = parser.parse_args()

    # --- Configuration Verification & Setup ---
    env_exists = os.path.exists(".env")
    if args.configure:
        print("Initializing environment configuration...")
        env_config()
        openai_config()
        print("\n.env configured successfully.")
        # Exit gracefully if this was just a configuration run
        if not any(vars(args).values()):
             sys.exit(0)
    elif not env_exists and not args.help:
        console.print("[bold red]Error: The .env file does not exist or is not configured.[/bold red]")
        console.print("Please run the script with the -c flag or use the interactive menu to configure it.")
        sys.exit(1)

    # Route: Reverse Image Search payload processing
    if args.reverse:
        do_reverse_image_search(args.reverse)
        sys.exit(0)

    # Route: Username enumeration via Sherlock / Maigret (400+ sites)
    if getattr(args, "username_enum", None):
        from search.username_enum import username_enum
        username_enum(args.username_enum,
                      backend=getattr(args, "enum_backend", "auto"))
        sys.exit(0)

    # Route: LLM-based query planner (multi-step ReAct investigation)
    if getattr(args, "plan", None):
        from cli.actions import do_query_planner
        do_query_planner(args.plan)
        sys.exit(0)

    # Route: Media scraping from a target URL
    if args.media_scrape:
        zip_file_name = "downloaded_media.zip"
        download_media(args.media_scrape, zip_file_name)
        sys.exit(0)

    # Lazily initialize AI agent only if explicitly requested for NLP tasks
    ia_agent = None
    if args.google_dorks or args.interactive or args.load_case:
        ia_agent = select_ia_agent()
        if not ia_agent and (args.google_dorks or args.interactive or args.load_case):
            console.print("[bold red]An AI agent is required for this action, but initialization failed.[/bold red]")
            sys.exit(1)

    # Route: Reload serialized state from previous investigations
    if args.load_case:
        if cargar_caso():
            from cli.menus import interactive_analysis_menu
            interactive_analysis_menu(state.ULTIMOS_RESULTADOS, ia_agent)
        sys.exit(0)
        
    # Route: LLM-based Google Dork generation
    if args.google_dorks:
        console.print(f"Generating dork for description: '{args.google_dorks}'", style="yellow")
        dork_generado = ia_agent.generate_gdork(args.google_dorks)
        if dork_generado:
            console.print("\n✅ Dork Generated:", style="bold green")
            console.print(dork_generado.strip())
        else:
            console.print("\n❌ Failed to generate the dork.", style="bold red")
        sys.exit(0)

    # Build the final search query string based on provided flags
    query = args.query
    if not query:
        guided_parts = []
        if args.nombre: guided_parts.append(f'"{args.nombre}"')
        if args.usuario: guided_parts.append(f'"{args.usuario}"')
        if args.email: guided_parts.append(f'"{args.email}"')
        if args.telefono: guided_parts.append(f'"{args.telefono}"')
        if args.buscar: guided_parts.append(f'"{args.buscar}"')
        
        # Aggregate parameters into a logical AND query
        if guided_parts:
            query = " AND ".join(guided_parts)

    # Validate that at least one search parameter or query is present
    if not query:
        console.print("[bold red]Error: You must provide a query via -q or use guided search arguments (-n, -u, -b, -e, -t).[/bold red]")
        sys.exit(1)

    # Latent imports to avoid circular dependency cycles
    from cli.actions import do_search, do_generate_dork_ia, do_deep_search

    # Dispatch to appropriate search engine or deep analysis pipeline
    if args.deep or args.email or args.telefono:
        do_deep_search(query, args.engine, args.pages, args.start_page, args.lang)
    else:
        do_search(query, args.engine, args.pages, args.start_page, args.lang, args.interactive, ia_agent)
    
    # Post-processing and export logic (active only if not in interactive mode)
    if not args.interactive and not (args.deep or args.email or args.telefono):
        resultados = state.ULTIMOS_RESULTADOS 
        rparser = ResultsParser(resultados)
        
        # Batch export results to requested formats
        if args.html: rparser.exportar_html(args.html)
        if args.json: rparser.exportar_json(args.json)
        if args.csv: rparser.exportar_csv(args.csv)
        if args.excel: rparser.exportar_excel(args.excel)
        
        # Execute automated file downloads and metadata extraction
        if args.download:
            file_types = [ft.strip() for ft in args.download.split(',')]
            urls = [resultado['link'] for resultado in resultados]
            fdownloader = FileDownload("Downloads")
            for url in urls:
                # Filter by file extension or process all if 'all' wildcard is used
                if any(url.lower().endswith(f".{file_type}") for file_type in file_types) or "all" in file_types:
                    fdownloader.descargar_archivo(url, args.metadata)

if __name__ == "__main__":
    main()
