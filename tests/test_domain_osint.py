"""Offline unit tests for ``analysis.domain_osint``."""

import asyncio
import json
from types import SimpleNamespace

import pytest
import requests

from analysis import domain_osint as do
from core.cache import SQLiteCache
from core.throttle import reset_buckets


@pytest.fixture
def cache(tmp_path, monkeypatch):
    sqlite_cache = SQLiteCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("core.cache.get_cache", lambda: sqlite_cache)
    reset_buckets()
    return sqlite_cache


class TestTargetNormalisation:
    @pytest.mark.parametrize("raw, expected", [
        ("example.com", ("example.com", "https://example.com")),
        ("https://Example.COM/path?q=1", ("example.com", "https://Example.COM/path?q=1")),
        ("sub.example.com:8443/api", ("sub.example.com", "https://sub.example.com")),
        ("", ("", None)),
    ])
    def test_normalize_target(self, raw, expected):
        assert do._normalize_target(raw) == expected


class TestWhoisAndDNS:
    def test_whois_lookup_normalises_and_caches(self, cache, monkeypatch):
        calls = []

        class FakeWhois(dict):
            domain_name = ["EXAMPLE.COM", "example.com"]

        def fake_whois(domain):
            calls.append(domain)
            return FakeWhois(
                domain_name=["EXAMPLE.COM", "example.com"],
                registrar="Example Registrar",
                name_servers=["NS2.EXAMPLE.COM", "ns1.example.com"],
                emails=["admin@example.com", "admin@example.com"],
                country="US",
            )

        monkeypatch.setattr(do, "_HAS_WHOIS", True)
        monkeypatch.setattr(do, "whois", SimpleNamespace(whois=fake_whois), raising=False)

        first = do.whois_lookup("example.com")
        second = do.whois_lookup("EXAMPLE.COM")
        assert first == second
        assert len(calls) == 1
        assert first["name_servers"] == ["ns1.example.com", "ns2.example.com"]
        assert first["emails"] == ["admin@example.com"]

    def test_dns_records_caches_per_record_type(self, cache, monkeypatch):
        fetched = []

        def fake_fetch(domain, types):
            fetched.append(types)
            return {"A": ["93.184.216.34"]}

        monkeypatch.setattr(do, "_dns_fetch", fake_fetch)

        first = do.dns_records("example.com", types=("A", "MX"))
        second = do.dns_records("example.com", types=("A", "MX"))
        assert first == {"A": ["93.184.216.34"]}
        assert second == first
        assert len(fetched) == 1  # even empty MX result was cached


class TestHeadersAndTLS:
    def test_http_security_headers_scores_and_falls_back_to_get(self, monkeypatch):
        methods = []

        def fake_head(url, **kw):
            methods.append("HEAD")
            return SimpleNamespace(url=url, status_code=405, headers={})

        def fake_get(url, **kw):
            methods.append("GET")
            return SimpleNamespace(
                url=url, status_code=200,
                headers={
                    "Strict-Transport-Security": "max-age=31536000",
                    "X-Content-Type-Options": "nosniff",
                    "Server": "nginx",
                },
            )

        monkeypatch.setattr(do.requests, "head", fake_head)
        monkeypatch.setattr(do.requests, "get", fake_get)

        res = do.http_security_headers("https://example.com")
        assert methods == ["HEAD", "GET"]
        assert res["score"] == f"2/{len(do._SECURITY_HEADERS)}"
        assert res["server"] == "nginx"
        assert "Content-Security-Policy" in res["missing"]

    def test_tls_fetch_parses_certificate(self, monkeypatch):
        cert = {
            "subject": ((("commonName", "example.com"),),),
            "issuer": ((("organizationName", "Let's Encrypt"),),),
            "subjectAltName": (("DNS", "example.com"), ("DNS", "www.example.com")),
            "notBefore": "Jan  1 00:00:00 2025 GMT",
            "notAfter": "Dec 31 23:59:59 2030 GMT",
        }

        class FakeSSLSock:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def getpeercert(self): return cert
            def cipher(self): return ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
            def version(self): return "TLSv1.3"

        class FakeSock:
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class FakeCtx:
            def wrap_socket(self, sock, server_hostname=None):
                return FakeSSLSock()

        monkeypatch.setattr(do.ssl, "create_default_context", lambda: FakeCtx())
        monkeypatch.setattr(do.socket, "create_connection", lambda addr, timeout=None: FakeSock())

        info = do.tls_certificate("example.com")
        assert info["san"] == ["example.com", "www.example.com"]
        assert info["tls_version"] == "TLSv1.3"
        assert info["days_left"] > 0


