import textwrap
from rich.console import Console
from rich.table import Table

console = Console()

def print_startup_banner(google_api_key_found):
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

    with console.status("[bold green]Inicializando...[/bold green]", spinner="dots") as status:
        status.update("Cargando variables de entorno...")
        console.log("[green]Variables de entorno cargadas.[/green]")
        
        if google_api_key_found:
            console.log("[green]Clave de API de Gemini encontrada en .env.[/green]")
        else:
            console.log("[yellow]Clave de API de Gemini no encontrada en .env.[/yellow]")
    console.rule()
