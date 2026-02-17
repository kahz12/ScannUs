# -*- coding: utf-8 -*-

# Importaciones de bibliotecas estándar y de terceros
import os
import requests  # Para realizar peticiones HTTP y descargar archivos.
import datetime  # Para trabajar con fechas, especialmente para metadatos.
from PyPDF2 import PdfReader  # Para leer y extraer metadatos de archivos PDF.
from rich.console import Console  # Para una salida de terminal más atractiva y legible.
from rich.table import Table  # Para formatear datos en tablas en la consola.

class FileDownload:
    """
    Clase diseñada para gestionar la descarga de archivos desde URLs.
    Incluye funcionalidades para crear directorios de destino y para extraer
    metadatos de tipos de archivo específicos, como PDF.
    """

    def __init__(self, directorio_destino):
        """
        Inicializa la instancia de FileDownload.

        Args:
            directorio_destino (str): La ruta del directorio donde se guardarán
                                      los archivos descargados.
        """
        self.directorio = directorio_destino
        self.crear_directorio()  # Se asegura de que el directorio de destino exista.
        self.console = Console()  # Inicializa una consola de `rich` para toda la clase.

    def crear_directorio(self):
        """
        Crea el directorio de destino especificado en el constructor si este no existe.
        """
        if not os.path.exists(self.directorio):
            os.makedirs(self.directorio)

    def _extract_pdf_metadata(self, file_path):
        """
        Método privado para extraer y mostrar los metadatos de un archivo PDF.

        Args:
            file_path (str): La ruta local al archivo PDF.
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

    def extract_metadata(self, file_path):
        """
        Extrae metadatos de un archivo basándose en su extensión.
        Actualmente, tiene soporte especializado para PDF. Para otros archivos,
        muestra información básica del sistema de archivos.

        Args:
            file_path (str): La ruta al archivo del que se extraerán los metadatos.
        """
        self.console.print(f"\n--- Extrayendo metadatos para: [cyan]{os.path.basename(file_path)}[/cyan] ---")

        # Obtiene la extensión del archivo para decidir qué extractor usar.
        _, extension = os.path.splitext(file_path)

        if extension.lower() == '.pdf':
            # Llama al método específico para PDF.
            self._extract_pdf_metadata(file_path)
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
        Descarga un archivo desde una URL.

        Args:
            url (str): La URL del archivo a descargar.
            extract_metadata (bool): Si es True, intentará extraer metadatos después de la descarga.
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
        Método de conveniencia que actúa como un alias para `descargar_archivo`.
        Simplifica las llamadas desde otras partes del código que solo necesitan descargar un archivo.
        """
        self.descargar_archivo(url, extract_metadata)
