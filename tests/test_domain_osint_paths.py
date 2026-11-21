"""
``analysis.domain_osint`` with stand-ins for dnspython, aiohttp, sockets and
requests: the parsing of each answer, every failure path, and the parallel
recon that renders whatever each probe returned.
"""

import asyncio
import json
from types import SimpleNamespace

import aiohttp
import pytest
import requests

from analysis import domain_osint as do
from core.cache import SQLiteCache
from core.throttle import reset_buckets

DOMAIN = "acme.test"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    sqlite_cache = SQLiteCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("core.cache.get_cache", lambda: sqlite_cache)
    reset_buckets()
    return sqlite_cache


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


def run(coroutine):
    return asyncio.run(coroutine)


# ---------------------------------------------------------------------------
# dnspython stand-in
# ---------------------------------------------------------------------------

class Rdata:
    """One DNS answer; TXT answers may carry their text as byte chunks."""

    def __init__(self, text, strings=None):
        self.text = text
        if strings is not None:
            self.strings = strings

    def to_text(self):
        return self.text


@pytest.fixture
def answers(monkeypatch):
    """Maps ``(name, rtype)`` to answers or an exception; anything else has no answer."""
    table: dict = {}

    def lookup(name, rtype):
        answer = table.get((name, rtype), do.dns.resolver.NoAnswer())
        if isinstance(answer, BaseException):
            raise answer
        return answer

    class Resolver:
        def resolve(self, name, rtype):
            return lookup(name, rtype)

    class AsyncResolver:
        async def resolve(self, name, rtype):
            return lookup(name, rtype)

    monkeypatch.setattr(do.dns.resolver, "Resolver", Resolver)
    monkeypatch.setattr(do.dns.asyncresolver, "Resolver", AsyncResolver)
    return table


class TestDnsRecords:
    def fill(self, answers):
        answers[(DOMAIN, "A")] = [Rdata("203.0.113.7")]
        answers[(DOMAIN, "TXT")] = [Rdata('"v=spf1 -all"')]
        answers[(DOMAIN, "MX")] = do.dns.exception.Timeout()
        answers[(DOMAIN, "NS")] = do.dns.resolver.NXDOMAIN()

    def test_sync(self, answers, flat):
        self.fill(answers)

        found = do._dns_fetch(DOMAIN, ("A", "TXT", "MX", "NS"))

        assert found == {"A": ["203.0.113.7"], "TXT": ["v=spf1 -all"]}
        assert "MX:" in flat()

    def test_async(self, answers):
        self.fill(answers)

        found = run(do._dns_fetch_async(DOMAIN, ("A", "TXT", "MX", "NS")))

        assert found == {"A": ["203.0.113.7"], "TXT": ["v=spf1 -all"]}

    def test_async_records_are_cached_per_type(self, answers, cache):
        answers[(DOMAIN, "A")] = [Rdata("203.0.113.7")]

        first = run(do._dns_records_async(DOMAIN, ("A", "MX")))
        answers[(DOMAIN, "A")] = [Rdata("198.51.100.1")]
        second = run(do._dns_records_async(DOMAIN, ("A", "MX")))

        assert first == second == {"A": ["203.0.113.7"]}

    def test_no_records_is_said_plainly(self, answers, cache, flat):
        assert do.dns_records(DOMAIN, ("A",)) == {}
        assert "No DNS records returned" in flat()


class TestEmailSecurity:
    def fill(self, answers):
        answers[(DOMAIN, "TXT")] = [
            Rdata("ignored", strings=[b"v=spf1 ", b"include:_spf.acme.test -all"]),
            Rdata("ignored", strings=[b"google-site-verification=1"]),
        ]
        answers[(f"_dmarc.{DOMAIN}", "TXT")] = [Rdata('"v=DMARC1; p=reject"')]
        answers[(f"google._domainkey.{DOMAIN}", "TXT")] = [Rdata("k=rsa; p=MIGf")]

    EXPECTED = {"spf": "v=spf1 include:_spf.acme.test -all", "dmarc": "v=DMARC1; p=reject",
                "dkim_selectors": ["google"]}

    def test_sync(self, answers, flat):
        self.fill(answers)

        assert do.email_security(DOMAIN) == self.EXPECTED
        assert "v=DMARC1; p=reject" in flat()

    def test_async(self, answers):
        self.fill(answers)

        assert run(do._email_security_fetch_async(DOMAIN)) == self.EXPECTED

    def test_missing_records_are_flagged(self, answers, flat):
        assert do.email_security(DOMAIN) == {"spf": None, "dmarc": None, "dkim_selectors": []}
        out = flat()
        assert "missing" in out and "no common selectors found" in out


