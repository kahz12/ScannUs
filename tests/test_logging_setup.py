"""
Unit tests for core.logging_setup.

The ``scannus`` logger is a process-global singleton, so the autouse fixture
restores it to a quiet, handler-free state after each test — otherwise a
temp-dir file handler configured here could outlive the test and have other
suites (e.g. cache logging) write into a deleted directory.
"""

import logging

import pytest

from core.logging_setup import get_logger, setup_logging


@pytest.fixture(autouse=True)
def _restore_scannus_logger():
    yield
    lg = logging.getLogger("scannus")
    for h in list(lg.handlers):
        lg.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    lg.addHandler(logging.NullHandler())
    lg.setLevel(logging.WARNING)
    lg.propagate = True


def _read_log(tmp_path):
    return (tmp_path / "scannus.log").read_text(encoding="utf-8")


class TestGetLogger:
    def test_namespacing(self):
        assert get_logger().name == "scannus"
        assert get_logger("core.cache").name == "scannus.core.cache"

    def test_no_double_prefix(self):
        assert get_logger("scannus.x").name == "scannus.x"


class TestSetupLogging:
    def test_creates_file_and_writes_info(self, tmp_path):
        setup_logging(debug=False, log_dir=str(tmp_path))
        get_logger("test").info("hello-info-42")
        assert "hello-info-42" in _read_log(tmp_path)

    def test_info_mode_suppresses_debug(self, tmp_path):
        setup_logging(debug=False, log_dir=str(tmp_path))
        get_logger("test").debug("should-not-appear")
        get_logger("test").info("anchor")
        contents = _read_log(tmp_path)
        assert "anchor" in contents
        assert "should-not-appear" not in contents

    def test_debug_mode_captures_debug(self, tmp_path):
        setup_logging(debug=True, log_dir=str(tmp_path))
        get_logger("test").debug("debug-visible-99")
        assert "debug-visible-99" in _read_log(tmp_path)

    def test_child_logger_propagates_to_parent_handlers(self, tmp_path):
        # A module using get_logger(__name__) must reach the parent's file.
        setup_logging(debug=False, log_dir=str(tmp_path))
        get_logger("search.engines.duckduckgo").info("engine-line")
        assert "engine-line" in _read_log(tmp_path)

    def test_idempotent_no_handler_duplication(self, tmp_path):
        setup_logging(debug=True, log_dir=str(tmp_path))
        first = len(logging.getLogger("scannus").handlers)
        setup_logging(debug=True, log_dir=str(tmp_path))
        second = len(logging.getLogger("scannus").handlers)
        assert first == second
        # And a single info yields exactly one line for that message.
        get_logger("t").info("once-only")
        assert _read_log(tmp_path).count("once-only") == 1

    def test_propagate_disabled_after_setup(self, tmp_path):
        setup_logging(debug=False, log_dir=str(tmp_path))
        assert logging.getLogger("scannus").propagate is False

    def test_missing_log_dir_is_created(self, tmp_path):
        nested = tmp_path / "a" / "b" / "logs"
        setup_logging(debug=False, log_dir=str(nested))
        get_logger("t").info("nested-dir-ok")
        assert (nested / "scannus.log").exists()
