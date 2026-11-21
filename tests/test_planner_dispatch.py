"""
Every planner tool dispatcher: a missing argument, a tool that fails or finds
nothing, and the summary and data the model reads when it works.
"""

import pytest

from core import planner, state
from core.findings import FindingsHub


@pytest.fixture(autouse=True)
def hub(monkeypatch):
    hub = FindingsHub()
    monkeypatch.setattr(planner, "get_hub", lambda: hub)
    monkeypatch.setattr(state, "LAST_RESULTS", [])
    monkeypatch.setattr(state, "CURRENT_CASE",
                        {"search_params": {}, "results": [], "evidence": [], "investigation": None})
    return hub


def dispatch(tool, agent=None, **args):
    return planner.TOOL_DISPATCH[tool](args, agent)


def returns(value):
    return lambda *args, **kwargs: value


def fails(*args, **kwargs):
    raise RuntimeError("service down")


def test_every_catalog_tool_has_a_dispatcher():
    assert set(planner.TOOL_CATALOG) == set(planner.TOOL_DISPATCH)


def test_plan_step_round_trip():
    step = planner.PlanStep.from_dict({"tool": " whois ", "args": "bad", "rationale": " lead "})

    assert step.to_dict() == {"tool": "whois", "args": {}, "rationale": "lead"}


@pytest.mark.parametrize("tool, message", [
    ("search", "search: missing 'query'"),
    ("deep_search", "deep_search: missing 'query'"),
    ("extract_pii", "extract_pii: missing 'url'"),
    ("tech_scan", "tech_scan: missing 'url'"),
    ("username_enum", "username_enum: missing 'username'"),
    ("email_enum", "email_enum: missing 'email'"),
    ("phone_osint", "phone_osint: missing 'phone'"),
    ("screenshot", "screenshot: missing 'url'"),
    ("wayback", "wayback: missing 'url'"),
    ("wayback_fetch", "wayback_fetch: missing 'url'"),
    ("wayback_extract", "wayback_extract: missing 'url'"),
    ("wayback_diff", "wayback_diff: requires 'url', 'ts_a', 'ts_b'"),
    ("summarize_url", "summarize_url: missing 'url'"),
    ("domain_recon", "domain_recon: missing 'target'"),
    ("whois", "whois: missing 'domain'"),
    ("dns_records", "dns_records: missing 'domain'"),
    ("tls_certificate", "tls_certificate: missing 'host'"),
    ("http_security_headers", "http_security_headers: missing 'url'"),
    ("subdomains", "subdomains: missing 'domain'"),
    ("reverse_image", "reverse_image: missing 'url'"),
    ("hibp_account", "hibp_account: missing 'email'"),
    ("hibp_domain", "hibp_domain: missing 'domain'"),
    ("hibp_breach", "hibp_breach: missing 'name'"),
    ("hibp_password", "hibp_password: provide either 'password' or 'sha1'"),
])
def test_missing_argument_is_a_failed_step(tool, message):
    assert dispatch(tool, **{"query": "  "} if "search" in tool else {}) == {
        "status": "error", "summary": message}


@pytest.mark.parametrize("tool, patched, args, message", [
    ("tech_scan", "analysis.tech_scanner.tech_scan", {"url": "u"}, "tech_scan failed"),
    ("username_enum", "search.username_enum.username_enum", {"username": "alee"},
     "username_enum failed"),
    ("email_enum", "search.email_enum.email_enum", {"email": "a@b.test"}, "email_enum failed"),
    ("phone_osint", "search.phone_osint.phone_lookup", {"phone": "1"}, "phone_osint failed"),
    ("screenshot", "analysis.advanced_osint.take_screenshot", {"url": "u"}, "screenshot failed"),
    ("wayback", "analysis.advanced_osint.check_wayback_machine", {"url": "u"}, "wayback failed"),
    ("domain_recon", "analysis.domain_osint.domain_recon", {"target": "acme.test"},
     "domain_recon failed"),
    ("reverse_image", "search.reverse_image_engines.reverse_image_aggregate", {"url": "u"},
     "reverse_image failed"),
    ("deep_search", "cli.actions.do_deep_search", {"query": "acme"}, "deep_search failed"),
])
def test_tool_exception_is_a_failed_step(monkeypatch, tool, patched, args, message):
    monkeypatch.setattr("search.email_enum.HOLEHE_AVAILABLE", True)
    monkeypatch.setattr(patched, fails)

    assert dispatch(tool, **args) == {"status": "error", "summary": f"{message}: service down"}


