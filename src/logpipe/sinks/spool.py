"""On-disk spool for batches that could not be delivered.

Each batch is written to its own file named
``<ns-timestamp>-<sequence>-<count>.batch`` so that a later run can replay them
oldest-first. Files are written to a
temporary name and renamed into place, so a crash never leaves a partially
written batch behind.
"""

from __future__ import annotations

import itertools
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

_SUFFIX = ".batch"


class SpoolFullError(RuntimeError):
    """The spool already holds ``max_files`` batches."""


class Spool:
    def __init__(self, directory: str | Path, *, max_files: int = 1000) -> None:
        if max_files < 1:
            raise ValueError("max_files must be >= 1")
        self.directory = Path(directory)
        self.max_files = max_files
        self.directory.mkdir(parents=True, exist_ok=True)
        self._sequence = itertools.count()

    def pending(self) -> list[Path]:
        """Spooled batch files, oldest first."""
        return sorted(self.directory.glob(f"*{_SUFFIX}"))

    def record_count(self) -> int:
        total = 0
        for path in self.pending():
            try:
                total += int(path.stem.rsplit("-", 1)[1])
            except (IndexError, ValueError):
                log.warning("ignoring spool file with unexpected name: %s", path.name)
        return total

    def store(self, body: bytes, *, count: int) -> Path:
        if len(self.pending()) >= self.max_files:
            raise SpoolFullError(f"spool {self.directory} is full ({self.max_files} batches)")
        name = f"{time.time_ns():020d}-{next(self._sequence):06d}-{count}{_SUFFIX}"
        tmp = self.directory / f".{name}.tmp"
        final = self.directory / name
        with open(tmp, "wb") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, final)
        return final

    def drain(
        self,
        send: Callable[[bytes], None],
        *,
        errors: tuple[type[BaseException], ...] = (),
    ) -> int:
        """Re-send spooled batches oldest first.

        Each file is removed only after ``send`` returns. An exception listed
        in ``errors`` stops the drain, leaving that batch and everything newer
        in place for the next attempt; any other exception propagates.
        Returns the number of batches delivered.
        """
        delivered = 0
        for path in self.pending():
            try:
                send(path.read_bytes())
            except errors as exc:
                log.warning("stopped replaying spool at %s: %s", path.name, exc)
                break
            path.unlink()
            delivered += 1
        if delivered:
            log.info("replayed %d spooled batch(es) from %s", delivered, self.directory)
        return delivered
