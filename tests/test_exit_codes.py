"""What main() reports to the shell, and what --recon writes with --json."""

import json
import sys

import pytest

import main
import utils.results_parse as rp


@pytest.fixture
def run_main(tmp_path, monkeypatch):
    """Returns a callable that runs main() and gives back its exit code."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rp, "DIR_REPORTS", str(tmp_path))
    monkeypatch.setattr(main, "init_directories", lambda: None)
    monkeypatch.setattr(main, "setup_logging", lambda debug: None)
    monkeypatch.setattr(main, "print_startup_banner", lambda has_key: None)
    monkeypatch.setattr(main, "load_environment", lambda: None)

    def run(*flags):
        monkeypatch.setattr(sys, "argv", ["main.py", *flags])
        with pytest.raises(SystemExit) as exit_info:
            main.main()
        return exit_info.value.code

    return run


@pytest.mark.parametrize("flags, route, result, code", [
    (["--username-enum", "jdoe88"], "search.username_enum.username_enum", [], 0),
    (["--username-enum", "jdoe88"], "search.username_enum.username_enum", None, 1),
    (["--email-enum", "a@acme-corp.io"], "search.email_enum.email_enum", [], 0),
    (["--email-enum", "a@acme-corp.io"], "search.email_enum.email_enum", None, 1),
    (["--phone-osint", "+14155552671"], "search.phone_osint.phone_osint", {"valid": True}, 0),
    (["--phone-osint", "nonsense"], "search.phone_osint.phone_osint", None, 1),
    (["--hibp-account", "a@acme-corp.io"], "analysis.hibp.check_account", {"checked": True}, 0),
    (["--hibp-account", "a@acme-corp.io"], "analysis.hibp.check_account", {"checked": False}, 1),
    (["--hibp-breach", "Adobe"], "analysis.hibp.hibp_breach", None, 1),
    (["-rev", "https://site.test/a.jpg"], "main.do_reverse_image_search", True, 0),
    (["-rev", "https://site.test/a.jpg"], "main.do_reverse_image_search", False, 1),
])
def test_exit_code_reflects_whether_the_command_could_run(
        run_main, monkeypatch, flags, route, result, code):
    monkeypatch.setattr(route, lambda *args, **kwargs: result)

    assert run_main(*flags) == code


def test_clean_account_is_a_success_but_a_missing_key_is_not(monkeypatch):
    from analysis import hibp

    monkeypatch.setattr(hibp, "render_breached_account", lambda *args: None)
    monkeypatch.setattr(hibp, "render_pastes_for_account", lambda *args: None)
    monkeypatch.setattr(hibp, "hibp_pastes_for_account", lambda email: None)

    monkeypatch.setattr(hibp, "hibp_breached_account", lambda email: [])
    assert hibp.check_account("a@acme-corp.io")["checked"] is True

    monkeypatch.setattr(hibp, "hibp_breached_account", lambda email: None)
    assert hibp.check_account("a@acme-corp.io")["checked"] is False


def test_recon_json_writes_the_report(run_main, tmp_path, monkeypatch):
    report = {"domain": "acme-corp.io", "subdomains": ["www.acme-corp.io"], "seen": {1, 2}}
    monkeypatch.setattr("analysis.domain_osint.domain_recon", lambda target: report)

    assert run_main("--recon", "acme-corp.io", "--json", "recon.json") == 0

    saved = json.loads((tmp_path / "recon.json").read_text(encoding="utf-8"))
    assert saved["subdomains"] == ["www.acme-corp.io"]
    assert saved["seen"] == "{1, 2}"


def test_recon_without_json_writes_nothing(run_main, tmp_path, monkeypatch):
    monkeypatch.setattr("analysis.domain_osint.domain_recon", lambda target: {})

    assert run_main("--recon", "acme-corp.io") == 0

    assert list(tmp_path.iterdir()) == []
