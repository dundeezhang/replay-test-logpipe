from datetime import datetime, timedelta, timezone

import pytest

from logpipe.record import Level
from logpipe.stages import build_stage

T0 = datetime(2024, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def test_suppresses_repeats_within_window(make_record):
    stage = build_stage({"type": "dedup", "window": 10})
    records = [
        make_record("disk full", ts=at(0)),
        make_record("disk full", ts=at(5)),
        make_record("disk full", ts=at(9)),
        make_record("disk full", ts=at(20)),
    ]
    kept = list(stage.process(records))
    assert [r.timestamp for r in kept] == [at(0), at(20)]
    assert stage.suppressed == 2


def test_level_is_part_of_the_key(make_record):
    stage = build_stage({"type": "dedup", "window": 60})
    kept = list(
        stage.process(
            [
                make_record("retrying", Level.INFO, ts=at(0)),
                make_record("retrying", Level.ERROR, ts=at(1)),
            ]
        )
    )
    assert len(kept) == 2


def test_tracked_keys_are_bounded(make_record):
    stage = build_stage({"type": "dedup", "max_keys": 3})
    list(stage.process(make_record(f"msg {i}", ts=at(i)) for i in range(10)))
    assert len(stage._seen) == 3


@pytest.mark.parametrize("spec", [{"window": 0}, {"max_keys": 0}])
def test_invalid_options(spec):
    with pytest.raises(ValueError):
        build_stage({"type": "dedup", **spec})
