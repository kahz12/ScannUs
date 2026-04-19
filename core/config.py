import os
from dotenv import load_dotenv, set_key
from cli.ui import console, THEME, print_success, print_section

# Base Output Paths Definition
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

DIR_CASES       = os.path.join(OUTPUT_DIR, "cases")
DIR_DOWNLOADS   = os.path.join(OUTPUT_DIR, "downloads")
DIR_MEDIA       = os.path.join(OUTPUT_DIR, "media")
DIR_REPORTS     = os.path.join(OUTPUT_DIR, "reports")
DIR_SCREENSHOTS = os.path.join(OUTPUT_DIR, "screenshots")
DIR_GRAPHS      = os.path.join(OUTPUT_DIR, "graphs")


def init_directories():
    """
    Verifies and creates the required directory scaffold for application output.
    Silently succeeds if dirs exist; reports any permission errors.
    """
    for directory in [OUTPUT_DIR, DIR_CASES, DIR_DOWNLOADS,
                      DIR_MEDIA, DIR_REPORTS, DIR_SCREENSHOTS, DIR_GRAPHS]:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except Exception as e:
                console.print(f"  [{THEME['ERROR']}]✘[/]  Cannot create {directory}: {e}")


def load_environment():
    """
    Loads runtime config from .env into the OS environment namespace.
    Returns the primary Gemini key as a readiness signal (None if absent).
    """
    load_dotenv()
    return os.getenv("GOOGLE_API_KEY_FOR_GEMINI")


def _prompt(label: str, hint: str = "") -> str:
    """Styled credential prompt with optional hint line."""
    if hint:
        console.print(f"  [{THEME['DIM']}]{hint}[/]")
    return console.input(f"  [{THEME['INPUT']}]❯[/] {label}: ").strip()


def env_config():
    """
    Interactive TUI wizard to capture and persist API credentials to `.env`.
    """
    print_section("Google Custom Search API")
    api_key_search = _prompt("Google Custom Search API KEY",
                             "Required for Google engine searches")
    engine_id      = _prompt("Search Engine ID (CX)",
                             "From console.developers.google.com")
    set_key(".env", "API_KEY_GOOGLE", api_key_search)
    set_key(".env", "SEARCH_ENGINE_ID", engine_id)
    if api_key_search:
        print_success("Google Search credentials saved.")

    print_section("Google AI (Gemini)")
    api_key_gemini = _prompt("Google AI Studio API KEY",
                             "From aistudio.google.com — needed for AI features")
    set_key(".env", "GOOGLE_API_KEY_FOR_GEMINI", api_key_gemini)
    os.environ["GOOGLE_API_KEY_FOR_GEMINI"] = api_key_gemini
    if api_key_gemini:
        print_success("Gemini API Key updated in the current session.")

    print_section("Brave Search API")
    api_key_brave = _prompt("Brave Search API KEY",
                            "From api.search.brave.com — optional")
    set_key(".env", "BRAVE_API_KEY", api_key_brave)
    os.environ["BRAVE_API_KEY"] = api_key_brave
    if api_key_brave:
        print_success("Brave API Key saved.")


def openai_config():
    """
    Isolated wizard for OpenAI platform credential capture.
    """
    print_section("OpenAI Configuration")
    api_key = _prompt("OpenAI API KEY", "From platform.openai.com")
    set_key(".env", "OPENAI_API_KEY", api_key)
    os.environ["OPENAI_API_KEY"] = api_key
    if api_key:
        print_success("OpenAI API Key saved.")
