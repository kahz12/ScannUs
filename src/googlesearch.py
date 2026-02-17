# -*- coding: utf-8 -*-

# Importa la biblioteca `requests` para realizar peticiones HTTP a la API de Google.
import requests

class GoogleSearch:
    """
    Clase que encapsula la lógica para interactuar con la API de Búsqueda Personalizada de Google.
    Permite realizar búsquedas automatizadas, manejar la paginación y formatear los resultados.
    """

    def __init__(self, api_key, engine_id):
        """
        Inicializa una nueva instancia de GoogleSearch.

        Args:
            api_key (str): Tu clave de API de Google, necesaria para autenticar las peticiones.
            engine_id (str): El ID de tu motor de búsqueda personalizado (conocido como CX).
                             Este ID le dice a Google qué configuración de búsqueda utilizar.
        """
        self.api_key = api_key
        self.engine_id = engine_id

    def search(self, query, start_page=1, pages=1, lang="lang_es"):
        """
        Realiza una búsqueda en Google utilizando los parámetros proporcionados y maneja la paginación.

        Args:
            query (str): La consulta o "dork" de búsqueda que se enviará a Google.
            start_page (int): La página de resultados por la que empezar (por defecto es 1).
            pages (int): El número total de páginas de resultados a obtener (por defecto es 1).
                         Cada página contiene hasta 10 resultados.
            lang (str): El código de idioma para los resultados de la búsqueda.
                        Por defecto es "lang_es" para español.

        Returns:
            list: Una lista de diccionarios, donde cada diccionario representa un resultado
                  de búsqueda formateado con título, descripción y enlace.

        Raises:
            Exception: Si ocurre un error de red, un error HTTP (como 4xx o 5xx),
                       o un error al decodificar la respuesta JSON.
        """
        final_results = []  # Lista para acumular los resultados de todas las páginas solicitadas.
        results_per_page = 10  # La API de Google devuelve un máximo de 10 resultados por página.

        # Itera sobre el número de páginas que el usuario desea obtener.
        for page in range(pages):
            # Calcula el índice de inicio (`start`) para la paginación de la API de Google.
            # La API usa un índice basado en 1, no en 0.
            # Ejemplo: para la página 1, start=1; para la página 2, start=11; para la página 3, start=21.
            start_index = (start_page - 1) * results_per_page + 1 + (page * results_per_page)
            
            # Construye la URL de la API con todos los parámetros necesarios.
            url = f"https://www.googleapis.com/customsearch/v1?key={self.api_key}&cx={self.engine_id}&q={query}&start={start_index}&lr={lang}"
            
            try:
                # Realiza la petición GET a la API de Google con un tiempo de espera para evitar bloqueos.
                response = requests.get(url, timeout=10)
                # Lanza una excepción si la respuesta tiene un código de estado de error (ej. 403 Forbidden, 404 Not Found).
                response.raise_for_status()
                # Decodifica la respuesta JSON en un diccionario de Python.
                data = response.json()
                # Extrae la lista de resultados ('items') del JSON. Si no existe, devuelve una lista vacía.
                results = data.get("items", [])
                # Formatea los resultados para extraer solo la información relevante.
                cresults = self.custom_results(results)
                # Añade los resultados formateados de la página actual a la lista final.
                final_results.extend(cresults)
            except requests.exceptions.RequestException as e:
                # Maneja errores de red (ej. problemas de DNS, conexión rechazada).
                error_msg = f"Error de red o HTTP al obtener la página {page + 1}: {e}"
                print(error_msg)
                raise Exception(error_msg)
            except ValueError as e:  # Atrapa errores de decodificación de JSON.
                error_msg = f"Error al decodificar JSON de la página {page + 1}: {e}"
                print(error_msg)
                raise Exception(error_msg)
                
        return final_results

    def custom_results(self, results):
        """
        Formatea una lista de resultados crudos de la API para extraer solo los campos de interés.

        Args:
            results (list): La lista de 'items' devuelta por la API de Google.

        Returns:
            list: Una lista de diccionarios, cada uno con las claves "title", "description" y "link".
        """
        custom_results = []
        # Itera sobre cada resultado de la búsqueda.
        for result in results:
            # Crea un diccionario con la información clave de cada resultado.
            # `result.get(key, default_value)` se usa para evitar errores si una clave no está presente en la respuesta.
            cresult = {
                "title": result.get("title"),
                "description": result.get("snippet"),  # 'snippet' es el campo de descripción en la API de Google.
                "link": result.get("link")
            }
            custom_results.append(cresult)
        return custom_results