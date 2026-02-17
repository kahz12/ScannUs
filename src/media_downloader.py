# Importaciones de bibliotecas estándar y de terceros
import os
import requests  # Para realizar peticiones HTTP a las URLs.
import tempfile  # Para crear directorios temporales que se limpian automáticamente.
import zipfile   # Para crear y gestionar archivos ZIP.
from urllib.parse import urljoin, urlparse  # Para construir y analizar URLs de forma robusta.
from bs4 import BeautifulSoup  # Biblioteca para extraer datos de archivos HTML y XML.
from rich.console import Console  # Para crear salidas de terminal ricas y atractivas.
from rich.progress import Progress, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn # Componentes para barras de progreso.
from rich.table import Table # Para mostrar datos en tablas bien formateadas.
from rich.box import ROUNDED # Estilo para las cajas de los paneles y tablas de rich.

# Inicializa una única instancia de la consola de `rich` para ser usada en todo el módulo.
console = Console()

def download_media_from_url(url, output_zip_path="media_download.zip", media_type='all'):
    """
    Función principal que orquesta la descarga de medios desde una página web.
    Navega a una URL, extrae enlaces de imágenes y/o videos, los descarga a un
    directorio temporal y finalmente los comprime en un archivo ZIP.

    Args:
        url (str): La URL de la página web a analizar.
        output_zip_path (str): La ruta donde se guardará el archivo ZIP final.
        media_type (str): Especifica qué tipo de medio descargar.
                          Puede ser 'images', 'videos' o 'all'.
    """
    # Define cabeceras de User-Agent para simular una petición desde un navegador web,
    # lo que puede ayudar a evitar bloqueos por parte de algunos servidores.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        # Realiza la petición GET a la URL.
        console.print(f"Accediendo a la URL: [cyan]{url}[/cyan]")
        response = requests.get(url, headers=headers, timeout=20)
        # Si la respuesta es un código de error HTTP (4xx o 5xx), lanza una excepción.
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        # Captura cualquier error relacionado con la red (DNS, conexión, timeout, etc.).
        console.print(f"[bold red]Error al acceder a la URL:[/bold red] {e}")
        return

    # Analiza el contenido HTML de la respuesta usando BeautifulSoup.
    soup = BeautifulSoup(response.text, 'html.parser')
    media_urls = []
    debug_data = [] # Lista para almacenar datos de depuración.

    # Determina qué etiquetas HTML buscar basado en el `media_type` solicitado.
    tags_to_find = []
    if media_type == 'images':
        tags_to_find = ['img']
    elif media_type == 'videos':
        tags_to_find = ['video', 'source']
    else: # 'all'
        tags_to_find = ['img', 'video', 'source']

    # Itera sobre todas las etiquetas encontradas en el HTML.
    for tag in soup.find_all(tags_to_find):
        src = tag.get('src') # Obtiene el atributo 'src' de la etiqueta.
        # Se asegura de que 'src' exista y no sea un 'data URI'.
        if src and not src.startswith('data:'):
            # Convierte la URL relativa (ej. '/images/foto.jpg') en una URL absoluta.
            absolute_url = urljoin(url, src)
            media_urls.append(absolute_url)
            # Guarda información para la tabla de depuración.
            debug_data.append({
                "tag": f"<{tag.name}>",
                "src": src,
                "absolute_url": absolute_url
            })

    # Muestra una tabla con la información de las URLs encontradas para depuración.
    table = Table(title="Análisis y Depuración de URLs", box=ROUNDED, header_style="bold blue", title_style="bold magenta")
    table.add_column("Etiqueta", style="cyan")
    table.add_column("SRC Original", style="magenta")
    table.add_column("URL Absoluta Construida", style="green")
    
    for item in debug_data:
        table.add_row(item["tag"], item["src"], item["absolute_url"])
    
    console.print(table)

    # Elimina URLs duplicadas para evitar descargar el mismo archivo varias veces.
    media_urls = list(dict.fromkeys(media_urls))

    if not media_urls:
        console.print(f"[yellow]No se encontraron {media_type} en la página.[/yellow]")
        return

    console.print(f"Se encontraron [green]{len(media_urls)}[/green] archivos de tipo '{media_type}'. Iniciando descarga...")

    # Usa un directorio temporal que se crea y se elimina de forma segura.
    with tempfile.TemporaryDirectory() as temp_dir:
        for media_url in media_urls:
            try:
                # Realiza la petición para descargar el archivo multimedia en modo 'stream'.
                media_response = requests.get(media_url, headers=headers, stream=True, timeout=20)
                media_response.raise_for_status()

                # Intenta obtener un nombre de archivo válido desde la URL.
                parsed_url = urlparse(media_url)
                file_name = os.path.basename(parsed_url.path)
                if not file_name: # Si la URL no tiene un nombre de archivo claro.
                    file_name = media_url.split('/')[-1].split('?')[0]

                # Si el archivo no tiene extensión, intenta deducirla del 'content-type'.
                if not os.path.splitext(file_name)[1]:
                    content_type = media_response.headers.get('content-type')
                    if content_type and 'image' in content_type:
                        ext = '.' + content_type.split('/')[1]
                        file_name += ext
                    else: # Si no se puede deducir, asume '.jpg' como último recurso.
                        file_name += '.jpg'

                file_path = os.path.join(temp_dir, file_name)
                
                # Obtiene el tamaño total del archivo para la barra de progreso.
                total_size = int(media_response.headers.get('content-length', 0))

                # Configura y muestra una barra de progreso para la descarga actual.
                with Progress(
                    "[progress.description]{task.description}",
                    BarColumn(),
                    "[progress.percentage]{task.percentage:>3.0f}%",
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    "ETA:", TimeRemainingColumn(),
                ) as progress:
                    task = progress.add_task(f"[cyan]Descargando {file_name[:30]}", total=total_size)
                    
                    # Escribe el contenido del archivo en fragmentos (chunks) para manejar archivos grandes.
                    with open(file_path, 'wb') as f:
                        for chunk in media_response.iter_content(chunk_size=8192):
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))

            except requests.exceptions.RequestException as e:
                console.print(f"[yellow]No se pudo descargar {media_url}:[/yellow] {e}")

        # Una vez descargados todos los archivos, los comprime en un archivo ZIP.
        console.print(f"\nComprimiendo archivos en [cyan]{output_zip_path}[/cyan]...")
        with zipfile.ZipFile(output_zip_path, 'w') as zipf:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    # Escribe cada archivo en el ZIP.
                    zipf.write(os.path.join(root, file), arcname=file)

    console.print(f"[bold green]¡Éxito! Medios descargados y guardados en {output_zip_path}[/bold green]")

def download_media(url, output_path, media_type='all'):
    """
    Función de conveniencia que sirve como punto de entrada principal para la descarga.
    Simplemente llama a la función más detallada `download_media_from_url`.
    Esto proporciona una API más simple para los módulos que la importan.
    """
    download_media_from_url(url, output_path, media_type)