class TestWithoutDnspython:
    def test_every_dns_tool_says_what_to_install(self, monkeypatch, flat):
        monkeypatch.setattr(do, "_HAS_DNS", False)

        assert do._dns_fetch(DOMAIN, ("A",)) == {}
        assert do.email_security(DOMAIN) == {}
        assert do._email_security_fetch(DOMAIN) == {}
        assert run(do._dns_fetch_async(DOMAIN, ("A",))) == {}
        assert run(do._email_security_fetch_async(DOMAIN)) == {}
        assert flat().count("pip install dnspython") == 2


# ---------------------------------------------------------------------------
# WHOIS
# ---------------------------------------------------------------------------

class TestWhois:
    @pytest.mark.parametrize("lookup, message", [
        (lambda domain: (_ for _ in ()).throw(OSError("connection refused")),
         "WHOIS lookup failed: connection refused"),
        (lambda domain: SimpleNamespace(domain_name=None), "No WHOIS data returned"),
    ])
    def test_failures_give_no_data(self, monkeypatch, flat, lookup, message):
        monkeypatch.setattr(do, "_HAS_WHOIS", True)
        monkeypatch.setattr(do, "whois", SimpleNamespace(whois=lookup), raising=False)

        assert do._whois_fetch(DOMAIN) == {}
        assert message in flat()

    def test_without_python_whois(self, monkeypatch, flat):
        monkeypatch.setattr(do, "_HAS_WHOIS", False)

        assert do._whois_fetch(DOMAIN) == {}
        assert "pip install python-whois" in flat()

    def test_async_lookup_caches_only_found_data(self, monkeypatch, cache):
        fetched = []
        replies = [{}, {"domain": DOMAIN, "registrar": "R"}]

        def fetch(domain):
            fetched.append(domain)
            return replies[len(fetched) - 1]

        monkeypatch.setattr(do, "_whois_fetch", fetch)

        assert run(do._whois_lookup_async(DOMAIN)) == {}
        assert run(do._whois_lookup_async(DOMAIN))["registrar"] == "R"
        assert run(do._whois_lookup_async(DOMAIN))["registrar"] == "R"
        assert len(fetched) == 2

    def test_single_status_and_email_are_shown(self, flat):
        do._render_whois_body({"domain": DOMAIN, "status": "clientTransferProhibited",
                               "emails": "abuse@registrar.test"})
        do._render_whois_body({})

        out = flat()
        assert "clientTransferProhibited" in out and "abuse@registrar.test" in out


# ---------------------------------------------------------------------------
# Resolution and TLS
# ---------------------------------------------------------------------------

class TestResolution:
    def test_first_ip(self, monkeypatch):
        monkeypatch.setattr(do.socket, "gethostbyname", lambda domain: "203.0.113.7")
        assert do._resolve_first_ip(DOMAIN) == "203.0.113.7"

        def unknown(domain):
            raise OSError("Name or service not known")

        monkeypatch.setattr(do.socket, "gethostbyname", unknown)
        assert do._resolve_first_ip(DOMAIN) is None

    @pytest.mark.parametrize("dns, ip", [
        ({"A": ["203.0.113.7", "203.0.113.8"]}, "203.0.113.7"),
        ({"A": []}, None),
        ({}, None),
        (None, None),
    ])
    def test_first_a_record(self, dns, ip):
        assert do._first_a(dns) == ip


