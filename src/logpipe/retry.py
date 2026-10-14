"""Retry policy with exponential backoff and jitter."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class RetryableError(Exception):
    """Raised by an operation to signal that it may succeed if retried.

    ``retry_after`` carries a server-provided delay hint, in seconds, which
    takes precedence over the computed backoff.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RetriesExhausted(Exception):
    """The operation kept failing until the policy gave up."""

    def __init__(self, attempts: int, last_error: BaseException) -> None:
        super().__init__(f"giving up after {attempts} attempt(s): {last_error}")
        self.attempts = attempts
        self.last_error = last_error


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff: ``base_delay * multiplier ** (attempt - 1)``.

    ``max_attempts`` counts the first call, so ``max_attempts=3`` means one
    call plus up to two retries. ``None`` keeps retrying until the operation
    succeeds or raises a non-retryable error, which is what a log shipper
    wants during a collector outage: back off and hold the batch rather than
    drop it.
    """

    max_attempts: int | None = None
    base_delay: float = 0.5
    max_delay: float = 30.0
    multiplier: float = 2.0
    jitter: float = 0.1

    def __post_init__(self) -> None:
        if self.max_attempts is not None and self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1 or None")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays must be non-negative")
        if self.multiplier < 1:
            raise ValueError("multiplier must be >= 1")

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        """Seconds to wait after failed attempt number ``attempt`` (1-based)."""
        if retry_after is not None:
            return retry_after
        delay = self.base_delay * self.multiplier ** (attempt - 1)
        if self.jitter:
            delay += random.uniform(0, delay * self.jitter)
        return delay

    def call(
        self,
        fn: Callable[[], T],
        *,
        sleep: Callable[[float], None] = time.sleep,
        describe: str = "operation",
    ) -> T:
        """Call ``fn`` until it succeeds, retrying on :class:`RetryableError`."""
        attempt = 0
        while True:
            attempt += 1
            try:
                return fn()
            except RetryableError as exc:
                if self.max_attempts is not None and attempt >= self.max_attempts:
                    raise RetriesExhausted(attempt, exc) from exc
                delay = self.delay_for(attempt, exc.retry_after)
                log.warning(
                    "%s failed on attempt %d (%s); retrying in %.2fs",
                    describe,
                    attempt,
                    exc,
                    delay,
                )
                sleep(delay)
