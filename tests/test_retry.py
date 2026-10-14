import pytest

from logpipe.retry import RetriesExhausted, RetryableError, RetryPolicy


class Flaky:
    """Fails ``failures`` times with a retryable error, then returns ``result``."""

    def __init__(self, failures, result="ok", retry_after=None):
        self.failures = failures
        self.result = result
        self.retry_after = retry_after
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise RetryableError(f"boom {self.calls}", retry_after=self.retry_after)
        return self.result


def test_exponential_delays_without_jitter():
    policy = RetryPolicy(base_delay=1.0, multiplier=2.0, jitter=0)
    assert [policy.delay_for(n) for n in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 8.0]


def test_backoff_is_capped_at_max_delay():
    policy = RetryPolicy(base_delay=1.0, max_delay=10.0, jitter=0)
    assert [policy.delay_for(n) for n in (3, 4, 5, 20)] == [4.0, 8.0, 10.0, 10.0]


def test_jitter_only_adds_time():
    policy = RetryPolicy(base_delay=1.0, jitter=0.5)
    for _ in range(50):
        assert 1.0 <= policy.delay_for(1) <= 1.5


def test_retry_after_overrides_backoff():
    policy = RetryPolicy(base_delay=1.0, jitter=0)
    assert policy.delay_for(5, retry_after=0.25) == 0.25


def test_call_retries_until_success():
    sleeps = []
    fn = Flaky(failures=3)
    policy = RetryPolicy(base_delay=0.1, jitter=0)
    assert policy.call(fn, sleep=sleeps.append) == "ok"
    assert fn.calls == 4
    assert sleeps == pytest.approx([0.1, 0.2, 0.4])


def test_call_gives_up_after_max_attempts():
    sleeps = []
    fn = Flaky(failures=10)
    policy = RetryPolicy(max_attempts=3, base_delay=0.1, jitter=0)
    with pytest.raises(RetriesExhausted) as excinfo:
        policy.call(fn, sleep=sleeps.append)
    assert fn.calls == 3
    assert len(sleeps) == 2
    assert excinfo.value.attempts == 3
    assert "boom 3" in str(excinfo.value.last_error)


def test_non_retryable_errors_propagate_immediately():
    calls = []

    def fn():
        calls.append(1)
        raise KeyError("nope")

    with pytest.raises(KeyError):
        RetryPolicy().call(fn, sleep=lambda _: None)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "kwargs",
    [{"max_attempts": 0}, {"base_delay": -1}, {"multiplier": 0.5}],
)
def test_invalid_policies(kwargs):
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)
