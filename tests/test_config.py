import pytest

from logpipe.config import ConfigError, config_from_dict, load_config

EXAMPLE = """
log_level = "info"

[input]
format = "syslog"
paths = ["/var/log/syslog", "/var/log/auth.log"]

[[stages]]
type = "level"
min = "warning"

[sink]
type = "file"
path = "/var/lib/logpipe/out.jsonl"
"""


def test_load_example(tmp_path):
    path = tmp_path / "logpipe.toml"
    path.write_text(EXAMPLE)
    cfg = load_config(path)
    assert cfg.input.format == "syslog"
    assert cfg.input.paths == ["/var/log/syslog", "/var/log/auth.log"]
    assert cfg.stages == [{"type": "level", "min": "warning"}]
    assert cfg.sink.type == "file"
    assert cfg.sink.options == {"path": "/var/lib/logpipe/out.jsonl"}
    assert cfg.log_level == "info"


def test_defaults():
    cfg = config_from_dict({})
    assert cfg.input.paths == ["-"]
    assert cfg.sink.type == "stdout"
    assert cfg.stages == []


def test_single_path_string_is_accepted():
    assert config_from_dict({"input": {"paths": "/tmp/a.log"}}).input.paths == ["/tmp/a.log"]


@pytest.mark.parametrize(
    "data",
    [
        {"input": "syslog"},
        {"input": {"fmt": "syslog"}},
        {"input": {"strict": "yes"}},
        {"stages": {"type": "level"}},
        {"stages": [{"min": "info"}]},
        {"log_level": "verbose"},
    ],
)
def test_invalid_configs(data):
    with pytest.raises(ConfigError):
        config_from_dict(data)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")
