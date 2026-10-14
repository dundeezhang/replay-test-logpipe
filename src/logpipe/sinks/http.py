"""Ship records to an HTTP collector in batches.

Records are buffered and POSTed as newline-delimited JSON (or a JSON array)
once the batch reaches ``batch_size`` records, ``batch_bytes`` bytes, or
``flush_interval`` seconds since the last flush. Retryable failures (network
errors, 408/429/5xx) are retried with exponential backoff; batches that still
cannot be delivered are written to ``spool_dir`` when one is configured, and
dropped otherwise.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from logpipe import __version__
from logpipe.pipeline import Sink
from logpipe.record import LogRecord
from logpipe.retry import RetriesExhausted, RetryableError, RetryPolicy
from logpipe.sinks import register_sink
from logpipe.sinks.spool import Spool, SpoolFullError

log = logging.getLogger(__name__)

Encoding = Literal["ndjson", "json"]

_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_CONTENT_TYPES: dict[str, str] = {
    "ndjson": "application/x-ndjson",
    "json": "application/json",
}


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""


class Transport(Protocol):
    def __call__(
        self, url: str, body: bytes, headers: dict[str, str], timeout: float
    ) -> Response: ...


def urllib_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> Response:
    """Default transport built on :mod:`urllib.request` (no extra dependencies)."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return Response(resp.status, resp_headers, resp.read())
    except urllib.error.HTTPError as exc:
        resp_headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
        return Response(exc.code, resp_headers, exc.read())


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a delta-seconds ``Retry-After`` header (HTTP-date is ignored)."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class HttpSinkError(RuntimeError):
    """The collector rejected a batch with a non-retryable status."""


@register_sink("http")
class HttpSink(Sink):
    def __init__(
        self,
        url: str,
        *,
        token: str | None = None,
        token_env: str | None = "LOGPIPE_TOKEN",
        headers: dict[str, str] = {},
        batch_size: int = 500,
        batch_bytes: int = 1_000_000,
        flush_interval: float = 5.0,
        encoding: Encoding = "ndjson",
        compress: bool = True,
        timeout: float = 10.0,
        max_attempts: int | None = None,
        spool_dir: str | None = None,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"http sink url must start with http:// or https://: {url!r}")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if batch_bytes < 1:
            raise ValueError("batch_bytes must be >= 1")
        if encoding not in _CONTENT_TYPES:
            raise ValueError(f"unsupported encoding {encoding!r}")

        self.url = url
        self.batch_size = batch_size
        self.batch_bytes = batch_bytes
        self.flush_interval = flush_interval
        self.encoding: Encoding = encoding
        self.compress = compress
        self.timeout = timeout

        if token is None and token_env:
            token = os.environ.get(token_env)
        self._headers = headers
        self._headers.setdefault("Content-Type", _CONTENT_TYPES[encoding])
        self._headers.setdefault("User-Agent", f"logpipe/{__version__}")
        if compress:
            self._headers["Content-Encoding"] = "gzip"
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

        self._retry = RetryPolicy(max_attempts=max_attempts)
        self._spool = Spool(spool_dir) if spool_dir else None
        self._transport: Transport = transport or urllib_transport
        self._clock = clock
        self._sleep = sleep

        self._buffer: list[bytes] = []
        self._buffer_bytes = 0
        self._last_flush = clock()

        self.sent_batches = 0
        self.sent_records = 0
        self.failed_records = 0

        log.info(
            "http sink -> %s (batch_size=%d, encoding=%s, headers=%s)",
            url,
            batch_size,
            encoding,
            self._headers,
        )

    # -- buffering -----------------------------------------------------------

    def write(self, record: LogRecord) -> None:
        line = json.dumps(record.to_dict(), default=str, separators=(",", ":")).encode()
        if self._buffer and self._buffer_bytes + len(line) + 1 > self.batch_bytes:
            self.flush()
        self._buffer.append(line)
        self._buffer_bytes += len(line) + 1
        if (
            len(self._buffer) >= self.batch_size
            or self._clock() - self._last_flush >= self.flush_interval
        ):
            self.flush()

    def _encode(self, lines: list[bytes]) -> bytes:
        if self.encoding == "ndjson":
            return b"\n".join(lines) + b"\n"
        return b"[" + b",".join(lines) + b"]"

    # -- delivery ------------------------------------------------------------

    def _send(self, body: bytes) -> None:
        payload = gzip.compress(body) if self.compress else body
        try:
            response = self._transport(self.url, payload, self._headers, self.timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise RetryableError(f"transport error: {exc}") from exc
        if 200 <= response.status < 300:
            return
        detail = response.body[:200].decode("utf-8", "replace").strip()
        message = f"HTTP {response.status} from {self.url}: {detail}"
        if response.status in _RETRYABLE_STATUS:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            raise RetryableError(message, retry_after=retry_after)
        raise HttpSinkError(message)

    def _deliver(self, body: bytes) -> None:
        self._retry.call(lambda: self._send(body), sleep=self._sleep, describe="http batch")

    def flush(self) -> None:
        if not self._buffer:
            return
        lines, self._buffer, self._buffer_bytes = self._buffer, [], 0
        self._last_flush = self._clock()
        body = self._encode(lines)
        try:
            self._deliver(body)
        except (RetriesExhausted, HttpSinkError) as exc:
            self.failed_records += len(lines)
            self._spool_or_drop(body, len(lines), exc)
            return
        self.sent_batches += 1
        self.sent_records += len(lines)

    def _spool_or_drop(self, body: bytes, count: int, error: Exception) -> None:
        if self._spool is None:
            log.error("dropping %d record(s): %s", count, error)
            return
        try:
            path = self._spool.store(body, count=count)
        except (SpoolFullError, OSError) as spool_error:
            log.error("dropping %d record(s): %s (spool: %s)", count, error, spool_error)
            return
        log.error("spooled %d undelivered record(s) to %s: %s", count, path, error)

    def replay_spool(self) -> int:
        """Re-send batches left in the spool by earlier runs.

        Returns the number of batches delivered. Stops at the first batch that
        still cannot be delivered and leaves it (and anything newer) in place.
        """
        if self._spool is None:
            return 0
        return self._spool.drain(self._deliver, errors=(RetriesExhausted, HttpSinkError))

    def close(self) -> None:
        self.flush()
        log.info(
            "http sink closed: %d record(s) in %d batch(es) sent, %d failed",
            self.sent_records,
            self.sent_batches,
            self.failed_records,
        )