@pytest.mark.parametrize("tool, patched, args, message", [
    ("username_enum", "search.username_enum.username_enum", {"username": "alee"},
     "username_enum: no backend installed or empty input"),
    ("email_enum", "search.email_enum.email_enum", {"email": "a@b.test"},
     "email_enum: holehe could not check any service for a@b.test"),
    ("phone_osint", "search.phone_osint.phone_lookup", {"phone": "12"},
     "phone_osint: could not parse '12' as a number"),
    ("screenshot", "analysis.advanced_osint.take_screenshot", {"url": "u"},
     "screenshot failed for u"),
    ("wayback", "analysis.advanced_osint.check_wayback_machine", {"url": "u"},
     "wayback lookup failed for u"),
    ("whois", "analysis.domain_osint.whois_lookup", {"domain": "acme.test"},
     "whois: no data for acme.test"),
    ("dns_records", "analysis.domain_osint.dns_records", {"domain": "acme.test"},
     "dns: no records for acme.test"),
    ("tls_certificate", "analysis.domain_osint.tls_certificate", {"host": "acme.test"},
     "tls: handshake failed for acme.test:443"),
    ("http_security_headers", "analysis.domain_osint.http_security_headers", {"url": "u"},
     "headers: request failed for u"),
    ("wayback_fetch", "analysis.advanced_osint.wayback_fetch_snapshot", {"url": "u"},
     "wayback_fetch: no snapshot for u"),
    ("wayback_extract", "analysis.advanced_osint.wayback_extract_pii", {"url": "u"},
     "wayback_extract: no content for u @ latest"),
    ("wayback_diff", "analysis.advanced_osint.wayback_diff",
     {"url": "u", "ts_a": "2020", "ts_b": "2024"},
     "wayback_diff: could not fetch one or both snapshots"),
    ("hibp_breach", "analysis.hibp.hibp_breach", {"name": "Nope"},
     "hibp_breach: no record for 'Nope'"),
    ("deep_search", "cli.actions.do_deep_search", {"query": "acme"}, "deep search failed"),
])
def test_tool_with_nothing_to_report_is_a_failed_step(monkeypatch, tool, patched, args, message):
    monkeypatch.setattr("search.email_enum.HOLEHE_AVAILABLE", True)
    monkeypatch.setattr(patched, returns(None))

    assert dispatch(tool, **args) == {"status": "error", "summary": message}


class TestPageTools:
    def test_extract_pii_records_evidence(self, monkeypatch, hub):
        monkeypatch.setattr("analysis.web_analyzer.get_text_from_url",
                            returns("Mail ana@acme.test or bob@acme.test"))

        result = dispatch("extract_pii", url="https://acme.test")

        assert result["summary"] == "extracted: emails×2"
        assert len(state.CURRENT_CASE["evidence"]) == 2
        assert len(hub.of_kind("email")) == 2

    @pytest.mark.parametrize("text, expected", [
        ("", {"status": "error", "summary": "could not fetch https://acme.test"}),
        ("Nothing here.", {"status": "ok", "summary": "https://acme.test: no identifiers found",
                           "data": {}}),
    ])
    def test_extract_pii_without_identifiers(self, monkeypatch, text, expected):
        monkeypatch.setattr("analysis.web_analyzer.get_text_from_url", returns(text))

        assert dispatch("extract_pii", url="https://acme.test") == expected

    def test_tech_scan_with_nothing_detected(self, monkeypatch):
        monkeypatch.setattr("analysis.tech_scanner.tech_scan", returns(("WebTech", [])))

        result = dispatch("tech_scan", url="https://acme.test")

        assert result["summary"] == "tech_scan https://acme.test: 0 technologies (nothing detected)"

    def test_screenshot(self, monkeypatch):
        monkeypatch.setattr("analysis.advanced_osint.take_screenshot", returns("shot.png"))

        assert dispatch("screenshot", url="u")["data"] == {"path": "shot.png"}

    def test_summarize_url(self, monkeypatch):
        monkeypatch.setattr("analysis.web_analyzer.get_text_from_url", returns("page"))
        monkeypatch.setattr("analysis.web_analyzer.summarize_text_with_ia", returns("x" * 300))

        result = dispatch("summarize_url", agent="agent", url="u")

        assert result["status"] == "ok"
        assert len(result["summary"]) < 250
        assert result["data"]["full"] == "x" * 300

    @pytest.mark.parametrize("agent, text, summarize, message", [
        (None, "page", None, "summarize_url: no AI agent available"),
        ("agent", "", None, "could not fetch u"),
        ("agent", "page", fails, "summarize failed: service down"),
    ])
    def test_summarize_url_failures(self, monkeypatch, agent, text, summarize, message):
        monkeypatch.setattr("analysis.web_analyzer.get_text_from_url", returns(text))
        if summarize:
            monkeypatch.setattr("analysis.web_analyzer.summarize_text_with_ia", summarize)

        assert dispatch("summarize_url", agent=agent, url="u") == {
            "status": "error", "summary": message}


