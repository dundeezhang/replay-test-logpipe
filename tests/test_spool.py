import pytest

from logpipe.sinks.spool import Spool, SpoolFullError


def test_store_and_list_oldest_first(tmp_path):
    spool = Spool(tmp_path)
    first = spool.store(b"a\n", count=1)
    second = spool.store(b"b\nc\n", count=2)
    assert spool.pending() == [first, second]
    assert spool.record_count() == 3
    assert first.read_bytes() == b"a\n"


def test_no_temp_files_left_behind(tmp_path):
    spool = Spool(tmp_path)
    spool.store(b"x", count=1)
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_full_spool_rejects_new_batches(tmp_path):
    spool = Spool(tmp_path, max_files=2)
    spool.store(b"1", count=1)
    spool.store(b"2", count=1)
    with pytest.raises(SpoolFullError):
        spool.store(b"3", count=1)


def test_drain_deletes_delivered_batches(tmp_path):
    spool = Spool(tmp_path)
    spool.store(b"one", count=1)
    spool.store(b"two", count=1)
    sent = []
    assert spool.drain(sent.append) == 2
    assert sent == [b"one", b"two"]
    assert spool.pending() == []


def test_drain_stops_on_listed_errors(tmp_path):
    spool = Spool(tmp_path)
    spool.store(b"one", count=1)
    spool.store(b"two", count=1)
    sent = []

    def send(body):
        if body == b"two":
            raise ConnectionError("down")
        sent.append(body)

    assert spool.drain(send, errors=(ConnectionError,)) == 1
    assert sent == [b"one"]
    assert len(spool.pending()) == 1


def test_drain_propagates_unexpected_errors(tmp_path):
    spool = Spool(tmp_path)
    spool.store(b"one", count=1)

    def send(body):
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        spool.drain(send)
    assert len(spool.pending()) == 1


def test_ignores_unexpected_file_names(tmp_path):
    spool = Spool(tmp_path)
    (tmp_path / "garbage.batch").write_bytes(b"")
    spool.store(b"x", count=4)
    assert spool.record_count() == 4
