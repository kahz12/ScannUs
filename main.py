import sys
import argparse
import os

from core.config import load_environment, env_config, openai_config, init_directories
from cli.ui import console, print_startup_banner
from cli.parser import get_parser, show_custom_help
from cli.menus import show_main_menu, select_ia_agent
from cli.actions import do_search, do_generate_dork_ia
from search.reverse_image import do_reverse_image_search
from core.case_manager import cargar_caso
from utils.file_download import FileDownload
from utils.media_downloader import download_media
from utils.results_parse import ResultsParser
from core import state

def main():
    init_directories()
    google_api_key_found = load_environment()
    print_startup_banner(bool(google_api_key_found))
    
    parser = get_parser()

    if '-h' in sys.argv or '--help' in sys.argv:
        show_custom_help(parser)
        sys.exit(0)
    
    if len(sys.argv) == 1:
        show_main_menu()
        sys.exit(0)

    args = parser.parse_args()

    # --- Configuration Verification ---
    env_exists = os.path.exists(".env")
    if args.configure:
        print("Iniciando configuración del entorno...")
        env_config()
        openai_config()
        print("\n.env configurado exitosamente.")
        if not any(vars(args).values()):
             sys.exit(0)
    elif not env_exists and not args.help:
        console.print("[bold red]Error: El fichero .env no existe o no está configurado.[/bold red]")
        console.print("Por favor, ejecuta el script con el flag -c o desde el menú interactivo para configurarlo.")
        sys.exit(1)

    if args.reverse:
        do_reverse_image_search()
        sys.exit(0)

    if args.media_scrape:
        zip_file_name = "media_descargada.zip"
        download_media(args.media_scrape, zip_file_name)
        sys.exit(0)

    ia_agent = None
    if args.google_dorks or args.interactive or args.load_case:
        ia_agent = select_ia_agent()
        if not ia_agent and (args.google_dorks or args.interactive or args.load_case):
            console.print("[bold red]Se requiere un agente de IA para esta acción, pero no se pudo inicializar.[/bold red]")
            sys.exit(1)

    if args.load_case:
        if cargar_caso():
            from cli.menus import interactive_analysis_menu
            interactive_analysis_menu(state.ULTIMOS_RESULTADOS, ia_agent)
        sys.exit(0)
        
    if args.google_dorks:
        console.print(f"Generando dork para la descripción: '{args.google_dorks}'", style="yellow")
        dork_generado = ia_agent.generate_gdork(args.google_dorks)
        if dork_generado:
            console.print("\n✅ Dork Generado:", style="bold green")
            console.print(dork_generado.strip())
        else:
            console.print("\n❌ No se pudo generar el dork.", style="bold red")
        sys.exit(0)

    query = args.query
    if not query:
        guided_parts = []
        if args.nombre: guided_parts.append(f'"{args.nombre}"')
        if args.usuario: guided_parts.append(f'"{args.usuario}"')
        if args.buscar: guided_parts.append(f'"{args.buscar}"')
        if guided_parts:
            query = " AND ".join(guided_parts)

    if not query:
        console.print("[bold red]Error: Debes indicar una consulta con -q o usar los argumentos de búsqueda guiada (-n, -u, -b).[/bold red]")
        sys.exit(1)

    do_search(query, args.engine, args.pages, args.start_page, args.lang, args.interactive, ia_agent)
    
    if not args.interactive:
        resultados = state.ULTIMOS_RESULTADOS 
        rparser = ResultsParser(resultados)
        
        if args.html: rparser.exportar_html(args.html)
        if args.json: rparser.exportar_json(args.json)
        if args.csv: rparser.exportar_csv(args.csv)
        if args.excel: rparser.exportar_excel(args.excel)
        if args.download:
            file_types = [ft.strip() for ft in args.download.split(',')]
            urls = [resultado['link'] for resultado in resultados]
            fdownloader = FileDownload("Descargas")
            for url in urls:
                if any(url.lower().endswith(f".{file_type}") for file_type in file_types) or "all" in file_types:
                    fdownloader.descargar_archivo(url, args.metadata)

if __name__ == "__main__":
    main()