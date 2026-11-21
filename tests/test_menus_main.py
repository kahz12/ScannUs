"""The main menu and its tool runners, driven through a scripted terminal."""

from types import SimpleNamespace

import pytest

from cli import actions, menus
from core import ai_agent, state


# ---------------------------------------------------------------------------
# AI provider picker
# ---------------------------------------------------------------------------

class TestSelectAgent:
    @pytest.mark.parametrize("answer", ["cancel", None])
    def test_cancel_gives_no_agent(self, tui, answer):
        tui.script(answer)

        assert menus.select_ia_agent() is None

    def test_gemini_needs_its_key(self, tui, monkeypatch, flat):
        monkeypatch.delenv("GOOGLE_API_KEY_FOR_GEMINI", raising=False)
        tui.script("ge")

        assert menus.select_ia_agent() is None
        assert "GOOGLE_API_KEY_FOR_GEMINI is missing" in flat()

    def test_gemini(self, tui, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY_FOR_GEMINI", "key")
        tui.script("ge")

        assert type(menus.select_ia_agent().generator).__name__ == "GeminiGenerator"

    def test_openai_without_a_key_opens_its_setup(self, tui, monkeypatch, record):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr("openai.OpenAI", lambda timeout: SimpleNamespace())
        setup = record()
        monkeypatch.setattr(menus, "openai_config", setup)
        tui.script("op")

        agent = menus.select_ia_agent()

        assert type(agent.generator).__name__ == "OpenAIGenerator"
        assert len(setup.calls) == 1

    def test_claude_needs_its_key(self, tui, monkeypatch, flat):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        tui.script("claude")

        assert menus.select_ia_agent() is None
        assert "ANTHROPIC_API_KEY is missing" in flat()

    def test_claude(self, tui, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        monkeypatch.setattr("anthropic.Anthropic", lambda api_key, timeout: SimpleNamespace())
        tui.script("claude")

        assert type(menus.select_ia_agent().generator).__name__ == "AnthropicGenerator"

    def test_claude_that_cannot_start_gives_no_agent(self, tui, monkeypatch, flat):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")

        class Broken(ai_agent.AnthropicGenerator):
            def __init__(self, *args, **kwargs):
                raise RuntimeError("anthropic SDK not installed")

        monkeypatch.setattr(ai_agent, "AnthropicGenerator", Broken)
        tui.script("claude")

        assert menus.select_ia_agent() is None
        assert "anthropic SDK not installed" in flat()

    @pytest.mark.parametrize("reachable", [True, False])
    def test_ollama_needs_its_daemon(self, tui, monkeypatch, reachable):
        monkeypatch.setattr("core.providers.ollama_provider.OllamaGenerator._ping",
                            lambda self: reachable)
        tui.script("ollama")

        agent = menus.select_ia_agent()

        assert (agent is not None) is reachable

    def test_ollama_that_cannot_start_gives_no_agent(self, tui, monkeypatch, flat):
        def broken(*args, **kwargs):
            raise OSError("bad OLLAMA_HOST")

        monkeypatch.setattr(ai_agent, "OllamaGenerator", broken)
        tui.script("ollama")

        assert menus.select_ia_agent() is None
        assert "Ollama init failed: bad OLLAMA_HOST" in flat()


# ---------------------------------------------------------------------------
# Main menu dispatch
# ---------------------------------------------------------------------------

RUNNERS = [
    "_run_guided_search", "_run_direct_search", "_run_tech_scan", "_run_username_enum",
    "_run_email_enum", "_run_phone_osint", "_run_domain_recon", "_run_hibp_menu",
    "findings_hub_menu", "_offer_hub", "delete_case_prompt", "env_config", "openai_config",
    "select_ia_agent", "load_case", "interactive_analysis_menu",
]


@pytest.fixture
def runners(monkeypatch, record):
    """Replaces every tool the main menu starts; returns the stand-ins by name."""
    fakes = {name: record(True) for name in RUNNERS}
    for name, fake in fakes.items():
        monkeypatch.setattr(menus, name, fake)
    for name in ("do_generate_dork_ia", "do_query_planner"):
        fakes[name] = record()
        monkeypatch.setattr(actions, name, fakes[name])
    fakes["do_reverse_image_search"] = record(True)
    monkeypatch.setattr("search.reverse_image.do_reverse_image_search",
                        fakes["do_reverse_image_search"])
    return fakes


class TestMainMenu:
    @pytest.mark.parametrize("choice, started", [
        ("guided",      ["_run_guided_search"]),
        ("direct",      ["_run_direct_search"]),
        ("dork",        ["do_generate_dork_ia"]),
        ("planner",     ["do_query_planner"]),
        ("hub",         ["findings_hub_menu"]),
        ("reverse",     ["do_reverse_image_search", "_offer_hub"]),
        ("tech",        ["_run_tech_scan"]),
        ("user-enum",   ["_run_username_enum"]),
        ("email-enum",  ["_run_email_enum"]),
        ("phone-osint", ["_run_phone_osint"]),
        ("recon",       ["_run_domain_recon"]),
        ("hibp",        ["_run_hibp_menu"]),
        ("load",        ["select_ia_agent", "load_case", "interactive_analysis_menu"]),
        ("del-case",    ["delete_case_prompt"]),
        ("config",      ["env_config", "openai_config"]),
    ])
    def test_each_choice_starts_its_tool(self, tui, menu_hub, runners, choice, started):
        tui.script(choice, "exit")

        menus.show_main_menu()

        assert sorted(name for name, fake in runners.items() if fake.calls) == sorted(started)

    @pytest.mark.parametrize("leave", ["exit", None])
    def test_exit_and_esc_close_the_session(self, tui, menu_hub, runners, flat, leave):
        tui.script(leave)

        menus.show_main_menu()

        assert "Session closed" in flat()

    def test_footer_shows_the_findings(self, tui, menu_hub, flat):
        menu_hub.add_email("ana@site.test", source="test")
        tui.script("exit")

        menus.show_main_menu()

        assert "1 email" in flat()


# ---------------------------------------------------------------------------
# Breach & leak check
# ---------------------------------------------------------------------------

@pytest.fixture
def hibp(monkeypatch, record):
    fakes = SimpleNamespace(
        check_account=record(), check_domain=record(), check_password=record(),
        hibp_breach=record(), offer=record(),
    )
    for name in ("check_account", "check_domain", "check_password", "hibp_breach"):
        monkeypatch.setattr(f"analysis.hibp.{name}", getattr(fakes, name))
    monkeypatch.setattr(menus, "_offer_hub", fakes.offer)
    return fakes


class TestHibpMenu:
    def test_email_check_feeds_the_hub(self, tui, menu_hub, hibp):
        tui.script("email", "Ana@Site.test", False, "back")

        menus._run_hibp_menu()

        assert hibp.check_account.calls == [(("Ana@Site.test",), {"include_pastes": False})]
        assert [f.value for f in menu_hub.of_kind("email")] == ["ana@site.test"]
        assert len(hibp.offer.calls) == 1

    def test_domain_check_feeds_the_hub(self, tui, menu_hub, hibp):
        tui.script("domain", "acme.test", "back")

        menus._run_hibp_menu()

        assert hibp.check_domain.calls == [(("acme.test",), {})]
        assert [f.value for f in menu_hub.of_kind("domain")] == ["acme.test"]

    def test_empty_answers_are_refused(self, tui, menu_hub, hibp, flat):
        tui.script("email", "", "domain", "", "breach", "", None)

        menus._run_hibp_menu()

        out = flat()
        for message in ("Email cannot be empty", "Domain cannot be empty",
                        "Breach name cannot be empty"):
            assert message in out
        assert not (hibp.check_account.calls or hibp.check_domain.calls)

    def test_breach_details_are_shown(self, tui, menu_hub, monkeypatch, hibp, flat, record):
        monkeypatch.setattr("analysis.hibp.hibp_breach", record({
            "Name": "Adobe", "BreachDate": "2013-10-04", "Domain": "adobe.com",
            "PwnCount": 152445165, "IsVerified": True, "IsSensitive": False,
            "DataClasses": ["Email addresses", "Passwords"],
            "Description": "Customer records were leaked.",
        }))
        tui.script("breach", "Adobe", "back")

        menus._run_hibp_menu()

        out = flat()
        assert "152,445,165" in out
        assert "Email addresses, Passwords" in out
        assert "Customer records were leaked." in out

    def test_unknown_breach_is_reported(self, tui, menu_hub, hibp, flat):
        tui.script("breach", "Nope", "back")

        menus._run_hibp_menu()

        assert "No record for 'Nope'" in flat()

    @pytest.mark.parametrize("typed, checked, message", [
        ("hunter2", ["hunter2"], ""),
        ("", [], "Password cannot be empty"),
        (KeyboardInterrupt(), [], "Cancelled"),
    ])
    def test_password_is_read_hidden(self, tui, menu_hub, hibp, monkeypatch, flat,
                                     typed, checked, message):
        def getpass(prompt):
            if isinstance(typed, BaseException):
                raise typed
            return typed

        monkeypatch.setattr("getpass.getpass", getpass)
        tui.script("password", "back")

        menus._run_hibp_menu()

        assert [args[0] for args, _ in hibp.check_password.calls] == checked
        assert message in flat()


# ---------------------------------------------------------------------------
# Domain recon
# ---------------------------------------------------------------------------

@pytest.fixture
def recon(monkeypatch, record):
    fakes = SimpleNamespace(
        domain_recon=record({"subdomains": ["dev.acme.test"]}),
        whois_lookup=record({"emails": "admin@acme.test"}),
        dns_records=record({"A": ["203.0.113.7"]}),
        email_security=record(),
        tls_certificate=record({"san": ["mail.acme.test"]}),
        http_security_headers=record(),
        subdomains_crtsh=record(["api.acme.test"]),
        shodan_host=record({"hostnames": ["edge.acme.test"]}),
        _resolve_first_ip=record("203.0.113.9"),
        offer=record(),
    )
    for name in vars(fakes):
        if name != "offer":
            monkeypatch.setattr(f"analysis.domain_osint.{name}", getattr(fakes, name))
    monkeypatch.setattr(menus, "_offer_hub", fakes.offer)
    return fakes


class TestDomainRecon:
    def test_every_tool_feeds_the_hub(self, tui, menu_hub, recon):
        tui.script("https://www.acme.test/about", "full", "whois", "dns", "email-sec", "tls",
                   "headers", "subs", "shodan", "back")

        menus._run_domain_recon()

        assert recon.http_security_headers.calls == [(("https://www.acme.test/about",), {})]
        assert recon.shodan_host.calls == [(("203.0.113.9",), {})]
        assert recon.email_security.calls == [(("www.acme.test",), {})]
        assert {f.value for f in menu_hub.of_kind("domain")} == {
            "acme.test", "dev.acme.test", "mail.acme.test", "api.acme.test", "edge.acme.test"}
        assert {f.value for f in menu_hub.of_kind("ip")} == {"203.0.113.7", "203.0.113.9"}
        assert [f.value for f in menu_hub.of_kind("email")] == ["admin@acme.test"]
        assert len(recon.offer.calls) == 1

    def test_bare_domain_gets_https_for_the_headers(self, tui, menu_hub, recon):
        tui.script("acme.test", "headers", None)

        menus._run_domain_recon()

        assert recon.http_security_headers.calls == [(("https://acme.test",), {})]

    def test_shodan_needs_an_ip(self, tui, menu_hub, recon, monkeypatch, record, flat):
        monkeypatch.setattr("analysis.domain_osint._resolve_first_ip", record(None))
        tui.script("acme.test", "shodan", "back")

        menus._run_domain_recon()

        assert "Could not resolve target to an IP" in flat()
        assert recon.shodan_host.calls == []

    @pytest.mark.parametrize("typed, message", [
        ("", "Target cannot be empty"),
        ("http://", "Could not parse a domain"),
    ])
    def test_unusable_target_stops_before_the_menu(self, tui, menu_hub, recon, flat,
                                                   typed, message):
        tui.script(typed)

        menus._run_domain_recon()

        assert message in flat()
        assert tui.menus == []


# ---------------------------------------------------------------------------
# Searches
# ---------------------------------------------------------------------------

@pytest.fixture
def searches(monkeypatch, record):
    rows = [{"title": "A", "link": "https://acme.test/a"}]

    def do_search(*args, **kwargs):
        do_search.calls.append((args, kwargs))
        state.LAST_RESULTS = rows

    do_search.calls = []
    fakes = SimpleNamespace(do_search=do_search, do_deep_search=record(), rows=rows,
                            results_menu=record(), offer=record())
    monkeypatch.setattr(actions, "do_search", do_search)
    monkeypatch.setattr(actions, "do_deep_search", fakes.do_deep_search)
    monkeypatch.setattr(menus, "interactive_analysis_menu", fakes.results_menu)
    monkeypatch.setattr(menus, "_offer_hub", fakes.offer)
    return fakes


class TestGuidedSearch:
    def test_terms_are_joined_and_results_browsed(self, tui, menu_hub, searches):
        tui.script("Ana Lee", "alee", "", "", "", "brave")

        menus._run_guided_search()

        (query, engine), _ = searches.do_search.calls[0]
        assert (query, engine) == ('"Ana Lee" AND "alee"', "brave")
        assert searches.results_menu.calls == [((searches.rows,), {"ia_agent": None})]
        assert [f.value for f in menu_hub.of_kind("username")] == ["alee"]

    def test_email_or_phone_switches_to_deep_search(self, tui, menu_hub, searches):
        tui.script("", "", "ana@site.test", "+573001234567", "", None)

        menus._run_guided_search()

        (query, engine), _ = searches.do_deep_search.calls[0]
        assert query == '"ana@site.test" AND "+573001234567"'
        assert engine == "duckduckgo"
        assert searches.do_search.calls == []
        assert len(searches.offer.calls) == 1
        assert menu_hub.counts() == {"email": 1, "phone": 1}

    def test_no_terms_runs_nothing(self, tui, menu_hub, searches, flat):
        tui.script("", "", "", "", "")

        menus._run_guided_search()

        assert "At least one search term is required" in flat()
        assert searches.do_search.calls == searches.do_deep_search.calls == []


class TestDirectSearch:
    def test_query_is_searched_and_browsed(self, tui, menu_hub, searches):
        tui.script("site:acme.test staff", "tavily")

        menus._run_direct_search()

        (query, engine), _ = searches.do_search.calls[0]
        assert (query, engine) == ("site:acme.test staff", "tavily")
        assert len(searches.results_menu.calls) == 1

    def test_search_without_results_does_not_open_the_browser(self, tui, menu_hub, searches,
                                                               monkeypatch, record):
        monkeypatch.setattr(actions, "do_search", record())
        tui.script("acme", "duckduckgo")

        menus._run_direct_search()

        assert searches.results_menu.calls == []

    def test_empty_query_is_refused(self, tui, menu_hub, searches, flat):
        tui.script("")

        menus._run_direct_search()

        assert "Query cannot be empty" in flat()


# ---------------------------------------------------------------------------
# Single-target tools
# ---------------------------------------------------------------------------

class TestSingleTargetTools:
    @pytest.fixture(autouse=True)
    def offer(self, monkeypatch, record):
        fake = record()
        monkeypatch.setattr(menus, "_offer_hub", fake)
        return fake

    def test_tech_scan_feeds_url_and_domain(self, tui, menu_hub, monkeypatch, record, offer):
        scan = record()
        monkeypatch.setattr("analysis.tech_scanner.tech_scan", scan)
        tui.script("https://acme.test/shop")

        menus._run_tech_scan()

        assert scan.calls == [(("https://acme.test/shop",), {})]
        assert menu_hub.counts() == {"url": 1, "domain": 1}
        assert len(offer.calls) == 1

    @pytest.mark.parametrize("backend, timeout, used_backend, used_timeout", [
        ("maigret", "abc", "maigret", 20),
        (None, "2", "auto", 5),
        ("sherlock", "", "sherlock", 20),
    ])
    def test_username_enum_options(self, tui, menu_hub, monkeypatch, record,
                                   backend, timeout, used_backend, used_timeout):
        enum = record([{"site": "GitHub", "url": "https://github.test/alee"}])
        monkeypatch.setattr("search.username_enum.username_enum", enum)
        tui.script("alee", backend, timeout)

        menus._run_username_enum()

        assert enum.calls == [(("alee",), {"backend": used_backend, "timeout": used_timeout})]
        assert [f.value for f in menu_hub.of_kind("url")] == ["https://github.test/alee"]

    def test_email_enum_keeps_registered_services(self, tui, menu_hub, monkeypatch, record):
        enum = record([{"service": "svc", "domain": "svc.test", "status": "claimed"},
                       {"service": "other", "domain": "other.test", "status": "available"}])
        monkeypatch.setattr("search.email_enum.email_enum", enum)
        tui.script("ana@site.test", False)

        menus._run_email_enum()

        assert enum.calls == [(("ana@site.test",), {"only_used": False})]
        assert [f.value for f in menu_hub.of_kind("domain")] == ["svc.test"]

    @pytest.mark.parametrize("region, used", [("us", "US"), ("", None)])
    def test_phone_osint_region_hint(self, tui, menu_hub, monkeypatch, record, region, used):
        report = {"footprint": [{"label": "x", "kind": "search", "value": "q"}]}
        lookup, followup = record(report), record()
        monkeypatch.setattr("search.phone_osint.phone_osint", lookup)
        monkeypatch.setattr(menus, "_phone_footprint_followup", followup)
        tui.script("+14155552671", region)

        menus._run_phone_osint()

        assert lookup.calls == [(("+14155552671",), {"region": used})]
        assert followup.calls == [((report,), {})]

    def test_phone_without_a_report_offers_no_pivots(self, tui, menu_hub, monkeypatch, record):
        followup = record()
        monkeypatch.setattr("search.phone_osint.phone_osint", record(None))
        monkeypatch.setattr(menus, "_phone_footprint_followup", followup)
        tui.script("123", "")

        menus._run_phone_osint()

        assert followup.calls == []

    @pytest.mark.parametrize("runner, message", [
        ("_run_tech_scan", "URL cannot be empty"),
        ("_run_username_enum", "Username cannot be empty"),
        ("_run_email_enum", "Email cannot be empty"),
        ("_run_phone_osint", "Phone number cannot be empty"),
    ])
    def test_empty_target_is_refused(self, tui, menu_hub, flat, offer, runner, message):
        tui.script("")

        getattr(menus, runner)()

        assert message in flat()
        assert offer.calls == []
