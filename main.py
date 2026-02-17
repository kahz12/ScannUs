# --- Importaciones ---
import sys
import os

# Add src directory to path to allow importing modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
import argparse
import shutil
import tempfile
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import re
import subprocess
import json
from datetime import datetime
import textwrap

# --- Configuración de Dependencias Externas ---

# La biblioteca `webtech` necesita un directorio de datos. Este bloque se asegura de que exista.
# Esto previene errores si el script se ejecuta en un entorno nuevo.
data_dir = os.path.expanduser("~/.local/share/webtech")
if not os.path.exists(data_dir):
    os.makedirs(data_dir)

# Importaciones de bibliotecas de terceros
from webtech import WebTech
from dotenv import load_dotenv, set_key
from rich.console import Console
from rich.table import Table

# Importaciones de módulos locales del proyecto
from googlesearch import GoogleSearch
from duckduckgosearch import DuckDuckGoSearch
from bravesearch import BraveSearch
from results_parse import ResultsParser
from file_download import FileDownload
from ai_agent import OpenAIGenerator, GeminiGenerator, IAAgent
from media_downloader import download_media
from web_analyzer import get_text_from_url, summarize_text_with_ia
from smart_search import extract_information, SmartSearch

# Inicializa la consola de `rich` para una salida de terminal estilizada y legible.
console = Console()

# --- Variables Globales de Casos ---
ULTIMOS_RESULTADOS = []
CASO_ACTUAL = {"terminos": {}, "resultados": []}

def print_startup_banner():
    """
    Imprime un banner de bienvenida ASCII art y carga las configuraciones iniciales.
    Muestra el estado de la carga de variables de entorno y la configuración de la API de Gemini.
    """
    banner = textwrap.dedent(r"""
    [bold #00ff00]   _____                         _   _           [/]
    [bold #00ff40]  / ____|                       | | | |          [/]
    [bold #00ff80] | (___   ___ __ _ _ __  _ __   | | | | ___      [/]
    [bold #00ffbf]  \___ \ / __/ _` | '_ \| '_ \  | | | |/ __|     [/]
    [bold #00ffff]  ____) | (_| (_| | | | | | | | | |_| |\__ \     [/]
    [bold #00bfff] |_____/ \___\__,_|_| |_|_| |_|  \___/ |___/     [/]
    """).strip()

    console.print(banner, justify="center")
    console.print()
    console.rule("[bold green]Herramienta de Búsqueda y Análisis Avanzado[/bold green]")

    # Muestra un spinner mientras se realizan las tareas de inicialización.
    with console.status("[bold green]Inicializando...[/bold green]", spinner="dots") as status:
        status.update("Cargando variables de entorno...")
        load_dotenv()
        console.log("[green]Variables de entorno cargadas.[/green]")
        
        # Configura la API de Gemini si la clave está disponible.
        if GOOGLE_API_KEY_FOR_GEMINI:
            console.log("[green]Clave de API de Gemini encontrada en .env.[/green]")
        else:
            console.log("[yellow]Clave de API de Gemini no encontrada en .env.[/yellow]")
    console.rule()

# Carga las variables de entorno del archivo .env para que estén disponibles globalmente.
load_dotenv()
GOOGLE_API_KEY_FOR_GEMINI = os.getenv("GOOGLE_API_KEY_FOR_GEMINI")

# Llama a la función del banner para mostrarlo al iniciar el script.
print_startup_banner()

