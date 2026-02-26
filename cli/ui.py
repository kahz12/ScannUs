import textwrap
from rich.console import Console
from rich.table import Table

# Initialize global Rich console for standardized TUI rendering
console = Console()

def print_startup_banner(google_api_key_found):
    """
    Renders the ASCII art banner and performs bootstrap sequence logging.
    
    Args:
        google_api_key_found (bool): Readiness flag for the LLM provider context.
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
    console.rule("[bold green]Advanced Search & OSINT Analysis Tool[/bold green]")

    with console.status("[bold green]Initializing system context...[/bold green]", spinner="dots") as status:
        status.update("Resolving environment variables...")
        console.log("[green]Environment configuration resolved.[/green]")
        
        if google_api_key_found:
            console.log("[green]Gemini API Key identified in local configuration.[/green]")
        else:
            console.log("[yellow]Gemini API Key not found in .env configuration.[/yellow]")
    console.rule()
