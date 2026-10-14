"""NCSA combined log format, as written by nginx and Apache httpd.

    $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent
        "$http_referer" "$http_user_agent"

Lines in the older common log format (without referer and user agent) are
accepted too. Two widespread extensions are understood:

* Apache's ``vhost_combined`` layout, which prefixes each line with
  ``%v:%p`` (enable with ``vhost=True``), and
* a trailing ``$request_time`` in seconds, which many nginx setups append.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from logpipe.parsers import register
from logpipe.parsers.base import ParseError, Parser
from logpipe.record import Level, LogRecord

_TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"

_BODY = r"""
    (?P<remote_addr>\S+)\s
    (?P<ident>\S+)\s
    (?P<remote_user>\S+)\s
    \[(?P<time>[^\]]+)\]\s
    "(?P<request>(?:[^"\\]|\\.)*)"\s
    (?P<status>\d{3})\s
    (?P<size>\d+|-)
    (?:\s"(?P<referer>(?:[^"\\]|\\.)*)"\s"(?P<user_agent>(?:[^"\\]|\\.)*)")?
    (?:\s(?P<request_time>\d+(?:\.\d+)?))?
    \s*$
"""

_LINE_RE = re.compile(r"^" + _BODY, re.VERBOSE)
_VHOST_LINE_RE = re.compile(r"^(?P<vhost>[^\s:]+):(?P<port>\d+)\s" + _BODY, re.VERBOSE)

# Well-behaved clients send "METHOD target PROTOCOL", but scanners and some
# embedded clients send targets containing unencoded spaces, so the target is
# allowed to span several whitespace-separated chunks.
_REQUEST_RE = re.compile(
    r"^(?P<method>[A-Z]+) (?P<target>(?:\S+\s?)+) (?P<protocol>HTTP/\d(?:\.\d)?)$"
)


def _none_if_dash(value: str | None) -> str | None:
    return None if value in (None, "-", "") else value


def _level_for_status(status: int) -> Level:
    if status >= 500:
        return Level.ERROR
    if status > 400:
        return Level.WARNING
    return Level.INFO


def _split_request(request: str) -> dict[str, Any]:
    """Break the raw request line into method, path, query and protocol."""
    if request in ("", "-"):
        return {}
    match = _REQUEST_RE.match(request)
    if match is None:
        return {"request": request}
    target = match["target"].rstrip()
    parts = urlsplit(target)
    out: dict[str, Any] = {
        "method": match["method"],
        "path": parts.path or target,
        "protocol": match["protocol"],
    }
    if parts.query:
        out["query"] = parts.query
    return out


@register
class CombinedLogParser(Parser):
    name = "combined"
    description = "nginx/Apache combined or common access log"

    def __init__(self, *, source: str = "", vhost: bool = False) -> None:
        super().__init__(source=source)
        self.vhost = vhost
        self._line_re = _VHOST_LINE_RE if vhost else _LINE_RE

    def parse_line(self, line: str) -> LogRecord:
        match = self._line_re.match(line)
        if match is None:
            raise ParseError("not a combined/common access log line", line)

        try:
            timestamp = datetime.strptime(match["time"], _TIME_FORMAT)
        except ValueError as exc:
            raise ParseError(f"bad timestamp: {exc}", line) from exc

        status = int(match["status"])
        fields: dict[str, Any] = {
            "remote_addr": match["remote_addr"],
            "status": status,
            "bytes": int(match["size"]),
        }
        fields.update(_split_request(match["request"]))
        if user := _none_if_dash(match["remote_user"]):
            fields["remote_user"] = user
        if referer := _none_if_dash(match["referer"]):
            fields["referer"] = referer
        if user_agent := _none_if_dash(match["user_agent"]):
            fields["user_agent"] = user_agent
        if match["request_time"] is not None:
            fields["request_time"] = float(match["request_time"])
        if self.vhost:
            fields["vhost"] = match["vhost"]
            fields["port"] = int(match["port"])

        if "method" in fields:
            message = f"{fields['method']} {fields['path']} {status}"
        else:
            message = f"{match['request'] or '-'} {status}"

        return LogRecord(
            timestamp=timestamp,
            message=message,
            level=_level_for_status(status),
            source=self.source or "access",
            host=fields.get("vhost"),
            fields=fields,
            raw=line,
        )