def show_custom_help(parser):
    """
    Muestra un mensaje de ayuda personalizado utilizando tablas de `rich`
    en lugar del formato de ayuda estándar de `argparse`.
    """
    console.print("\n[bold green]Tabla de Ayuda de NinjaDorks[/bold green]")
    
    # Itera sobre los grupos de argumentos definidos en el parser (ej. "Opciones de Búsqueda").
    for group in parser._action_groups:
        # Filtra las acciones que son argumentos de línea de comandos (tienen `option_strings`).
        actions = [action for action in group._group_actions if action.option_strings]
        if not actions:
            continue

        # Crea una tabla para cada grupo de argumentos.
        table = Table(title=f"[bold magenta]{group.title}[/bold magenta]", show_header=True, header_style="bold cyan", box=None)
        table.add_column("Argumento", style="cyan", no_wrap=True)
        table.add_column("Descripción", style="green")
        table.add_column("Valor Esperado", style="yellow")

        for action in actions:
            opts = ", ".join(action.option_strings) # ej. "-q, --query"
            metavar = action.metavar or "" # El valor esperado, ej. "URL"
            table.add_row(opts, action.help, metavar)
        
        console.print(table)
    
    # Muestra ejemplos de uso.
    console.rule("[bold_green]Ejemplos de Uso:[/bold_green]")
    console.print("  [white]1. Búsqueda Básica:[/white]")
    console.print("     [cyan]python main.py -q \"site:.gov filetype:pdf\"[/cyan]")
    console.print("  [white]2. Búsqueda con Motor Específico (Google/DuckDuckGo/Brave):[/white]")
    console.print("     [cyan]python main.py -q \"OSINT tools\" --engine brave --pages 2[/cyan]")
    console.print("  [white]3. Generación de Dork con IA:[/white]")
    console.print("     [cyan]python main.py -gd \"Encontrar listas de precios en Excel de empresas de tecnología\"[/cyan]")
    console.print("  [white]4. Búsqueda Guiada (Nombre/Usuario):[/white]")
    console.print("     [cyan]python main.py -n \"John Doe\" -u \"jdoe88\"[/cyan]")
    console.print("  [white]5. Descarga de Medios de una URL:[/white]")
    console.print("     [cyan]python main.py --media-scrape \"https://ejemplo.com/galeria\"[/cyan]")
    console.print("  [white]6. Modo Interactivo Directo:[/white]")
    console.print("     [cyan]python main.py -i[/cyan]")

# --- Funciones de Configuración ---

def env_config():
    """
    Asistente interactivo para configurar las claves de API de Google en el archivo .env.
    """
    print("--- Configuración de Google Search API ---")
    api_key_search = input("Ingresa tu API KEY de Google Custom Search: ").strip()
    engine_id = input("Ingresa tu ID del motor de búsqueda (CX): ").strip()
    set_key(".env", "API_KEY_GOOGLE", api_key_search)
    set_key(".env", "SEARCH_ENGINE_ID", engine_id)
    
    print("\n--- Configuración de Google AI (Gemini) ---")
    api_key_gemini = input("Ingresa tu API KEY de Google AI Studio (para Gemini): ").strip()
    set_key(".env", "GOOGLE_API_KEY_FOR_GEMINI", api_key_gemini)
    
    # Reload Gemini configuration immediately
    global GOOGLE_API_KEY_FOR_GEMINI
    GOOGLE_API_KEY_FOR_GEMINI = api_key_gemini
    if GOOGLE_API_KEY_FOR_GEMINI:
        # Set environment variable for the new SDK to pick up
        os.environ["GOOGLE_API_KEY_FOR_GEMINI"] = api_key_gemini
        print("[green]Clave de API de Gemini actualizada en el entorno.[/green]")

    print("\n--- Configuración de Brave Search API ---")
    api_key_brave = input("Ingresa tu API KEY de Brave Search: ").strip()
    set_key(".env", "BRAVE_API_KEY", api_key_brave)
    # Reload Brave API Key environment variable for current process
    os.environ["BRAVE_API_KEY"] = api_key_brave

def openai_config():
    """
    Asistente interactivo para configurar la clave de API de OpenAI en el archivo .env.
    """
    print("\n--- Configuración de OpenAI ---")
    api_key = input("Ingresa tu API KEY de OpenAI: ").strip()
    set_key(".env", "OPENAI_API_KEY", api_key)
    # Reload OpenAI API Key environment variable for current process
    os.environ["OPENAI_API_KEY"] = api_key

# --- Funciones de Análisis ---

def tech_scan(url):
    """
    Analiza una URL para identificar las tecnologías web que utiliza (frameworks, CMS, etc.).
    """
    console.print(f"\n--- Analizando tecnologías para: {url} ---", style="bold blue")
    try:
        wt = WebTech()
        results = wt.start_from_url(url, timeout=10)

        if isinstance(results, dict) and results:
            table = Table(title="Tecnologías Detectadas", show_header=True, header_style="bold magenta")
            table.add_column("Tecnología", style="cyan")
            table.add_column("Versión", style="green")
            for tech, version in results.items():
                table.add_row(tech, version)
            console.print(table)
        else:
            console.print("  [yellow]No se detectaron tecnologías o el resultado no fue el esperado.[/yellow]")
    except Exception as e:
        console.print(f"  [bold red]Ocurrió un error durante el análisis:[/bold red] {e}")

