"""
``analysis.hibp``: how each HIBP answer is read, what each renderer shows,
and the wrappers the menus and the command line call.
"""

import hashlib
from types import SimpleNamespace

import pytest
import requests

from analysis import hibp
from core.cache import SQLiteCache


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


@pytest.fixture
def api(monkeypatch, tmp_path):
    """
    Answers every HIBP request with ``api.reply`` (a response or an exception)
    and keeps the headers sent. Retries and rate limits are bypassed: they have
    their own tests in test_throttle_and_wayback.
    """
    holder = SimpleNamespace(reply=None, headers=[])

    def get(url, headers=None, timeout=None):
        holder.headers.append(headers)
        if isinstance(holder.reply, BaseException):
            raise holder.reply
        return holder.reply

    sqlite_cache = SQLiteCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("core.cache.get_cache", lambda: sqlite_cache)
    monkeypatch.setattr(hibp.requests, "get", get)
    monkeypatch.setattr(hibp, "retry_http_sync", lambda call, **kwargs: call()[:2])
    monkeypatch.setenv("HIBP_API_KEY", " key ")
    return holder


def reply(status=200, payload=None, text=""):
    def parse():
        if isinstance(payload, BaseException):
            raise payload
        return payload

    return SimpleNamespace(status_code=status, json=parse, text=text, headers={})


class TestRequests:
    @pytest.mark.parametrize("answer, result", [
        (requests.exceptions.ConnectionError("refused"), (0, "transport: refused")),
        (reply(200, ValueError("plain"), text="plain body"), (200, "plain body")),
        (reply(404), (404, [])),
        (reply(401, text="Unauthorised"), (401, "Unauthorised")),
    ])
    def test_answers_are_normalised(self, api, answer, result):
        api.reply = answer

        assert hibp._get("https://haveibeenpwned.test/x", api_key="key") == result
        assert api.headers[0]["hibp-api-key"] == "key"

    def test_free_endpoints_send_no_key(self, api):
        api.reply = reply(404)

        hibp._get("https://haveibeenpwned.test/x")

        assert "hibp-api-key" not in api.headers[0]


class TestAccountLookups:
    @pytest.mark.parametrize("fetch", [
        lambda: hibp._fetch_breached_account("ana@acme.test", truncate=False),
        lambda: hibp._fetch_pastes_for_account("ana@acme.test"),
    ])
    @pytest.mark.parametrize("answer, result", [
        (reply(200, [{"Name": "Adobe"}]), [{"Name": "Adobe"}]),
        (reply(404), []),
        (reply(429, text="slow down"), None),
    ])
    def test_answers(self, api, fetch, answer, result):
        api.reply = answer

        assert fetch() == result

    def test_without_a_key_nothing_is_sent(self, api, monkeypatch):
        monkeypatch.setenv("HIBP_API_KEY", "   ")

        assert hibp._fetch_breached_account("ana@acme.test", truncate=True) is None
        assert hibp._fetch_pastes_for_account("ana@acme.test") is None
        assert api.headers == []

    def test_unknown_breach(self, api):
        api.reply = reply(404)

        assert hibp._fetch_breach("Nope") is None


class TestPwnedPasswords:
    SHA = hashlib.sha1(b"hunter2").hexdigest().upper()

    def test_unreadable_count_means_not_seen(self, api):
        api.reply = reply(200, text=f"{self.SHA[5:]}:lots\nAAAA:3")

        assert hibp.hibp_password_pwned_hash(self.SHA) == 0

    @pytest.mark.parametrize("answer", [
        requests.exceptions.ConnectionError("refused"), reply(500, text="boom")])
    def test_failed_range_lookup_is_unknown(self, api, answer):
        api.reply = answer

        assert hibp.hibp_password_pwned_hash(self.SHA) is None


class TestRenderers:
    def test_account_breaches(self, flat):
        hibp.render_breached_account("ana@acme.test", None)
        hibp.render_breached_account("ana@acme.test", [])
        hibp.render_breached_account("ana@acme.test", [{
            "Title": "Adobe", "Domain": "adobe.com", "BreachDate": "2013-10-04",
            "PwnCount": "lots", "DataClasses": ["Email addresses"] * 8}])

        out = flat()
        assert "no breaches found" in out
        assert "Breaches for ana@acme.test (1 hit)" in out
        assert "lots" in out and "…" in out

    def test_account_pastes(self, flat):
        hibp.render_pastes_for_account("ana@acme.test", None)
        hibp.render_pastes_for_account("ana@acme.test", [])
        hibp.render_pastes_for_account("ana@acme.test", [
            {"Source": "Pastebin", "Id": "8Q0BvKD8", "Date": "2014-03-04",
             "EmailCount": 139, "Title": "syslog" * 20}])

        out = flat()
        assert "no pastes found" in out
        assert "Pastebin" in out and "8Q0BvKD8" in out

    def test_domain_breaches(self, flat):
        hibp.render_breaches_for_domain("acme.test", None)
        hibp.render_breaches_for_domain("acme.test", [])
        hibp.render_breaches_for_domain("acme.test", [
            {"Name": "Acme", "BreachDate": "2020-01-01", "PwnCount": 1200, "IsVerified": True}])

        out = flat()
        assert "HIBP lookup failed" in out and "no breaches recorded" in out
        assert "1,200" in out and "yes" in out

    @pytest.mark.parametrize("count, message", [
        (None, "lookup failed"),
        (0, "not found in any known HIBP breach"),
        (3, "3 time(s) — change it"),
        (9, "9 time(s) — change it"),
        (10, "10 time(s) — do NOT use it anywhere"),
        (52256179, "52,256,179 time(s) — do NOT use it anywhere"),
    ])
    def test_password(self, flat, count, message):
        hibp.render_password_pwned(count)

        assert message in flat()


class TestWrappers:
    def test_account_with_pastes(self, monkeypatch, flat):
        monkeypatch.setattr(hibp, "hibp_breached_account", lambda email: [{"Name": "Adobe"}])
        monkeypatch.setattr(hibp, "hibp_pastes_for_account", lambda email: [{"Id": "p"}])

        result = hibp.check_account("ana@acme.test")

        assert (result["checked"], result["breach_count"], result["paste_count"]) == (True, 1, 1)

    def test_domain_and_password(self, monkeypatch, flat):
        monkeypatch.setattr(hibp, "hibp_breaches_for_domain", lambda domain: [])
        monkeypatch.setattr(hibp, "hibp_password_pwned", lambda password: 0)

        assert hibp.check_domain("acme.test") == []
        assert hibp.check_password("correct horse") == 0
        out = flat()
        assert "no breaches recorded" in out and "Password not found" in out
