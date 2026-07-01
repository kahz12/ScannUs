"""
core/logging_setup.py — central logging configuration for ScannUs.

All application logs live under the ``scannus`` logger tree. In a module, get a
namespaced child with ``get_logger(__name__)`` (e.g. ``scannus.core.cache``);
records propagate to whatever handlers :func:`setup_logging` installs on the
``scannus`` parent.

By default a rotating file handler captures INFO+ to
``outputs/logs/scannus.log``. Passing ``debug=True`` (the ``--debug`` CLI flag)
lowers the file threshold to DEBUG and adds a concise stderr handler so the
same detail is visible live — on stderr, so it doesn't corrupt the Rich TUI
rendered on stdout.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

_APP_LOGGER_NAME = "scannus"

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Return an application logger. ``get_logger("core.cache")`` yields
    ``scannus.core.cache``; ``get_logger()`` yields the ``scannus`` parent.
    """
    if not name:
        return logging.getLogger(_APP_LOGGER_NAME)
    # Avoid a doubled prefix if a caller passes an already-namespaced name.
    if name == _APP_LOGGER_NAME or name.startswith(_APP_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_APP_LOGGER_NAME}.{name}")


def setup_logging(debug: bool = False, log_dir: str | None = None) -> logging.Logger:
    """
    (Re)configure the ``scannus`` logger tree. Idempotent: existing handlers
    are cleared first, so calling this twice never duplicates output.

    Args:
        debug:   If True, capture DEBUG+ and also stream to stderr.
        log_dir: Where ``scannus.log`` lives. Defaults to ``core.config.DIR_LOGS``.

    Returns:
        The configured ``scannus`` logger.
    """
    logger = logging.getLogger(_APP_LOGGER_NAME)

    # Clear prior handlers so re-invocation (tests, TUI re-entry) is clean.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False  # keep app logs off the root logger / stdout

    if log_dir is None:
        try:
            from core.config import DIR_LOGS
            log_dir = DIR_LOGS
        except Exception:
            log_dir = os.path.join(os.getcwd(), "outputs", "logs")

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    file_handler_ok = False
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "scannus.log"),
            maxBytes=2_000_000, backupCount=3, encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        file_handler_ok = True
    except OSError:
        # Read-only filesystem or permission issue — degrade gracefully;
        # console (if debug) or the NullHandler below still applies.
        pass

    if debug:
        stream_handler = logging.StreamHandler()  # stderr by default
        stream_handler.setLevel(logging.DEBUG)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    # Guarantee at least one handler so records never fall through to the
    # root logger's last-resort stderr writer.
    if not file_handler_ok and not debug:
        logger.addHandler(logging.NullHandler())

    logger.debug("logging initialised (debug=%s, dir=%s)", debug, log_dir)
    return logger
