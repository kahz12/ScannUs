import os
from dotenv import load_dotenv, set_key
from cli.ui import console, THEME, print_success, print_section, print_warn

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
DIR_LOGS        = os.path.join(OUTPUT_DIR, "logs")


def _make_private(path: str, mode: int) -> bool:
    """Limits a path to the current user. Returns False when the system refuses."""
    try:
        os.chmod(path, mode)
    except OSError:
        return False
    return True


def init_directories():
    """
    Verifies and creates the required directory scaffold for application output.
    Silently succeeds if dirs exist; reports any permission problems.

    Reports, exports, the cache and the logs hold investigation data, so these
    folders and every file this run creates are limited to the current user.
    Older files keep their own mode, and the folder keeps others away from them.
    """
    os.umask(0o077)
    private = True
    for directory in [OUTPUT_DIR, DIR_CASES, DIR_DOWNLOADS,
                      DIR_MEDIA, DIR_REPORTS, DIR_SCREENSHOTS, DIR_GRAPHS,
                      DIR_CACHE, DIR_LOGS]:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except Exception as e:
                console.print(f"  [{THEME['ERROR']}]✘[/]  Cannot create {directory}: {e}")
                continue
        private = _make_private(directory, 0o700) and private
    if not private:
        print_warn(f"Could not limit {OUTPUT_DIR} to your user, so others may read it.")


def load_environment():
    """
    Loads runtime config from .env into the OS environment namespace.
    Returns the primary Gemini key as a readiness signal (None if absent).

    A .env copied by hand from the template starts readable by other users,
    so it is limited to the current user before it is used.
    """
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        _make_private(env_path, 0o600)
    load_dotenv()
    return os.getenv("GOOGLE_API_KEY_FOR_GEMINI")


def _prompt(label: str, hint: str = "") -> str:
    """Styled credential prompt with optional hint line."""
    if hint:
        console.print(f"  [{THEME['DIM']}]{hint}[/]")
    return console.input(f"  [{THEME['INPUT']}]❯[/] {label}: ").strip()


def _save_key(name: str, value: str) -> bool:
    """
    Stores a value in `.env` and in the running session.

    A blank answer saves nothing, so pressing Enter keeps the stored value.
    Returns True when the value was saved.
    """
    if not value:
        return False
    set_key(".env", name, value)
    os.environ[name] = value
    _make_private(".env", 0o600)
    return True


def env_config():
    """
    Interactive TUI wizard to capture and persist API credentials to `.env`.
    """
    print_section("Google AI (Gemini)")
    if _save_key("GOOGLE_API_KEY_FOR_GEMINI",
                 _prompt("Google AI Studio API KEY",
                         "From aistudio.google.com — needed for AI features")):
        print_success("Gemini API Key updated in the current session.")

    print_section("Brave Search API")
    if _save_key("BRAVE_API_KEY",
                 _prompt("Brave Search API KEY",
                         "From api.search.brave.com — optional, also used "
                         "when DuckDuckGo blocks a search")):
        print_success("Brave API Key saved.")

    print_section("Tavily Search API")
    if _save_key("TAVILY_API_KEY",
                 _prompt("Tavily API KEY",
                         "From app.tavily.com — optional, free monthly credits, no card")):
        print_success("Tavily API Key saved.")

    print_section("Exa Search API")
    if _save_key("EXA_API_KEY",
                 _prompt("Exa API KEY",
                         "From dashboard.exa.ai — optional, free monthly credit, no card")):
        print_success("Exa API Key saved.")

    print_section("Have I Been Pwned (HIBP)")
    if _save_key("HIBP_API_KEY",
                 _prompt("HIBP API KEY",
                         "From haveibeenpwned.com/API/Key — paid, optional. "
                         "Without it, only the free domain/breach catalog "
                         "and Pwned Passwords endpoints work.")):
        print_success("HIBP API Key saved.")

    print_section("Anthropic Claude")
    if _save_key("ANTHROPIC_API_KEY",
                 _prompt("Anthropic API KEY",
                         "From console.anthropic.com — optional, for Claude")):
        print_success("Anthropic API Key saved.")

    print_section("Ollama (local LLM)")
    ollama_host = _prompt("Ollama host URL",
                          "Default: http://localhost:11434 — leave blank to keep default")
    ollama_model = _prompt("Default Ollama model",
                           "Default: llama3 — must already be pulled with `ollama pull`")
    if _save_key("OLLAMA_HOST", ollama_host):
        print_success("Ollama host saved.")
    if _save_key("OLLAMA_MODEL", ollama_model):
        print_success("Ollama default model saved.")


def openai_config():
    """
    Isolated wizard for OpenAI platform credential capture.
    """
    print_section("OpenAI Configuration")
    if _save_key("OPENAI_API_KEY", _prompt("OpenAI API KEY", "From platform.openai.com")):
        print_success("OpenAI API Key saved.")
