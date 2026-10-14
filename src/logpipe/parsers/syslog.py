"""BSD syslog (RFC 3164) parser.

Handles the common ``<PRI>Mmm dd hh:mm:ss host tag[pid]: message`` shape as
written by rsyslog/syslog-ng with the traditional file format. The PRI prefix
is optional because most on-disk syslog files strip it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone, tzinfo

from logpipe.parsers import register
from logpipe.parsers.base import ParseError, Parser
from logpipe.record import Level, LogRecord

# RFC 5424 severity codes, 0 (emergency) .. 7 (debug).
_SEVERITY_TO_LEVEL = {
    0: Level.CRITICAL,
    1: Level.CRITICAL,
    2: Level.CRITICAL,
    3: Level.ERROR,
    4: Level.WARNING,
    5: Level.NOTICE,
    6: Level.INFO,
    7: Level.DEBUG,
}

_LINE_RE = re.compile(
    r"""
    ^(?:<(?P<pri>\d{1,3})>)?
    (?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s
    (?P<time>\d{2}:\d{2}:\d{2})\s
    (?P<host>\S+)\s
    (?P<tag>[^\s:\[]+)(?:\[(?P<pid>\d+)\])?:\s?
    (?P<message>.*)$
    """,
    re.VERBOSE,
)

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    start=1,
)}


@register
class SyslogParser(Parser):
    name = "syslog"
    description = "BSD syslog (RFC 3164), with or without <PRI> prefix"

    def __init__(
        self,
        *,
        source: str = "",
        tz: tzinfo = timezone.utc,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(source=source)
        self.tz = tz
        self._now = now or (lambda: datetime.now(tz=self.tz))

    def _timestamp(self, month: str, day: str, clock: str) -> datetime:
        # RFC 3164 timestamps carry no year. Assume the current year unless that
        # would put the event in the future, which happens around New Year.
        now = self._now()
        hour, minute, second = (int(p) for p in clock.split(":"))
        ts = datetime(now.year, _MONTHS[month], int(day), hour, minute, second, tzinfo=self.tz)
        if ts > now and (ts - now).days > 1:
            ts = ts.replace(year=now.year - 1)
        return ts

    def parse_line(self, line: str) -> LogRecord:
        match = _LINE_RE.match(line)
        if match is None or match["month"] not in _MONTHS:
            raise ParseError("not a syslog line", line)
        try:
            ts = self._timestamp(match["month"], match["day"], match["time"])
        except ValueError as exc:
            raise ParseError(f"bad timestamp: {exc}", line) from exc

        level = Level.INFO
        fields: dict[str, object] = {"tag": match["tag"]}
        if match["pri"] is not None:
            pri = int(match["pri"])
            if pri > 191:
                raise ParseError("PRI out of range", line)
            facility, severity = divmod(pri, 8)
            level = _SEVERITY_TO_LEVEL[severity]
            fields["facility"] = facility
        if match["pid"] is not None:
            fields["pid"] = int(match["pid"])

        return LogRecord(
            timestamp=ts,
            message=match["message"],
            level=level,
            source=self.source or match["tag"],
            host=match["host"],
            fields=fields,
            raw=line,
        )
