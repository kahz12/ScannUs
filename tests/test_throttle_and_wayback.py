"""Offline unit tests for ``core.throttle``, ``search.reverse_image_engines`` and Wayback tools."""

import asyncio
from types import SimpleNamespace

import pytest

from analysis import advanced_osint as ao
from core import throttle
from core.cache import SQLiteCache
from core.findings import FindingsHub
from search import reverse_image as ri
from search import reverse_image_engines as rie


@pytest.fixture
def fresh_env(tmp_path, monkeypatch):
    cache = SQLiteCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("core.cache.get_cache", lambda: cache)
    throttle.reset_buckets()
    monkeypatch.setattr(throttle.time, "sleep", lambda s: None)
    return cache


# ---------------------------------------------------------------------------
# TokenBucket, decorators & HTTP retries
# ---------------------------------------------------------------------------

class TestThrottle:
    def test_token_bucket_rate_validation_and_debt(self):
        with pytest.raises(ValueError):
            throttle.TokenBucket(0)
        b = throttle.TokenBucket(rate=2.0, capacity=1.0)
        assert b.acquire() == 0.0
        wait = b.acquire()
        assert 0.0 < wait <= 0.55

    def test_throttled_retries_on_transient_error(self, fresh_env):
        attempts = [0]

        @throttle.throttled("default", max_retries=2)
        def flaky():
            attempts[0] += 1
            if attempts[0] < 3:
                raise throttle.TransientError("try again")
            return "ok"

        assert flaky() == "ok"
        assert attempts[0] == 3

    def test_throttled_async_retries_and_succeeds(self, fresh_env, monkeypatch):
        async def _no_sleep(_): return None
        monkeypatch.setattr(throttle.asyncio, "sleep", _no_sleep)
        attempts = [0]

        @throttle.throttled_async("default", max_retries=1)
        async def flaky():
            attempts[0] += 1
            if attempts[0] == 1:
                raise throttle.TransientError("blip")
            return "async-ok"

        assert asyncio.run(flaky()) == "async-ok"
        assert attempts[0] == 2

    def test_retry_http_sync_honours_retry_after(self, fresh_env, monkeypatch):
        sleeps = []
        monkeypatch.setattr(throttle.time, "sleep", sleeps.append)
        responses = iter([(429, "slow", "2.5"), (200, "done", None)])

        status, body = throttle.retry_http_sync(
            lambda: next(responses), namespace="hibp_breach", max_retries=2,
        )
        assert (status, body) == (200, "done")
        assert 2.5 in sleeps

    def test_retry_http_async_retries_503(self, fresh_env, monkeypatch):
        sleeps = []
        async def _rec(s): sleeps.append(s)
        monkeypatch.setattr(throttle.asyncio, "sleep", _rec)
        responses = iter([(503, "busy", "1"), (200, "ok", None)])

        async def call():
            return next(responses)

        status, body = asyncio.run(
            throttle.retry_http_async(call, namespace="crtsh", max_retries=2)
        )
        assert (status, body) == (200, "ok")
        assert 1.0 in sleeps


# ---------------------------------------------------------------------------
# Reverse image engines + hub ingestion
# ---------------------------------------------------------------------------

