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
    respuesta = ""
    while respuesta.lower() not in ("ge", "op"):
        respuesta = input("¿Qué modelo de IA quieres utilizar? Gemini (ge) o OpenAI (op): ")
    
    if respuesta.lower() == "ge":
        if not os.getenv("GOOGLE_API_KEY_FOR_GEMINI"):
            console.print("[bold red]Error: La clave GOOGLE_API_KEY_FOR_GEMINI no se encuentra en .env.[/bold red]")
            return None
        console.print("--- Usando Gemini ---", style="bold green")
        return IAAgent(GeminiGenerator())
    elif respuesta.lower() == "op":
        if not os.getenv("OPENAI_API_KEY"):
            console.print("[bold yellow]La API Key de OpenAI no está configurada.[/bold yellow]")
            openai_config()
        console.print("--- Usando OpenAI ---", style="bold green")
        return IAAgent(OpenAIGenerator(model_name="gpt-4o"))
    return None

def process_selected_url(url, ia_agent):
    while True:
        console.print(f"\n--- Analizando URL: [cyan]{url}[/cyan] ---", style="bold blue")
        console.print("Elige una acción:")
        console.print("1. [green]Resumir[/green] contenido con IA")
        console.print("2. [green]Extraer[/green] información (emails, teléfonos, etc.)")
        console.print("3. [green]Escanear[/green] tecnologías web")
        console.print("4. [green]Descargar[/green] archivo (si es un enlace directo)")
        console.print("5. [green]Descargar Medios[/green] (imágenes/videos) de la página)")
        console.print("6. [magenta]Capturar Pantalla[/magenta] (Screenshot)")
        console.print("7. [magenta]Verificar histórico[/magenta] en Wayback Machine")
        console.print("8. [yellow]Traducir y Analizar[/yellow] contexto con IA")
        console.print("9. [yellow]Grafo de Entidades[/yellow] (Pyvis) con IA")
        console.print("10. [cyan]Extracción Profunda[/cyan] (Renderizado JS / Contenido Oculto)")
        console.print("0. [red]Volver[/red] al menú principal")
        action = input("> ").strip()

        if action == '1':
            if not ia_agent:
                console.print("[bold red]Requiere configurar una IA para esta opción.[/bold red]")
                continue
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
            fdownloader = FileDownload()
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
            take_screenshot(url)
            
        elif action == '7':
            check_wayback_machine(url)
            
        elif action == '8':
            if not ia_agent:
                console.print("[bold red]Requiere configurar una IA para esta opción.[/bold red]")
                continue
            console.print("\n[yellow]Obteniendo contenido para traducir y analizar...[/yellow]")
            page_text = get_text_from_url(url)
            if page_text:
                analysis = translate_and_analyze_with_ia(page_text, ia_agent)
                console.print("\n--- Análisis de IA ---", style="bold green")
                console.print(analysis)
                
        elif action == '9':
            if not ia_agent:
                console.print("[bold red]Requiere configurar una IA para esta opción.[/bold red]")
                continue
            console.print("\n[yellow]Extrayendo entidades para construir grafo...[/yellow]")
            page_text = get_text_from_url(url)
            if page_text:
                domain = urlparse(url).netloc.replace('.', '_')
                graph_file = f"grafo_{domain}.html"
                result_file = extract_entities_and_graph(page_text, ia_agent, output_filename=graph_file)
                if result_file:
                    console.print(f"[bold green]Se ha creado el archivo de grafo de relaciones:[/bold green] {result_file}")
                    
        elif action == '10':
            console.print("\n[yellow]Iniciando Extracción Profunda (esto puede tardar unos segundos)...[/yellow]")
            page_text = get_dynamic_text_from_url(url)
            if page_text:
                console.print(f"\n[green]Extracción exitosa. Longitud del texto recuperado: {len(page_text)} caracteres.[/green]")
                console.print("[cyan]Analizando información vital (emails, teléfonos)...[/cyan]")
                extracted_data = extract_information(page_text)
                if extracted_data:
                    table = Table(title="Información Extraída (Scraping Profundo)", show_header=True, header_style="bold magenta")
                    table.add_column("Tipo de Dato", style="cyan")
                    table.add_column("Valores Encontrados", style="green")
                    for key, values in extracted_data.items():
                        table.add_row(key.replace('_', ' ').capitalize(), "\n".join(values))
                    console.print(table)
                else:
                    console.print("  [yellow]No se encontró información extraíble en el texto profundo.[/yellow]")
                
        elif action == '0':
            break
        else:
            console.print("[bold red]Opción no válida.[/bold red]")


