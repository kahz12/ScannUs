"""
core/cache.py — Persistent SQLite-backed cache with TTL + namespaces.

A single ``cache.db`` lives under ``DIR_CACHE`` and is shared by every
caller in the project. The cache survives across sessions and process
restarts, dramatically reducing repeat traffic to slow or rate-limited
upstreams (WHOIS registries, Archive.org, search engines, DNS, etc.).

Design notes:
  - Namespaces isolate different content types (``search``, ``http_text``,
    ``whois``, ``dns``, ``wayback`` …) so eviction can be selective.
  - Each entry carries a per-row ``expires_at`` (epoch seconds). Reads
    transparently filter out expired rows; a periodic ``purge_expired()``
    sweep keeps the DB compact.
  - Values are JSON-serialised. Callers that need to cache bytes must
    encode them (e.g. base64) before calling :meth:`set`.
  - The cache is opt-out via ``SCANNUS_CACHE_DISABLE=1``. When disabled,
    all reads return ``None`` and writes are no-ops.

Concurrency: every public method opens its own short-lived connection
(WAL journal mode), so the cache is safe across threads and across
multiple processes accessing the same DB file.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Per-namespace TTLs (seconds). Override at the call site if needed.
DEFAULT_TTL: dict[str, int] = {
    "search":      24 * 60 * 60,        # 24h — SERPs change slowly
    "http_text":   6  * 60 * 60,        # 6h — page content drifts faster
    "whois":       7  * 24 * 60 * 60,   # 7d — registry data rarely changes
    "dns":         1  * 60 * 60,        # 1h — short to honour TTLs
    "wayback":     30 * 24 * 60 * 60,   # 30d — archives are immutable
    "crtsh":       24 * 60 * 60,        # 24h — CT logs grow append-only
    "default":     6  * 60 * 60,
}


def _disabled() -> bool:
    """Returns True if caching is opted out via env."""
    return os.getenv("SCANNUS_CACHE_DISABLE", "").strip() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# SQLiteCache
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    namespace   TEXT NOT NULL,
    key         TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL,                       -- NULL = never expires
    PRIMARY KEY (namespace, key)
);
CREATE INDEX IF NOT EXISTS idx_cache_expires
    ON cache(expires_at) WHERE expires_at IS NOT NULL;
"""


class SQLiteCache:
    """Persistent, namespaced, TTL-aware key/value store backed by SQLite."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._hits   = 0
        self._misses = 0
        self._initialize()

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _initialize(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def get(self, namespace: str, key: str) -> Any | None:
        """
        Return the cached value for ``(namespace, key)``, or ``None`` on
        cache miss / expired row. Expired rows are NOT lazily deleted here
        — use :meth:`purge_expired` to reclaim space.
        """
        if _disabled():
            return None
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value_json, expires_at FROM cache "
                    "WHERE namespace = ? AND key = ?",
                    (namespace, key),
                ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            self._misses += 1
            return None
        value_json, expires_at = row
        if expires_at is not None and expires_at < time.time():
            self._misses += 1
            return None
        self._hits += 1
        try:
            return json.loads(value_json)
        except json.JSONDecodeError:
            return None

    def set(self, namespace: str, key: str, value: Any,
            ttl: int | None = None) -> None:
        """
        Store ``value`` under ``(namespace, key)``. ``ttl`` overrides the
        per-namespace default. Pass ``ttl=0`` for "never expires".
        """
        if _disabled():
            return
        try:
            value_json = json.dumps(value, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            return  # silently skip un-serialisable payloads

        now = time.time()
        if ttl is None:
            ttl = DEFAULT_TTL.get(namespace, DEFAULT_TTL["default"])
        expires_at = (now + ttl) if ttl else None

        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO cache(namespace, key, value_json, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(namespace, key) DO UPDATE SET "
                    "  value_json = excluded.value_json, "
                    "  created_at = excluded.created_at, "
                    "  expires_at = excluded.expires_at",
                    (namespace, key, value_json, now, expires_at),
                )
        except sqlite3.Error:
            pass

    def invalidate(self, namespace: str, key: str) -> None:
        """Remove a single entry. No-op if absent."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM cache WHERE namespace = ? AND key = ?",
                    (namespace, key),
                )
        except sqlite3.Error:
            pass

    def clear(self, namespace: str | None = None) -> int:
        """
        Wipe every row in ``namespace`` (or the entire cache if ``None``).
        Returns the number of rows removed.
        """
        try:
            with self._connect() as conn:
                if namespace is None:
                    cur = conn.execute("DELETE FROM cache")
                else:
                    cur = conn.execute(
                        "DELETE FROM cache WHERE namespace = ?", (namespace,)
                    )
                return cur.rowcount or 0
        except sqlite3.Error:
            return 0

    def purge_expired(self) -> int:
        """Delete rows whose ``expires_at`` has elapsed. Returns count removed."""
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at < ?",
                    (time.time(),),
                )
                return cur.rowcount or 0
        except sqlite3.Error:
            return 0

    def stats(self) -> dict:
        """
        Return aggregate stats: in-process hit/miss counters plus on-disk
        row counts by namespace.
        """
        total = self._hits + self._misses
        ratio = (self._hits / total * 100) if total else 0.0
        by_ns: dict[str, int] = {}
        size_bytes = 0
        try:
            with self._connect() as conn:
                for ns, n in conn.execute(
                    "SELECT namespace, COUNT(*) FROM cache GROUP BY namespace"
                ):
                    by_ns[ns] = n
            if os.path.exists(self.db_path):
                size_bytes = os.path.getsize(self.db_path)
        except sqlite3.Error:
            pass
        return {
            "hits":       self._hits,
            "misses":     self._misses,
            "hit_ratio":  f"{ratio:.1f}%",
            "rows":       sum(by_ns.values()),
            "by_namespace": by_ns,
            "db_path":    self.db_path,
            "db_size":    size_bytes,
            "disabled":   _disabled(),
        }

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @staticmethod
    def make_key(*parts: Any) -> str:
        """Build a stable cache key by joining parts with ``|``."""
        return "|".join(str(p).strip() for p in parts if p is not None)


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_GLOBAL: SQLiteCache | None = None


def get_cache() -> SQLiteCache:
    """Return the process-wide cache instance, creating it lazily."""
    global _GLOBAL
    if _GLOBAL is None:
        # Defer import so this module can be loaded before init_directories()
        from core.config import DIR_CACHE
        _GLOBAL = SQLiteCache(os.path.join(DIR_CACHE, "cache.db"))
    return _GLOBAL


def cached_call(namespace: str, key_parts: Iterable[Any],
                producer, ttl: int | None = None) -> Any:
    """
    High-level helper: return cached value if present, otherwise call
    ``producer()``, store its return, and return it.

    Example::

        text = cached_call("http_text", [url],
                           lambda: _fetch_and_clean(url))
    """
    cache = get_cache()
    key = cache.make_key(*key_parts)
    hit = cache.get(namespace, key)
    if hit is not None:
        return hit
    value = producer()
    if value is not None:
        cache.set(namespace, key, value, ttl=ttl)
    return value
