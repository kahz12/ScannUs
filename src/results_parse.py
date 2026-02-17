# Importaciones de bibliotecas estándar
import json
import os
import csv
from rich.console import Console
from rich.table import Table

# Define la clase para procesar y mostrar los resultados de búsqueda.
class ResultsParser:
    """
    Clase diseñada para manejar los resultados obtenidos de una búsqueda.
    Proporciona métodos para formatear y exportar estos resultados a diferentes
    formatos, como una tabla en la consola, un archivo HTML o un archivo JSON.
    """

    def __init__(self, resultados):
        """
        Inicializa el parser con una lista de resultados.

        Args:
            resultados (list): Una lista de diccionarios. Cada diccionario representa
                               un resultado de búsqueda y debe contener claves como
                               'title', 'description' y 'link'.
        """
        self.resultados = resultados

    def exportar_html(self, archivo_salida):
        """
        Exporta los resultados de la búsqueda a un archivo HTML bien formateado.

        Este método utiliza una plantilla HTML predefinida (`html_template.html`)
        para asegurar una estructura y estilo consistentes en el informe final.

        Args:
            archivo_salida (str): La ruta y el nombre del archivo HTML a crear.
        """
        try:
            # Define la ruta a la plantilla HTML. Se asume que está en el mismo directorio.
            template_path = "html_template.html"
            # Verifica si el archivo de plantilla existe antes de proceder.
            if not os.path.exists(template_path):
                print(f"Error: La plantilla HTML '{template_path}' no se encuentra.")
                return

            # Lee el contenido de la plantilla.
            with open(template_path, 'r', encoding='utf-8') as f:
                plantilla = f.read()

            # Construye dinámicamente el contenido HTML para cada resultado.
            elementos_html = ''
            for indice, resultado in enumerate(self.resultados, start=1):
                # Crea un bloque <div> para cada resultado, incluyendo título, descripción y enlace.
                elemento = (
                    f'<div class="resultado">'
                    f'<div class="indice">Resultado {indice}</div>'
                    f'<h5>{resultado.get("title", "Sin título")}</h5>'
                    f'<p>{resultado.get("description", "Sin descripción")}</p>'
                    f'<a href="{resultado.get("link", "#")}" target="_blank">{resultado.get("link", "Sin enlace")}</a>'
                    f'</div>'
                )
                elementos_html += elemento
            
            # Reemplaza el marcador de posición '{{ resultados }}' en la plantilla con el HTML generado.
            informe_html = plantilla.replace('{{ resultados }}', elementos_html)
            
            # Escribe el informe HTML final en el archivo de salida.
            with open(archivo_salida, 'w', encoding='utf-8') as f:
                f.write(informe_html)
            print(f"Resultados exportados a HTML. Fichero creado: {archivo_salida}")
        except IOError as e:
            # Maneja errores específicos de lectura/escritura de archivos.
            print(f"Error de E/S al exportar a HTML: {e}")
        except Exception as e:
            # Captura cualquier otro error inesperado durante la exportación.
            print(f"Ocurrió un error inesperado al exportar a HTML: {e}")

    def exportar_csv(self, archivo_salida):
        """
        Exporta una lista de resultados a un archivo CSV.
        
        Args:
            archivo_salida (str): La ruta del archivo CSV a crear.
        """
        try:
            with open(archivo_salida, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['ID', 'Título', 'Descripción', 'Enlace'])
                for i, r in enumerate(self.resultados, 1):
                    writer.writerow([i, r.get('title', ''), r.get('description', ''), r.get('link', '')])
            print(f"Resultados exportados a CSV. Fichero creado: {archivo_salida}")
        except IOError as e:
            print(f"Error de E/S al exportar a CSV: {e}")
        except Exception as e:
            print(f"Ocurrió un error inesperado al exportar a CSV: {e}")

    def exportar_json(self, archivo_salida):
        """
        Exporta la lista de resultados a un archivo en formato JSON.

        Args:
            archivo_salida (str): La ruta y el nombre del archivo JSON a crear.
        """
        try:
            # Abre el archivo de salida en modo de escritura.
            with open(archivo_salida, 'w', encoding='utf-8') as f:
                # Vuelca la lista de resultados al archivo JSON.
                # `ensure_ascii=False` es importante para guardar correctamente caracteres especiales (ej. tildes, ñ).
                # `indent=4` formatea el JSON con sangría para que sea fácilmente legible por humanos.
                json.dump(self.resultados, f, ensure_ascii=False, indent=4)
            print(f"Resultados exportados a JSON. Fichero creado: {archivo_salida}")
        except IOError as e:
            # Maneja errores que puedan ocurrir al escribir en el archivo.
            print(f"Error de E/S al exportar a JSON: {e}")
        except Exception as e:
            # Captura otros errores inesperados.
            print(f"Ocurrió un error inesperado al exportar a JSON: {e}")

    def to_table(self):
        """
        Convierte la lista de resultados en una tabla formateada para la consola.

        Utiliza la biblioteca `rich` para crear una tabla visualmente atractiva y legible,
        ideal para mostrar la información directamente en la terminal.

        Returns:
            Table: Un objeto `Table` de `rich` que puede ser impreso en la consola.
        """
        # Crea una instancia de la tabla, definiendo el estilo de la cabecera.
        table = Table(show_header=True, header_style='green')
        # Define las columnas de la tabla con sus respectivos estilos y anchos.
        table.add_column("#", style="dim")  # Columna para el número de resultado.
        table.add_column("Titulo", width=25) # Columna para el título.
        table.add_column("Descripcion")     # Columna para la descripción.
        table.add_column("Enlace")          # Columna para el enlace.

        # Itera sobre la lista de resultados para poblar la tabla.
        for indice, resultado in enumerate(self.resultados, start=1):
            # Añade una fila a la tabla con los datos de cada resultado.
            # `resultado.get("clave", "N/A")` se usa para evitar errores si una clave no existe.
            table.add_row(
                str(indice),
                resultado.get("title", "N/A"),
                resultado.get("description", "N/A"),
                resultado.get("link", "N/A")
            )
            # Añade una fila vacía como separador para mejorar la legibilidad entre resultados.
            table.add_row("", "", "", "")

        return table