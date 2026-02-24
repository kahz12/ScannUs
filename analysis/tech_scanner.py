import os
from rich.table import Table
from webtech import WebTech
from cli.ui import console

data_dir = os.path.expanduser("~/.local/share/webtech")
if not os.path.exists(data_dir):
    os.makedirs(data_dir)

def tech_scan(url):
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
