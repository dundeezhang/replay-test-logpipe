import json

from logpipe.cli import main

LINES = [
    {"time": "2024-05-01T12:00:05Z", "level": "info", "msg": "GET /", "duration_ms": 12},
    {"time": "2024-05-01T12:00:20Z", "level": "error", "msg": "GET /api", "duration_ms": 950},
    {"time": "2024-05-01T12:00:48Z", "level": "info", "msg": "GET /", "duration_ms": 15},
    {"time": "2024-05-01T12:01:02Z", "level": "warn", "msg": "GET /slow", "duration_ms": 480},
]


def write_log(tmp_path):
    path = tmp_path / "app.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in LINES))
    return str(path)


def test_aggregate_jsonl_report(tmp_path, capsys):
    path = write_log(tmp_path)
    code = main(
        ["aggregate", "-f", "jsonl", "-m", "duration_ms", "-p", "50", "--report", "jsonl", path]
    )
    assert code == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["count"] for row in rows] == [3, 1]
    assert rows[0]["metric"]["p50"] == 15.0
    assert rows[0]["levels"] == {"info": 2, "error": 1}


def test_aggregate_table_grouped_by_level(tmp_path, capsys):
    path = write_log(tmp_path)
    assert main(["aggregate", "-f", "jsonl", "-g", "level", path]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].split()[:3] == ["window", "level", "count"]
    assert len(out) == 2 + 3


def test_aggregate_csv_requires_path(tmp_path, capsys):
    path = write_log(tmp_path)
    assert main(["aggregate", "-f", "jsonl", "--report", "csv", path]) == 2
    assert "--csv-path" in capsys.readouterr().err