class TestCrtShAndShodan:
    def test_crtsh_parse_dedupes_and_handles_wildcards(self):
        entries = [
            {"name_value": "*.api.example.com\nwww.example.com\nother.org"},
            {"name_value": "api.example.com"},
        ]
        assert do._crtsh_parse(entries, "example.com", include_wildcards=False) == [
            "api.example.com", "www.example.com",
        ]
        assert "*.api.example.com" in do._crtsh_parse(entries, "example.com", include_wildcards=True)

    def test_crtsh_sync_caches_success_and_retries_502_without_caching_failure(self, cache, monkeypatch):
        monkeypatch.setattr("core.throttle.time.sleep", lambda s: None)
        statuses = iter([502, 200])
        calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(params["q"])
            st = next(statuses)
            return SimpleNamespace(
                status_code=st,
                headers={},
                json=lambda: [{"name_value": "dev.example.com"}],
            )

        monkeypatch.setattr(do.requests, "get", fake_get)

        first = do.subdomains_crtsh("example.com")
        second = do.subdomains_crtsh("EXAMPLE.COM")
        assert first == ["dev.example.com"]
        assert second == ["dev.example.com"]
        assert len(calls) == 2  # 502 + retry 200, then cache hit!

    def test_crtsh_failure_is_not_cached(self, cache, monkeypatch):
        monkeypatch.setattr("core.throttle.time.sleep", lambda s: None)
        monkeypatch.setattr(
            do.requests, "get",
            lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")),
        )
        assert do.subdomains_crtsh("broken.example") == []
        assert cache.get("crtsh", cache.make_key("broken.example", 0)) is None

    def test_crtsh_async_uses_cache(self, cache, monkeypatch):
        cache.set("crtsh", cache.make_key("cached.example", 0), ["a.cached.example"])
        res = asyncio.run(do._crtsh_fetch_async("cached.example"))
        assert res == {"subdomains": ["a.cached.example"]}

    def test_shodan_handles_missing_key_404_and_200(self, cache, monkeypatch):
        monkeypatch.delenv("SHODAN_API_KEY", raising=False)
        assert do.shodan_host("1.1.1.1") == {}

        monkeypatch.setenv("SHODAN_API_KEY", "test-key")
        monkeypatch.setattr(
            do.requests, "get",
            lambda *a, **k: SimpleNamespace(status_code=404, text="not found"),
        )
        assert do.shodan_host("1.1.1.1") == {}

        payload = {"org": "Cloudflare", "ports": [80, 443], "hostnames": ["one.one.one.one"]}
        monkeypatch.setattr(
            do.requests, "get",
            lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload, text=json.dumps(payload)),
        )
        assert do.shodan_host("1.1.1.1") == payload


def test_domain_recon_runs_all_probes_and_aggregates(cache, monkeypatch):
    monkeypatch.delenv("SHODAN_API_KEY", raising=False)

    async def _whois(d): return {"domain": d, "registrar": "R"}
    async def _dns(d): return {"A": ["93.184.216.34"]}
    async def _mail(d): return {"spf": "v=spf1 -all", "dmarc": None, "dkim_selectors": []}
    async def _hdr(u): return {"url": u, "status": 200, "headers": {"Strict-Transport-Security": "max-age=1"}}
    async def _subs(d): return {"subdomains": ["api.example.com"]}

    monkeypatch.setattr(do, "_whois_lookup_async", _whois)
    monkeypatch.setattr(do, "_dns_records_async", _dns)
    monkeypatch.setattr(do, "_email_security_fetch_async", _mail)
    monkeypatch.setattr(do, "_tls_fetch", lambda h, p, t: {"san": [h], "days_left": 90, "tls_version": "TLSv1.3"})
    monkeypatch.setattr(do, "_http_headers_fetch_async", _hdr)
    monkeypatch.setattr(do, "_crtsh_fetch_async", _subs)

    report = do.domain_recon("example.com")
    assert report["target"] == "example.com"
    assert report["whois"]["registrar"] == "R"
    assert report["dns"]["A"] == ["93.184.216.34"]
    assert report["email_security"]["spf"] == "v=spf1 -all"
    assert report["tls"]["san"] == ["example.com"]
    assert report["subdomains"] == ["api.example.com"]
    assert report["headers"]["score"].startswith("1/")
