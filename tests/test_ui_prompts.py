"""
``cli.ui`` prompts in both modes, a terminal with questionary and a plain
pipe, plus the layout helpers and the startup screen.
"""

from types import SimpleNamespace

import pytest

from cli import ui


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


@pytest.fixture
def typed(monkeypatch):
    """Feeds ``console.input`` the given lines and keeps each prompt shown."""
    holder = SimpleNamespace(lines=[], prompts=[])

    def read(prompt=""):
        holder.prompts.append(prompt)
        return holder.lines.pop(0)

    monkeypatch.setattr(ui, "_interactive_tty", lambda: False)
    monkeypatch.setattr(ui.console, "input", read)
    return holder


@pytest.fixture
def questionary(monkeypatch):
    """A questionary stand-in; ``answer`` is returned by ask() or raised."""
    holder = SimpleNamespace(answer=None, calls=[])

    class Prompt:
        def ask(self):
            if isinstance(holder.answer, BaseException):
                raise holder.answer
            return holder.answer

    def prompt(kind):
        def make(message, **kwargs):
            holder.calls.append((kind, message, kwargs))
            return Prompt()
        return make

    fake = SimpleNamespace(select=prompt("select"), confirm=prompt("confirm"),
                           Choice=lambda title, value: SimpleNamespace(title=title, value=value))
    monkeypatch.setattr(ui, "questionary", fake)
    monkeypatch.setattr(ui, "_interactive_tty", lambda: True)
    return holder


CHOICES = [("Alpha", "alpha", "first"), ("Beta", "beta")]


class TestPlainPrompts:
    def test_ask_strips_and_falls_back_to_the_default(self, typed):
        typed.lines = ["  acme  ", ""]

        assert ui.ask("Target") == "acme"
        assert ui.ask("Engine", default="duckduckgo") == "duckduckgo"
        assert "duckduckgo" in typed.prompts[1]

    @pytest.mark.parametrize("line, default, result", [
        ("", True, True), ("", False, False), ("sí", False, True), ("Y", False, True),
        ("nope", True, False),
    ])
    def test_confirm(self, typed, line, default, result):
        typed.lines = [line]

        assert ui.confirm("Go?", default=default) is result
        assert ("[Y/n]" if default else "[y/N]") in typed.prompts[0]

    @pytest.mark.parametrize("lines, default, result", [
        (["2"], None, "beta"),
        (["beta"], None, "beta"),
        (["9", "x", "1"], None, "alpha"),
        ([""], "beta", "beta"),
    ])
    def test_numbered_menu(self, typed, flat, lines, default, result):
        typed.lines = list(lines)

        assert ui.select_menu("Pick one", CHOICES, default=default) == result
        out = flat()
        assert "Alpha" in out and "first" in out
        if len(lines) > 1:
            assert "Enter a number from the list" in out


class TestTerminalPrompts:
    def test_menu_marks_the_default_and_shows_hints(self, questionary):
        questionary.answer = "beta"

        assert ui.select_menu("Pick one", CHOICES, default="beta") == "beta"
        _, _, options = questionary.calls[0]
        assert [c.title for c in options["choices"]] == ["Alpha    [first]", "Beta"]
        assert options["default"].value == "beta"

    @pytest.mark.parametrize("kind, call", [
        ("select", lambda: ui.select_menu("Pick one", CHOICES)),
        ("confirm", lambda: ui.confirm("Go?", default=True)),
    ])
    def test_ctrl_c_cancels(self, questionary, kind, call):
        questionary.answer = KeyboardInterrupt()

        assert call() in (None, False)
        assert questionary.calls[0][0] == kind

    def test_confirm(self, questionary):
        questionary.answer = True

        assert ui.confirm("Go?") is True


def test_interactive_needs_both_ttys_and_questionary(monkeypatch):
    monkeypatch.setattr(ui, "_HAS_QUESTIONARY", True)
    monkeypatch.setattr(ui.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(ui.sys.stdout, "isatty", lambda: False, raising=False)

    assert ui._interactive_tty() is False


class TestLayout:
    def test_section_with_and_without_subtitle(self, flat):
        ui.print_section("Results", "3 found")
        ui.print_section("Plain")

        out = flat()
        assert "Results 3 found" in out and "Plain" in out

    def test_table_columns_from_names_or_pairs(self, flat):
        table = ui.make_table("T", "Name", ("Value", "green"))
        table.add_row("a", "b")
        ui.console.print(table)

        assert "Name" in flat()

    def test_empty_status_footer_prints_nothing(self, flat):
        ui.status_footer([])

        assert flat() == ""


class TestStartupScreen:
    @pytest.mark.parametrize("env, label", [
        ({}, "not set"),
        ({"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k", "OLLAMA_MODEL": "llama3"},
         "OpenAI, Claude, Ollama"),
    ])
    def test_configured_providers(self, monkeypatch, env, label):
        for name in ("GOOGLE_API_KEY_FOR_GEMINI", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                     "OLLAMA_HOST", "OLLAMA_MODEL"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)

        assert ui._configured_ai_summary(False)[0] == label
        assert ui._configured_ai_summary(True)[0].startswith("Gemini")

    def test_version_falls_back_when_not_installed(self, monkeypatch):
        def missing(name):
            raise LookupError(name)

        monkeypatch.setattr("importlib.metadata.version", missing)

        assert ui._app_version() == "0.1.0"

    @pytest.mark.parametrize("found, backend", [
        ({"sherlock"}, "Sherlock"), ({"maigret"}, "Maigret"), (set(), "none")])
    def test_username_backend(self, monkeypatch, found, backend):
        monkeypatch.setattr("shutil.which",
                            lambda name, path=None: f"/bin/{name}" if name in found else None)

        assert ui._detect_username_backend() == backend

    def test_banner(self, monkeypatch, flat):
        monkeypatch.setattr(ui, "_detect_username_backend", lambda: "Sherlock")

        ui.print_startup_banner(True)

        out = flat()
        assert "Advanced OSINT & Search Analysis Framework" in out
        assert "Gemini" in out and "Sherlock" in out