class TestTls:
    def test_handshake_failure(self, monkeypatch, flat):
        def refused(address, timeout=None):
            raise ConnectionRefusedError("connection refused")

        monkeypatch.setattr(do.socket, "create_connection", refused)

        assert do.tls_certificate(DOMAIN) == {}
        assert "TLS handshake failed: connection refused" in flat()

    def test_unreadable_expiry_date(self, monkeypatch):
        class SSLSock:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def getpeercert(self): return {"notAfter": "soon"}
            def cipher(self): return None
            def version(self): return "TLSv1.2"

        class Sock:
            def __enter__(self): return self
            def __exit__(self, *args): return False

        monkeypatch.setattr(do.ssl, "create_default_context",
                            lambda: SimpleNamespace(wrap_socket=lambda sock, server_hostname: SSLSock()))
        monkeypatch.setattr(do.socket, "create_connection", lambda address, timeout=None: Sock())

        info = do._tls_fetch(DOMAIN)

        assert (info["days_left"], info["cipher"], info["san"]) == (None, None, [])

    @pytest.mark.parametrize("days, cell", [
        (-3, "[red]expired[/red]"), (29, "[yellow]29[/yellow]"), (30, "30"), (None, "—")])
    def test_days_left_cell(self, monkeypatch, days, cell):
        rows = {}

        class Table:
            def add_row(self, field, value):
                rows[field] = value

        monkeypatch.setattr(do, "make_table", lambda *args, **kwargs: Table())
        monkeypatch.setattr(do.console, "print", lambda *args, **kwargs: None)

        do._render_tls_body(DOMAIN, 443, {"days_left": days, "tls_version": "TLSv1.3",
                                          "cipher": "TLS_AES_128_GCM_SHA256"})

        assert rows["Days left"] == cell
        assert rows["TLS"] == "TLSv1.3  TLS_AES_128_GCM_SHA256"

    def test_nothing_to_render(self, flat):
        do._render_tls_body(DOMAIN, 443, {})
        assert flat() == ""


# ---------------------------------------------------------------------------
# aiohttp stand-in
# ---------------------------------------------------------------------------

class Response:
    def __init__(self, status=200, text="", payload=None, url="https://acme.test/",
                 headers=None):
        self.status, self._text, self._payload = status, text, payload
        self.url, self.headers = url, headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return self._text

    async def json(self, content_type=None):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


@pytest.fixture
def session(monkeypatch):
    """Replaces aiohttp.ClientSession; ``routes`` maps head/get to a Response or an exception."""
    routes: dict = {}

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def _answer(self, method):
            answer = routes[method]
            if isinstance(answer, BaseException):
                raise answer
            return answer

        def head(self, url, **kwargs):
            return self._answer("head")

        def get(self, url, **kwargs):
            return self._answer("get")

    monkeypatch.setattr(do, "_HAS_AIOHTTP", True)
    monkeypatch.setattr(do.aiohttp, "ClientSession", Session)
    return routes


class TestHttpHeaders:
    def test_sync_request_failure(self, monkeypatch, flat):
        def refused(*args, **kwargs):
            raise requests.exceptions.ConnectionError("connection refused")

        monkeypatch.setattr(do.requests, "head", refused)

        assert do.http_security_headers("https://acme.test") == {}
        assert "HTTP request failed: connection refused" in flat()

    def test_async_head(self, session):
        session["head"] = Response(200, headers={"Server": "nginx"})

        assert run(do._http_headers_fetch_async("https://acme.test")) == {
            "url": "https://acme.test/", "status": 200, "headers": {"Server": "nginx"}}

    def test_async_falls_back_to_get(self, session):
        session["head"] = Response(405)
        session["get"] = Response(200, url="https://acme.test/home")

        assert run(do._http_headers_fetch_async("https://acme.test"))["url"] == (
            "https://acme.test/home")

    @pytest.mark.parametrize("failure, reason", [
        (aiohttp.ClientConnectionError("refused"), "refused"),
        (asyncio.TimeoutError(), "timeout"),
    ])
    def test_async_failures(self, session, failure, reason):
        session["head"] = failure

        assert run(do._http_headers_fetch_async("https://acme.test")) == {"_error": reason}

    def test_async_without_aiohttp_uses_a_thread(self, monkeypatch):
        monkeypatch.setattr(do, "_HAS_AIOHTTP", False)
        monkeypatch.setattr(do, "_http_headers_fetch", lambda url: {"url": url, "status": 200})

        assert run(do._http_headers_fetch_async("https://acme.test"))["status"] == 200


