import json

from logpipe.cli import main


def test_run_jsonl_to_stdout(tmp_path, capsys):
    src = tmp_path / "app.log"
    src.write_text(
        '{"time": "2024-05-01T10:00:00Z", "level": "debug", "msg": "cache warm"}\n'
        '{"time": "2024-05-01T10:00:01Z", "level": "error", "msg": "db timeout"}\n'
    )
    assert main(["run", "-f", "jsonl", "--min-level", "info", "-o", "json", str(src)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line)["message"] for line in lines] == ["db timeout"]


def test_unknown_format_is_reported(tmp_path, capsys):
    src = tmp_path / "x.log"
    src.write_text("hello\n")
    assert main(["run", "-f", "xml", str(src)]) == 2
    assert "unknown input format" in capsys.readouterr().err


def test_formats_lists_everything(capsys):
    assert main(["formats"]) == 0
    out = capsys.readouterr().out
    assert "syslog" in out
    assert "stdout" in out