def interactive_analysis_menu(resultados, ia_agent):
    state.ULTIMOS_RESULTADOS = resultados
    if not state.CASO_ACTUAL["terminos"]:
        state.CASO_ACTUAL["terminos"] = {"tipo": "manual", "valor": "N/A"}
    
    formatted_results = []
    for i, r in enumerate(resultados):
        formatted_results.append({
            'id': i + 1, 'title': r.get('title', 'N/A'),
            'description': r.get('description', 'N/A'), 'link': r.get('link', 'N/A')
        })
    state.CASO_ACTUAL["resultados"] = formatted_results
    
    while True:
        table = Table(title="Resultados de la Búsqueda", show_header=True, header_style="bold green")
        table.add_column("ID", style="dim", width=4)
        table.add_column("Título", style="bold")
        table.add_column("Enlace", style="cyan")
        for res in state.CASO_ACTUAL["resultados"]:
            table.add_row(str(res['id']), res['title'], res['link'])
        console.print(table)

        console.print("\n[bold]Selecciona una opción:[/bold]")
        console.print(" - Ingresa el [cyan]número (ID)[/cyan] del resultado para analizarlo.")
        console.print(" - Escribe '[magenta]media[/magenta]' para descargar imágenes/videos de uno o más resultados.")
        console.print(" - Escribe '[yellow]guardar[/yellow]' para guardar la sesión actual como un caso.")
        console.print(" - Escribe '[green]excel[/green]' para exportar la sesión a Excel.")
        console.print(" - Escribe '[red]salir[/red]' para terminar.")
        choice = input("\n> ").strip().lower()

        if choice == 'salir':
            break
        
        if choice == 'guardar':
            guardar_caso()
            continue
            
        if choice == 'excel':
            archivo = input("Ingrese el nombre del archivo Excel (ej: resultados.xlsx) [resultados.xlsx]: ").strip()
            if not archivo:
                archivo = "resultados.xlsx"
            if not archivo.endswith('.xlsx'):
                archivo += '.xlsx'
            rparser = ResultsParser(state.CASO_ACTUAL.get("resultados", []))
            rparser.exportar_excel(archivo)
            continue
            
        if choice == 'media':
            ids_str = input("Elige el ID o los IDs a descargar, separados por comas (ej: 1, 3, 8): ")
            ids_to_download = [int(i.strip()) for i in ids_str.split(',') if i.strip().isdigit()]
            
            for index in ids_to_download:
                if 0 < index <= len(state.CASO_ACTUAL["resultados"]):
                    url = state.CASO_ACTUAL["resultados"][index - 1]['link']
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
            if 0 <= index < len(state.CASO_ACTUAL["resultados"]):
                selected_url = state.CASO_ACTUAL["resultados"][index]['link']
                process_selected_url(selected_url, ia_agent)
            else:
                console.print("[bold red]Número fuera de rango. Inténtalo de nuevo.[/bold red]")
        except ValueError:
            console.print("[bold red]Entrada no válida. Ingresa un número, 'media', 'guardar', 'excel' o 'salir'.[/bold red]")

def show_main_menu():
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

            cli.actions.do_search(query, engine, pages=1, start_page=1, lang='lang_es', interactive=(interactive_mode == 's'), ia_agent=ia_agent)

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
                
            cli.actions.do_search(query, engine, pages=1, start_page=1, lang='lang_es', interactive=(interactive_mode == 's'), ia_agent=ia_agent)

        elif choice == '3':
            cli.actions.do_generate_dork_ia()

        elif choice == '4':
            do_reverse_image_search()

        elif choice == '5':
            url = input("Ingrese la URL a analizar: ")
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
            console.print("[bold green]¡Hasta luego![/bold green]")
            break
        else:
            console.print("[bold red]Opción no válida. Por favor, intente de nuevo.[/bold red]")