class TestIdentityTools:
    def test_username_enum_counts_claimed_accounts(self, monkeypatch, hub):
        monkeypatch.setattr("search.username_enum.username_enum", returns([
            {"site": "GitHub", "url": "https://github.test/alee", "status": "found"}]))

        result = dispatch("username_enum", username="alee", backend="Sherlock")

        assert result["summary"] == "username_enum: 1 claimed account(s) for @alee"
        assert [f.value for f in hub.of_kind("url")] == ["https://github.test/alee"]

    def test_email_enum_needs_holehe(self, monkeypatch):
        monkeypatch.setattr("search.email_enum.HOLEHE_AVAILABLE", False)

        assert dispatch("email_enum", email="a@b.test")["summary"] == (
            "email_enum: holehe not installed (pip install holehe)")

    @pytest.mark.parametrize("only_used, shown", [(True, 1), (False, 3)])
    def test_email_enum_warns_about_unchecked_services(self, monkeypatch, hub, only_used, shown):
        monkeypatch.setattr("search.email_enum.HOLEHE_AVAILABLE", True)
        monkeypatch.setattr("search.email_enum.email_enum", returns([
            {"service": "svc", "domain": "svc.test", "status": "claimed"},
            {"service": "slow", "domain": "slow.test", "status": "unchecked", "rate_limited": True},
            {"service": "free", "domain": "free.test", "status": "available"},
        ]))

        result = dispatch("email_enum", email="a@b.test", only_used=only_used)

        assert result["summary"] == (
            "email_enum: 1 service registration(s) found for a@b.test · 1 of 3 service(s) "
            "could not be checked, so the email may be registered there too")
        assert len(result["data"]["records"]) == shown
        assert [f.value for f in hub.of_kind("domain")] == ["svc.test"]

    def test_phone_osint_reads_the_number_offline(self, hub):
        result = dispatch("phone_osint", phone="+14155552671", region="us")

        assert result["summary"].startswith("phone_osint: +14155552671 is valid")
        assert [f.value for f in hub.of_kind("phone")] == ["+14155552671"]

    def test_reverse_image_counts_per_engine(self, monkeypatch):
        seen = []

        def aggregate(url, engines):
            seen.append(engines)
            return [{"engine": "tineye"}, {"engine": "tineye"}, {"engine": "manual"}]

        monkeypatch.setattr("search.reverse_image_engines.reverse_image_aggregate", aggregate)

        result = dispatch("reverse_image", image_url="https://img.test/a.png",
                          engines="tineye, manual,")

        assert seen == [["tineye", "manual"]]
        assert result["summary"] == "reverse_image: 3 entries (tineye×2, manual×1)"


