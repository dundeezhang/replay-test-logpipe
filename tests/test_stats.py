import math

import pytest

from logpipe.aggregate.stats import Summary, percentile, percentile_label


@pytest.mark.parametrize(
    ("values", "p", "expected"),
    [
        ([3, 1, 2], 50, 2),
        ([7], 99, 7),
        ([5, 1, 4, 2, 3], 0, 1),
        ([5, 1, 4, 2, 3], 100, 5),
        ([5, 1, 4, 2, 3], 90, 5),
        ([0.25, 0.5, 0.125], 50, 0.25),
    ],
)
def test_percentile(values, p, expected):
    assert percentile(values, p) == expected


def test_percentile_does_not_mutate_input():
    values = [3, 1, 2]
    percentile(values, 50)
    assert values == [3, 1, 2]


def test_percentile_errors():
    with pytest.raises(ValueError, match="empty"):
        percentile([], 50)
    with pytest.raises(ValueError, match="between 0 and 100"):
        percentile([1, 2], 101)


@pytest.mark.parametrize(("p", "label"), [(50, "p50"), (99.0, "p99"), (99.9, "p99_9")])
def test_percentile_label(p, label):
    assert percentile_label(p) == label


def test_summary_basic_stats():
    summary = Summary()
    summary.extend([4.0, 1.0, 3.0, 2.0, 5.0])
    assert summary.count == 5
    assert summary.mean == 3.0
    assert summary.to_dict([50]) == {
        "count": 5,
        "sum": 15.0,
        "min": 1.0,
        "max": 5.0,
        "mean": 3.0,
        "p50": 3.0,
    }


def test_empty_summary():
    summary = Summary()
    assert summary.mean is None
    assert summary.to_dict([50, 99]) == {"count": 0}
    assert summary.minimum == math.inf


def test_reservoir_keeps_memory_bounded():
    summary = Summary(max_samples=100)
    summary.extend(float(i) for i in range(10_000))
    assert summary.count == 10_000
    assert len(summary.samples) == 100
    assert summary.minimum == 0.0
    assert summary.maximum == 9999.0
    # A uniform sample of 0..9999 should have its median somewhere in the middle.
    assert 2500 < percentile(summary.samples, 50) < 7500
