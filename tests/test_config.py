import pytest

from logpipe.config import (
    Config,
    ConfigError,
    apply_env_overrides,
    config_from_dict,
    load_config,
)

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


def test_env_overrides():
    cfg = config_from_dict({"input": {"format": "syslog"}, "sink": {"type": "stdout"}})
    apply_env_overrides(
        cfg,
        {
            "LOGPIPE_LOG_LEVEL": "DEBUG",
            "LOGPIPE_INPUT_FORMAT": "jsonl",
            "LOGPIPE_INPUT_PATHS": "/var/log/a.log, /var/log/b.log",
            "LOGPIPE_INPUT_STRICT": "true",
            "LOGPIPE_SINK_TYPE": "http",
            "LOGPIPE_SINK_URL": "https://collector.test/ingest",
            "LOGPIPE_SINK_BATCH_SIZE": "100",
            "LOGPIPE_SINK_COMPRESS": "false",
            "HOME": "/root",
        },
    )
    assert cfg.log_level == "debug"
    assert cfg.input.format == "jsonl"
    assert cfg.input.paths == ["/var/log/a.log", "/var/log/b.log"]
    assert cfg.input.strict is True
    assert cfg.sink.type == "http"
    assert cfg.sink.options == {
        "url": "https://collector.test/ingest",
        "batch_size": 100,
        "compress": False,
    }


def test_env_log_level_is_validated():
    with pytest.raises(ConfigError, match="LOGPIPE_LOG_LEVEL"):
        apply_env_overrides(Config(), {"LOGPIPE_LOG_LEVEL": "loud"})
