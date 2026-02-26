import argparse
import sys
from cli.ui import console
from rich.table import Table

def show_custom_help(parser):
    """
    Renders a colorized and structured help menu using the Rich library.
    Iterates through argparse groups to present command-line options in a 
    standardized TUI table format, followed by usage examples.
    """
    console.print("\n[bold green]ScannUs Help Table[/bold green]")
    for group in parser._action_groups:
        # Filter for actions that have associated option flags
        actions = [action for action in group._group_actions if action.option_strings]
        if not actions:
            continue
        
        table = Table(title=f"[bold magenta]{group.title}[/bold magenta]", show_header=True, header_style="bold cyan", box=None)
        table.add_column("Argument", style="cyan", no_wrap=True)
        table.add_column("Description", style="green")
        table.add_column("Expected Value", style="yellow")
        
        for action in actions:
            opts = ", ".join(action.option_strings)
            metavar = action.metavar or ""
            table.add_row(opts, action.help, metavar)
        console.print(table)
    
    # Showcase common CLI usage patterns to assist the operator
    console.rule("[bold_green]Usage Examples:[/bold_green]")
    console.print("  [white]1. Basic Search Query:[/white]")
    console.print("     [cyan]python main.py -q \"site:.gov filetype:pdf\"[/cyan]")
    console.print("  [white]2. Target Engine Selection (Brave/Google/DuckDuckGo):[/white]")
    console.print("     [cyan]python main.py -q \"OSINT tools\" --engine brave --pages 2[/cyan]")
    console.print("  [white]3. Natural Language Dork Generation:[/white]")
    console.print("     [cyan]python main.py -gd \"Find excel price lists of tech companies\"[/cyan]")
    console.print("  [white]4. Guided Multi-Parameter Search:[/white]")
    console.print("     [cyan]python main.py -n \"John Doe\" -u \"jdoe88\"[/cyan]")
    console.print("  [white]5. Media Scraper Pipeline:[/white]")
    console.print("     [cyan]python main.py --media-scrape \"https://example.com/gallery\"[/cyan]")
    console.print("  [white]6. Enter Interactive TUI Mode:[/white]")
    console.print("     [cyan]python main.py -i[/cyan]")

def get_parser():
    """
    Initializes and configures the global ArgumentParser instance.
    Arguments are categorized into logical groups to optimize CLI ergonomics.
    """
    parser = argparse.ArgumentParser(
        description="ScannUs: Advanced Search Orchestrator and OSINT Analysis Engine.",
        add_help=False # Suppress default help to use custom rich renderer
    )
    
    general_group = parser.add_argument_group('Main Arguments')
    general_group.add_argument("-h", "--help", action="store_true", help="Display this custom help table.")
    general_group.add_argument("-q", "--query", type=str, help="Primary search string or complex Google Dork.")
    general_group.add_argument("-c", "--configure", action="store_true", help="Start the .env credential setup sequence.")
    general_group.add_argument("-i", "--interactive", action="store_true", help="Enter the interactive investigation menu.")
    
    case_group = parser.add_argument_group('Case Management')
    case_group.add_argument("--load-case", action="store_true", help="Hydrate session state from a previously saved case.")

    search_group = parser.add_argument_group('Search Parameters')
    search_group.add_argument("--engine", type=str, default="duckduckgo", help="Target engine (google, duckduckgo, brave).")
    search_group.add_argument("-n", "--nombre", help="Target's full legal name.")
    search_group.add_argument("-u", "--usuario", help="Target's primary username/handle.")
    search_group.add_argument("-b", "--buscar", help="Generic search term or topic.")
    search_group.add_argument("-e", "--email", help="Target's email address.")
    search_group.add_argument("-t", "--telefono", help="Target's phone number.")
    search_group.add_argument("--deep", action="store_true", help="Execute recursive analysis on each search result.")
    search_group.add_argument("-rev", "--reverse", help="Image URL for reverse lookup.")
    search_group.add_argument("--start-page", type=int, default=1, help="Starting SERP offset (default: 1).")
    search_group.add_argument("--pages", type=int, default=1, help="Number of result pages to retrieve (default: 1).")
    search_group.add_argument("--lang", type=str, default="lang_es", help="Language code filter (default: lang_es).")

    ia_group = parser.add_argument_group('AI & NLP Options')
    ia_group.add_argument("-gd", "--google-dorks", type=str, metavar='"DESC"', help="Synthesize a Google Dork from a natural language prompt.")

    media_group = parser.add_argument_group('Media Processing')
    media_group.add_argument("--media-scrape", type=str, metavar="URL", help="Extract and archive media from a remote URL.")

    output_group = parser.add_argument_group('Export Options')
    output_group.add_argument("--json", type=str, metavar="FILE.json", help="Serialize findings to a JSON artifact.")
    output_group.add_argument("--html", type=str, metavar="FILE.html", help="Generate a stylized HTML report.")
    output_group.add_argument("--csv", type=str, metavar="FILE.csv", help="Export flat data to a CSV file.")
    output_group.add_argument("--excel", type=str, metavar="FILE.xlsx", help="Export structured data to an Excel workbook.")
    output_group.add_argument("--download", type=str, metavar="TYPES", help="Batch download filetypes (e.g., 'pdf,docx' or 'all').")
    output_group.add_argument("--metadata", action="store_true", help="Trigger automated metadata extraction on downloaded artifacts.")
    
    return parser
