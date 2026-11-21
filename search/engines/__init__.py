"""Web search engines. DuckDuckGo needs no key; Brave, Tavily and Exa need an API key."""

import os

SEARCH_ENGINES = ("duckduckgo", "brave", "tavily", "exa")

# Engines that need a key, in the order a blocked DuckDuckGo search tries them.
API_KEY_VARS = {
    "brave":  "BRAVE_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "exa":    "EXA_API_KEY",
}

# Engines that rejected their key or ran out of credit in this process, with
# the reason. They stay out of the fallback order and of the planner's list
# until the program restarts, since neither condition clears mid-session.
_UNAVAILABLE: dict[str, str] = {}


class EngineUnavailableError(RuntimeError):
    """The engine refused the request for a reason a retry cannot change."""


def mark_unavailable(engine: str, reason: str) -> None:
    """Records that *engine* cannot serve searches for the rest of the session."""
    _UNAVAILABLE[engine] = reason


def unavailable_engines() -> dict[str, str]:
    """Engines marked unusable in this session, mapped to the reason."""
    return dict(_UNAVAILABLE)


def available_engines() -> list[str]:
    """
    Engines that can take a search now: DuckDuckGo, plus every key-based engine
    whose key is set and that has not been marked unavailable.
    """
    return [
        name for name in SEARCH_ENGINES
        if name not in _UNAVAILABLE
        and (name not in API_KEY_VARS or os.getenv(API_KEY_VARS[name]))
    ]
