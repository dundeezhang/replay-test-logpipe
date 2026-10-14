from datetime import datetime, timedelta, timezone

import pytest

from logpipe.aggregate import Aggregator
from logpipe.record import Level

T0 = datetime(2024, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def test_counts_per_window(make_record):
    agg = Aggregator(60)
    records = [make_record(ts=at(s)) for s in (0, 10, 59, 60, 61, 185)]
    rows = list(agg.run(records))
    assert [(row.window.start, row.count) for row in rows] == [
        (at(0), 3),
        (at(60), 2),
        (at(180), 1),
    ]


def test_group_by_level_and_host(make_record):
    agg = Aggregator(60, group_by=["level", "host"])
    records = [
        make_record(level=Level.ERROR, host="web-1", ts=at(1)),
        make_record(level=Level.ERROR, host="web-1", ts=at(2)),
        make_record(level=Level.INFO, host="web-1", ts=at(3)),
        make_record(level=Level.ERROR, host="web-2", ts=at(4)),
    ]
    rows = agg.run(records)
    assert [(row.group, row.count) for row in rows] == [
        ({"level": "error", "host": "web-1"}, 2),
        ({"level": "error", "host": "web-2"}, 1),
        ({"level": "info", "host": "web-1"}, 1),
    ]


def test_level_breakdown(make_record):
    agg = Aggregator(60)
    agg.add(make_record(level=Level.ERROR, ts=at(0)))
    agg.add(make_record(level=Level.WARNING, ts=at(1)))
    agg.add(make_record(level=Level.ERROR, ts=at(2)))
    (row,) = agg.finish()
    assert row.levels == {"error": 2, "warning": 1}
    assert row.to_flat_dict()["errors"] == 2


def test_metric_summary(make_record):
    agg = Aggregator(60, metric="request_time", percentiles=[50, 90])
    for i, value in enumerate([0.5, 0.1, 0.3, 0.2, 0.4]):
        agg.add(make_record(ts=at(i), fields={"request_time": value}))
    agg.add(make_record(ts=at(6), fields={"request_time": "n/a"}))
    agg.add(make_record(ts=at(7)))
    (row,) = agg.finish()
    assert row.count == 7
    assert row.metric == {
        "count": 5,
        "sum": pytest.approx(1.5),
        "min": 0.1,
        "max": 0.5,
        "mean": pytest.approx(0.3),
        "p50": 0.3,
        "p90": 0.5,
    }
    assert agg.non_numeric == 2


def test_windows_close_as_event_time_advances(make_record):
    agg = Aggregator(60)
    assert agg.add(make_record(ts=at(5))) == []
    assert agg.add(make_record(ts=at(30))) == []
    closed = agg.add(make_record(ts=at(61)))
    assert [row.window.start for row in closed] == [at(0)]
    assert agg.open_windows[0].start == at(60)


def test_allowed_lateness_keeps_windows_open(make_record):
    agg = Aggregator(60, allowed_lateness=15)
    agg.add(make_record(ts=at(10)))
    assert agg.add(make_record(ts=at(70))) == []
    assert agg.add(make_record(ts=at(50))) == []
    closed = agg.add(make_record(ts=at(76)))
    assert [(row.window.start, row.count) for row in closed] == [(at(0), 2)]


def test_late_records_are_counted_and_ignored(make_record):
    agg = Aggregator(60)
    agg.add(make_record(ts=at(10)))
    agg.add(make_record(ts=at(130)))
    assert agg.add(make_record(ts=at(20))) == []
    assert agg.late_records == 1
    assert [row.count for row in agg.finish()] == [1]


def test_flush_expired_uses_wall_clock(make_record):
    agg = Aggregator(60)
    agg.add(make_record(ts=at(10)))
    assert agg.flush_expired(now=at(59)) == []
    rows = agg.flush_expired(now=at(61))
    assert [row.window.start for row in rows] == [at(0)]
    assert agg.open_windows == []


def test_nested_field_groups(make_record):
    agg = Aggregator(60, group_by=["http.status"])
    records = [
        make_record(ts=at(1), fields={"http": {"status": 200}}),
        make_record(ts=at(2), fields={"http": {"status": 502}}),
        make_record(ts=at(3)),
    ]
    groups = [row.group["http.status"] for row in agg.run(records)]
    assert groups == [None, 200, 502]


@pytest.mark.parametrize(
    "kwargs",
    [{"percentiles": [101]}, {"allowed_lateness": -1}, {"width": 0}],
)
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        Aggregator(**kwargs)
