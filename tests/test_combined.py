from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from logpipe.inputs import read_records
from logpipe.parsers import ParseError, available_parsers, get_parser
from logpipe.record import Level

DATA = Path(__file__).parent / "data" / "access.log"

NGINX_LINE = (
    '198.51.100.23 - alice [14/Oct/2024:09:12:04 +0200] "POST /api/v1/orders?dry_run=1 HTTP/1.1" '
    '201 512 "https://example.com/checkout" "curl/8.5.0" 0.084'
)


def test_registered():
    assert "combined" in available_parsers()


def test_parses_full_combined_line():
    record = get_parser("combined").parse_line(NGINX_LINE)
    assert record.timestamp == datetime(2024, 10, 14, 9, 12, 4, tzinfo=timezone(timedelta(hours=2)))
    assert record.message == "POST /api/v1/orders 201"
    assert record.level is Level.INFO
    assert record.source == "access"
    assert record.fields == {
        "remote_addr": "198.51.100.23",
        "remote_user": "alice",
        "status": 201,
        "bytes": 512,
        "method": "POST",
        "path": "/api/v1/orders",
        "query": "dry_run=1",
        "protocol": "HTTP/1.1",
        "referer": "https://example.com/checkout",
        "user_agent": "curl/8.5.0",
        "request_time": 0.084,
    }


def test_common_log_format_without_referer_or_agent():
    line = '192.0.2.99 - - [14/Oct/2024:09:12:20 +0000] "GET /wp-login.php HTTP/1.1" 404 153'
    record = get_parser("combined").parse_line(line)
    assert record.fields["status"] == 404
    assert "referer" not in record.fields
    assert "user_agent" not in record.fields
    assert record.level is Level.WARNING


@pytest.mark.parametrize(
    ("status", "level"),
    [(200, Level.INFO), (302, Level.INFO), (404, Level.WARNING), (503, Level.ERROR)],
)
def test_level_follows_status(status, level):
    line = f'10.0.0.1 - - [14/Oct/2024:09:00:00 +0000] "GET /x HTTP/1.1" {status} 10'
    assert get_parser("combined").parse_line(line).level is level


def test_dash_size_means_no_body():
    line = '10.0.0.1 - - [14/Oct/2024:09:00:00 +0000] "GET /logo.png HTTP/1.1" 304 - "-" "curl/8.5.0"'
    record = get_parser("combined").parse_line(line)
    assert record.fields["bytes"] == 0
    assert record.fields["status"] == 304


def test_empty_request_line():
    line = '192.0.2.10 - - [14/Oct/2024:09:12:13 +0000] "-" 408 0 "-" "-"'
    record = get_parser("combined").parse_line(line)
    assert record.message == "- 408"
    assert "method" not in record.fields
    assert "user_agent" not in record.fields


def test_target_with_unencoded_space():
    line = '10.0.0.1 - - [14/Oct/2024:09:00:00 +0000] "GET /files/annual report.pdf HTTP/1.1" 200 1'
    record = get_parser("combined").parse_line(line)
    assert record.fields["path"] == "/files/annual report.pdf"
    assert record.fields["protocol"] == "HTTP/1.1"


def test_escaped_quotes_in_user_agent():
    line = (
        '10.0.0.1 - - [14/Oct/2024:09:00:00 +0000] "GET / HTTP/1.1" 200 1 "-" '
        '"Weird \\"Agent\\" 1.0"'
    )
    record = get_parser("combined").parse_line(line)
    assert record.fields["user_agent"] == 'Weird \\"Agent\\" 1.0'


def test_vhost_combined():
    line = (
        'shop.example.com:443 10.0.0.1 - - [14/Oct/2024:09:00:00 +0000] '
        '"GET /cart HTTP/1.1" 200 734 "-" "Mozilla/5.0"'
    )
    record = get_parser("combined", vhost=True).parse_line(line)
    assert record.host == "shop.example.com"
    assert record.fields["vhost"] == "shop.example.com"
    assert record.fields["port"] == 443


@pytest.mark.parametrize(
    "line",
    [
        "not an access log line",
        '10.0.0.1 - - [99/Oct/2024:09:00:00 +0000] "GET / HTTP/1.1" 200 1',
        '10.0.0.1 - - [14/Oct/2024:09:00:00 +0000] "GET / HTTP/1.1" 2000 1',
    ],
)
def test_rejects_malformed_lines(line):
    with pytest.raises(ParseError):
        get_parser("combined").parse_line(line)


def test_sample_file():
    records = list(read_records([str(DATA)], "combined"))
    assert len(records) == 9
    assert [r.fields["status"] for r in records if r.level is Level.ERROR] == [502]
    assert sum(r.fields["bytes"] for r in records) == 24485
