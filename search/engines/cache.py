"""
search/engines/cache.py — Search-result cache (persistent SQLite backend).

The search engines use ``search_cache`` (get / set / make_key) to skip a
query they have already answered. It stores everything in the ``search``
namespace of :class:`core.cache.SQLiteCache`, which gives:

  - Persistence across sessions, so a repeated query costs no request
  - TTL eviction (default 24h for the ``search`` namespace)
  - Shared storage with WHOIS / DNS / HTTP / Wayback caches under one DB
"""

from core.cache import get_cache


_NAMESPACE = "search"


class _SearchCacheShim:
    """The small cache interface the search engines call, backed by core.cache."""

    @staticmethod
    def make_key(engine: str, query: str, **kwargs) -> str:
        """
        Builds a canonical cache key from search parameters.

        Example:
            make_key("brave", "site:example.com pdf", pages=2, start=1)
            -> "brave|site:example.com pdf|pages=2|start=1"
        """
        extras = "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"{engine.lower()}|{query.strip()}|{extras}"

    def get(self, key: str):
        # An empty result set is never worth reusing: it may be a stale entry
        # from a blocked or failed search, so it counts as a miss.
        return get_cache().get(_NAMESPACE, key) or None

    def set(self, key: str, value) -> None:
        if value:
            get_cache().set(_NAMESPACE, key, value)

    def invalidate(self, key: str) -> None:
        get_cache().invalidate(_NAMESPACE, key)

    def clear(self) -> int:
        return get_cache().clear(_NAMESPACE)

    @property
    def stats(self) -> dict:
        return get_cache().stats()


search_cache = _SearchCacheShim()
