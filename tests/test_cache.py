"""
Unit tests for ``core.cache.SQLiteCache``.

The cache is instantiated with an explicit ``db_path`` (a pytest ``tmp_path``)
so these tests never touch the real on-disk cache or the process-wide
singleton. TTL expiry is exercised by monkeypatching ``core.cache.time.time``
rather than sleeping, keeping the suite fast and deterministic.
"""

import core.cache as cache_mod
from core.cache import SQLiteCache


def make_cache(tmp_path) -> SQLiteCache:
    return SQLiteCache(str(tmp_path / "cache.db"))


class TestRoundTrip:
    def test_set_then_get(self, tmp_path):
        c = make_cache(tmp_path)
        c.set("search", "k1", {"hits": [1, 2, 3]})
        assert c.get("search", "k1") == {"hits": [1, 2, 3]}

    def test_missing_key_returns_none(self, tmp_path):
        c = make_cache(tmp_path)
        assert c.get("search", "absent") is None

    def test_namespaces_are_isolated(self, tmp_path):
        c = make_cache(tmp_path)
        c.set("search", "k", "from-search")
        c.set("dns", "k", "from-dns")
        assert c.get("search", "k") == "from-search"
        assert c.get("dns", "k") == "from-dns"

    def test_overwrite_updates_value(self, tmp_path):
        c = make_cache(tmp_path)
        c.set("search", "k", "old")
        c.set("search", "k", "new")
        assert c.get("search", "k") == "new"


class TestExpiry:
    def test_ttl_zero_never_expires(self, tmp_path, monkeypatch):
        c = make_cache(tmp_path)
        monkeypatch.setattr(cache_mod.time, "time", lambda: 1000.0)
        c.set("search", "k", "v", ttl=0)
        # Jump far into the future — value must still be present
        monkeypatch.setattr(cache_mod.time, "time", lambda: 10**12)
        assert c.get("search", "k") == "v"

    def test_expired_entry_returns_none(self, tmp_path, monkeypatch):
        c = make_cache(tmp_path)
        monkeypatch.setattr(cache_mod.time, "time", lambda: 1000.0)
        c.set("search", "k", "v", ttl=100)  # expires at 1100
        monkeypatch.setattr(cache_mod.time, "time", lambda: 1200.0)
        assert c.get("search", "k") is None

    def test_not_yet_expired_returns_value(self, tmp_path, monkeypatch):
        c = make_cache(tmp_path)
        monkeypatch.setattr(cache_mod.time, "time", lambda: 1000.0)
        c.set("search", "k", "v", ttl=100)  # expires at 1100
        monkeypatch.setattr(cache_mod.time, "time", lambda: 1050.0)
        assert c.get("search", "k") == "v"

    def test_purge_expired_reclaims_rows(self, tmp_path, monkeypatch):
        c = make_cache(tmp_path)
        monkeypatch.setattr(cache_mod.time, "time", lambda: 1000.0)
        c.set("search", "fresh", "v", ttl=10_000)
        c.set("search", "stale", "v", ttl=10)
        monkeypatch.setattr(cache_mod.time, "time", lambda: 2000.0)
        removed = c.purge_expired()
        assert removed == 1
        assert c.get("search", "fresh") == "v"


class TestMutation:
    def test_invalidate_single_entry(self, tmp_path):
        c = make_cache(tmp_path)
        c.set("search", "k", "v")
        c.invalidate("search", "k")
        assert c.get("search", "k") is None

    def test_clear_namespace_returns_count(self, tmp_path):
        c = make_cache(tmp_path)
        c.set("search", "a", 1)
        c.set("search", "b", 2)
        c.set("dns", "c", 3)
        removed = c.clear("search")
        assert removed == 2
        assert c.get("search", "a") is None
        assert c.get("dns", "c") == 3  # other namespace untouched

    def test_clear_everything(self, tmp_path):
        c = make_cache(tmp_path)
        c.set("search", "a", 1)
        c.set("dns", "b", 2)
        removed = c.clear()
        assert removed == 2
        assert c.get("search", "a") is None
        assert c.get("dns", "b") is None


class TestStats:
    def test_hit_and_miss_counters(self, tmp_path):
        c = make_cache(tmp_path)
        c.set("search", "k", "v")
        c.get("search", "k")        # hit
        c.get("search", "absent")   # miss
        stats = c.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_ratio"] == "50.0%"

    def test_row_count_by_namespace(self, tmp_path):
        c = make_cache(tmp_path)
        c.set("search", "a", 1)
        c.set("search", "b", 2)
        c.set("dns", "c", 3)
        stats = c.stats()
        assert stats["rows"] == 3
        assert stats["by_namespace"] == {"search": 2, "dns": 1}


class TestSerialisation:
    def test_unserialisable_payload_is_skipped(self, tmp_path):
        c = make_cache(tmp_path)
        circular: list = []
        circular.append(circular)  # json.dumps raises ValueError on this
        c.set("search", "k", circular)  # must not raise
        assert c.get("search", "k") is None


class TestDisabled:
    def test_disabled_env_disables_reads_and_writes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SCANNUS_CACHE_DISABLE", "1")
        c = make_cache(tmp_path)
        c.set("search", "k", "v")   # no-op
        assert c.get("search", "k") is None
        assert c.stats()["disabled"] is True


class TestMakeKey:
    def test_join_and_strip(self, tmp_path):
        assert SQLiteCache.make_key(" a ", "b", 3) == "a|b|3"

    def test_none_parts_dropped(self, tmp_path):
        assert SQLiteCache.make_key("a", None, "b") == "a|b"

    def test_stable_across_calls(self, tmp_path):
        assert SQLiteCache.make_key("x", 1) == SQLiteCache.make_key("x", 1)
