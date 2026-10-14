from datetime import datetime, timedelta, timezone

import pytest

from logpipe.aggregate.window import TumblingWindows, Window

UTC = timezone.utc


def test_windows_align_to_epoch():
    windows = TumblingWindows(60)
    window = windows.window_for(datetime(2024, 5, 1, 12, 3, 41, 500, tzinfo=UTC))
    assert window.start == datetime(2024, 5, 1, 12, 3, tzinfo=UTC)
    assert window.end == datetime(2024, 5, 1, 12, 4, tzinfo=UTC)
    assert window.width == timedelta(minutes=1)
    assert window.label() == "2024-05-01T12:03:00Z"


def test_boundaries_are_half_open():
    windows = TumblingWindows(timedelta(minutes=5))
    edge = datetime(2024, 5, 1, 12, 5, tzinfo=UTC)
    window = windows.window_for(edge)
    assert window.start == edge
    assert edge in window
    assert window.end not in window


def test_non_utc_timestamps_map_to_utc_windows():
    plus_two = timezone(timedelta(hours=2))
    windows = TumblingWindows(3600)
    window = windows.window_for(datetime(2024, 5, 1, 14, 30, tzinfo=plus_two))
    assert window.start == datetime(2024, 5, 1, 12, 0, tzinfo=UTC)
    assert window.start.tzinfo == UTC


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        TumblingWindows(60).window_for(datetime(2024, 5, 1, 12, 0))


@pytest.mark.parametrize("width", [0, -5, 7, 86400 * 2])
def test_invalid_widths(width):
    with pytest.raises(ValueError):
        TumblingWindows(width)


def test_windows_between_fills_gaps():
    windows = TumblingWindows(60)
    first = windows.window_for(datetime(2024, 5, 1, 12, 0, 10, tzinfo=UTC))
    last = windows.window_for(datetime(2024, 5, 1, 12, 3, 59, tzinfo=UTC))
    starts = [w.start.minute for w in windows.windows_between(first, last)]
    assert starts == [0, 1, 2, 3]


def test_windows_sort_chronologically():
    a = Window(datetime(2024, 1, 1, 0, 1, tzinfo=UTC), datetime(2024, 1, 1, 0, 2, tzinfo=UTC))
    b = Window(datetime(2024, 1, 1, 0, 0, tzinfo=UTC), datetime(2024, 1, 1, 0, 1, tzinfo=UTC))
    assert sorted([a, b]) == [b, a]
