"""Drop records below a minimum severity."""

from __future__ import annotations

from logpipe.pipeline import Filter
from logpipe.record import Level, LogRecord
from logpipe.stages import register_stage


@register_stage("level")
class LevelFilter(Filter):
    def __init__(self, min: str | int = "info") -> None:  # noqa: A002 - config key
        self.min_level = Level.parse(min)

    def keep(self, record: LogRecord) -> bool:
        return record.level >= self.min_level
