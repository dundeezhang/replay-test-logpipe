"""Core record type shared by parsers, stages and sinks."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_LEVEL_ALIASES = {
    "WARN": "WARNING",
    "ERR": "ERROR",
    "CRIT": "CRITICAL",
    "FATAL": "CRITICAL",
    "ALERT": "CRITICAL",
    "EMERG": "CRITICAL",
    "PANIC": "CRITICAL",
    "INFORMATIONAL": "INFO",
}


class Level(enum.IntEnum):
    """Severity levels, numerically compatible with :mod:`logging`."""

    TRACE = 5
    DEBUG = 10
    INFO = 20
    NOTICE = 25
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

    @classmethod
    def parse(cls, value: str | int | None) -> Level:
        """Parse a level name or number.

        Numbers that do not correspond to a defined level are snapped down to
        the closest level below them, so ``35`` becomes ``WARNING``.
        """
        if value is None:
            return cls.INFO
        if isinstance(value, int):
            candidates = [lvl for lvl in cls if lvl <= value]
            return max(candidates) if candidates else cls.TRACE
        name = value.strip().upper()
        name = _LEVEL_ALIASES.get(name, name)
        try:
            return cls[name]
        except KeyError:
            raise ValueError(f"unknown log level: {value!r}") from None


@dataclass(slots=True)
class LogRecord:
    """A single structured log event.

    ``timestamp`` is always timezone-aware; naive datetimes are assumed to be
    UTC when the record is constructed.
    """

    timestamp: datetime
    message: str
    level: Level = Level.INFO
    source: str = ""
    host: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    raw: str | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.name.lower(),
            "message": self.message,
        }
        if self.source:
            data["source"] = self.source
        if self.host:
            data["host"] = self.host
        if self.fields:
            data["fields"] = dict(self.fields)
        if include_raw and self.raw is not None:
            data["raw"] = self.raw
        return data

    def get(self, name: str, default: Any = None) -> Any:
        """Look up a top-level attribute or a dotted ``fields`` path."""
        if name in ("timestamp", "message", "level", "source", "host"):
            return getattr(self, name)
        current: Any = self.fields
        for part in name.removeprefix("fields.").split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current