class TestCrtShAsync:
    def test_subdomains_are_parsed_and_cached(self, session, cache):
        session["get"] = Response(200, text=json.dumps(
            [{"name_value": "dev.acme.test\n*.acme.test"}, {"name_value": "other.test"}]))

        first = run(do._crtsh_fetch_async(DOMAIN))
        session["get"] = Response(500)
        second = run(do._crtsh_fetch_async(DOMAIN))

        assert first == second == {"subdomains": ["acme.test", "dev.acme.test"]}

    @pytest.mark.parametrize("answer, reason", [
        (Response(404), "HTTP 404"),
        (Response(200, text="<html>slow down</html>"), "non-JSON (likely rate-limited)"),
        (aiohttp.ClientConnectionError("refused"), "transport: refused"),
        (asyncio.TimeoutError(), "transport: timeout"),
    ])
    def test_failures_are_not_cached(self, session, cache, answer, reason):
        session["get"] = answer

        assert run(do._crtsh_fetch_async(DOMAIN)) == {"_error": reason, "subdomains": []}
        assert cache.get("crtsh", cache.make_key(DOMAIN, 0)) is None

    def test_without_aiohttp_uses_the_sync_fetch(self, monkeypatch, cache):
        monkeypatch.setattr(do, "_HAS_AIOHTTP", False)
        monkeypatch.setattr(do, "_crtsh_fetch",
                            lambda domain, timeout, wildcards: {"subdomains": ["x.acme.test"]})

        assert run(do._crtsh_fetch_async(DOMAIN)) == {"subdomains": ["x.acme.test"]}

    def test_long_lists_are_cut_on_screen(self, flat):
        subs = [f"h{n}.acme.test" for n in range(205)]

        assert do._render_subdomains_body(DOMAIN, {"subdomains": subs}) == subs
        assert "(+5 more not shown)" in flat()

    def test_failure_is_reported(self, flat):
        assert do._render_subdomains_body(DOMAIN, {"_error": "HTTP 503"}) == []
        assert "crt.sh request failed: HTTP 503" in flat()


# ---------------------------------------------------------------------------
# Shodan
# ---------------------------------------------------------------------------

class TestShodan:
    @pytest.fixture(autouse=True)
    def key(self, monkeypatch):
        monkeypatch.setenv("SHODAN_API_KEY", "key")

    @pytest.mark.parametrize("reply, reason", [
        (requests.exceptions.ConnectionError("refused"), "refused"),
        (SimpleNamespace(status_code=500, text="server boom"), "500: server boom"),
        (SimpleNamespace(status_code=200, text="",
                         json=lambda: (_ for _ in ()).throw(ValueError("bad"))), "non-JSON"),
    ])
    def test_sync_failures(self, monkeypatch, reply, reason):
        def get(*args, **kwargs):
            if isinstance(reply, BaseException):
                raise reply
            return reply

        monkeypatch.setattr(do.requests, "get", get)

        assert do._shodan_fetch.__wrapped__("203.0.113.7") == {"_error": reason}

    @pytest.mark.parametrize("answer, result", [
        (Response(404), {"_error": "404"}),
        (Response(500, text="server boom"), {"_error": "500: server boom"}),
        (Response(200, payload={"org": "Acme"}), {"org": "Acme"}),
        (Response(200, payload=ValueError("bad")), {"_error": "non-JSON"}),
        (aiohttp.ClientConnectionError("refused"), {"_error": "refused"}),
        (asyncio.TimeoutError(), {"_error": "timeout"}),
    ])
    def test_async(self, session, answer, result):
        session["get"] = answer

        assert run(do._shodan_fetch_async.__wrapped__("203.0.113.7")) == result

    def test_async_without_a_key(self, monkeypatch):
        monkeypatch.delenv("SHODAN_API_KEY")

        assert run(do._shodan_fetch_async.__wrapped__("203.0.113.7")) == {"_error": "no_key"}

    def test_async_without_aiohttp_uses_a_thread(self, monkeypatch):
        monkeypatch.setattr(do, "_HAS_AIOHTTP", False)
        monkeypatch.setattr(do.requests, "get",
                            lambda *args, **kwargs: SimpleNamespace(status_code=404, text=""))

        assert run(do._shodan_fetch_async.__wrapped__("203.0.113.7")) == {"_error": "404"}

    def test_other_failures_are_reported(self, flat):
        assert do._render_shodan_body("203.0.113.7", {"_error": "500: server boom"}) == {}
        assert "Shodan: 500: server boom" in flat()


# ---------------------------------------------------------------------------
# Parallel recon
# ---------------------------------------------------------------------------

