from datetime import datetime, timezone

import pytest

from logpipe.record import Level, LogRecord


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("info", Level.INFO),
        ("WARN", Level.WARNING),
        ("fatal", Level.CRITICAL),
        (40, Level.ERROR),
        (35, Level.WARNING),
        (1, Level.TRACE),
        (None, Level.INFO),
    ],
)
def test_level_parse(value, expected):
    assert Level.parse(value) is expected


def test_level_parse_rejects_unknown_names():
    with pytest.raises(ValueError, match="unknown log level"):
        Level.parse("loud")


def test_naive_timestamp_is_assumed_utc():
    record = LogRecord(timestamp=datetime(2024, 1, 1, 8, 30), message="x")
    assert record.timestamp.tzinfo is timezone.utc


def test_get_supports_dotted_field_paths(make_record):
    record = make_record(fields={"http": {"status": 502}})
    assert record.get("fields.http.status") == 502
    assert record.get("http.status") == 502
    assert record.get("http.missing", "n/a") == "n/a"
    assert record.get("message") == "hello"
