"""Saving, loading and deleting cases through the prompts, on a real SQLite file."""

from types import SimpleNamespace

import pytest

from core import case_manager, state
from core.database import DBManager
from core.findings import FindingsHub

RESULTS = [{"id": 1, "title": "A", "description": "d", "link": "https://acme.test/a"}]


@pytest.fixture
def flat(capsys):
    return lambda: " ".join(capsys.readouterr().out.split())


@pytest.fixture
def session(tmp_path, monkeypatch):
    """A blank case, hub and database; ``session.typed`` feeds the prompts in order."""
    holder = SimpleNamespace(typed=[], hub=FindingsHub())
    database = str(tmp_path / "cases.db")
    monkeypatch.setattr(case_manager, "DBManager", lambda: DBManager(database))
    monkeypatch.setattr(case_manager, "get_hub", lambda: holder.hub)
    monkeypatch.setattr(case_manager.console, "input", lambda prompt="": holder.typed.pop(0))
    monkeypatch.setattr(state, "LAST_RESULTS", [])
    monkeypatch.setattr(state, "CURRENT_CASE",
                        {"search_params": {}, "results": [], "evidence": [], "investigation": None})
    holder.db = lambda: DBManager(database)
    return holder


def with_results():
    state.CURRENT_CASE["results"] = list(RESULTS)


class TestSave:
    def test_nothing_to_save(self, session, flat):
        case_manager.save_case()
        assert case_manager.save_case_as("empty") is False

        out = flat()
        assert "No results to save" in out and "Nothing to save" in out
        assert session.db().get_all_cases() == []

    def test_empty_name_is_refused(self, session, flat):
        with_results()
        session.typed = ["  "]

        case_manager.save_case()

        assert "Case name cannot be empty" in flat()
        assert session.db().get_all_cases() == []

    def test_new_case(self, session):
        with_results()
        session.typed = ["acme"]

        case_manager.save_case()

        assert [row[1] for row in session.db().get_all_cases()] == ["acme"]

    @pytest.mark.parametrize("answer, kept_title", [("y", "B"), ("n", "A")])
    def test_existing_name_asks_before_overwriting(self, session, flat, answer, kept_title):
        with_results()
        assert case_manager.save_case_as("acme") is True
        state.CURRENT_CASE["results"] = [dict(RESULTS[0], title="B")]
        session.typed = ["acme", answer]

        case_manager.save_case()

        case_id = session.db().get_all_cases()[0][0]
        assert session.db().get_case_by_id(case_id)["results"][0]["title"] == kept_title
        if answer == "n":
            assert "Save cancelled" in flat()

    @pytest.mark.parametrize("saved, updated, message", [
        ((False, "disk full", False), None, "disk full"),
        ((False, "exists", True), (False, "locked"), "locked"),
    ])
    def test_database_failures(self, session, monkeypatch, flat, saved, updated, message):
        with_results()
        session.typed = ["acme", "y"]
        monkeypatch.setattr(DBManager, "save_case", lambda self, name, case: saved)
        monkeypatch.setattr(DBManager, "update_case", lambda self, name, case: updated)

        case_manager.save_case()

        assert message in flat()


class TestLoad:
    def test_no_cases(self, session, flat):
        assert case_manager.load_case() is False
        assert "No saved cases found" in flat()

    @pytest.mark.parametrize("typed", ["0", "x", "9"])
    def test_invalid_selection(self, session, flat, typed):
        with_results()
        case_manager.save_case_as("acme")
        session.typed = [typed]

        assert case_manager.load_case() is False
        assert "is not a valid selection" in flat()

    def test_unreadable_case(self, session, monkeypatch, flat):
        with_results()
        case_manager.save_case_as("acme")
        monkeypatch.setattr(DBManager, "get_case_by_id", lambda self, case_id: None)
        session.typed = ["1"]

        assert case_manager.load_case() is False
        assert "Could not load case data" in flat()

    def test_empty_case(self, session, monkeypatch, flat):
        with_results()
        case_manager.save_case_as("acme")
        monkeypatch.setattr(DBManager, "get_case_by_id", lambda self, case_id: {
            "search_params": {}, "results": [], "evidence": [], "investigation": None})
        session.typed = ["1"]

        assert case_manager.load_case() is False
        assert "exists but it is empty" in flat()


class TestDelete:
    def test_no_cases(self, session, flat):
        assert case_manager.delete_case_prompt() is False
        assert "No saved cases found" in flat()

    @pytest.mark.parametrize("typed, message", [
        ([""], "Delete cancelled"),
        (["7"], "is not a valid selection"),
        (["1", "n"], "Delete cancelled"),
    ])
    def test_nothing_is_deleted(self, session, flat, typed, message):
        with_results()
        case_manager.save_case_as("acme")
        session.typed = list(typed)

        assert case_manager.delete_case_prompt() is False
        assert message in flat()
        assert len(session.db().get_all_cases()) == 1

    def test_confirmed_delete(self, session):
        with_results()
        case_manager.save_case_as("acme")
        session.typed = ["1", "y"]

        assert case_manager.delete_case_prompt() is True
        assert session.db().get_all_cases() == []
