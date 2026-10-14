"""Newline-delimited JSON parser for structured application logs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from logpipe.parsers import register
from logpipe.parsers.base import ParseError, Parser
from logpipe.record import Level, LogRecord

_TIME_KEYS = ("timestamp", "time", "ts", "@timestamp")
_MESSAGE_KEYS = ("message", "msg", "event")
_LEVEL_KEYS = ("level", "severity", "lvl")


def _first(obj: dict[str, Any], keys: tuple[str, ...]) -> tuple[str | None, Any]:
    for key in keys:
        if key in obj:
            return key, obj[key]
    return None, None


def _parse_time(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        # Heuristic: values this large are epoch milliseconds.
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"unsupported timestamp type {type(value).__name__}")


@register
class JsonLinesParser(Parser):
    name = "jsonl"
    description = "one JSON object per line (timestamp/time/ts, message/msg, level)"

    def parse_line(self, line: str) -> LogRecord:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ParseError(f"invalid JSON: {exc.msg}", line) from exc
        if not isinstance(obj, dict):
            raise ParseError("expected a JSON object", line)

        time_key, raw_time = _first(obj, _TIME_KEYS)
        if time_key is None:
            raise ParseError("missing timestamp", line)
        try:
            timestamp = _parse_time(raw_time)
        except (ValueError, OverflowError, OSError) as exc:
            raise ParseError(f"bad timestamp: {exc}", line) from exc

        msg_key, message = _first(obj, _MESSAGE_KEYS)
        level_key, raw_level = _first(obj, _LEVEL_KEYS)
        try:
            level = Level.parse(raw_level)
        except ValueError:
            level = Level.INFO

        consumed = {time_key, msg_key, level_key, "source", "host"}
        fields = {k: v for k, v in obj.items() if k not in consumed}
        return LogRecord(
            timestamp=timestamp,
            message="" if message is None else str(message),
            level=level,
            source=str(obj.get("source", "")),
            host=obj.get("host"),
            fields=fields,
            raw=line,
        )
