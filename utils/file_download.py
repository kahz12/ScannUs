# -*- coding: utf-8 -*-

# Standard and third-party library imports
import os
import requests
import datetime
from PyPDF2 import PdfReader
from rich.console import Console
from rich.table import Table
import exifread
from core.config import DIR_DOWNLOADS

class FileDownload:
    """
    Service layer for artifact retrieval and post-download processing.
    Handles chunked HTTP streaming, destination scaffolding, and 
    automated metadata extraction for PDF and image (EXIF) payloads.
    """

    def __init__(self, directorio_destino=DIR_DOWNLOADS):
        """
        Initializes the download context.

        Args:
            directorio_destino (str): Target directory for persisted artifacts.
        """
        self.directorio = directorio_destino
        self.crear_directorio() 
        self.console = Console()

    def crear_directorio(self):
        """
        Idempotent directory initialization for the download dropzone.
        """
        if not os.path.exists(self.directorio):
            os.makedirs(self.directorio)

    def _extract_pdf_metadata(self, file_path):
        """
        Specialized parser for PDF document properties.

        Args:
            file_path (str): Pointer to the local PDF artifact.
        """
        try:
            with open(file_path, 'rb') as f:
                reader = PdfReader(f)
                meta = reader.metadata

                if not meta:
                    self.console.print("  [yellow]No metadata found in the PDF.[/yellow]")
                    return

                # Render extracted properties in a Rich table
                table = Table(title=f"Metadata for {os.path.basename(file_path)}", show_header=False, box=None)
                table.add_column("Field", style="cyan")
                table.add_column("Value", style="green")

                # Map PDF internal keys to human-readable descriptors
                meta_map = {
                    '/Author': 'Author',
                    '/Creator': 'Creator (Software)',
                    '/Producer': 'Producer (Software)',
                    '/Subject': 'Subject',
                    '/Title': 'Title',
                    '/CreationDate': 'Creation Date',
                    '/ModDate': 'Modification Date'
                }

                for key, readable_name in meta_map.items():
                    if key in meta:
                        table.add_row(readable_name, str(meta[key]))

                self.console.print(table)

        except Exception as e:
            self.console.print(f"  [bold red]Error extracting PDF metadata:[/bold red] {e}")

    def _extract_exif_metadata(self, file_path):
        """
        Specialized parser for image EXIF telemetry.
        """
        try:
            with open(file_path, 'rb') as f:
                # detail=False suppresses high-volume binary blobs
                tags = exifread.process_file(f, details=False)
                
                if not tags:
                    self.console.print("  [yellow]No EXIF metadata found in the image.[/yellow]")
                    return

                table = Table(title=f"EXIF Metadata for {os.path.basename(file_path)}", show_header=False, box=None)
                table.add_column("Field", style="cyan")
                table.add_column("Value", style="green")

                # Filter out raw thumbnails and proprietary maker notes to reduce noise
                for tag, value in tags.items():
                    if tag not in ('JPEGThumbnail', 'TIFFThumbnail', 'Filename', 'EXIF MakerNote'):
                        table.add_row(tag, str(value))
                        
                self.console.print(table)
        except Exception as e:
            self.console.print(f"  [bold red]Error extracting EXIF metadata:[/bold red] {e}")

    def extract_metadata(self, file_path):
        """
        Dispatches the file to the appropriate metadata extraction pipeline
        based on its file extension.

        Args:
            file_path (str): Path to the artifact on disk.
        """
        self.console.print(f"\n--- Extracting metadata for: [cyan]{os.path.basename(file_path)}[/cyan] ---")

        _, extension = os.path.splitext(file_path)

        if extension.lower() == '.pdf':
            self._extract_pdf_metadata(file_path)
        elif extension.lower() in ['.jpg', '.jpeg', '.png', '.tiff']:
            self._extract_exif_metadata(file_path)
        else:
            # Fallback to filesystem-level stat metadata for unsupported formats
            self.console.print(f"  [yellow]No specialized metadata extractor available for '{extension}' files.[/yellow]")
            try:
                stat = os.stat(file_path)
                self.console.print(f"  -> Size: {stat.st_size} bytes")
                self.console.print(f"  -> Last Modification: {datetime.datetime.fromtimestamp(stat.st_mtime)}")
            except Exception as e:
                self.console.print(f"[bold red]Error during basic filesystem metadata extraction:[/bold red] {e}")

    def descargar_archivo(self, url, extract_metadata=False):
        """
        Performs a chunked binary download from a target URL.

        Args:
            url (str): Source URI.
            extract_metadata (bool): If True, triggers post-download metadata analysis.
        """
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            nombre_archivo = os.path.basename(parsed_url.path)

            # Fallback name synthesis for endpoints without a direct path-to-filename mapping
            if not nombre_archivo:
                import hashlib
                hash_object = hashlib.md5(url.encode())
                nombre_archivo = hash_object.hexdigest() + ".bin" 
                self.console.print(f"[yellow]Warning: Could not determine filename from URL. Using hash:[/yellow] {nombre_archivo}")

            ruta_completa = os.path.join(self.directorio, nombre_archivo)

            self.console.print(f"Downloading '[green]{nombre_archivo}[/green]' from '{url}'...")

            # Execute streaming GET to handle large binary artifacts without memory spikes
            respuesta = requests.get(url, stream=True, timeout=15)
            respuesta.raise_for_status()

            # Iterate over the response stream in 8KB buffers
            with open(ruta_completa, "wb") as archivo:
                for chunk in respuesta.iter_content(chunk_size=8192):
                    archivo.write(chunk)
            self.console.print(f"Success! File [green]{nombre_archivo}[/green] downloaded to [cyan]{ruta_completa}[/cyan]")

            if extract_metadata:
                self.extract_metadata(ruta_completa)

        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Network or HTTP error downloading {url}:[/bold red] {e}")
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error downloading {url}:[/bold red] {e}")

    def descargar_archivo_directo(self, url, extract_metadata=False):
        """
        Exposes a simplified interface for direct file downloads.
        """
        self.descargar_archivo(url, extract_metadata)
