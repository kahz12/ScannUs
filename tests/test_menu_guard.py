"""A tool that crashes or is cancelled returns to its menu and keeps the session."""

import pytest

from cli import hub_menu, menus, ui
from core.findings import FindingsHub


def flat(capsys):
    """Captured output with Rich's line wrapping undone."""
    return " ".join(capsys.readouterr().out.split())


def crash():
    raise AttributeError("'dict' object has no attribute 'lower'")


class TestRunGuarded:
    def test_returns_the_result(self):
        assert ui.run_guarded(lambda x: x * 2, 21) == 42

    def test_crash_is_reported_and_logged(self, monkeypatch, capsys):
        logged = []

        class Log:
            def exception(self, *args):
                logged.append(args)

        monkeypatch.setattr("core.logging_setup.get_logger", lambda name=None: Log())

        assert ui.run_guarded(crash, label="Username Enumeration") is None

        out = flat(capsys)
        assert "Username Enumeration stopped unexpectedly: AttributeError:" in out
        assert "scannus.log" in out
        assert logged == [("menu action %r stopped", "Username Enumeration")]

    def test_ctrl_c_cancels_only_the_action(self, capsys):
        def interrupted():
            raise KeyboardInterrupt

        assert ui.run_guarded(interrupted, label="Domain Recon") is None
        assert "Domain Recon cancelled" in flat(capsys)

    def test_markup_in_the_message_is_shown_as_text(self, capsys):
        def broken():
            raise ValueError("[/bold] broken [")

        ui.run_guarded(broken, label="Search")

        assert "[/bold] broken [" in flat(capsys)


@pytest.fixture
def hub(monkeypatch):
    """A hub holding one email, shared by both menus."""
    hub = FindingsHub()
    hub.add_email("ana@site.test", source="test")
    monkeypatch.setattr(menus, "get_hub", lambda: hub)
    return hub


def answer(monkeypatch, module, *choices):
    """Makes the menus of *module* pick *choices* in order."""
    picks = list(choices)
    monkeypatch.setattr(module, "select_menu", lambda *args, **kwargs: picks.pop(0))


class TestMenusSurviveACrash:
    def test_main_menu_keeps_running_and_keeps_the_findings(self, monkeypatch, hub, capsys):
        answer(monkeypatch, menus, "user-enum", "exit")
        monkeypatch.setattr(menus, "_run_username_enum", crash)

        menus.show_main_menu()

        out = flat(capsys)
        assert "Username Enumeration stopped unexpectedly" in out
        assert "Session closed" in out
        assert [f.value for f in hub.of_kind("email")] == ["ana@site.test"]

    def test_hub_keeps_running_after_a_pivot_crashes(self, monkeypatch, hub, capsys):
        answer(monkeypatch, hub_menu, "email-enum", "back")
        monkeypatch.setattr(hub_menu, "_hub_email_pivot", lambda hub: crash())

        hub_menu.findings_hub_menu()

        assert "Enumerate an email stopped unexpectedly" in flat(capsys)
        assert [f.value for f in hub.of_kind("email")] == ["ana@site.test"]
