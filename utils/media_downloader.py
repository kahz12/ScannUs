# Standard and third-party library imports
import os
import requests
import tempfile
import zipfile
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from rich.table import Table
from rich.box import ROUNDED
from core.config import DIR_MEDIA

# Initialize a global Console instance for Rich-formatted TUI output.
console = Console()

def download_media_from_url(url, output_zip_path="media_download.zip", media_type='all'):
    """
    Orchestrates the scraping and archiving of media assets from a target URL.
    Crawls the DOM for media-specific tags, resolves relative links, 
    downloads assets concurrently to a temporary buffer, and aggregates them 
    into a monolithic ZIP archive.

    Args:
        url (str): Target webpage URL.
        output_zip_path (str): Final destination for the ZIP artifact.
        media_type (str): Media filter ('images', 'videos', or 'all').
    """
    output_zip_path = os.path.join(DIR_MEDIA, os.path.basename(output_zip_path))
    
    # User-Agent spoofing to bypass rudimentary WAF/bot detection.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        console.print(f"Accessing URL: [cyan]{url}[/cyan]")
        response = requests.get(url, headers=headers, timeout=20)
        # Immediate exit on non-200 HTTP status codes.
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Error accessing URL:[/bold red] {e}")
        return

    # Parse DOM structure.
    soup = BeautifulSoup(response.text, 'html.parser')
    media_urls = []
    debug_data = [] # Diagnostics cache for link resolution tracing.

    # Filter definitions based on media_type selection.
    tags_to_find = []
    if media_type == 'images':
        tags_to_find = ['img']
    elif media_type == 'videos':
        tags_to_find = ['video', 'source']
    else:
        tags_to_find = ['img', 'video', 'source']

    # Crawl the DOM for matching nodes.
    for tag in soup.find_all(tags_to_find):
        src = tag.get('src')
        
        # Filter out empty nodes and inline data blobs (base64).
        if src and not src.startswith('data:'):
            # Normalize relative paths to fully-qualified absolute URIs.
            absolute_url = urljoin(url, src)
            media_urls.append(absolute_url)
            
            # Record resolution metadata for the diagnostic table.
            debug_data.append({
                "tag": f"<{tag.name}>",
                "src": src,
                "absolute_url": absolute_url
            })

    # Render a diagnostic table for post-extraction verification.
    table = Table(title="URL Analysis & Debugging", box=ROUNDED, header_style="bold blue", title_style="bold magenta")
    table.add_column("Tag", style="cyan")
    table.add_column("Original SRC", style="magenta")
    table.add_column("Constructed Absolute URL", style="green")
    
    for item in debug_data:
        table.add_row(item["tag"], item["src"], item["absolute_url"])
    
    console.print(table)

    # Deduplicate URL list to optimize network throughput.
    media_urls = list(dict.fromkeys(media_urls))

    if not media_urls:
        console.print(f"[yellow]No {media_type} found on the page.[/yellow]")
        return

    console.print(f"Found [green]{len(media_urls)}[/green] files of type '{media_type}'. Starting download...")

    # Utilize a TemporaryDirectory context for localized binary processing.
    with tempfile.TemporaryDirectory() as temp_dir:
        for media_url in media_urls:
            try:
                # Stream binary payload to avoid memory exhaustion on large assets.
                media_response = requests.get(media_url, headers=headers, stream=True, timeout=20)
                media_response.raise_for_status()

                # Heuristic filename extraction from URI path.
                parsed_url = urlparse(media_url)
                file_name = os.path.basename(parsed_url.path)
                if not file_name:
                    file_name = media_url.split('/')[-1].split('?')[0]

                # Extension inference via MIME Content-Type headers if missing in path.
                if not os.path.splitext(file_name)[1]:
                    content_type = media_response.headers.get('content-type')
                    if content_type and 'image' in content_type:
                        ext = '.' + content_type.split('/')[1]
                        file_name += ext
                    else:
                        file_name += '.jpg'

                file_path = os.path.join(temp_dir, file_name)
                
                # Fetch payload size for progress bar synchronization.
                total_size = int(media_response.headers.get('content-length', 0))

                with Progress(
                    "[progress.description]{task.description}",
                    BarColumn(),
                    "[progress.percentage]{task.percentage:>3.0f}%",
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    "ETA:", TimeRemainingColumn(),
                ) as progress:
                    task = progress.add_task(f"[cyan]Downloading {file_name[:30]}", total=total_size)
                    
                    # Buffer binary write to disk.
                    with open(file_path, 'wb') as f:
                        for chunk in media_response.iter_content(chunk_size=8192):
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))

            except requests.exceptions.RequestException as e:
                console.print(f"[yellow]Could not download {media_url}:[/yellow] {e}")

        # Consolidate downloaded assets into a monolithic ZIP archive.
        console.print(f"\nCompressing files into [cyan]{output_zip_path}[/cyan]...")
        with zipfile.ZipFile(output_zip_path, 'w') as zipf:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    zipf.write(os.path.join(root, file), arcname=file)

    console.print(f"[bold green]Success! Media downloaded and archived in {output_zip_path}[/bold green]")

def download_media(url, output_path, media_type='all'):
    """
    Public API wrapper for the media downloader pipeline.
    """
    download_media_from_url(url, output_path, media_type)