class TestDomainTools:
    def test_recon_digest(self, monkeypatch, hub):
        monkeypatch.setattr("analysis.domain_osint.domain_recon", returns({
            "subdomains": ["dev.acme.test"], "headers": {"score": "4/7"},
            "dns": {"A": ["203.0.113.7"]}, "whois": {"registrar": "R"},
        }))

        result = dispatch("domain_recon", url="https://acme.test")

        assert result["summary"] == "recon complete · 1 subdomains · headers 4/7"
        assert result["data"]["subdomains"] == ["dev.acme.test"]
        assert [f.value for f in hub.of_kind("ip")] == ["203.0.113.7"]

    def test_whois_feeds_contact_emails(self, monkeypatch, hub):
        monkeypatch.setattr("analysis.domain_osint.whois_lookup", returns(
            {"registrar": "R", "expires": "2030-01-01", "emails": ["admin@acme.test"]}))

        result = dispatch("whois", target="acme.test")

        assert result["summary"] == "whois acme.test: registrar=R, expires=2030-01-01"
        assert [f.value for f in hub.of_kind("email")] == ["admin@acme.test"]

    def test_dns_records(self, monkeypatch):
        monkeypatch.setattr("analysis.domain_osint.dns_records",
                            returns({"A": ["203.0.113.7"], "MX": ["mx1", "mx2"]}))

        assert dispatch("dns_records", domain="acme.test")["summary"] == "dns A×1, MX×2"

    @pytest.mark.parametrize("port, used", [("8443", 8443), ("https", 443), (None, 443)])
    def test_tls_certificate_port(self, monkeypatch, hub, port, used):
        seen = []

        def certificate(host, port):
            seen.append(port)
            return {"days_left": 30, "tls_version": "TLSv1.3", "san": ["www.acme.test"]}

        monkeypatch.setattr("analysis.domain_osint.tls_certificate", certificate)

        result = dispatch("tls_certificate", domain="acme.test", port=port)

        assert seen == [used]
        assert result["summary"] == f"tls acme.test:{used} · expires in 30 days · TLSv1.3"
        assert [f.value for f in hub.of_kind("domain")] == ["acme.test"]

    def test_security_headers(self, monkeypatch):
        monkeypatch.setattr("analysis.domain_osint.http_security_headers",
                            returns({"score": "5/7"}))

        assert dispatch("http_security_headers", target="https://acme.test")["summary"] == (
            "headers 5/7 present")

    def test_subdomains(self, monkeypatch, hub):
        monkeypatch.setattr("analysis.domain_osint.subdomains_crtsh",
                            returns(["a.acme.test", "b.acme.test"]))

        result = dispatch("subdomains", domain="acme.test")

        assert result["summary"] == "2 subdomain(s) from crt.sh"
        assert len(hub.of_kind("domain")) == 2


class TestWaybackTools:
    @pytest.mark.parametrize("snapshots, summary", [
        ([], "wayback: no snapshots of u"),
        ([{"date": "2024-05-01"}, {"date": "2019-01-01"}],
         "wayback: 2 snapshots of u, newest 2024-05-01, oldest 2019-01-01"),
    ])
    def test_timeline(self, monkeypatch, snapshots, summary):
        monkeypatch.setattr("analysis.advanced_osint.check_wayback_machine", returns(snapshots))

        assert dispatch("wayback", url="u")["summary"] == summary

    def test_fetch_truncates_the_text(self, monkeypatch):
        monkeypatch.setattr("analysis.advanced_osint.wayback_fetch_snapshot", returns({
            "timestamp": "20200101000000", "date": "2020-01-01", "archive_url": "a",
            "mime": "text/html", "size": 9000, "text": "t" * 9000}))

        result = dispatch("wayback_fetch", url="u", timestamp="2020")

        assert result["summary"] == "snapshot 2020-01-01 · text/html · 9000 bytes"
        assert len(result["data"]["text"]) <= 4001

    @pytest.mark.parametrize("counts, summary", [
        ({"emails": 2}, "extracted from 2020-01-01: emails×2"),
        ({}, "extracted from 2020-01-01: no identifiers"),
    ])
    def test_extract(self, monkeypatch, counts, summary):
        monkeypatch.setattr("analysis.advanced_osint.wayback_extract_pii", returns({
            "date": "2020-01-01", "archive_url": "a", "counts": counts, "evidence": []}))

        assert dispatch("wayback_extract", url="u")["summary"] == summary

    @pytest.mark.parametrize("identical, suffix", [(True, " (identical)"), (False, "")])
    def test_diff(self, monkeypatch, identical, suffix):
        monkeypatch.setattr("analysis.advanced_osint.wayback_diff", returns({
            "date_a": "2020-01-01", "date_b": "2024-01-01", "added_count": 3,
            "removed_count": 1, "identical": identical}))

        result = dispatch("wayback_diff", url="u", ts_a="2020", ts_b="2024")

        assert result["summary"] == "2020-01-01 -> 2024-01-01: +3 -1" + suffix


