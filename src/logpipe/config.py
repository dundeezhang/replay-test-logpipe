"""Loading and validating ``logpipe.toml`` configuration files."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOG_LEVELS = ("debug", "info", "warning", "error", "critical")


class ConfigError(ValueError):
    """Raised for missing, malformed or invalid configuration."""


@dataclass
class InputConfig:
    format: str = "jsonl"
    paths: list[str] = field(default_factory=lambda: ["-"])
    strict: bool = False
    encoding: str = "utf-8"


@dataclass
class SinkConfig:
    type: str = "stdout"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    input: InputConfig = field(default_factory=InputConfig)
    stages: list[dict[str, Any]] = field(default_factory=list)
    sink: SinkConfig = field(default_factory=SinkConfig)
    log_level: str = "warning"


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}] must be a table, got {type(value).__name__}")
    return value


def _parse_input(table: dict[str, Any]) -> InputConfig:
    cfg = InputConfig()
    unknown = set(table) - {"format", "paths", "strict", "encoding"}
    if unknown:
        raise ConfigError(f"unknown key(s) in [input]: {', '.join(sorted(unknown))}")
    if "format" in table:
        cfg.format = str(table["format"])
    if "paths" in table:
        paths = table["paths"]
        if isinstance(paths, str):
            paths = [paths]
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ConfigError("[input].paths must be a string or a list of strings")
        cfg.paths = list(paths)
    if "strict" in table:
        if not isinstance(table["strict"], bool):
            raise ConfigError("[input].strict must be true or false")
        cfg.strict = table["strict"]
    if "encoding" in table:
        cfg.encoding = str(table["encoding"])
    return cfg


def _parse_stages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ConfigError("stages must be an array of tables ([[stages]])")
    stages: list[dict[str, Any]] = []
    for index, spec in enumerate(value):
        if not isinstance(spec, dict) or "type" not in spec:
            raise ConfigError(f"stages[{index}] must be a table with a 'type' key")
        stages.append(dict(spec))
    return stages


def config_from_dict(data: dict[str, Any]) -> Config:
    cfg = Config()
    cfg.input = _parse_input(_table(data, "input"))
    cfg.stages = _parse_stages(data.get("stages", []))

    sink = dict(_table(data, "sink"))
    cfg.sink = SinkConfig(type=str(sink.pop("type", "stdout")), options=sink)

    log_level = str(data.get("log_level", cfg.log_level)).lower()
    if log_level not in _LOG_LEVELS:
        raise ConfigError(f"log_level must be one of {', '.join(_LOG_LEVELS)}")
    cfg.log_level = log_level
    return cfg


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return config_from_dict(data)
