import os
from rich.table import Table
from webtech import WebTech
from cli.ui import console

# Set up the local directory for the webtech fingerprint database
data_dir = os.path.expanduser("~/.local/share/webtech")
if not os.path.exists(data_dir):
    os.makedirs(data_dir)

def tech_scan(url):
    """
    Executes a technology stack fingerprinter on the target URL via WebTech.
    Identifies CMS, frameworks, web servers, and client-side libraries.
    Results are rendered in a Rich Table for high-visibility analysis.
    """
    console.print(f"\n--- Analyzing technology stack for: {url} ---", style="bold blue")
    try:
        wt = WebTech()
        # Timeout configured to prevent hanging on unresponsive or throttled targets
        results = wt.start_from_url(url, timeout=10)

        # Validate and serialize the results dictionary for TUI rendering
        if isinstance(results, dict) and results:
            table = Table(title="Detected Technologies", show_header=True, header_style="bold magenta")
            table.add_column("Technology", style="cyan")
            table.add_column("Version", style="green")
            for tech, version in results.items():
                table.add_row(tech, version)
            console.print(table)
        else:
            console.print("  [yellow]No technologies detected or unexpected response format.[/yellow]")
    except Exception as e:
        console.print(f"  [bold red]An error occurred during tech analysis:[/bold red] {e}")
