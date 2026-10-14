import gzip
import json
import urllib.error
from dataclasses import dataclass

import pytest

from logpipe.sinks import build_sink
from logpipe.sinks.http import HttpSink, Response, _parse_retry_after

URL = "https://collector.test/ingest"


@dataclass
class SentRequest:
    url: str
    body: bytes
    headers: dict
    timeout: float

    def records(self):
        raw = self.body
        if self.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        text = raw.decode()
        if text.startswith("["):
            return json.loads(text)
        return [json.loads(line) for line in text.splitlines()]


class FakeTransport:
    """Returns scripted responses (or raises scripted exceptions) in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[SentRequest] = []

    def __call__(self, url, body, headers, timeout):
        self.requests.append(SentRequest(url, body, dict(headers), timeout))
        result = self.responses.pop(0) if self.responses else Response(202)
        if isinstance(result, Exception):
            raise result
        return result


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def sleeps():
    return []


def make_sink(transport, sleeps, **kwargs):
    kwargs.setdefault("token_env", None)
    return HttpSink(URL, transport=transport, sleep=sleeps.append, **kwargs)


def test_registered_as_http_sink():
    sink = build_sink("http", url=URL, transport=FakeTransport(), token_env=None)
    assert isinstance(sink, HttpSink)


@pytest.mark.parametrize("url", ["collector.test/ingest", "ftp://collector.test", ""])
def test_rejects_non_http_urls(url):
    with pytest.raises(ValueError, match="http"):
        HttpSink(url)


@pytest.mark.parametrize("kwargs", [{"batch_size": 0}, {"batch_bytes": 0}, {"encoding": "xml"}])
def test_rejects_invalid_options(kwargs):
    with pytest.raises(ValueError):
        HttpSink(URL, transport=FakeTransport(), **kwargs)


def test_batches_by_record_count(make_record, sleeps):
    transport = FakeTransport()
    sink = make_sink(transport, sleeps, batch_size=2)
    for i in range(5):
        sink.write(make_record(f"event {i}"))
    assert len(transport.requests) == 2
    sink.close()
    assert len(transport.requests) == 3
    messages = [r["message"] for req in transport.requests for r in req.records()]
    assert messages == [f"event {i}" for i in range(5)]
    assert (sink.sent_batches, sink.sent_records, sink.failed_records) == (3, 5, 0)


def test_batches_by_size(make_record, sleeps):
    transport = FakeTransport()
    one = len(json.dumps(make_record("x" * 100).to_dict(), separators=(",", ":"))) + 1
    sink = make_sink(transport, sleeps, batch_size=1000, batch_bytes=one * 3)
    for _ in range(7):
        sink.write(make_record("x" * 100))
    sink.close()
    assert [len(req.records()) for req in transport.requests] == [3, 3, 1]


def test_flushes_after_interval(make_record, sleeps):
    transport = FakeTransport()
    clock = FakeClock()
    sink = make_sink(transport, sleeps, batch_size=1000, flush_interval=5.0, clock=clock)
    sink.write(make_record("a"))
    clock.now += 2
    sink.write(make_record("b"))
    assert transport.requests == []
    clock.now += 4
    sink.write(make_record("c"))
    assert len(transport.requests) == 1
    assert [r["message"] for r in transport.requests[0].records()] == ["a", "b", "c"]


def test_gzip_ndjson_by_default(make_record, sleeps):
    transport = FakeTransport()
    sink = make_sink(transport, sleeps)
    sink.write(make_record("hello"))
    sink.close()
    request = transport.requests[0]
    assert request.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(request.body).endswith(b"\n")
    assert request.records()[0]["message"] == "hello"


def test_json_array_encoding_without_compression(make_record, sleeps):
    transport = FakeTransport()
    sink = make_sink(transport, sleeps, encoding="json", compress=False)
    sink.write(make_record("one"))
    sink.write(make_record("two"))
    sink.close()
    body = json.loads(transport.requests[0].body)
    assert [r["message"] for r in body] == ["one", "two"]


def test_bearer_token_from_environment(monkeypatch, make_record, sleeps):
    monkeypatch.setenv("LOGPIPE_TEST_TOKEN", "test-token-not-real")
    transport = FakeTransport()
    sink = make_sink(transport, sleeps, token_env="LOGPIPE_TEST_TOKEN")
    sink.write(make_record())
    sink.close()
    assert transport.requests[0].headers["Authorization"] == "Bearer test-token-not-real"


def test_custom_headers_are_sent(make_record, sleeps):
    transport = FakeTransport()
    sink = make_sink(transport, sleeps, headers={"X-Tenant": "acme"})
    sink.write(make_record())
    sink.close()
    headers = transport.requests[0].headers
    assert headers["X-Tenant"] == "acme"
    assert headers["User-Agent"].startswith("logpipe/")


def test_retries_retryable_statuses(make_record, sleeps):
    transport = FakeTransport(
        Response(503, body=b"upstream unavailable"),
        Response(429, headers={"retry-after": "3"}),
        Response(202),
    )
    sink = make_sink(transport, sleeps)
    sink.write(make_record())
    sink.close()
    assert len(transport.requests) == 3
    assert len(sleeps) == 2
    assert sleeps[1] == 3.0
    assert sink.sent_records == 1


def test_backoff_respects_max_backoff(make_record, sleeps):
    transport = FakeTransport(*[Response(503)] * 6)
    sink = make_sink(transport, sleeps, max_backoff=2.0)
    sink.write(make_record())
    sink.close()
    assert len(transport.requests) == 7
    assert max(sleeps) <= 2.0 * 1.1


def test_transport_errors_are_retried(make_record, sleeps):
    transport = FakeTransport(urllib.error.URLError("connection refused"), Response(200))
    sink = make_sink(transport, sleeps)
    sink.write(make_record())
    sink.close()
    assert len(transport.requests) == 2
    assert sink.sent_batches == 1


def test_client_errors_are_not_retried(make_record, sleeps):
    transport = FakeTransport(Response(400, body=b'{"error": "bad payload"}'))
    sink = make_sink(transport, sleeps)
    sink.write(make_record())
    sink.write(make_record())
    sink.close()
    assert len(transport.requests) == 1
    assert sleeps == []
    assert sink.failed_records == 2


def test_undeliverable_batches_are_spooled_and_replayed(tmp_path, make_record, sleeps):
    spool_dir = tmp_path / "spool"
    down = FakeTransport(*[Response(503)] * 4)
    sink = make_sink(down, sleeps, max_attempts=2, batch_size=2, spool_dir=str(spool_dir))
    for i in range(4):
        sink.write(make_record(f"m{i}"))
    sink.close()
    assert sink.failed_records == 4
    assert len(list(spool_dir.glob("*.batch"))) == 2

    up = FakeTransport()
    replayer = make_sink(up, sleeps, spool_dir=str(spool_dir))
    assert replayer.replay_spool() == 2
    assert list(spool_dir.glob("*.batch")) == []
    assert [r["message"] for req in up.requests for r in req.records()] == ["m0", "m1", "m2", "m3"]


def test_replay_stops_at_first_failure(tmp_path, make_record, sleeps):
    spool_dir = tmp_path / "spool"
    sink = make_sink(FakeTransport(Response(500)), sleeps, max_attempts=1, spool_dir=str(spool_dir))
    sink.write(make_record())
    sink.close()

    replayer = make_sink(
        FakeTransport(Response(401)), sleeps, max_attempts=1, spool_dir=str(spool_dir)
    )
    assert replayer.replay_spool() == 0
    assert len(list(spool_dir.glob("*.batch"))) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("7", 7.0), ("1.5", 1.5), ("-3", 0.0), ("Wed, 21 Oct 2015", None)],
)
def test_parse_retry_after(value, expected):
    assert _parse_retry_after(value) == expected
