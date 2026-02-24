import argparse
import sys
from cli.ui import console
from rich.table import Table

def show_custom_help(parser):
    console.print("\n[bold green]Tabla de Ayuda de NinjaDorks[/bold green]")
    for group in parser._action_groups:
        actions = [action for action in group._group_actions if action.option_strings]
        if not actions:
            continue
        table = Table(title=f"[bold magenta]{group.title}[/bold magenta]", show_header=True, header_style="bold cyan", box=None)
        table.add_column("Argumento", style="cyan", no_wrap=True)
        table.add_column("Descripción", style="green")
        table.add_column("Valor Esperado", style="yellow")
        for action in actions:
            opts = ", ".join(action.option_strings)
            metavar = action.metavar or ""
            table.add_row(opts, action.help, metavar)
        console.print(table)
    
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

def get_parser():
    parser = argparse.ArgumentParser(
        description="Herramienta para realizar búsquedas avanzadas en Google y análisis de resultados.",
        add_help=False
    )
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
    ia_group.add_argument("-gd", "--google-dorks", type=str, metavar='"DESC"', help="Genera un Dork usando IA a partir de una descripción.")

    media_group = parser.add_argument_group('Opciones de Medios')
    media_group.add_argument("--media-scrape", type=str, metavar="URL", help="Descarga todos los medios de una URL a un archivo ZIP.")

    output_group = parser.add_argument_group('Opciones de Salida (No Interactivo)')
    output_group.add_argument("--json", type=str, metavar="FILE.json", help="Exporta los resultados a un fichero JSON.")
    output_group.add_argument("--html", type=str, metavar="FILE.html", help="Exporta los resultados a un fichero HTML.")
    output_group.add_argument("--csv", type=str, metavar="FILE.csv", help="Exporta los resultados a un fichero CSV.")
    output_group.add_argument("--excel", type=str, metavar="FILE.xlsx", help="Exporta los resultados a un fichero Excel.")
    output_group.add_argument("--download", type=str, metavar="pdf,docx", help="Descarga archivos por tipo. Ej: 'pdf,docx' o 'all'.")
    output_group.add_argument("--metadata", action="store_true", help="Extrae metadatos de los archivos descargados.")
    return parser
