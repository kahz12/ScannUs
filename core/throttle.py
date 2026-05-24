"""
core/throttle.py — Per-namespace token-bucket rate limiting + retry/backoff.

Centralises two things that every network-touching tool in this project used
to reinvent (or skip): outbound rate limiting and transient-failure retries.

Why a single shared module?
  * HIBP, Shodan, crt.sh, and every subprocess wrapper each had — or did
    not have — its own ad-hoc retry loop. Inconsistent + easy to forget.
  * Token buckets are stateful: the budget for "polite HIBP traffic" must
    be shared across every caller in the process, not re-created per call.
  * The same primitives need to work in sync and async code paths.

Primitives provided here:

  * :class:`TokenBucket`         — classic leaky-bucket implementation,
                                    thread-safe, sync + async wait methods.
  * :func:`get_bucket`           — process-wide singleton per namespace.
  * :func:`DEFAULT_RATES`        — sensible defaults per upstream.
  * :func:`backoff_delay`        — exponential backoff with full jitter.
  * :class:`TransientError`      — opt-in sentinel for "retry me".
  * :func:`throttled` /          — decorators that combine rate-limit +
    :func:`throttled_async`         retry. Sync and async variants.
  * :func:`retry_http_sync`      — helper for the common HIBP/crt.sh
                                    shape: fn returning ``(status, body)``,
                                    retried on 429/5xx with Retry-After.

The buckets are *per process*: separate runs of ``main.py`` reset their
counters. That's fine for an interactive CLI; if this ever moves to a
long-lived daemon the buckets will need to be persisted (or seeded from
HTTP Retry-After hints on startup).
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from functools import wraps
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Default rates (tokens / second) per upstream namespace
# ---------------------------------------------------------------------------
# Rule of thumb:
#   * If the upstream documents a rate, use it.
#   * If we've observed flakiness (e.g. crt.sh's regular 502s), be gentler.
#   * If unknown, default to 2 rps and adjust on first failure.

DEFAULT_RATES: dict[str, float] = {
    "hibp_account":   1.5,    # HIBP throttles paid API at ~1.5 rps; respect that
    "hibp_breach":    5.0,    # free catalog endpoints — Cloudflare-fronted, lenient
    "hibp_password":  10.0,   # k-anon range is a CDN endpoint; very lenient
    "crtsh":          0.5,    # crt.sh frequently returns 502 — be slow + patient
    "shodan":         1.0,    # Shodan free tier docs: 1 rps
    "wayback":        2.0,
    "default":        2.0,
}


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------

class TokenBucket:
    """
    Classic token-bucket rate limiter.

    Tokens refill at ``rate`` per second up to ``capacity``. ``acquire``
    returns the wait time (without sleeping) to satisfy the request;
    ``wait`` / ``wait_async`` actually sleep for that duration.

    Thread-safe via a single ``threading.Lock``. The wait methods release
    the lock before sleeping so concurrent callers can update the bucket
    independently.
    """

    def __init__(self, rate: float, capacity: float | None = None):
        if rate <= 0:
            raise ValueError(f"rate must be > 0, got {rate}")
        self.rate = float(rate)
        # Default capacity = 1s worth of tokens (or at least 1).
        self.capacity = float(capacity if capacity is not None else max(rate, 1.0))
        self.tokens = self.capacity
        self.last = time.monotonic()
        self._lock = threading.Lock()

    def _refill_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last = now

    def acquire(self, tokens: float = 1.0) -> float:
        """
        Reserve ``tokens`` from the bucket. Returns the wait time (seconds)
        the caller should sleep before proceeding. Does NOT sleep itself.

        The bucket is always decremented (potentially into a negative
        balance) so that simultaneous callers can't both "spend" the same
        token while one of them is sleeping out a deficit. The next caller
        either finds the bucket recovered (refill > 0) or waits its own
        share of the debt.
        """
        with self._lock:
            self._refill_locked()
            wait = 0.0 if self.tokens >= tokens else (tokens - self.tokens) / self.rate
            self.tokens -= tokens
            return wait

    def wait(self, tokens: float = 1.0) -> None:
        """Sync: block until ``tokens`` are available."""
        wait = self.acquire(tokens)
        if wait > 0:
            time.sleep(wait)

    async def wait_async(self, tokens: float = 1.0) -> None:
        """Async: await until ``tokens`` are available."""
        wait = self.acquire(tokens)
        if wait > 0:
            await asyncio.sleep(wait)


# ---------------------------------------------------------------------------
# Process-wide bucket registry
# ---------------------------------------------------------------------------

_BUCKETS: dict[str, TokenBucket] = {}
_BUCKETS_LOCK = threading.Lock()


def get_bucket(namespace: str, rate: float | None = None,
               capacity: float | None = None) -> TokenBucket:
    """
    Return the process-wide bucket for ``namespace``, creating it lazily.

    The first caller's ``rate``/``capacity`` win for the lifetime of the
    process. Subsequent callers passing different values are ignored —
    this is intentional: rate limits must be globally consistent for the
    bucket to mean anything.
    """
    with _BUCKETS_LOCK:
        bucket = _BUCKETS.get(namespace)
        if bucket is None:
            effective_rate = rate if rate is not None else \
                DEFAULT_RATES.get(namespace, DEFAULT_RATES["default"])
            bucket = TokenBucket(rate=effective_rate, capacity=capacity)
            _BUCKETS[namespace] = bucket
        return bucket


def reset_buckets() -> None:
    """Clear all buckets — for tests and bench harnesses."""
    with _BUCKETS_LOCK:
        _BUCKETS.clear()


# ---------------------------------------------------------------------------
# Backoff helpers
# ---------------------------------------------------------------------------

def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """
    Exponential backoff with full jitter (Marc Brooker / AWS recommendation).
    ``attempt`` is 0-indexed: 0=first retry.
    """
    upper = min(cap, base * (2 ** attempt))
    return random.uniform(0, upper)


class TransientError(Exception):
    """Raise this from a guarded callable to trigger a retry."""


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

_log = logging.getLogger(__name__)


def throttled(namespace: str, *, rate: float | None = None,
              max_retries: int = 0,
              retry_on: tuple[type[BaseException], ...] = (TransientError,),
              backoff_base: float = 1.0,
              backoff_cap: float = 30.0):
    """
    Sync decorator: rate-limit + (optional) retry with exponential backoff.

    Rate limit is enforced before every attempt (including retries) so a
    flapping upstream can't burst us past the bucket.
    """
    def deco(fn: Callable):
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            bucket = get_bucket(namespace, rate)
            attempt = 0
            while True:
                bucket.wait()
                try:
                    return fn(*args, **kwargs)
                except retry_on as e:
                    if attempt >= max_retries:
                        raise
                    delay = backoff_delay(attempt, backoff_base, backoff_cap)
                    _log.debug("throttled[%s] retry %d after %s: %.2fs",
                               namespace, attempt + 1, type(e).__name__, delay)
                    time.sleep(delay)
                    attempt += 1
        return wrapper
    return deco


def throttled_async(namespace: str, *, rate: float | None = None,
                    max_retries: int = 0,
                    retry_on: tuple[type[BaseException], ...] = (TransientError,),
                    backoff_base: float = 1.0,
                    backoff_cap: float = 30.0):
    """Async variant of :func:`throttled`."""
    def deco(fn: Callable):
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any):
            bucket = get_bucket(namespace, rate)
            attempt = 0
            while True:
                await bucket.wait_async()
                try:
                    return await fn(*args, **kwargs)
                except retry_on as e:
                    if attempt >= max_retries:
                        raise
                    delay = backoff_delay(attempt, backoff_base, backoff_cap)
                    _log.debug("throttled_async[%s] retry %d after %s: %.2fs",
                               namespace, attempt + 1, type(e).__name__, delay)
                    await asyncio.sleep(delay)
                    attempt += 1
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# HTTP-shaped retry helper
# ---------------------------------------------------------------------------
# Most callers in this codebase return ``(status, body)`` from a thin HTTP
# wrapper rather than raising — see analysis/hibp.py:_get for the pattern.
# This helper bakes in the canonical "retry on 429/502/503/504, honour
# Retry-After" loop so callers don't reimplement it.

_RETRY_STATUSES_DEFAULT = frozenset({429, 502, 503, 504})


def _parse_retry_after(value: str | None, fallback: float) -> float:
    """Parse a ``Retry-After`` header. Returns ``fallback`` if absent/invalid."""
    if not value:
        return fallback
    value = value.strip()
    try:
        # Most CDNs send integer seconds; HIBP sometimes sends a float.
        return max(0.0, float(value))
    except ValueError:
        return fallback


def retry_http_sync(call: Callable[[], tuple[int, Any, Any]],
                    *, namespace: str,
                    max_retries: int = 2,
                    retry_statuses: frozenset[int] = _RETRY_STATUSES_DEFAULT,
                    backoff_base: float = 1.0,
                    backoff_cap: float = 30.0) -> tuple[int, Any]:
    """
    Run ``call`` under the namespace's rate limit; retry on transient HTTP
    statuses (default 429/502/503/504) with exponential backoff. Honours
    ``Retry-After`` when the server provides it.

    ``call`` must return ``(status, body, retry_after_header_or_None)``.
    The third tuple element lets callers surface the server's hint without
    this helper having to know about ``requests`` / ``aiohttp`` specifics.

    Returns ``(status, body)`` from the last attempt — does not raise on
    exhausted retries; the caller inspects the status to decide what to do.
    """
    bucket = get_bucket(namespace)
    last_status: int = 0
    last_body: Any = None
    for attempt in range(max_retries + 1):
        bucket.wait()
        try:
            status, body, retry_after = call()
        except TransientError:
            if attempt >= max_retries:
                return 0, "transport: TransientError after retries"
            time.sleep(backoff_delay(attempt, backoff_base, backoff_cap))
            continue
        last_status, last_body = status, body
        if status not in retry_statuses:
            return status, body
        if attempt >= max_retries:
            return status, body
        delay = _parse_retry_after(retry_after,
                                   backoff_delay(attempt, backoff_base, backoff_cap))
        _log.debug("retry_http_sync[%s] HTTP %d → sleep %.2fs (attempt %d/%d)",
                   namespace, status, delay, attempt + 1, max_retries)
        time.sleep(delay)
    return last_status, last_body


async def retry_http_async(call: Callable[[], "asyncio.Future[tuple[int, Any, Any]]"],
                           *, namespace: str,
                           max_retries: int = 2,
                           retry_statuses: frozenset[int] = _RETRY_STATUSES_DEFAULT,
                           backoff_base: float = 1.0,
                           backoff_cap: float = 30.0) -> tuple[int, Any]:
    """Async variant of :func:`retry_http_sync`."""
    bucket = get_bucket(namespace)
    last_status: int = 0
    last_body: Any = None
    for attempt in range(max_retries + 1):
        await bucket.wait_async()
        try:
            status, body, retry_after = await call()
        except TransientError:
            if attempt >= max_retries:
                return 0, "transport: TransientError after retries"
            await asyncio.sleep(backoff_delay(attempt, backoff_base, backoff_cap))
            continue
        last_status, last_body = status, body
        if status not in retry_statuses:
            return status, body
        if attempt >= max_retries:
            return status, body
        delay = _parse_retry_after(retry_after,
                                   backoff_delay(attempt, backoff_base, backoff_cap))
        _log.debug("retry_http_async[%s] HTTP %d → sleep %.2fs (attempt %d/%d)",
                   namespace, status, delay, attempt + 1, max_retries)
        await asyncio.sleep(delay)
    return last_status, last_body
