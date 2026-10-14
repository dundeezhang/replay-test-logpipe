"""Keep (or drop) records whose field matches a regular expression."""

from __future__ import annotations

import re

from logpipe.pipeline import Filter
from logpipe.record import LogRecord
from logpipe.stages import register_stage


@register_stage("match")
class MatchFilter(Filter):
    """Filter on ``field`` matching ``pattern``.

    ``field`` may be a record attribute (``message``, ``source``, ``host``) or
    a dotted path into ``fields``. Records missing the field never match.
    Set ``invert = true`` to drop matching records instead.
    """

    def __init__(
        self,
        pattern: str,
        field: str = "message",
        invert: bool = False,
        ignore_case: bool = False,
    ) -> None:
        flags = re.IGNORECASE if ignore_case else 0
        self.regex = re.compile(pattern, flags)
        self.field = field
        self.invert = invert

    def keep(self, record: LogRecord) -> bool:
        value = record.get(self.field)
        matched = value is not None and self.regex.search(str(value)) is not None
        return matched != self.invert
