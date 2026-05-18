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
DIR_CACHE       = os.path.join(OUTPUT_DIR, "cache")


def init_directories():
    """
    Verifies and creates the required directory scaffold for application output.
    Silently succeeds if dirs exist; reports any permission errors.
    """
    for directory in [OUTPUT_DIR, DIR_CASES, DIR_DOWNLOADS,
                      DIR_MEDIA, DIR_REPORTS, DIR_SCREENSHOTS, DIR_GRAPHS,
                      DIR_CACHE]:
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

    print_section("Have I Been Pwned (HIBP)")
    api_key_hibp = _prompt("HIBP API KEY",
                           "From haveibeenpwned.com/API/Key — paid, optional. "
                           "Without it, only the free domain/breach catalog "
                           "and Pwned Passwords endpoints work.")
    set_key(".env", "HIBP_API_KEY", api_key_hibp)
    os.environ["HIBP_API_KEY"] = api_key_hibp
    if api_key_hibp:
        print_success("HIBP API Key saved.")

    print_section("Anthropic Claude")
    api_key_anthropic = _prompt("Anthropic API KEY",
                                "From console.anthropic.com — optional, for Claude")
    set_key(".env", "ANTHROPIC_API_KEY", api_key_anthropic)
    os.environ["ANTHROPIC_API_KEY"] = api_key_anthropic
    if api_key_anthropic:
        print_success("Anthropic API Key saved.")

    print_section("Ollama (local LLM)")
    ollama_host = _prompt("Ollama host URL",
                          "Default: http://localhost:11434 — leave blank to keep default")
    ollama_model = _prompt("Default Ollama model",
                           "Default: llama3 — must already be pulled with `ollama pull`")
    if ollama_host:
        set_key(".env", "OLLAMA_HOST", ollama_host)
        os.environ["OLLAMA_HOST"] = ollama_host
        print_success("Ollama host saved.")
    if ollama_model:
        set_key(".env", "OLLAMA_MODEL", ollama_model)
        os.environ["OLLAMA_MODEL"] = ollama_model
        print_success("Ollama default model saved.")


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
