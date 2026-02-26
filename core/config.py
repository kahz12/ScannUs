import os
from dotenv import load_dotenv, set_key
from cli.ui import console

# Base Output Paths Definition
# Establishes the core directory scaffolding mapped dynamically from this file's path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

# Discrete output destinations by operation type
DIR_CASES = os.path.join(OUTPUT_DIR, "cases")
DIR_DOWNLOADS = os.path.join(OUTPUT_DIR, "downloads")
DIR_MEDIA = os.path.join(OUTPUT_DIR, "media")
DIR_REPORTS = os.path.join(OUTPUT_DIR, "reports")
DIR_SCREENSHOTS = os.path.join(OUTPUT_DIR, "screenshots")
DIR_GRAPHS = os.path.join(OUTPUT_DIR, "graphs")

def init_directories():
    """
    Verifies and creates the necessary directory structure for unified application output.
    Silently passes if directories exist, catches and reports localized permission errors.
    """
    directories = [
        OUTPUT_DIR,
        DIR_CASES,
        DIR_DOWNLOADS,
        DIR_MEDIA,
        DIR_REPORTS,
        DIR_SCREENSHOTS,
        DIR_GRAPHS
    ]
    
    for directory in directories:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except Exception as e:
                console.print(f"[bold red]Error creating directory {directory}:[/bold red] {e}")

def load_environment():
    """
    Loads runtime configs from the local .env into system OS environment namespace.
    Returns the primary Gemini AI key as a readiness signal.
    """
    load_dotenv()
    return os.getenv("GOOGLE_API_KEY_FOR_GEMINI")

def env_config():
    """
    Interactive TUI sequence to capture and persist system-wide API credentials 
    to the `.env` configuration file securely.
    """
    print("--- Google Search API Configuration ---")
    api_key_search = input("Enter your Google Custom Search API KEY: ").strip()
    engine_id = input("Enter your Search Engine ID (CX): ").strip()
    set_key(".env", "API_KEY_GOOGLE", api_key_search)
    set_key(".env", "SEARCH_ENGINE_ID", engine_id)
    
    print("\n--- Google AI (Gemini) Configuration ---")
    api_key_gemini = input("Enter your Google AI Studio API KEY (for Gemini): ").strip()
    set_key(".env", "GOOGLE_API_KEY_FOR_GEMINI", api_key_gemini)
    
    # Mirror locally into current runtime immediately to avoid requiring a restart
    os.environ["GOOGLE_API_KEY_FOR_GEMINI"] = api_key_gemini
    if api_key_gemini:
        console.print("[green]Gemini API Key updated in the current environment.[/green]")

    print("\n--- Brave Search API Configuration ---")
    api_key_brave = input("Enter your Brave Search API KEY: ").strip()
    set_key(".env", "BRAVE_API_KEY", api_key_brave)
    os.environ["BRAVE_API_KEY"] = api_key_brave

def openai_config():
    """
    Interactive TUI sequence specifically isolated for capturing OpenAI platform keys.
    """
    print("\n--- OpenAI Configuration ---")
    api_key = input("Enter your OpenAI API KEY: ").strip()
    set_key(".env", "OPENAI_API_KEY", api_key)
    os.environ["OPENAI_API_KEY"] = api_key
