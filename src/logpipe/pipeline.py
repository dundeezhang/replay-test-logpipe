"""Pipeline primitives: stages transform record streams, sinks consume them."""

from __future__ import annotations

import abc
import logging
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from logpipe.record import LogRecord

log = logging.getLogger(__name__)


class Stage(abc.ABC):
    """A transformation applied to a stream of records.

    Stages are lazy: :meth:`process` receives an iterator and should yield
    records as they become available rather than materialising the stream.
    """

    name: str = "stage"

    @abc.abstractmethod
    def process(self, records: Iterable[LogRecord]) -> Iterator[LogRecord]:
        raise NotImplementedError

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release any resources held by the stage."""


class Filter(Stage):
    """A stage that keeps or drops records without modifying them."""

    @abc.abstractmethod
    def keep(self, record: LogRecord) -> bool:
        raise NotImplementedError

    def process(self, records: Iterable[LogRecord]) -> Iterator[LogRecord]:
        for record in records:
            if self.keep(record):
                yield record


class Transform(Stage):
    """A stage that maps each record to a (possibly modified) record."""

    @abc.abstractmethod
    def apply(self, record: LogRecord) -> LogRecord:
        raise NotImplementedError

    def process(self, records: Iterable[LogRecord]) -> Iterator[LogRecord]:
        for record in records:
            yield self.apply(record)


class Sink(abc.ABC):
    """Terminal consumer of records."""

    name: str = "sink"

    @abc.abstractmethod
    def write(self, record: LogRecord) -> None:
        raise NotImplementedError

    def flush(self) -> None:  # noqa: B027 - optional hook
        """Push any buffered records downstream."""

    def close(self) -> None:
        self.flush()

    def __enter__(self) -> Sink:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


@dataclass(slots=True)
class PipelineStats:
    read: int = 0
    written: int = 0
    elapsed: float = 0.0

    @property
    def dropped(self) -> int:
        return self.read - self.written


class Pipeline:
    """Chain of stages feeding a single sink."""

    def __init__(self, stages: Sequence[Stage], sink: Sink) -> None:
        self.stages = list(stages)
        self.sink = sink

    def _counted(self, records: Iterable[LogRecord], stats: PipelineStats) -> Iterator[LogRecord]:
        for record in records:
            stats.read += 1
            yield record

    def run(self, records: Iterable[LogRecord]) -> PipelineStats:
        stats = PipelineStats()
        started = time.monotonic()
        stream: Iterable[LogRecord] = self._counted(records, stats)
        for stage in self.stages:
            stream = stage.process(stream)
        try:
            for record in stream:
                self.sink.write(record)
                stats.written += 1
        finally:
            for stage in self.stages:
                stage.close()
            self.sink.close()
            stats.elapsed = time.monotonic() - started
        log.info(
            "pipeline finished: read=%d written=%d dropped=%d in %.3fs",
            stats.read,
            stats.written,
            stats.dropped,
            stats.elapsed,
        )
        return stats
