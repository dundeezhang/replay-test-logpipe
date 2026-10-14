from datetime import datetime, timezone

import pytest

from logpipe.parsers import ParseError, available_parsers, get_parser
from logpipe.record import Level

NOW = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)


def syslog_parser(**kwargs):
    return get_parser("syslog", now=lambda: NOW, **kwargs)


def test_builtin_parsers_are_registered():
    assert {"jsonl", "syslog"} <= set(available_parsers())


def test_syslog_with_priority():
    record = syslog_parser().parse_line(
        "<34>Mar 15 10:22:01 web-1 sshd[4021]: Failed password for root from 10.0.0.5"
    )
    assert record.timestamp == datetime(2024, 3, 15, 10, 22, 1, tzinfo=timezone.utc)
    assert record.host == "web-1"
    assert record.source == "sshd"
    assert record.level is Level.CRITICAL
    assert record.fields == {"tag": "sshd", "facility": 4, "pid": 4021}
    assert record.message.startswith("Failed password")


def test_syslog_without_priority_defaults_to_info():
    record = syslog_parser().parse_line("Mar  3 01:02:03 db-2 kernel: eth0 link up")
    assert record.level is Level.INFO
    assert record.fields == {"tag": "kernel"}


def test_syslog_rolls_back_year_for_december_lines_in_january():
    parser = get_parser("syslog", now=lambda: datetime(2024, 1, 2, tzinfo=timezone.utc))
    record = parser.parse_line("Dec 31 23:59:59 host cron[1]: tick")
    assert record.timestamp.year == 2023


def test_syslog_rejects_garbage():
    with pytest.raises(ParseError):
        syslog_parser().parse_line("this is not syslog")


def test_jsonl_maps_common_keys():
    line = '{"ts": 1714564800, "msg": "started", "level": "warn", "host": "a", "port": 8080}'
    record = get_parser("jsonl").parse_line(line)
    assert record.timestamp == datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)
    assert record.message == "started"
    assert record.level is Level.WARNING
    assert record.host == "a"
    assert record.fields == {"port": 8080}


def test_jsonl_epoch_millis():
    record = get_parser("jsonl").parse_line('{"timestamp": 1714564800123, "message": "x"}')
    assert record.timestamp.microsecond == 123000


def test_parse_skips_bad_lines_unless_strict():
    parser = get_parser("jsonl")
    lines = ['{"time": "2024-05-01T00:00:00Z", "msg": "ok"}\n', "not json\n", "\n"]
    assert [r.message for r in parser.parse(lines)] == ["ok"]
    assert parser.errors == 1
    with pytest.raises(ParseError) as excinfo:
        list(get_parser("jsonl").parse(lines, strict=True))
    assert excinfo.value.lineno == 2
