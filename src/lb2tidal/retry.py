"""Shared bounded-retry helper (§5.5).

A failing call is retried 4 times, then given up on. The wait doubles each time
(1 s, 2 s, 4 s, 8 s) with the actual delay drawn at random below that ceiling, so
repeated runs never retry in lockstep. One failing call costs at most ~15 s.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

import requests

log = logging.getLogger(__name__)

T = TypeVar("T")

ATTEMPTS = 5
BASE_DELAY = 1.0
RETRY_AFTER_CAP = 60.0
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class RetriesExhausted(Exception):
    """Every attempt failed. Carries the last underlying error."""

    def __init__(self, description: str, cause: BaseException) -> None:
        super().__init__(f"{description}: gave up after {ATTEMPTS} attempts ({cause})")
        self.cause = cause


def _retry_after(exc: BaseException) -> float | None:
    """Seconds requested by a Retry-After header, capped, or None."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return min(float(raw), RETRY_AFTER_CAP)
    except ValueError:
        return None  # HTTP-date form; the computed backoff is good enough.


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        return response is not None and response.status_code in RETRYABLE_STATUS
    return isinstance(exc, requests.ConnectionError | requests.Timeout)


def with_retry(description: str, call: Callable[[], T]) -> T:
    """Run ``call``, retrying transient failures with jittered exponential backoff."""
    last: BaseException | None = None

    for attempt in range(ATTEMPTS):
        try:
            return call()
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            last = exc
            if attempt == ATTEMPTS - 1:
                break
            ceiling = BASE_DELAY * (2**attempt)
            delay = _retry_after(exc) or random.uniform(0, ceiling)
            log.warning(
                "%s failed (%s), retrying in %.1fs [%d/%d]",
                description,
                exc,
                delay,
                attempt + 1,
                ATTEMPTS - 1,
            )
            time.sleep(delay)

    assert last is not None
    raise RetriesExhausted(description, last)
