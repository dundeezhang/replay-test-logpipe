import io
import json

import pytest

from logpipe.pipeline import Pipeline, Sink
from logpipe.record import Level
from logpipe.sinks import build_sink
from logpipe.stages import build_stage


class ListSink(Sink):
    def __init__(self):
        self.records = []
        self.closed = False

    def write(self, record):
        self.records.append(record)

    def close(self):
        self.closed = True


def test_pipeline_applies_stages_in_order(make_record):
    records = [
        make_record("debug noise", Level.DEBUG),
        make_record("disk full", Level.ERROR),
        make_record("healthcheck ok", Level.WARNING),
    ]
    stages = [
        build_stage({"type": "level", "min": "warning"}),
        build_stage({"type": "match", "pattern": "healthcheck", "invert": True}),
    ]
    sink = ListSink()
    stats = Pipeline(stages, sink).run(records)
    assert [r.message for r in sink.records] == ["disk full"]
    assert (stats.read, stats.written, stats.dropped) == (3, 1, 2)
    assert sink.closed


def test_match_filter_on_nested_field(make_record):
    stage = build_stage({"type": "match", "field": "http.status", "pattern": r"^5\d\d$"})
    kept = list(
        stage.process(
            [
                make_record(fields={"http": {"status": 503}}),
                make_record(fields={"http": {"status": 200}}),
                make_record(),
            ]
        )
    )
    assert len(kept) == 1


def test_build_stage_errors():
    with pytest.raises(ValueError, match="missing 'type'"):
        build_stage({"min": "info"})
    with pytest.raises(ValueError, match="unknown stage type"):
        build_stage({"type": "nope"})
    with pytest.raises(ValueError, match="invalid options"):
        build_stage({"type": "level", "bogus": 1})


def test_stdout_sink_json(make_record):
    buf = io.StringIO()
    sink = build_sink("stdout", format="json", stream=buf)
    sink.write(make_record("hi", host="h1"))
    payload = json.loads(buf.getvalue())
    assert payload == {
        "timestamp": "2024-05-01T12:00:00+00:00",
        "level": "info",
        "message": "hi",
        "host": "h1",
    }


def test_file_sink_appends(tmp_path, make_record):
    path = tmp_path / "out" / "events.log"
    with build_sink("file", path=str(path), format="text") as sink:
        sink.write(make_record("one"))
        sink.write(make_record("two"))
    assert path.read_text().count("\n") == 2
