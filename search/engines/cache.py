"""
search/engines/cache.py — Search-result cache (persistent SQLite backend).

This module preserves the historical ``search_cache`` API so the three
engines (DDG, Brave, Google) don't need to be touched. Under the hood
everything is now routed through :class:`core.cache.SQLiteCache`, which
adds:

  - Persistence across sessions (no more cold-start every CLI invocation)
  - TTL eviction (default 24h for the ``search`` namespace)
  - Shared storage with WHOIS / DNS / HTTP / Wayback caches under one DB
"""

from core.cache import get_cache


_NAMESPACE = "search"


class _SearchCacheShim:
    """Backwards-compatible facade matching the old in-memory ``search_cache``."""

    @staticmethod
    def make_key(engine: str, query: str, **kwargs) -> str:
        """
        Builds a canonical cache key from search parameters.

        Example:
            make_key("google", "site:example.com pdf", pages=2, lang="lang_en")
            -> "google|site:example.com pdf|lang=lang_en|pages=2"
        """
        extras = "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"{engine.lower()}|{query.strip()}|{extras}"

    def get(self, key: str):
        return get_cache().get(_NAMESPACE, key)

    def set(self, key: str, value) -> None:
        get_cache().set(_NAMESPACE, key, value)

    def invalidate(self, key: str) -> None:
        get_cache().invalidate(_NAMESPACE, key)

    def clear(self) -> int:
        return get_cache().clear(_NAMESPACE)

    @property
    def stats(self) -> dict:
        return get_cache().stats()


search_cache = _SearchCacheShim()
