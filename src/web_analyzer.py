# Importaciones de bibliotecas estándar y de terceros
import requests  # Para realizar peticiones HTTP y obtener el contenido de las páginas web.
from bs4 import BeautifulSoup  # Para analizar (parsear) el HTML y extraer información.
from ai_agent import IAAgent, GeminiGenerator  # Importa las clases para interactuar con la IA.

def get_text_from_url(url):
    """
    Extrae y limpia el contenido de texto de una página web.

    Esta función realiza una petición GET a la URL especificada, analiza el HTML resultante,
    elimina las etiquetas de script y estilo que no contienen texto visible para el usuario,
    y finalmente limpia el texto restante para devolver una versión legible.

    Args:
        url (str): La URL de la página web de la que se extraerá el texto.

    Returns:
        str: Una cadena de texto limpia y legible extraída de la página.
             Retorna None si ocurre un error durante la petición o el procesamiento.
    """
    try:
        # Realiza la petición GET a la URL, con un timeout para evitar esperas indefinidas.
        response = requests.get(url, timeout=15)
        # Lanza una excepción si el código de estado de la respuesta es un error (ej. 404, 500).
        response.raise_for_status()
        
        # Analiza el contenido HTML de la respuesta usando BeautifulSoup.
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Elimina todas las etiquetas <script> y <style> del árbol HTML.
        # Esto es crucial para limpiar el contenido y obtener solo el texto principal,
        # evitando procesar código JavaScript o reglas CSS.
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
            
        # Extrae todo el texto del HTML ya limpio.
        text = soup.get_text()
        
        # Procesa el texto para mejorar su legibilidad:
        # 1. Divide el texto en líneas y elimina espacios en blanco al inicio y al final de cada una.
        lines = (line.strip() for line in text.splitlines())
        # 2. Divide cada línea en frases (usando "  " como separador) y elimina espacios.
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # 3. Une todas las frases que no estén vacías con saltos de línea.
        clean_text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return clean_text
    except requests.exceptions.RequestException as e:
        # Maneja errores específicos de la red (problemas de conexión, timeouts, etc.).
        print(f"  Error de red al acceder a la página: {e}")
        return None
    except Exception as e:
        # Captura cualquier otro error inesperado durante el proceso.
        print(f"  Ocurrió un error inesperado al procesar la URL: {e}")
        return None

def summarize_text_with_ia(text, ia_agent):
    """
    Utiliza un agente de Inteligencia Artificial (IA) para generar un resumen de un texto.

    Args:
        text (str): El texto que se desea resumir.
        ia_agent (IAAgent): Una instancia del agente de IA configurado (ej. con Gemini).

    Returns:
        str: El resumen generado por la IA. Si falla, devuelve un mensaje de error.
    """
    if not text:
        return "No se proporcionó texto para resumir."

    # Limita la longitud del texto para no exceder los límites de la API del modelo de IA.
    # Esto previene errores y controla los costos de la API.
    max_length = 4000
    if len(text) > max_length:
        text = text[:max_length]

    # Construye el "prompt" que se enviará al modelo de IA.
    # Un prompt bien definido es clave para obtener una respuesta de alta calidad.
    prompt = f"Por favor, resume el siguiente texto extraído de una página web:\n\n---\n{text}\n---"
    
    try:
        # Llama al método `generate` del generador de IA (ej. GeminiGenerator)
        # que está contenido dentro del `ia_agent`.
        summary = ia_agent.generator.generate(prompt)
        return summary if summary else "No se pudo generar un resumen."
    except Exception as e:
        # Captura cualquier error que pueda ocurrir durante la comunicación con la API de la IA.
        return f"Error al generar el resumen con IA: {e}"

# --- Bloque de Ejecución de Ejemplo ---
if __name__ == '__main__':
    """
    Este bloque se ejecuta solo si el script es invocado directamente.
    Sirve como una demostración de uso y una prueba rápida de las funcionalidades del módulo.
    """
    # URL de ejemplo para la prueba.
    test_url = "https://www.xataka.com/robotica-e-ia/gemini-1-5-pro-probamos-brutal-ia-google-que-analiza-documentos-videos-codigo-da-sopas-chatgpt-4"
    
    print(f"--- Obteniendo texto de: {test_url} ---")
    page_text = get_text_from_url(test_url)
    
    if page_text:
        print("\n--- Texto extraído (primeros 500 caracteres) ---")
        print(page_text[:500])
        
        print("\n--- Generando resumen con IA (Gemini) ---")
        # Este bloque intenta cargar las dependencias y la configuración necesarias
        # para instanciar el agente de IA y generar un resumen.
        try:
            from dotenv import load_dotenv
            import os
            from google import genai

            load_dotenv() # Carga las variables de entorno (ej. la clave de API).
            GOOGLE_API_KEY_FOR_GEMINI = os.getenv("GOOGLE_API_KEY_FOR_GEMINI")
            
            if GOOGLE_API_KEY_FOR_GEMINI:
                # Si la clave de API está disponible, configura el cliente de Gemini.
                # (GeminiGenerator ahora maneja la inicialización del cliente con la clave)
                pass
                # Crea las instancias del generador y del agente.
                gemini_gen = GeminiGenerator()
                agent = IAAgent(gemini_gen)
                # Llama a la función de resumen.
                resumen = summarize_text_with_ia(page_text, agent)
                print("\n--- Resumen de la página ---")
                print(resumen)
            else:
                # Advierte al usuario si la clave de API no está configurada.
                print("\nAdvertencia: La clave GOOGLE_API_KEY_FOR_GEMINI no está configurada en .env.")
                print("No se puede generar el resumen.")

        except ImportError:
            print("\nAdvertencia: Faltan dependencias para ejecutar el ejemplo completo (dotenv, google-generativeai).")
        except Exception as e:
            print(f"\nError durante el ejemplo de resumen: {e}")
