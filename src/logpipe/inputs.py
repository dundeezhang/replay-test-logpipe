"""Reading raw lines from files or stdin and turning them into records."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable, Iterator

from logpipe.parsers import get_parser
from logpipe.record import LogRecord

log = logging.getLogger(__name__)


def iter_lines(path: str, encoding: str = "utf-8") -> Iterator[str]:
    """Yield lines from ``path``; ``-`` means standard input."""
    if path == "-":
        yield from sys.stdin
        return
    with open(path, encoding=encoding, errors="replace") as fh:
        yield from fh


def read_records(
    paths: Iterable[str],
    fmt: str,
    *,
    strict: bool = False,
    encoding: str = "utf-8",
) -> Iterator[LogRecord]:
    parser = get_parser(fmt)
    for path in paths:
        log.debug("reading %s as %s", path, fmt)
        yield from parser.parse(iter_lines(path, encoding), strict=strict)
    if parser.errors:
        log.warning("%d line(s) could not be parsed as %s", parser.errors, fmt)