@pytest.fixture
def probes(monkeypatch):
    """Each probe of the parallel recon answers from ``replies``; an exception is raised."""
    replies = {
        "whois": {"domain": DOMAIN, "registrar": "R"},
        "dns": {"A": ["203.0.113.7"]},
        "mail": {"spf": "v=spf1 -all", "dmarc": None, "dkim_selectors": []},
        "tls": {"san": [DOMAIN], "days_left": 90, "tls_version": "TLSv1.3"},
        "headers": {"url": "https://acme.test", "status": 200, "headers": {}},
        "subs": {"subdomains": ["dev.acme.test"]},
        "shodan": {"org": "Acme", "hostnames": ["edge.acme.test"]},
    }

    def answer(name):
        reply = replies[name]
        if isinstance(reply, BaseException):
            raise reply
        return reply

    async def async_answer(name, *args):
        return answer(name)

    monkeypatch.setattr(do, "_whois_lookup_async", lambda d: async_answer("whois"))
    monkeypatch.setattr(do, "_dns_records_async", lambda d: async_answer("dns"))
    monkeypatch.setattr(do, "_email_security_fetch_async", lambda d: async_answer("mail"))
    monkeypatch.setattr(do, "_tls_fetch", lambda host, port, timeout: answer("tls"))
    monkeypatch.setattr(do, "_http_headers_fetch_async", lambda url: async_answer("headers"))
    monkeypatch.setattr(do, "_crtsh_fetch_async", lambda d: async_answer("subs"))
    monkeypatch.setattr(do, "_shodan_fetch_async", lambda ip: async_answer("shodan"))
    monkeypatch.setattr(do, "_resolve_first_ip", lambda d: None)
    monkeypatch.delenv("SHODAN_API_KEY", raising=False)
    return replies


class TestParallelRecon:
    def test_shodan_uses_the_first_a_record(self, probes):
        report = do.domain_recon(DOMAIN, include_shodan=True)

        assert report["shodan"] == {"org": "Acme", "hostnames": ["edge.acme.test"]}

    def test_shodan_runs_when_its_key_is_set(self, probes, monkeypatch):
        monkeypatch.setenv("SHODAN_API_KEY", "key")

        assert "shodan" in do.domain_recon(DOMAIN)

    def test_shodan_without_an_ip_is_skipped(self, probes, flat):
        probes["dns"] = {}

        report = do.domain_recon(DOMAIN, include_shodan=True)

        assert "shodan" not in report
        assert "Could not resolve target to an IP" in flat()

    def test_a_probe_that_raises_leaves_an_empty_entry(self, probes, flat):
        for name in ("whois", "dns", "mail", "tls", "headers", "subs"):
            probes[name] = RuntimeError(f"{name} down")

        report = do.domain_recon(DOMAIN)

        assert report == {"target": DOMAIN, "whois": {}, "dns": {}, "email_security": {},
                          "tls": {}, "headers": {}, "subdomains": []}
        out = flat()
        for message in ("WHOIS failed: whois down", "DNS failed: dns down",
                        "Email security failed: mail down", "TLS failed: tls down",
                        "HTTP headers failed: headers down", "crt.sh failed: subs down"):
            assert message in out

    def test_tls_failure_and_missing_dnspython(self, probes, monkeypatch, flat):
        monkeypatch.setattr(do, "_HAS_DNS", False)
        probes["tls"] = {"_error": "connection refused"}

        report = do.domain_recon(DOMAIN)

        assert report["tls"] == report["email_security"] == {}
        out = flat()
        assert "TLS handshake failed: connection refused" in out
        assert "pip install dnspython" in out

    def test_empty_target(self, flat):
        assert do.domain_recon("  ") == {}
        assert "Target cannot be empty" in flat()


class TestCrtShSync:
    @pytest.mark.parametrize("reply, reason", [
        (requests.exceptions.ConnectionError("refused"), "transport: refused"),
        (SimpleNamespace(status_code=200, headers={},
                         json=lambda: (_ for _ in ()).throw(ValueError("bad"))),
         "non-JSON (likely rate-limited)"),
    ])
    def test_failures_are_not_cached(self, monkeypatch, cache, reply, reason):
        def get(*args, **kwargs):
            if isinstance(reply, BaseException):
                raise reply
            return reply

        monkeypatch.setattr(do.requests, "get", get)

        assert do._crtsh_fetch(DOMAIN) == {"_error": reason, "subdomains": []}
        assert cache.get("crtsh", cache.make_key(DOMAIN, 0)) is None
