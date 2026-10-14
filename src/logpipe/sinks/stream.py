"""Sinks that write formatted records to a text stream or file."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Literal

from logpipe.pipeline import Sink
from logpipe.record import LogRecord
from logpipe.sinks import register_sink

Format = Literal["text", "json"]


def format_record(record: LogRecord, fmt: Format) -> str:
    if fmt == "json":
        return json.dumps(record.to_dict(), default=str, separators=(",", ":"))
    host = f" {record.host}" if record.host else ""
    source = f" {record.source}:" if record.source else ""
    return (
        f"{record.timestamp.isoformat()} {record.level.name:<8}{host}{source} {record.message}"
    )


@register_sink("stdout")
class StdoutSink(Sink):
    def __init__(self, format: Format = "text", stream: IO[str] | None = None) -> None:  # noqa: A002
        if format not in ("text", "json"):
            raise ValueError(f"unsupported output format {format!r}")
        self.format: Format = format
        self.stream = stream if stream is not None else sys.stdout

    def write(self, record: LogRecord) -> None:
        self.stream.write(format_record(record, self.format) + "\n")

    def flush(self) -> None:
        self.stream.flush()


@register_sink("file")
class FileSink(Sink):
    """Append records to a file, one per line."""

    def __init__(self, path: str, format: Format = "json", encoding: str = "utf-8") -> None:  # noqa: A002
        if format not in ("text", "json"):
            raise ValueError(f"unsupported output format {format!r}")
        self.path = Path(path)
        self.format: Format = format
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: IO[str] | None = self.path.open("a", encoding=encoding)

    def write(self, record: LogRecord) -> None:
        if self._fh is None:
            raise RuntimeError(f"sink for {self.path} is closed")
        self._fh.write(format_record(record, self.format) + "\n")

    def flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
