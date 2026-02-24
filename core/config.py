import os
from dotenv import load_dotenv, set_key
from cli.ui import console

# Base Output Paths Definition
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

DIR_CASES = os.path.join(OUTPUT_DIR, "cases")
DIR_DOWNLOADS = os.path.join(OUTPUT_DIR, "downloads")
DIR_MEDIA = os.path.join(OUTPUT_DIR, "media")
DIR_REPORTS = os.path.join(OUTPUT_DIR, "reports")
DIR_SCREENSHOTS = os.path.join(OUTPUT_DIR, "screenshots")
DIR_GRAPHS = os.path.join(OUTPUT_DIR, "graphs")

def init_directories():
    """
    Verifies and creates the necessary directory structure for unified application output.
    """
    directorios = [
        OUTPUT_DIR,
        DIR_CASES,
        DIR_DOWNLOADS,
        DIR_MEDIA,
        DIR_REPORTS,
        DIR_SCREENSHOTS,
        DIR_GRAPHS
    ]
    
    for directorio in directorios:
        if not os.path.exists(directorio):
            try:
                os.makedirs(directorio)
            except Exception as e:
                console.print(f"[bold red]Error creando el directorio {directorio}:[/bold red] {e}")
def load_environment():
    load_dotenv()
    return os.getenv("GOOGLE_API_KEY_FOR_GEMINI")

def env_config():
    print("--- Configuración de Google Search API ---")
    api_key_search = input("Ingresa tu API KEY de Google Custom Search: ").strip()
    engine_id = input("Ingresa tu ID del motor de búsqueda (CX): ").strip()
    set_key(".env", "API_KEY_GOOGLE", api_key_search)
    set_key(".env", "SEARCH_ENGINE_ID", engine_id)
    
    print("\n--- Configuración de Google AI (Gemini) ---")
    api_key_gemini = input("Ingresa tu API KEY de Google AI Studio (para Gemini): ").strip()
    set_key(".env", "GOOGLE_API_KEY_FOR_GEMINI", api_key_gemini)
    
    os.environ["GOOGLE_API_KEY_FOR_GEMINI"] = api_key_gemini
    if api_key_gemini:
        console.print("[green]Clave de API de Gemini actualizada en el entorno.[/green]")

    print("\n--- Configuración de Brave Search API ---")
    api_key_brave = input("Ingresa tu API KEY de Brave Search: ").strip()
    set_key(".env", "BRAVE_API_KEY", api_key_brave)
    os.environ["BRAVE_API_KEY"] = api_key_brave

def openai_config():
    print("\n--- Configuración de OpenAI ---")
    api_key = input("Ingresa tu API KEY de OpenAI: ").strip()
    set_key(".env", "OPENAI_API_KEY", api_key)
    os.environ["OPENAI_API_KEY"] = api_key
