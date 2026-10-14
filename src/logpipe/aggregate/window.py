"""Tumbling time windows aligned to the Unix epoch."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_DAY = timedelta(days=1)


@dataclass(frozen=True, order=True, slots=True)
class Window:
    """Half-open interval ``[start, end)`` in UTC."""

    start: datetime
    end: datetime

    def __contains__(self, ts: object) -> bool:
        return isinstance(ts, datetime) and self.start <= ts < self.end

    @property
    def width(self) -> timedelta:
        return self.end - self.start

    def label(self) -> str:
        return self.start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_timedelta(value: timedelta | float) -> timedelta:
    return value if isinstance(value, timedelta) else timedelta(seconds=value)


class TumblingWindows:
    """Assigns timestamps to fixed-width, non-overlapping windows.

    Windows are aligned to the Unix epoch in UTC, so a 60 second window always
    starts on a minute boundary regardless of when the first record arrives,
    and two processes aggregating the same stream agree on window edges.
    """

    def __init__(self, width: timedelta | float) -> None:
        width = _as_timedelta(width)
        if width <= timedelta(0):
            raise ValueError("window width must be positive")
        if width > _DAY or _DAY % width:
            raise ValueError("window width must divide a day evenly (e.g. 10s, 1m, 5m, 1h)")
        self.width = width

    def window_for(self, ts: datetime) -> Window:
        if ts.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        offset = (ts - _EPOCH) % self.width
        start = (ts - offset).astimezone(timezone.utc)
        return Window(start, start + self.width)

    def windows_between(self, first: Window, last: Window) -> Iterator[Window]:
        """Every window from ``first`` to ``last`` inclusive, e.g. to zero-fill gaps."""
        start = first.start
        while start <= last.start:
            yield Window(start, start + self.width)
            start += self.width
