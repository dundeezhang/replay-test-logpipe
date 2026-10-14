"""Suppress repeated records within a time window."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime, timedelta

from logpipe.pipeline import Filter
from logpipe.record import LogRecord
from logpipe.stages import register_stage

log = logging.getLogger(__name__)


@register_stage("dedup")
class DedupFilter(Filter):
    """Drop a record if the same message was seen less than ``window`` seconds ago.

    At most ``max_keys`` distinct messages are tracked; when the table is full
    the least recently seen message is forgotten, so memory stays bounded on
    high-cardinality streams.
    """

    def __init__(self, window: float = 60.0, max_keys: int = 10_000) -> None:
        if window <= 0:
            raise ValueError("window must be positive")
        if max_keys < 1:
            raise ValueError("max_keys must be >= 1")
        self.window = timedelta(seconds=window)
        self.max_keys = max_keys
        self.suppressed = 0
        self._seen: OrderedDict[tuple[int, str], datetime] = OrderedDict()

    def keep(self, record: LogRecord) -> bool:
        key = (int(record.level), record.message)
        last = self._seen.get(key)
        if last is not None and record.timestamp - last < self.window:
            self.suppressed += 1
            return False
        self._seen[key] = record.timestamp
        self._seen.move_to_end(key)
        if len(self._seen) > self.max_keys:
            self._seen.popitem()
        return True

    def close(self) -> None:
        if self.suppressed:
            log.info("dedup suppressed %d repeated record(s)", self.suppressed)