class TestReverseImage:
    def test_tineye_signs_request_and_maps_matches(self, monkeypatch):
        captured = {}

        def fake_get(url, params=None, timeout=None, headers=None):
            captured["params"] = params
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "results": {
                        "matches": [{
                            "score": 98.5,
                            "backlinks": [{
                                "backlink": "https://origin.test/post",
                                "backlink_label": "Origin Post",
                                "crawl_date": "2026-01-01",
                            }],
                        }]
                    }
                },
            )

        monkeypatch.setattr(rie.requests, "get", fake_get)
        hits = rie.tineye_search("https://img.test/a.jpg", public_key="pub", private_key="priv")
        assert len(hits) == 1
        assert hits[0]["engine"] == "tineye"
        assert hits[0]["link"] == "https://origin.test/post"
        assert len(captured["params"]["api_sig"]) == 64

    def test_bing_visual_search_parses_actions(self, monkeypatch):
        payload = {
            "tags": [{
                "actions": [{
                    "actionType": "PagesIncluding",
                    "data": {"value": [{
                        "name": "Match Title",
                        "hostPageUrl": "https://blog.test/img",
                        "hostPageDisplayUrl": "blog.test/img",
                    }]},
                }]
            }]
        }
        monkeypatch.setattr(
            rie.requests, "post",
            lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload),
        )
        hits = rie.bing_visual_search("https://img.test/a.jpg", api_key="bing-key")
        assert len(hits) == 1
        assert hits[0]["engine"] == "bing"
        assert hits[0]["link"] == "https://blog.test/img"

    def test_manual_urls_and_hub_ingestion(self, monkeypatch):
        manual = rie.manual_lookup_urls("https://img.test/a.jpg")
        assert len(manual) == 5
        assert all(m["engine"] == "manual" for m in manual)

        hub = FindingsHub()
        monkeypatch.setattr(ri, "get_hub", lambda: hub)
        monkeypatch.setattr(
            ri, "reverse_image_aggregate",
            lambda url: [
                {"title": "Hit", "link": "https://hit.test/1", "description": "[TinEye]", "engine": "tineye"},
                manual[0],
            ],
        )
        assert ri.do_reverse_image_search("https://img.test/a.jpg") is True
        # Only non-manual hits are ingested into the hub
        assert [f.value for f in hub.of_kind("url")] == ["https://hit.test/1"]


# ---------------------------------------------------------------------------
# Wayback Machine timeline, timestamp resolution, cached fetch & diff
# ---------------------------------------------------------------------------

class TestWayback:
    def test_check_wayback_machine_parses_cdx_rows(self, fresh_env, monkeypatch):
        cdx = [
            ["timestamp", "original", "mimetype", "statuscode", "digest"],
            ["20200101120000", "https://site.test/", "text/html", "200", "AAA"],
            ["20250615083000", "https://site.test/", "text/html", "200", "BBB"],
        ]
        monkeypatch.setattr(
            ao.requests, "get",
            lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: cdx),
        )
        snaps = ao.check_wayback_machine("https://site.test/")
        assert len(snaps) == 2
        assert snaps[0]["timestamp"] == "20250615083000"  # newest first
        assert snaps[0]["date"] == "2025-06-15 08:30:00"

    def test_wayback_resolve_timestamp_literal_and_fuzzy(self, fresh_env, monkeypatch):
        assert ao.wayback_resolve_timestamp("https://site.test/", "20200101120000") == "20200101120000"
        assert ao.wayback_resolve_timestamp("https://site.test/", "not-a-date") is None

        seen_params = []

        def fake_get(url, params=None, timeout=None):
            seen_params.append(params)
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: [["timestamp"], ["20230405000000"]],
            )

        monkeypatch.setattr(ao.requests, "get", fake_get)
        assert ao.wayback_resolve_timestamp("https://site.test/", "2023-04") == "20230405000000"
        assert seen_params[0]["from"] == "202304"

    def test_wayback_fetch_caches_and_diff_computes_changes(self, fresh_env, monkeypatch):
        pages = {
            "20200101000000": b"<html><body><p>Old line</p><p>Shared</p></body></html>",
            "20240101000000": b"<html><body><p>Shared</p><p>New line</p></body></html>",
        }
        fetches = []

        def fake_get(url, timeout=None, headers=None):
            fetches.append(url)
            ts = next(k for k in pages if k in url)
            return SimpleNamespace(
                status_code=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                content=pages[ts],
                text=pages[ts].decode(),
                raise_for_status=lambda: None,
            )

        monkeypatch.setattr(ao.requests, "get", fake_get)

        diff = ao.wayback_diff("https://site.test/", "20200101000000", "20240101000000")
        assert diff is not None
        assert diff["identical"] is False
        assert diff["added"] == ["New line"]
        assert diff["removed"] == ["Old line"]
        assert len(fetches) == 2

        # Second call served entirely from SQLite cache
        diff2 = ao.wayback_diff("https://site.test/", "20200101000000", "20240101000000")
        assert diff2["added"] == ["New line"]
        assert len(fetches) == 2
