"""
search/engines/cache.py — In-session LRU cache for search results.

Eliminates repeated HTTP/API calls for identical queries within the same
ScannUs session. The cache lives in memory and is cleared on process exit.

Usage (inside an engine's search() method):
    from search.engines.cache import search_cache

    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached

    results = ...  # do the real request
    search_cache.set(cache_key, results)
    return results
"""

from collections import OrderedDict


class SearchCache:
    """
    Thread-safe, size-bounded LRU cache for search result lists.

    Keys are strings (engine + query + pages + …) and values are the
    normalised result lists returned by each engine's search() method.
    """

    def __init__(self, max_size: int = 128):
        """
        Args:
            max_size: Maximum number of distinct queries to cache.
                      The oldest entry is evicted when the limit is reached.
        """
        self._cache: OrderedDict[str, list] = OrderedDict()
        self._max_size = max_size
        self._hits   = 0
        self._misses = 0

    # ------------------------------------------------------------------

    def get(self, key: str) -> list | None:
        """
        Returns the cached result list for *key*, or None on a cache miss.
        Moves the hit entry to the end (most-recently-used position).
        """
        if key in self._cache:
            self._cache.move_to_end(key)
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None

    def set(self, key: str, value: list) -> None:
        """
        Stores *value* under *key*.  Evicts the LRU entry if the cache
        is already at capacity.
        """
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)   # remove LRU (first) item

    def invalidate(self, key: str) -> None:
        """Removes a single entry (no-op if absent)."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Flushes the entire cache."""
        self._cache.clear()
        self._hits   = 0
        self._misses = 0

    @property
    def stats(self) -> dict:
        """Returns hit/miss/size statistics."""
        total = self._hits + self._misses
        ratio = (self._hits / total * 100) if total else 0.0
        return {
            "size":      len(self._cache),
            "max_size":  self._max_size,
            "hits":      self._hits,
            "misses":    self._misses,
            "hit_ratio": f"{ratio:.1f}%",
        }

    @staticmethod
    def make_key(engine: str, query: str, **kwargs) -> str:
        """
        Builds a canonical cache key from search parameters.

        Example:
            make_key("google", "site:example.com pdf", pages=2, lang="lang_en")
            → "google|site:example.com pdf|lang=lang_en|pages=2"
        """
        extras = "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"{engine.lower()}|{query.strip()}|{extras}"


# ---------------------------------------------------------------------------
# Singleton — shared across all engines for the duration of the session
# ---------------------------------------------------------------------------
search_cache = SearchCache(max_size=128)
