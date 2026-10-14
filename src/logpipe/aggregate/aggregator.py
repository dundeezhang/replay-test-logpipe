"""Group records into tumbling windows and summarise each group.

Windows are closed by an event-time watermark: the newest record timestamp
seen so far, minus ``allowed_lateness``. Once a window's end falls behind the
watermark its rows are emitted, and any record that arrives for it afterwards
is counted in :attr:`Aggregator.late_records` and otherwise ignored.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from logpipe.aggregate.stats import Summary
from logpipe.aggregate.window import TumblingWindows, Window
from logpipe.record import Level, LogRecord

GroupKey = tuple[Any, ...]


@dataclass(slots=True)
class AggregateRow:
    window: Window
    group: dict[str, Any]
    count: int
    levels: dict[str, int]
    metric: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "window_start": self.window.start.isoformat(),
            "window_end": self.window.end.isoformat(),
            "group": dict(self.group),
            "count": self.count,
            "levels": dict(self.levels),
        }
        if self.metric is not None:
            data["metric"] = dict(self.metric)
        return data

    def to_flat_dict(self) -> dict[str, Any]:
        """Single-level mapping for tabular output (text table, CSV)."""
        flat: dict[str, Any] = {"window": self.window.label()}
        flat.update(self.group)
        flat["count"] = self.count
        flat["errors"] = self.levels.get("error", 0) + self.levels.get("critical", 0)
        flat["warnings"] = self.levels.get("warning", 0)
        for key, value in (self.metric or {}).items():
            if key != "count":
                flat[key] = value
        return flat


@dataclass(slots=True)
class _Bucket:
    count: int = 0
    levels: Counter[str] = field(default_factory=Counter)
    metric: Summary | None = None


def _hashable(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def _display(value: Any) -> Any:
    if isinstance(value, Level):
        return value.name.lower()
    return value


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _sort_key(key: GroupKey) -> tuple[str, ...]:
    return tuple("" if v is None else str(_display(v)) for v in key)


class Aggregator:
    def __init__(
        self,
        width: timedelta | float = 60,
        *,
        group_by: Sequence[str] = (),
        metric: str | None = None,
        percentiles: Sequence[float] = (50, 90, 99),
        allowed_lateness: timedelta | float = 0,
    ) -> None:
        for p in percentiles:
            if not 0 <= p <= 100:
                raise ValueError(f"percentile must be between 0 and 100, got {p}")
        if not isinstance(allowed_lateness, timedelta):
            allowed_lateness = timedelta(seconds=allowed_lateness)
        if allowed_lateness < timedelta(0):
            raise ValueError("allowed_lateness must not be negative")

        self.windows = TumblingWindows(width)
        self.group_by = tuple(group_by)
        self.metric = metric
        self.percentiles = tuple(percentiles)
        self.allowed_lateness = allowed_lateness

        self.late_records = 0
        self.non_numeric = 0
        self._open: dict[Window, dict[GroupKey, _Bucket]] = {}
        self._watermark: datetime | None = None

    @property
    def open_windows(self) -> list[Window]:
        return sorted(self._open)

    def _group_key(self, record: LogRecord) -> GroupKey:
        return tuple(_hashable(record.get(name)) for name in self.group_by)

    def add(self, record: LogRecord) -> list[AggregateRow]:
        """Add one record and return rows for any windows it caused to close."""
        window = self.windows.window_for(record.timestamp)
        if self._watermark is not None and window.end + self.allowed_lateness <= self._watermark:
            self.late_records += 1
            return []

        buckets = self._open.setdefault(window, {})
        bucket = buckets.setdefault(self._group_key(record), _Bucket())
        bucket.count += 1
        bucket.levels[record.level.name.lower()] += 1
        if self.metric is not None:
            value = _as_number(record.get(self.metric))
            if value is None:
                self.non_numeric += 1
            else:
                if bucket.metric is None:
                    bucket.metric = Summary()
                bucket.metric.add(value)

        if self._watermark is None or record.timestamp > self._watermark:
            self._watermark = record.timestamp
            return self._close_through(self._watermark - self.allowed_lateness)
        return []

    def flush_expired(self, now: datetime | None = None) -> list[AggregateRow]:
        """Close windows using wall-clock time instead of the event watermark.

        On a live stream the watermark only moves when records arrive, so the
        most recent window would stay open through a quiet period. Calling
        this periodically closes windows whose end (plus the allowed lateness)
        is already in the past.
        """
        now = now or datetime.utcnow()
        return self._close_through(now - self.allowed_lateness)

    def finish(self) -> list[AggregateRow]:
        """Close and return every open window (end of input)."""
        rows: list[AggregateRow] = []
        for window in sorted(self._open):
            rows.extend(self._rows_for(window, self._open[window]))
        self._open.clear()
        return rows

    def run(self, records: Iterable[LogRecord]) -> Iterator[AggregateRow]:
        for record in records:
            yield from self.add(record)
        yield from self.finish()

    def _close_through(self, cutoff: datetime) -> list[AggregateRow]:
        rows: list[AggregateRow] = []
        for window in sorted(w for w in self._open if w.end <= cutoff):
            rows.extend(self._rows_for(window, self._open.pop(window)))
        return rows

    def _rows_for(self, window: Window, buckets: dict[GroupKey, _Bucket]) -> list[AggregateRow]:
        rows: list[AggregateRow] = []
        for key in sorted(buckets, key=_sort_key):
            bucket = buckets[key]
            rows.append(
                AggregateRow(
                    window=window,
                    group={name: _display(v) for name, v in zip(self.group_by, key)},
                    count=bucket.count,
                    levels=dict(bucket.levels),
                    metric=(
                        bucket.metric.to_dict(self.percentiles)
                        if bucket.metric is not None
                        else None
                    ),
                )
            )
        return rows
