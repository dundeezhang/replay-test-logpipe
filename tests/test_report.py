import csv
import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from logpipe.aggregate import Aggregator
from logpipe.aggregate.report import render_table, write_csv, write_jsonl
from logpipe.record import Level

T0 = datetime(2024, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def rows(make_record):
    agg = Aggregator(60, group_by=["host"], metric="latency_ms", percentiles=[50])
    records = [
        make_record(host="a", ts=T0, fields={"latency_ms": 12}),
        make_record(
            host="a", level=Level.ERROR, ts=T0 + timedelta(seconds=5), fields={"latency_ms": 40}
        ),
        make_record(host="b", ts=T0 + timedelta(seconds=7)),
        make_record(host="a", ts=T0 + timedelta(seconds=65), fields={"latency_ms": 9}),
    ]
    return list(agg.run(records))


def test_render_table(rows):
    out = io.StringIO()
    assert render_table(rows, out) == 3
    lines = out.getvalue().splitlines()
    assert lines[0].split() == [
        "window",
        "host",
        "count",
        "errors",
        "warnings",
        "sum",
        "min",
        "max",
        "mean",
        "p50",
    ]
    assert lines[2].split()[:9] == [
        "2024-05-01T12:00:00Z",
        "a",
        "2",
        "1",
        "0",
        "52",
        "12",
        "40",
        "26",
    ]
    assert lines[3].split()[:3] == ["2024-05-01T12:00:00Z", "b", "1"]
    assert lines[3].split()[5:] == ["-", "-", "-", "-", "-"]


def test_render_empty_table():
    out = io.StringIO()
    assert render_table([], out) == 0
    assert out.getvalue() == "(no data)\n"


def test_write_jsonl(rows):
    out = io.StringIO()
    assert write_jsonl(rows, out) == 3
    first = json.loads(out.getvalue().splitlines()[0])
    assert first["window_start"] == "2024-05-01T12:00:00+00:00"
    assert first["group"] == {"host": "a"}
    assert first["levels"] == {"info": 1, "error": 1}
    assert first["metric"]["max"] == 40.0


def test_write_csv(tmp_path, rows):
    path = tmp_path / "report.csv"
    assert write_csv(rows, path) == 3
    with path.open(newline="") as fh:
        table = list(csv.DictReader(fh))
    assert [r["host"] for r in table] == ["a", "b", "a"]
    assert table[1]["mean"] == ""
    assert table[2]["window"] == "2024-05-01T12:01:00Z"
