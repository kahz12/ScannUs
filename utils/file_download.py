# -*- coding: utf-8 -*-

# Standard and third-party library imports
import os
import requests  # To make HTTP requests and download files.
import datetime  # To work with dates, especially for metadata.
from PyPDF2 import PdfReader  # To read and extract metadata from PDF files.
from rich.console import Console  # For a more attractive and readable terminal output.
from rich.table import Table  # To format data into tables in the console.
import exifread
from core.config import DIR_DOWNLOADS

class FileDownload:
    """
    Class designed to manage downloading files from URLs.
    Includes features to create destination directories and extract
    metadata from specific file types, like PDF.
    """

    def __init__(self, directorio_destino=DIR_DOWNLOADS):
        """
        Initializes the FileDownload instance.

        Args:
            directorio_destino (str): The directory path where downloaded
                                      files will be saved.
        """
        self.directorio = directorio_destino
        self.crear_directorio()  # Se asegura de que el directorio de destino exista.
        self.console = Console()  # Inicializa una consola de `rich` para toda la clase.

    def crear_directorio(self):
        """
        Creates the destination directory specified in the constructor if it doesn't exist.
        """
        if not os.path.exists(self.directorio):
            os.makedirs(self.directorio)

    def _extract_pdf_metadata(self, file_path):
        """
        Private method to extract and display metadata from a PDF file.

        Args:
            file_path (str): The local path to the PDF file.
        """
        try:
            # Abre el archivo PDF en modo de lectura binaria ('rb').
            with open(file_path, 'rb') as f:
                reader = PdfReader(f)
                meta = reader.metadata  # Accede a la propiedad de metadatos del objeto.

                if not meta:
                    self.console.print("  [yellow]No se encontraron metadatos en el PDF.[/yellow]")
                    return

                # Crea una tabla de `rich` para mostrar los metadatos de forma ordenada.
                table = Table(title=f"Metadatos para {os.path.basename(file_path)}", show_header=False, box=None)
                table.add_column("Campo", style="cyan")
                table.add_column("Valor", style="green")

                # Mapea las claves crudas de los metadatos de PDF a nombres más legibles.
                meta_map = {
                    '/Author': 'Autor',
                    '/Creator': 'Creador (Software)',
                    '/Producer': 'Productor (Software)',
                    '/Subject': 'Asunto',
                    '/Title': 'Título',
                    '/CreationDate': 'Fecha de Creación',
                    '/ModDate': 'Fecha de Modificación'
                }

                # Itera sobre el mapa y, si la clave existe en los metadatos, la añade a la tabla.
                for key, readable_name in meta_map.items():
                    if key in meta:
                        table.add_row(readable_name, str(meta[key]))

                self.console.print(table)

        except Exception as e:
            # Captura y muestra cualquier error que ocurra durante la lectura del PDF.
            self.console.print(f"  [bold red]Error al extraer metadatos del PDF:[/bold red] {e}")

    def _extract_exif_metadata(self, file_path):
        """
        Private method to extract and display EXIF metadata from images.
        """
        try:
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, details=False)
                
                if not tags:
                    self.console.print("  [yellow]No se encontraron metadatos EXIF en la imagen.[/yellow]")
                    return

                table = Table(title=f"Metadatos EXIF para {os.path.basename(file_path)}", show_header=False, box=None)
                table.add_column("Campo", style="cyan")
                table.add_column("Valor", style="green")

                for tag, value in tags.items():
                    if tag not in ('JPEGThumbnail', 'TIFFThumbnail', 'Filename', 'EXIF MakerNote'):
                        table.add_row(tag, str(value))
                        
                self.console.print(table)
        except Exception as e:
            self.console.print(f"  [bold red]Error al extraer metadatos EXIF:[/bold red] {e}")

    def extract_metadata(self, file_path):
        """
        Extracts metadata from a file based on its extension.
        Currently, has specialized support for PDF. For other files,
        it displays basic file system information.

        Args:
            file_path (str): The path to the file from which metadata will be extracted.
        """
        self.console.print(f"\n--- Extrayendo metadatos para: [cyan]{os.path.basename(file_path)}[/cyan] ---")

        # Obtiene la extensión del archivo para decidir qué extractor usar.
        _, extension = os.path.splitext(file_path)

        if extension.lower() == '.pdf':
            # Llama al método específico para PDF.
            self._extract_pdf_metadata(file_path)
        elif extension.lower() in ['.jpg', '.jpeg', '.png', '.tiff']:
            self._extract_exif_metadata(file_path)
        else:
            # Para otros tipos de archivo, informa que no hay un extractor específico.
            self.console.print(f"  [yellow]No hay un extractor de metadatos para archivos '{extension}'.[/yellow]")
            try:
                # Muestra metadatos básicos del sistema de archivos como alternativa.
                stat = os.stat(file_path)
                self.console.print(f"  -> Tamaño: {stat.st_size} bytes")
                self.console.print(f"  -> Última modificación: {datetime.datetime.fromtimestamp(stat.st_mtime)}")
            except Exception as e:
                self.console.print(f"  [bold red]Ocurrió un error durante la extracción de metadatos básicos:[/bold red] {e}")

    def descargar_archivo(self, url, extract_metadata=False):
        """
        Downloads a file from a URL.

        Args:
            url (str): The URL of the file to download.
            extract_metadata (bool): If True, attempts to extract metadata after downloading.
        """
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            nombre_archivo = os.path.basename(parsed_url.path)

            # Si la URL no termina en un nombre de archivo (ej. '.../download?id=123'),
            # se genera un nombre de archivo único basado en un hash de la URL.
            if not nombre_archivo:
                import hashlib
                hash_object = hashlib.md5(url.encode())
                nombre_archivo = hash_object.hexdigest() + ".bin"  # Se usa una extensión genérica.
                self.console.print(f"[yellow]Advertencia: No se pudo determinar el nombre del archivo. Usando:[/yellow] {nombre_archivo}")

            ruta_completa = os.path.join(self.directorio, nombre_archivo)

            self.console.print(f"Descargando '[green]{nombre_archivo}[/green]' desde '{url}'...")

            # Realiza la petición GET. `stream=True` es importante para no cargar todo el archivo en memoria de una vez.
            respuesta = requests.get(url, stream=True, timeout=15)
            respuesta.raise_for_status()  # Lanza una excepción si la respuesta es un error HTTP.

            # Escribe el contenido de la respuesta en el archivo local en fragmentos (chunks).
            with open(ruta_completa, "wb") as archivo:
                for chunk in respuesta.iter_content(chunk_size=8192):
                    archivo.write(chunk)
            self.console.print(f"¡Éxito! Archivo [green]{nombre_archivo}[/green], descargado en [cyan]{ruta_completa}[/cyan]")

            # Si se solicita, llama a la función de extracción de metadatos.
            if extract_metadata:
                self.extract_metadata(ruta_completa)

        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error de red o HTTP al descargar {url}:[/bold red] {e}")
        except Exception as e:
            self.console.print(f"[bold red]Ocurrió un error inesperado al descargar {url}:[/bold red] {e}")

    def descargar_archivo_directo(self, url, extract_metadata=False):
        """
        Convenience method that acts as an alias for `descargar_archivo`.
        Simplifies calls from other parts of the code that only need to download a file.
        """
        self.descargar_archivo(url, extract_metadata)
