"""Shared fixtures for driving the interactive menus without a terminal."""

import pytest

from cli import hub_menu, menus, results_menu
from core import state
from core.findings import FindingsHub


class ScriptedTerminal:
    """
    Answers the menus' prompts in the order given to :meth:`script`.

    A menu answer must be one of the values that menu offers, or None as when
    the user presses Esc; a confirm answer must be a bool; an ask answer is the
    typed text, where "" takes the prompt's default like the real prompt does.
    Each menu shown is kept in ``menus`` as ``(title, offered values)``.
    """

    def __init__(self):
        self.answers: list = []
        self.menus: list[tuple[str, list[str]]] = []

    def script(self, *answers) -> None:
        self.answers.extend(answers)

    def _next(self, kind: str, prompt: str):
        if not self.answers:
            raise AssertionError(f"no scripted answer left for {kind} {prompt!r}")
        return self.answers.pop(0)

    def select_menu(self, title, choices, **kwargs):
        values = [choice[1] for choice in choices]
        self.menus.append((title, values))
        answer = self._next("menu", title)
        assert answer is None or answer in values, (
            f"{answer!r} is not offered by menu {title!r}: {values}")
        return answer

    def ask(self, question="", default=""):
        answer = self._next("ask", question)
        assert isinstance(answer, str), f"ask {question!r} got {answer!r}"
        return answer.strip() or default

    def confirm(self, question, default=False):
        answer = self._next("confirm", question)
        assert isinstance(answer, bool), f"confirm {question!r} got {answer!r}"
        return answer


@pytest.fixture
def tui(monkeypatch):
    """Replaces the prompts of every menu module; every scripted answer must be used."""
    terminal = ScriptedTerminal()
    for module in (menus, hub_menu, results_menu):
        for name in ("select_menu", "ask", "confirm"):
            monkeypatch.setattr(module, name, getattr(terminal, name))
    yield terminal
    assert not terminal.answers, f"scripted answers left over: {terminal.answers}"


@pytest.fixture
def menu_hub(monkeypatch):
    """A blank Findings Hub and case, shared by every menu module."""
    hub = FindingsHub()
    monkeypatch.setattr(menus, "get_hub", lambda: hub)
    monkeypatch.setattr(state, "LAST_RESULTS", [])
    monkeypatch.setattr(state, "CURRENT_CASE",
                        {"search_params": {}, "results": [], "evidence": [], "investigation": None})
    return hub


@pytest.fixture
def record():
    """Builds stand-ins that keep their calls: ``fake = record(result)``; ``fake.calls``."""
    def make(result=None):
        def fake(*args, **kwargs):
            fake.calls.append((args, kwargs))
            return result
        fake.calls = []
        return fake
    return make


@pytest.fixture
def flat(capsys):
    """Returns the captured output so far with Rich's line wrapping undone."""
    return lambda: " ".join(capsys.readouterr().out.split())
