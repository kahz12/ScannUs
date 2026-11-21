"""Offline unit tests for ``analysis.hibp``, ``search.phone_osint`` and ``core.unified``."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from analysis import hibp
from core import unified
from core.cache import SQLiteCache
from core.throttle import reset_buckets
from search import phone_osint as po


@pytest.fixture
def cache(tmp_path, monkeypatch):
    sqlite_cache = SQLiteCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("core.cache.get_cache", lambda: sqlite_cache)
    reset_buckets()
    return sqlite_cache


# ---------------------------------------------------------------------------
# HIBP k-anonymity & account/breach lookups
# ---------------------------------------------------------------------------

class TestHIBPKAnonymity:
    def test_only_five_char_sha1_prefix_leaves_process(self, cache, monkeypatch):
        password = "super-secret-password"
        digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        requested_urls = []

        def fake_get(url, headers=None, timeout=None):
            requested_urls.append((url, headers))
            body = f"00000000000000000000000000000000000:0\n{suffix}:42\n"
            return SimpleNamespace(status_code=200, text=body, headers={})

        monkeypatch.setattr(hibp.requests, "get", fake_get)

        count = hibp.hibp_password_pwned(password)
        assert count == 42
        assert len(requested_urls) == 1
        url, headers = requested_urls[0]
        assert url.endswith(f"/{prefix}")
        assert password not in url
        assert suffix not in url
        assert headers.get("Add-Padding") == "true"

        # Second call served from cache
        assert hibp.hibp_password_pwned(password) == 42
        assert len(requested_urls) == 1

    def test_clean_and_invalid_hashes(self, cache, monkeypatch):
        monkeypatch.setattr(
            hibp.requests, "get",
            lambda *a, **k: SimpleNamespace(status_code=200, text="AAAA:1\n", headers={}),
        )
        assert hibp.hibp_password_pwned("unique-clean-pw") == 0
        assert hibp.hibp_password_pwned("") is None
        assert hibp.hibp_password_pwned_hash("not-a-sha1") is None


class TestHIBPAccountAndBreach:
    def test_account_requires_api_key_and_handles_404(self, cache, monkeypatch):
        monkeypatch.delenv("HIBP_API_KEY", raising=False)
        assert hibp.hibp_breached_account("a@example.com") is None
        assert hibp.hibp_pastes_for_account("a@example.com") is None

        monkeypatch.setenv("HIBP_API_KEY", "paid-key")
        monkeypatch.setattr(hibp, "_get", lambda url, **kw: (404, []))
        assert hibp.hibp_breached_account("clean@example.com") == []
        assert hibp.hibp_pastes_for_account("clean@example.com") == []

    def test_breach_metadata_lookup_caches(self, cache, monkeypatch):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            return 200, {"Name": "Adobe", "PwnCount": 152445165, "DataClasses": ["Emails"]}

        monkeypatch.setattr(hibp, "_get", fake_get)
        assert hibp.hibp_breach("Adobe")["Name"] == "Adobe"
        assert hibp.hibp_breach("adobe")["Name"] == "Adobe"
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Phone OSINT (libphonenumber)
# ---------------------------------------------------------------------------

class TestPhoneOsint:
    def test_valid_international_number_metadata_and_footprint(self):
        report = po.phone_lookup("+14155552671")
        assert report is not None
        assert report["valid"] is True
        assert report["e164"] == "+14155552671"
        assert report["region_code"] == "US"
        assert report["country_code"] == 1
        kinds = {fp["kind"] for fp in report["footprint"]}
        assert kinds == {"search", "link"}
        assert any("wa.me/14155552671" in fp["value"] for fp in report["footprint"])

    def test_colombian_number_with_and_without_region_hint(self):
        for hint in ("CO", None):
            report = po.phone_lookup("300 123 4567", region=hint)
            assert report is not None
            assert report["valid"] is True
            assert report["e164"] == "+573001234567"
            assert report["region_code"] == "CO"

    def test_invalid_or_empty_returns_none(self):
        assert po.phone_lookup("") is None
        assert po.phone_lookup("not-a-phone") is None

    def test_phone_osint_saves_json_report(self, tmp_path, monkeypatch):
        monkeypatch.setattr(po, "DIR_REPORTS", str(tmp_path))
        report = po.phone_osint("+14155552671", save_json=True)
        assert report is not None
        files = list(tmp_path.glob("phone_*.json"))
        assert len(files) == 1
        saved = json.loads(files[0].read_text(encoding="utf-8"))
        assert saved["e164"] == "+14155552671"


# ---------------------------------------------------------------------------
# Unified record converters
# ---------------------------------------------------------------------------

class TestUnifiedConverters:
    def test_from_username_enum(self):
        recs = unified.from_username_enum("alice", [{"site": "GitHub", "url": "https://github.com/alice"}])
        assert recs == [{
            "identifier": "alice",
            "identifier_type": "username",
            "service": "GitHub",
            "status": "claimed",
            "evidence": {"url": "https://github.com/alice", "http_status": "", "response_time": ""},
        }]

    def test_from_email_enum_status_precedence(self):
        rows = [
            {"service": "A", "status": "claimed"},
            {"service": "B", "status": "unchecked", "rate_limited": True},
            {"service": "C", "status": "available"},
            {"service": "D", "status": "claimed", "error": "boom"},
        ]
        recs = unified.from_email_enum("a@b.io", rows)
        assert [(r["service"], r["status"]) for r in recs] == [
            ("A", "claimed"), ("B", "rate_limited"), ("C", "available"), ("D", "error"),
        ]

    def test_from_phone_and_hibp(self):
        p_recs = unified.from_phone_osint("+14155552671", po.phone_lookup("+14155552671"))
        assert p_recs[0]["status"] == "valid"
        assert p_recs[0]["identifier_type"] == "phone"

        b_recs = unified.from_hibp_breaches("a@b.io", [{"Name": "Adobe", "PwnCount": 10, "IsVerified": True}])
        assert b_recs[0]["status"] == "leaked"
        assert b_recs[0]["evidence"]["source"] == "hibp_breach"

        paste_recs = unified.from_hibp_pastes("a@b.io", [{"Source": "Pastebin", "Id": "xyz"}])
        assert paste_recs[0]["status"] == "leaked"
        assert paste_recs[0]["evidence"]["source"] == "hibp_paste"