# --- Gestión de Casos ---

def guardar_caso():
    """Guarda la sesión de búsqueda actual (términos y resultados) en un archivo JSON."""
    global CASO_ACTUAL
    if not CASO_ACTUAL["resultados"]:
        console.print("[bold red]No hay resultados para guardar.[/bold red]")
        return
    
    if not os.path.exists('cases'): os.makedirs('cases')
    
    nombre_caso = input("Ingrese un nombre para el caso (ej: investigacion_z): ")
    if not nombre_caso:
        console.print("[bold red]El nombre del caso no puede estar vacío.[/bold red]")
        return
        
    filename = f"cases/{nombre_caso}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(CASO_ACTUAL, f, indent=4, ensure_ascii=False)
    
    console.print(f"[bold green]Caso guardado exitosamente como '{filename}'[/bold green]")

def cargar_caso(ia_agent):
    """Carga una sesión de búsqueda previamente guardada desde un archivo JSON."""
    global ULTIMOS_RESULTADOS, CASO_ACTUAL
    cases_dir = 'cases'
    if not os.path.exists(cases_dir) or not os.listdir(cases_dir):
        console.print("[bold red]No hay casos guardados para cargar.[/bold red]")
        return

    console.print("[bold yellow]Casos guardados:[/bold yellow]")
    casos = [f for f in os.listdir(cases_dir) if f.endswith('.json')]
    for i, caso in enumerate(casos):
        console.print(f"  [cyan]{i+1}.[/cyan] {caso.replace('.json', '')}")
    
    choice = input("Seleccione el número del caso a cargar: ")
    if choice.isdigit() and 1 <= int(choice) <= len(casos):
        filename = os.path.join(cases_dir, casos[int(choice)-1])
        with open(filename, 'r', encoding='utf-8') as f:
            CASO_ACTUAL = json.load(f)
        
        ULTIMOS_RESULTADOS = CASO_ACTUAL.get("resultados", [])
        
        if not ULTIMOS_RESULTADOS:
            console.print("[bold red]El caso cargado no contiene resultados.[/bold red]")
            return

        console.print(f"Caso '{casos[int(choice)-1]}' cargado. Mostrando menú de análisis.")
        interactive_analysis_menu(ULTIMOS_RESULTADOS, ia_agent)
    else:
        console.print("[bold red]Selección no válida.[/bold red]")

# --- Funciones de Interacción con el Usuario ---

