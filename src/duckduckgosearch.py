# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote

class DuckDuckGoSearch:
    """
    Clase para realizar búsquedas y extraer resultados de DuckDuckGo
    mediante web scraping de su versión HTML.
    """

    def __init__(self):
        """
        Inicializa el buscador de DuckDuckGo.
        """
        self.base_url = "https://html.duckduckgo.com/html/"

    def search(self, query, pages=1):
        """
        Realiza una búsqueda en DuckDuckGo.

        Args:
            query (str): La consulta de búsqueda.
            pages (int): DuckDuckGo (HTML version) no tiene una paginación tradicional, 
                         por lo que este parámetro se ignora, pero se mantiene por compatibilidad.

        Returns:
            list: Una lista de diccionarios con los resultados (título, descripción, enlace).
        """
        final_results = []
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        
        params = {
            'q': query
        }

        try:
            response = requests.post(self.base_url, headers=headers, data=params, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Encuentra todos los contenedores de resultados
            results_container = soup.find_all('div', {'class': 'result'})

            for container in results_container:
                title_element = container.find('h2', {'class': 'result__title'})
                link_element = container.find('a', {'class': 'result__a'})
                snippet_element = container.find('a', {'class': 'result__snippet'})

                if title_element and link_element and snippet_element:
                    title = title_element.get_text(strip=True)
                    
                    # El enlace en DDG está en formato /url?q=URL&...
                    raw_link = link_element['href']
                    # Extraer la URL real del parámetro 'q'
                    parsed_link = self.clean_link(raw_link)
                    
                    snippet = snippet_element.get_text(strip=True)

                    if title and parsed_link and snippet:
                        final_results.append({
                            "title": title,
                            "description": snippet,
                            "link": parsed_link
                        })

        except requests.exceptions.RequestException as e:
            print(f"Error de red al buscar en DuckDuckGo: {e}")
        except Exception as e:
            print(f"Ocurrió un error inesperado al procesar DuckDuckGo: {e}")
            
        return final_results

    def clean_link(self, raw_link):
        """
        Limpia el enlace de redirección de DuckDuckGo para obtener la URL de destino final.
        Ejemplo: /l/?kh=-1&uddg=https%3A%2F%2Fwww.ejemplo.com
        """
        if raw_link.startswith("/l/"):
            # Busca el parámetro 'uddg=' que contiene la URL real
            param = 'uddg='
            try:
                start_index = raw_link.index(param) + len(param)
                # Decodifica la URL (ej. %3A -> :)
                url = unquote(raw_link[start_index:])
                return url
            except ValueError:
                return None # Si no se encuentra 'uddg='
        return raw_link


if __name__ == '__main__':
    # Ejemplo de uso
    ddg = DuckDuckGoSearch()
    search_results = ddg.search("python web scraping")
    if search_results:
        for i, res in enumerate(search_results, 1):
            print(f"--- Resultado {i} ---")
            print(f"Título: {res['title']}")
            print(f"Descripción: {res['description']}")
            print(f"Enlace: {res['link']}")
            print()
    else:
        print("No se encontraron resultados.")
