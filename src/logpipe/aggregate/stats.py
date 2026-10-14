"""Summary statistics for numeric metrics."""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile of ``values`` (which need not be sorted).

    ``p`` is in the range 0-100; ``p=0`` is the minimum and ``p=100`` the
    maximum. Raises ``ValueError`` for an empty sequence.
    """
    if not values:
        raise ValueError("percentile of an empty sequence")
    if not 0 <= p <= 100:
        raise ValueError(f"percentile must be between 0 and 100, got {p}")
    ordered = sorted(values)
    rank = int(p / 100 * len(ordered))
    return ordered[min(rank, len(ordered) - 1)]


def percentile_label(p: float) -> str:
    """``50`` -> ``"p50"``, ``99.9`` -> ``"p99_9"``."""
    text = str(int(p)) if float(p).is_integer() else str(p)
    return "p" + text.replace(".", "_")


@dataclass(slots=True)
class Summary:
    """Running count/sum/min/max plus a bounded sample for percentiles.

    Up to ``max_samples`` values are kept verbatim. Past that, reservoir
    sampling keeps a uniform random subset, so percentiles stay representative
    while memory per window stays bounded.
    """

    max_samples: int = 10_000
    count: int = 0
    total: float = 0.0
    minimum: float = math.inf
    maximum: float = -math.inf
    samples: list[float] = field(default_factory=list)
    rng: random.Random = field(default_factory=lambda: random.Random(0x5EED), repr=False)

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)
        if len(self.samples) < self.max_samples:
            self.samples.append(value)
            return
        slot = self.rng.randrange(self.count)
        if slot < self.max_samples:
            self.samples[slot] = value

    def extend(self, values: Iterable[float]) -> None:
        for value in values:
            self.add(value)

    @property
    def mean(self) -> float | None:
        return self.total / self.count if self.count else None

    def quantiles(self, ps: Iterable[float]) -> dict[str, float]:
        if not self.samples:
            return {}
        return {percentile_label(p): percentile(self.samples, p) for p in ps}

    def to_dict(self, percentiles: Sequence[float] = ()) -> dict[str, float | int | None]:
        if not self.count:
            return {"count": 0}
        out: dict[str, float | int | None] = {
            "count": self.count,
            "sum": self.total,
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.mean,
        }
        out.update(self.quantiles(percentiles))
        return out