def interactive_analysis_menu(resultados, ia_agent):
    """
    Muestra un menú interactivo después de una búsqueda para analizar los resultados.
    """
    global ULTIMOS_RESULTADOS, CASO_ACTUAL
    ULTIMOS_RESULTADOS = resultados
    if not CASO_ACTUAL["terminos"]:
        CASO_ACTUAL["terminos"] = {"tipo": "manual", "valor": "N/A"}
    
    # Asegurarse de que los resultados en CASO_ACTUAL tengan el formato correcto con IDs
    formatted_results = []
    for i, r in enumerate(resultados):
        formatted_results.append({
            'id': i + 1, 'title': r.get('title', 'N/A'),
            'description': r.get('description', 'N/A'), 'link': r.get('link', 'N/A')
        })
    CASO_ACTUAL["resultados"] = formatted_results
    
    while True:
        table = Table(title="Resultados de la Búsqueda", show_header=True, header_style="bold green")
        table.add_column("ID", style="dim", width=4)
        table.add_column("Título", style="bold")
        table.add_column("Enlace", style="cyan")
        for res in CASO_ACTUAL["resultados"]:
            table.add_row(str(res['id']), res['title'], res['link'])
        console.print(table)

        console.print("\n[bold]Selecciona una opción:[/bold]")
        console.print(" - Ingresa el [cyan]número (ID)[/cyan] del resultado para analizarlo.")
        console.print(" - Escribe '[magenta]media[/magenta]' para descargar imágenes/videos de uno o más resultados.")
        console.print(" - Escribe '[yellow]guardar[/yellow]' para guardar la sesión actual como un caso.")
        console.print(" - Escribe '[red]salir[/red]' para terminar.")
        choice = input("\n> ").strip().lower()

        if choice == 'salir':
            break
        
        if choice == 'guardar':
            guardar_caso()
            continue
            
        if choice == 'media':
            ids_str = input("Elige el ID o los IDs a descargar, separados por comas (ej: 1, 3, 8): ")
            ids_to_download = [int(i.strip()) for i in ids_str.split(',') if i.strip().isdigit()]
            
            for index in ids_to_download:
                if 0 < index <= len(CASO_ACTUAL["resultados"]):
                    url = CASO_ACTUAL["resultados"][index - 1]['link']
                    console.print(f"\n[yellow]Iniciando descarga de medios para ID {index} ({url})...[/yellow]")
                    try:
                        domain = urlparse(url).netloc.replace('.', '_')
                        zip_file_name = f"{domain}_media.zip"
                        download_media(url, zip_file_name)
                    except Exception as e:
                        console.print(f"[bold red]Ocurrió un error durante la descarga de medios para ID {index}:[/bold red] {e}")
                else:
                    console.print(f"[bold red]ID '{index}' está fuera de rango y será ignorado.[/bold red]")
            continue

        try:
            index = int(choice) - 1
            if 0 <= index < len(CASO_ACTUAL["resultados"]):
                selected_url = CASO_ACTUAL["resultados"][index]['link']
                process_selected_url(selected_url, ia_agent)
            else:
                console.print("[bold red]Número fuera de rango. Inténtalo de nuevo.[/bold red]")
        except ValueError:
            console.print("[bold red]Entrada no válida. Ingresa un número, 'media', 'guardar' o 'salir'.[/bold red]")

def process_selected_url(url, ia_agent):
    """
    Muestra un submenú de acciones de análisis para una URL específica.
    """
    while True:
        console.print(f"\n--- Analizando URL: [cyan]{url}[/cyan] ---", style="bold blue")
        console.print("Elige una acción:")
        console.print("1. [green]Resumir[/green] contenido con IA")
        console.print("2. [green]Extraer[/green] información (emails, teléfonos, etc.)")
        console.print("3. [green]Escanear[/green] tecnologías web")
        console.print("4. [green]Descargar[/green] archivo (si es un enlace directo)")
        console.print("5. [green]Descargar Medios[/green] (imágenes/videos) de la página))")
        console.print("6. [red]Volver[/red] al menú principal")
        action = input("> ").strip()

        if action == '1':
            console.print("\n[yellow]Obteniendo y resumiendo contenido...[/yellow]")
            page_text = get_text_from_url(url)
            if page_text:
                summary = summarize_text_with_ia(page_text, ia_agent)
                console.print("\n--- Resumen ---", style="bold green")
                console.print(summary)
        
        elif action == '2':
            console.print("\n[yellow]Extrayendo información...[/yellow]")
            page_text = get_text_from_url(url)
            if page_text:
                extracted_data = extract_information(page_text)
                if extracted_data:
                    table = Table(title="Información Extraída", show_header=True, header_style="bold magenta")
                    table.add_column("Tipo de Dato", style="cyan")
                    table.add_column("Valores Encontrados", style="green")
                    for key, values in extracted_data.items():
                        table.add_row(key.replace('_', ' ').capitalize(), "\n".join(values))
                    console.print(table)
                else:
                    console.print("  [yellow]No se encontró información extraíble (emails, teléfonos, etc.).[/yellow]")
        
        elif action == '3':
            tech_scan(url)

        elif action == '4':
            console.print("\n[yellow]Intentando descargar...[/yellow]")
            fdownloader = FileDownload("Descargas")
            fdownloader.descargar_archivo_directo(url, extract_metadata=True)

        elif action == '5':
            console.print("\n[yellow]Iniciando descarga de medios...[/yellow]")
            try:
                domain = urlparse(url).netloc.replace('.', '_')
                zip_file_name = f"{domain}_media.zip"
                download_media(url, zip_file_name)
            except Exception as e:
                console.print(f"[bold red]Ocurrió un error durante la descarga de medios:[/bold red] {e}")

        elif action == '6':
            break
        else:
            console.print("[bold red]Opción no válida.[/bold red]")

