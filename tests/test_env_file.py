"""ScannUs runs without a .env file; only features that need a key ask for one."""

import sys

import pytest

import main
from cli import actions
from core import state
from core.findings import FindingsHub


RESULT = {"title": "T", "description": "D", "link": "https://site.test/a"}


@pytest.fixture
def run_main(tmp_path, monkeypatch):
    """Returns a callable that runs main() in a folder with no .env file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "init_directories", lambda: None)
    monkeypatch.setattr(main, "setup_logging", lambda debug: None)
    monkeypatch.setattr(main, "print_startup_banner", lambda has_key: None)
    monkeypatch.setattr(main, "load_environment", lambda: None)

    def run(*flags):
        monkeypatch.setattr(sys, "argv", ["main.py", *flags])
        main.main()

    return run


@pytest.mark.parametrize("flags, route", [
    (["--hibp-domain", "acme-corp.io"], "analysis.hibp.check_domain"),
    (["--recon", "acme-corp.io"], "analysis.domain_osint.domain_recon"),
    (["--phone-osint", "+14155552671"], "search.phone_osint.phone_osint"),
    (["--username-enum", "jdoe88"], "search.username_enum.username_enum"),
    (["--email-enum", "a@acme-corp.io"], "search.email_enum.email_enum"),
])
def test_free_commands_run_without_env_file(run_main, monkeypatch, flags, route):
    calls = []

    def command_ran(*args, **kwargs):
        calls.append(args)
        return []

    monkeypatch.setattr(route, command_ran)

    with pytest.raises(SystemExit) as exit_info:
        run_main(*flags)

    assert exit_info.value.code == 0
    assert calls


def test_search_runs_without_env_file(run_main, monkeypatch):
    monkeypatch.setattr(actions, "get_search_engine", lambda *args: [RESULT])
    hub = FindingsHub()
    monkeypatch.setattr(actions, "get_hub", lambda: hub)
    monkeypatch.setattr(state, "LAST_RESULTS", [])
    monkeypatch.setattr(state, "CURRENT_CASE",
                        {"search_params": {}, "results": [], "evidence": [], "investigation": None})

    run_main("-q", "target")

    assert state.LAST_RESULTS == [RESULT]


def test_setup_wizard_still_runs_alone(run_main, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "env_config", lambda: calls.append("env"))
    monkeypatch.setattr(main, "openai_config", lambda: calls.append("openai"))

    with pytest.raises(SystemExit) as exit_info:
        run_main("-c")

    assert exit_info.value.code == 0
    assert calls == ["env", "openai"]
