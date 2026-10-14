"""Parser base class and error type."""

from __future__ import annotations

import abc
import logging
from collections.abc import Iterable, Iterator
from typing import ClassVar

from logpipe.record import LogRecord

log = logging.getLogger(__name__)


class ParseError(ValueError):
    """Raised when a line cannot be parsed by a parser."""

    def __init__(self, reason: str, line: str, lineno: int | None = None) -> None:
        self.reason = reason
        self.line = line
        self.lineno = lineno
        where = f" (line {lineno})" if lineno is not None else ""
        super().__init__(f"{reason}{where}: {line[:120]!r}")


class Parser(abc.ABC):
    """Turns raw text lines into :class:`LogRecord` objects."""

    name: ClassVar[str]
    description: ClassVar[str] = ""

    def __init__(self, *, source: str = "") -> None:
        self.source = source
        self.errors = 0

    @abc.abstractmethod
    def parse_line(self, line: str) -> LogRecord:
        """Parse a single line (without its trailing newline)."""
        raise NotImplementedError

    def parse(self, lines: Iterable[str], *, strict: bool = False) -> Iterator[LogRecord]:
        """Parse a stream of lines, skipping blanks.

        In non-strict mode unparseable lines are counted in :attr:`errors` and
        skipped; in strict mode the first :class:`ParseError` is re-raised with
        its line number attached.
        """
        for lineno, line in enumerate(lines, start=1):
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            try:
                record = self.parse_line(line)
            except ParseError as exc:
                if strict:
                    raise ParseError(exc.reason, exc.line, lineno) from exc
                self.errors += 1
                log.debug("skipping unparseable line %d: %s", lineno, exc.reason)
                continue
            if self.source and not record.source:
                record.source = self.source
            yield record