def do_search(query, engine, pages, start_page, lang, interactive, ia_agent):
    """
    Realiza una búsqueda con la consulta y parámetros especificados y maneja los resultados.
    """
    global CASO_ACTUAL
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
        else:  # Google es el por defecto
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
    
    CASO_ACTUAL["terminos"] = {"tipo": "directo", "valor": query}
    
    if interactive:
        if not ia_agent:
            console.print("[bold yellow]No se seleccionó un agente de IA. El modo interactivo tendrá funcionalidades limitadas.[/bold yellow]")
        interactive_analysis_menu(resultados, ia_agent)
    else:
        rparser = ResultsParser(resultados)
        console.print(rparser.to_table())

def do_generate_dork_ia():
    """
    Solicita una descripción al usuario, genera un dork con IA y lo muestra.
    """
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

def do_reverse_image_search():
    """
    Solicita una URL de imagen y realiza una búsqueda inversa.
    """
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


# --- Función Principal ---

def main(args):
    """
    Función principal que orquesta la ejecución del script basado en los argumentos.
    """
    global CASO_ACTUAL
    # --- Verificación de Configuración ---
    env_exists = os.path.exists(".env")
    if args.configure:
        print("Iniciando configuración del entorno...")
        env_config()
        openai_config()
        print("\n.env configurado exitosamente.")
        if not any(vars(args).values()): # Salir si solo se usó -c
             sys.exit(0)
            
    elif not env_exists and not args.help:
        console.print("[bold red]Error: El fichero .env no existe o no está configurado.[/bold red]")
        console.print("Por favor, ejecuta el script con el flag -c o desde el menú interactivo para configurarlo.")
        sys.exit(1)

    # --- Búsqueda Inversa de Imagen ---
    if args.reverse:
        do_reverse_image_search()
        sys.exit(0)

    # --- Inicialización del Agente de IA ---
    ia_agent = None
    if args.google_dorks or args.interactive or args.load_case:
        ia_agent = select_ia_agent()
        if not ia_agent and (args.google_dorks or args.interactive or args.load_case):
            console.print("[bold red]Se requiere un agente de IA para esta acción, pero no se pudo inicializar.[/bold red]")
            sys.exit(1)

    # --- Lógica de Comandos ---
    if args.load_case:
        cargar_caso(ia_agent)
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

    # --- Construcción de la Consulta ---
    query = args.query
    if not query:
        guided_parts = []
        if args.nombre:
            guided_parts.append(f'"{args.nombre}"')
        if args.usuario:
            guided_parts.append(f'"{args.usuario}"')
        if args.buscar:
            guided_parts.append(f'"{args.buscar}"')
        
        if guided_parts:
            query = " AND ".join(guided_parts)

    if not query:
        # Esto ya no debería ocurrir si se llama desde el menú, pero es una salvaguarda.
        console.print("[bold red]Error: Debes indicar una consulta con -q o usar los argumentos de búsqueda guiada (-n, -u, -b).[/bold red]")
        sys.exit(1)

    # --- Búsqueda ---
    do_search(query, args.engine, args.pages, args.start_page, args.lang, args.interactive, ia_agent)
    
    # --- Procesamiento de Resultados (Post-búsqueda no interactiva) ---
    if not args.interactive:
        # El parseo y la impresión ya se hacen en do_search, pero la exportación no.
        # Re-obtenemos los resultados para exportarlos.
        resultados = ULTIMOS_RESULTADOS 
        rparser = ResultsParser(resultados)
        
        if args.html:
            rparser.exportar_html(args.html)
        if args.json:
            rparser.exportar_json(args.json)
        if args.csv:
            rparser.exportar_csv(args.csv)
        if args.download:
            file_types = [ft.strip() for ft in args.download.split(',')]
            urls = [resultado['link'] for resultado in resultados]
            fdownloader = FileDownload("Descargas")
            for url in urls:
                if any(url.lower().endswith(f".{file_type}") for file_type in file_types) or "all" in file_types:
                    fdownloader.descargar_archivo(url, args.metadata)


