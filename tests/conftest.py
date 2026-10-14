from __future__ import annotations

from datetime import datetime, timezone

import pytest

from logpipe.record import Level, LogRecord


@pytest.fixture
def make_record():
    def _make(
        message: str = "hello",
        level: Level = Level.INFO,
        ts: datetime | None = None,
        **kwargs,
    ) -> LogRecord:
        return LogRecord(
            timestamp=ts or datetime(2024, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
            message=message,
            level=level,
            **kwargs,
        )

    return _make
