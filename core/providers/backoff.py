"""
core/providers/backoff.py — transient-failure retry with exponential backoff.

Shared by every provider wrapper in this package so a flaky 429 / 5xx from an
LLM API is retried a few times (with jitter) before the error surfaces to the
caller. Non-transient errors propagate immediately.
"""

import random
import time
from typing import Callable

from cli.ui import console, THEME


_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_DELAY = 1.0
_DEFAULT_MAX_DELAY = 30.0


def _is_transient_error(exc: Exception) -> bool:
    """Best-effort detection of retryable provider errors across SDK variants."""
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    transient_markers = (
        "timeout", "timed out", "rate limit", "temporarily", "unavailable",
        "overloaded", "connection reset", "econnreset", "502", "503", "504",
    )
    return any(marker in msg for marker in transient_markers)


def _retry_with_backoff(
    fn: Callable,
    *args,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_delay: float = _DEFAULT_BASE_DELAY,
    max_delay: float = _DEFAULT_MAX_DELAY,
    label: str = "provider call",
    **kwargs,
):
    """
    Invokes ``fn(*args, **kwargs)`` with exponential-backoff retry on transient
    errors. Non-transient errors propagate immediately.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt >= max_retries or not _is_transient_error(e):
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            delay += random.uniform(0, delay * 0.25)  # 0–25% jitter
            console.print(
                f"  [{THEME['DIM']}]↻ {label}: transient error "
                f"(attempt {attempt + 1}/{max_retries}) — retrying in {delay:.1f}s[/]"
            )
            time.sleep(delay)
    if last_exc:
        raise last_exc