def show_main_menu():
    """
    Muestra el menú principal interactivo y maneja la selección del usuario.
    """
    while True:
        console.rule("[bold green]Menú Principal de ScannUs[/bold green]")
        console.print("1. [cyan]Búsqueda Guiada[/cyan] (por nombre, usuario, etc.)")
        console.print("2. [cyan]Búsqueda Directa[/cyan] (con dork personalizado)")
        console.print("3. [yellow]Generar Dork con IA[/yellow]")
        console.print("4. [magenta]Búsqueda Inversa de Imagen[/magenta]")
        console.print("5. [blue]Analizar Tecnologías de un Sitio Web[/blue]")
        console.print("6. [green]Cargar Caso de Investigación[/green]")
        console.print("7. [red]Configurar Claves de API[/red]")
        console.print("8. [bold red]Salir[/bold red]")
        console.rule()
        
        choice = input("> ").strip()

        if choice == '1':
            console.print("[bold cyan]--- Búsqueda Guiada ---[/bold cyan]")
            nombre = input("Nombre completo (opcional): ")
            usuario = input("Nombre de usuario (opcional): ")
            buscar = input("Término general (opcional): ")
            
            guided_parts = []
            if nombre: guided_parts.append(f'"{nombre}"')
            if usuario: guided_parts.append(f'"{usuario}"')
            if buscar: guided_parts.append(f'"{buscar}"')
            
            if not guided_parts:
                console.print("[bold red]Debe ingresar al menos un término de búsqueda.[/bold red]")
                continue
            
            query = " AND ".join(guided_parts)
            engine = input("Motor de búsqueda (google/duckduckgo/brave) [duckduckgo]: ").lower() or "duckduckgo"
            interactive_mode = input("¿Activar modo interactivo para análisis? (s/n) [s]: ").lower() or 's'
            
            ia_agent = None
            if interactive_mode == 's':
                ia_agent = select_ia_agent()

            do_search(query, engine, pages=1, start_page=1, lang='lang_es', interactive=(interactive_mode == 's'), ia_agent=ia_agent)

        elif choice == '2':
            console.print("[bold cyan]--- Búsqueda Directa ---[/bold cyan]")
            query = input("Ingrese el dork de búsqueda: ")
            if not query:
                console.print("[bold red]La consulta no puede estar vacía.[/bold red]")
                continue
            
            engine = input("Motor de búsqueda (google/duckduckgo/brave) [duckduckgo]: ").lower() or "duckduckgo"
            interactive_mode = input("¿Activar modo interactivo para análisis? (s/n) [s]: ").lower() or 's'
            
            ia_agent = None
            if interactive_mode == 's':
                ia_agent = select_ia_agent()
                
            do_search(query, engine, pages=1, start_page=1, lang='lang_es', interactive=(interactive_mode == 's'), ia_agent=ia_agent)

        elif choice == '3':
            do_generate_dork_ia()

        elif choice == '4':
            do_reverse_image_search()

        elif choice == '5':
            url = input("Ingrese la URL a analizar: ")
            if url:
                tech_scan(url)
        elif choice == '6':
            ia_agent = select_ia_agent()
            if ia_agent:
                cargar_caso(ia_agent)
        elif choice == '7':
            env_config()
            openai_config()
        elif choice == '8':
            console.print("[bold green]¡Hasta luego![/bold green]")
            break
        else:
            console.print("[bold red]Opción no válida. Por favor, intente de nuevo.[/bold red]")

def select_ia_agent():
    """
    Solicita al usuario que elija un modelo de IA y devuelve una instancia del agente.
    """
    respuesta = ""
    while respuesta.lower() not in ("ge", "op"):
        respuesta = input("¿Qué modelo de IA quieres utilizar? Gemini (ge) o OpenAI (op): ")
    
    if respuesta.lower() == "ge":
        if not GOOGLE_API_KEY_FOR_GEMINI:
            console.print("[bold red]Error: La clave GOOGLE_API_KEY_FOR_GEMINI no se encuentra en .env.[/bold red]")
            return None
        console.print("--- Usando Gemini ---", style="bold green")
        return IAAgent(GeminiGenerator())
    elif respuesta.lower() == "op":
        if not os.getenv("OPENAI_API_KEY"):
            console.print("[bold yellow]La API Key de OpenAI no está configurada.[/bold yellow]")
            openai_config()
            load_dotenv() # Recargar para obtener la nueva clave
        console.print("--- Usando OpenAI ---", style="bold green")
        return IAAgent(OpenAIGenerator(model_name="gpt-4o"))
    return None

