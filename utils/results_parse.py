# Standard library imports
import json
import os
import csv
import openpyxl
from openpyxl.styles import Font
from rich.console import Console
from rich.table import Table
from core.config import DIR_REPORTS

class ResultsParser:
    """
    Data transformation layer for search results.
    Provides serialization and formatting logic for exporting findings into
    various report formats (HTML, JSON, CSV, Excel) and TUI-friendly tables.
    """

    def __init__(self, resultados):
        """
        Initializes the parser with a result set.

        Args:
            resultados (list): Collection of result dictionaries, each containing
                               'title', 'description', and 'link' keys.
        """
        self.resultados = resultados

    def exportar_html(self, archivo_salida):
        """
        Exports the current result set into a structured HTML report.
        Utilizes a local `html_template.html` for base styling and layout.

        Args:
            archivo_salida (str): Target filename for the HTML artifact.
        """
        archivo_salida = os.path.join(DIR_REPORTS, os.path.basename(archivo_salida))
        try:
            # Requires the companion template file in the project root.
            template_path = "html_template.html"
            
            if not os.path.exists(template_path):
                print(f"Error: HTML template '{template_path}' not found.")
                return

            with open(template_path, 'r', encoding='utf-8') as f:
                plantilla = f.read()

            # Construct dynamic HTML fragments for each record
            elementos_html = ''
            for indice, resultado in enumerate(self.resultados, start=1):
                elemento = (
                    f'<div class="resultado">'
                    f'<div class="indice">Result {indice}</div>'
                    f'<h5>{resultado.get("title", "No title")}</h5>'
                    f'<p>{resultado.get("description", "No description")}</p>'
                    f'<a href="{resultado.get("link", "#")}" target="_blank">{resultado.get("link", "No link")}</a>'
                    f'</div>'
                )
                elementos_html += elemento
            
            # Interpolate the generated fragments into the template
            informe_html = plantilla.replace('{{ resultados }}', elementos_html)
            
            # Write finalized report to disk
            with open(archivo_salida, 'w', encoding='utf-8') as f:
                f.write(informe_html)
            print(f"Results exported to HTML. File created: {archivo_salida}")
        except IOError as e:
            print(f"I/O error exporting to HTML: {e}")
        except Exception as e:
            print(f"Unexpected error exporting to HTML: {e}")

    def exportar_csv(self, archivo_salida):
        """
        Dumps the results into a flat CSV file for generic data processing.
        
        Args:
            archivo_salida (str): Target path for the CSV output.
        """
        archivo_salida = os.path.join(DIR_REPORTS, os.path.basename(archivo_salida))
        try:
            with open(archivo_salida, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # Define column headers
                writer.writerow(['ID', 'Title', 'Description', 'Link'])
                
                # Append formatted rows
                for i, r in enumerate(self.resultados, 1):
                    writer.writerow([i, r.get('title', ''), r.get('description', ''), r.get('link', '')])
            print(f"Results exported to CSV. File created: {archivo_salida}")
        except IOError as e:
            print(f"I/O error exporting to CSV: {e}")
        except Exception as e:
            print(f"Unexpected error exporting to CSV: {e}")

    def exportar_excel(self, archivo_salida):
        """
        Generates a native Excel (.xlsx) file with basic column styling.
        
        Args:
            archivo_salida (str): Target path for the Excel artifact.
        """
        archivo_salida = os.path.join(DIR_REPORTS, os.path.basename(archivo_salida))
        try:
            # Bootstrap a new openpyxl workbook context
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Results"
            
            header_font = Font(bold=True)
            
            # Setup headers
            headers = ['ID', 'Title', 'Description', 'Link']
            ws.append(headers)
            
            # Format the header row
            for cell in ws[1]:
                cell.font = header_font
            
            # Populate data rows
            for i, r in enumerate(self.resultados, 1):
                ws.append([i, r.get('title', ''), r.get('description', ''), r.get('link', '')])
            
            # Apply ergonomic column widths for immediate usability
            ws.column_dimensions['A'].width = 5
            ws.column_dimensions['B'].width = 40
            ws.column_dimensions['C'].width = 80
            ws.column_dimensions['D'].width = 60
            
            wb.save(archivo_salida)
            print(f"Results exported to Excel. File created: {archivo_salida}")
            
        except Exception as e:
            print(f"Unexpected error exporting to Excel: {e}")

    def exportar_json(self, archivo_salida):
        """
        Serializes the results list to a pretty-printed JSON file.

        Args:
            archivo_salida (str): Target path for the JSON output.
        """
        archivo_salida = os.path.join(DIR_REPORTS, os.path.basename(archivo_salida))
        try:
            with open(archivo_salida, 'w', encoding='utf-8') as f:
                # indentation enabled for human readability
                json.dump(self.resultados, f, ensure_ascii=False, indent=4)
            print(f"Results exported to JSON. File created: {archivo_salida}")
        except IOError as e:
            print(f"I/O error exporting to JSON: {e}")
        except Exception as e:
            print(f"Unexpected error exporting to JSON: {e}")

    def to_table(self):
        """
        Transforms the result set into a Rich TUI Table node.
        Used for rendering findings directly into the terminal interface.

        Returns:
            Table: An instantiated rich.table.Table object.
        """
        # Bootstrap the table layout
        table = Table(show_header=True, header_style='green')
        
        # Define the visual schema
        table.add_column("#", style="dim")  
        table.add_column("Title", width=25) 
        table.add_column("Description")     
        table.add_column("Link")          

        # Hydrate table rows with current data
        for indice, resultado in enumerate(self.resultados, start=1):
            table.add_row(
                str(indice),
                resultado.get("title", "N/A"),
                resultado.get("description", "N/A"),
                resultado.get("link", "N/A")
            )
            # Add visual padding between entries
            table.add_row("", "", "", "")

        return table