class TestHibpTools:
    @pytest.fixture
    def hibp(self, monkeypatch):
        calls = []
        for name in ("render_breached_account", "render_pastes_for_account",
                     "render_breaches_for_domain", "render_password_pwned"):
            monkeypatch.setattr(f"analysis.hibp.{name}", lambda *args, n=name: calls.append(n))
        return calls

    @pytest.mark.parametrize("include, pastes, pasted", [
        (True, [{"Id": "p1"}], 1),
        ("false", [{"Id": "p1"}], 0),
        (True, None, 0),
    ])
    def test_account(self, monkeypatch, hub, hibp, include, pastes, pasted):
        monkeypatch.setattr("analysis.hibp.hibp_breached_account",
                            returns([{"Name": "Adobe", "BreachDate": "2013-10-04"}]))
        monkeypatch.setattr("analysis.hibp.hibp_pastes_for_account", returns(pastes))

        result = dispatch("hibp_account", email="ana@acme.test", include_pastes=include)

        assert result["summary"] == f"ana@acme.test: 1 breach(es), {pasted} paste(s)"
        assert [f.value for f in hub.of_kind("email")] == ["ana@acme.test"]

    def test_account_without_a_key(self, monkeypatch, hibp):
        monkeypatch.setattr("analysis.hibp.hibp_breached_account", returns(None))

        assert dispatch("hibp_account", email="a@b.test")["summary"] == (
            "hibp_account: API key missing or request failed")

    @pytest.mark.parametrize("breaches, result", [
        (None, {"status": "error", "summary": "hibp_domain: lookup failed for acme.test"}),
        ([], {"status": "ok", "summary": "acme.test: 0 breach(es) recorded",
              "data": {"domain": "acme.test", "breaches": []}}),
    ])
    def test_domain(self, monkeypatch, hibp, breaches, result):
        monkeypatch.setattr("analysis.hibp.hibp_breaches_for_domain", returns(breaches))

        assert dispatch("hibp_domain", domain="acme.test") == result
        assert hibp == ["render_breaches_for_domain"]

    def test_breach(self, monkeypatch):
        monkeypatch.setattr("analysis.hibp.hibp_breach", returns({
            "Name": "Adobe", "BreachDate": "2013-10-04", "PwnCount": 152445165,
            "DataClasses": ["Email addresses", "Passwords"]}))

        assert dispatch("hibp_breach", name="Adobe")["summary"] == (
            "Adobe (2013-10-04): 152,445,165 accounts, data classes: Email addresses, Passwords")

    @pytest.mark.parametrize("args, count, summary, via", [
        ({"sha1": "5BAA6"}, 3730471, "password seen 3,730,471 time(s) in HIBP corpus", "sha1"),
        ({"password": "correct horse"}, 0, "password not in any known HIBP breach", "password"),
    ])
    def test_password(self, monkeypatch, hibp, args, count, summary, via):
        monkeypatch.setattr("analysis.hibp.hibp_password_pwned_hash", returns(count))
        monkeypatch.setattr("analysis.hibp.hibp_password_pwned", returns(count))

        result = dispatch("hibp_password", **args)

        assert (result["summary"], result["data"]["via"]) == (summary, via)

    def test_password_lookup_failure(self, monkeypatch, hibp):
        monkeypatch.setattr("analysis.hibp.hibp_password_pwned_hash", returns(None))

        assert dispatch("hibp_password", sha1="5BAA6") == {
            "status": "error", "summary": "hibp_password: lookup failed"}


def test_search_pages_that_are_not_a_number_mean_one(monkeypatch):
    seen = []
    monkeypatch.setattr("cli.actions.get_search_engine",
                        lambda engine, pages, start, query: seen.append(pages) or [])

    dispatch("search", query="acme", pages="two")

    assert seen == [1]