# --- Punto de Entrada del Script ---

if __name__ == "__main__":
    # Configura el parser de argumentos de la línea de comandos.
    parser = argparse.ArgumentParser(
        description="Herramienta para realizar búsquedas avanzadas en Google y análisis de resultados.",
        add_help=False # Desactiva la ayuda por defecto para usar la personalizada.
    )
    
    # --- Definición de Argumentos ---
    general_group = parser.add_argument_group('Argumentos Principales')
    general_group.add_argument("-h", "--help", action="store_true", help="Muestra esta tabla de ayuda y sale.")
    general_group.add_argument("-q", "--query", type=str, help="Especifica el dork que desea buscar.")
    general_group.add_argument("-c", "--configure", action="store_true", help="Inicia el proceso de configuración para .env")
    general_group.add_argument("-i", "--interactive", action="store_true", help="Activa el modo de análisis interactivo.")
    
    case_group = parser.add_argument_group('Gestión de Casos')
    case_group.add_argument("--load-case", action="store_true", help="Carga un caso de investigación guardado.")

    search_group = parser.add_argument_group('Opciones de Búsqueda')
    search_group.add_argument("--engine", type=str, default="duckduckgo", help="Motor de búsqueda a utilizar (google, duckduckgo, brave).")
    search_group.add_argument("-n", "--nombre", help="Nombre completo de la persona a buscar.")
    search_group.add_argument("-u", "--usuario", help="Nombre de usuario a buscar.")
    search_group.add_argument("-b", "--buscar", help="Término o tema de búsqueda general.")
    search_group.add_argument("-rev", "--reverse", help="URL de una imagen para búsqueda inversa.")
    search_group.add_argument("--start-page", type=int, default=1, help="Página de inicio para la búsqueda (def: 1).")
    search_group.add_argument("--pages", type=int, default=1, help="Número de páginas a revisar (def: 1).")
    search_group.add_argument("--lang", type=str, default="lang_es", help="Código de idioma para la búsqueda (def: lang_es).")

    ia_group = parser.add_argument_group('Opciones de IA')
    ia_group.add_argument("-gd", "--google-dorks", type=str, metavar="\"DESC\"", help="Genera un Dork usando IA a partir de una descripción.")

    media_group = parser.add_argument_group('Opciones de Medios')
    media_group.add_argument("--media-scrape", type=str, metavar="URL", help="Descarga todos los medios de una URL a un archivo ZIP.")

    output_group = parser.add_argument_group('Opciones de Salida (No Interactivo)')
    output_group.add_argument("--json", type=str, metavar="FILE.json", help="Exporta los resultados a un fichero JSON.")
    output_group.add_argument("--html", type=str, metavar="FILE.html", help="Exporta los resultados a un fichero HTML.")
    output_group.add_argument("--csv", type=str, metavar="FILE.csv", help="Exporta los resultados a un fichero CSV.")
    output_group.add_argument("--download", type=str, metavar="pdf,docx", help="Descarga archivos por tipo. Ej: 'pdf,docx' o 'all'.")
    output_group.add_argument("--metadata", action="store_true", help="Extrae metadatos de los archivos descargados.")

    # Si se usa -h o --help, muestra la ayuda personalizada y termina.
    if '-h' in sys.argv or '--help' in sys.argv:
        show_custom_help(parser)
        sys.exit(0)
    
    # Si no se pasan argumentos (solo el nombre del script), muestra el menú interactivo.
    if len(sys.argv) == 1:
        show_main_menu()
        sys.exit(0)

    args = parser.parse_args()

    # --- Manejo de Comandos Especiales ---
    if args.media_scrape:
        zip_file_name = "media_descargada.zip"
        download_media(args.media_scrape, zip_file_name)
        sys.exit(0)
    
    main(args)