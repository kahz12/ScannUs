import requests
import json
import os

class BraveSearch:
    """
    Clase para realizar búsquedas utilizando la API de Brave Search.
    Requiere una API Key válida.
    """

    def __init__(self, api_key):
        """
        Inicializa la instancia de BraveSearch.

        Args:
            api_key (str): Tu clave de API de Brave Search.
        """
        self.api_key = api_key
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    def search(self, query, pages=1):
        """
        Realiza una búsqueda en Brave Search.

        Args:
            query (str): La consulta de búsqueda.
            pages (int): Número de páginas de resultados (Brave permite hasta 20 resultados por request, 
                         pero paginación compleja. Simplificaremos a iterar offset).

        Returns:
            list: Lista de diccionarios con resultados (title, description, link).
        """
        final_results = []
        # La API de Brave Search por defecto devuelve 20 resultados dependiendo del plan,
        # pero el parámetro 'count' máximo es 20.
        count = 20
        
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key
        }

        for page in range(pages):
            # La API de Brave usa paginación basada en offset (0, 1, 2...).
            # El parámetro 'offset' indica el número de página de resultados a saltar (no la cantidad de ítems).
            # Por ejemplo: página 1 -> offset=0, página 2 -> offset=1.
            # Nota: El límite máximo de offset suele ser 9 en los planes estándar.
            
            params = {
                "q": query,
                "count": count,
                "offset": page # 0 para la primera página, 1 para la segunda...
            }
            
            try:
                response = requests.get(self.base_url, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                # Estructura de la respuesta de Brave:
                # { "web": { "results": [ ... ] } }
                
                web_results = data.get("web", {}).get("results", [])
                
                for result in web_results:
                    # Claves de los resultados de Brave: 'title', 'url' (enlace), 'description'
                    final_results.append({
                        "title": result.get("title"),
                        "description": result.get("description"),
                        "link": result.get("url")
                    })
                    
            except Exception as e:
                print(f"Error en búsqueda con Brave (página {page+1}): {e}")
                break
                
        return final_results
