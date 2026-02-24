# Standard library imports
import json
import os
import csv
import openpyxl
from openpyxl.styles import Font
from rich.console import Console
from rich.table import Table
from core.config import DIR_REPORTS

# Defines the class to process and display search results.
class ResultsParser:
    """
    Class designed to handle search results.
    Provides methods to format and export these results to different
    formats, such as a table in the console, an HTML file, or a JSON file.
    """

    def __init__(self, resultados):
        """
        Initializes the parser with a list of results.

        Args:
            resultados (list): A list of dictionaries. Each dictionary represents
                               a search result and must contain keys like
                               'title', 'description' and 'link'.
        """
        self.resultados = resultados

    def exportar_html(self, archivo_salida):
        """
        Exports search results to a well-formatted HTML file.

        This method uses a predefined HTML template (`html_template.html`)
        to ensure consistent structure and styling in the final report.

        Args:
            archivo_salida (str): The path and name of the HTML file to create.
        """
        archivo_salida = os.path.join(DIR_REPORTS, os.path.basename(archivo_salida))
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
        Exports a list of results to a CSV file.
        
        Args:
            archivo_salida (str): The path to the CSV file to create.
        """
        archivo_salida = os.path.join(DIR_REPORTS, os.path.basename(archivo_salida))
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

    def exportar_excel(self, archivo_salida):
        """
        Exports a list of results to an Excel file (.xlsx).
        
        Args:
            archivo_salida (str): The path to the Excel file to create.
        """
        archivo_salida = os.path.join(DIR_REPORTS, os.path.basename(archivo_salida))
        try:
            # Crear un libro de trabajo y seleccionar la hoja activa
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Resultados"
            
            # Definir estilos
            header_font = Font(bold=True)
            
            # Escribir cabecera
            headers = ['ID', 'Título', 'Descripción', 'Enlace']
            ws.append(headers)
            
            for cell in ws[1]:
                cell.font = header_font
            
            # Escribir datos
            for i, r in enumerate(self.resultados, 1):
                ws.append([i, r.get('title', ''), r.get('description', ''), r.get('link', '')])
            
            # Ajustar anchos básicos
            ws.column_dimensions['A'].width = 5
            ws.column_dimensions['B'].width = 40
            ws.column_dimensions['C'].width = 80
            ws.column_dimensions['D'].width = 60
            
            # Guardar archivo
            wb.save(archivo_salida)
            print(f"Resultados exportados a Excel. Fichero creado: {archivo_salida}")
            
        except Exception as e:
            print(f"Ocurrió un error inesperado al exportar a Excel: {e}")

    def exportar_json(self, archivo_salida):
        """
        Exports the list of results to a JSON formatted file.

        Args:
            archivo_salida (str): The path and name of the JSON file to create.
        """
        archivo_salida = os.path.join(DIR_REPORTS, os.path.basename(archivo_salida))
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
        Converts the list of results into a formatted table for the console.

        Uses the `rich` library to create a visually appealing and readable table,
        ideal for displaying information directly in the terminal.

        Returns:
            Table: A `rich` `Table` object that can be printed to the console.
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