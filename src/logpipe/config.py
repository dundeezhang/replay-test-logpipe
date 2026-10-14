"""Loading and validating ``logpipe.toml`` configuration files."""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_LOG_LEVELS = ("debug", "info", "warning", "error", "critical")
_SINK_ENV_PREFIX = "LOGPIPE_SINK_"


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


def _coerce(value: str) -> Any:
    """Best-effort conversion of an environment string to bool/int/float."""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def apply_env_overrides(cfg: Config, environ: Mapping[str, str] | None = None) -> Config:
    """Override ``cfg`` in place from ``LOGPIPE_*`` environment variables.

    Recognised: ``LOGPIPE_LOG_LEVEL``, ``LOGPIPE_INPUT_FORMAT``,
    ``LOGPIPE_INPUT_PATHS`` (comma-separated), ``LOGPIPE_INPUT_STRICT``,
    ``LOGPIPE_SINK_TYPE`` and ``LOGPIPE_SINK_<OPTION>`` for any sink option.
    """
    env = os.environ if environ is None else environ
    if level := env.get("LOGPIPE_LOG_LEVEL"):
        if level.lower() not in _LOG_LEVELS:
            raise ConfigError(f"LOGPIPE_LOG_LEVEL must be one of {', '.join(_LOG_LEVELS)}")
        cfg.log_level = level.lower()
    if fmt := env.get("LOGPIPE_INPUT_FORMAT"):
        cfg.input.format = fmt
    if paths := env.get("LOGPIPE_INPUT_PATHS"):
        cfg.input.paths = [p.strip() for p in paths.split(",") if p.strip()]
    if (strict := env.get("LOGPIPE_INPUT_STRICT")) is not None:
        cfg.input.strict = strict.strip().lower() in ("1", "true", "yes", "on")
    if sink_type := env.get("LOGPIPE_SINK_TYPE"):
        cfg.sink.type = sink_type
    for key, value in env.items():
        if key.startswith(_SINK_ENV_PREFIX) and key != "LOGPIPE_SINK_TYPE":
            cfg.sink.options[key.removeprefix(_SINK_ENV_PREFIX).lower()] = _coerce(value)
    return cfg


def describe(cfg: Config) -> str:
    """One-line JSON summary of the effective configuration, for startup logs."""
    return json.dumps(asdict(cfg), sort_keys=True, default=str)
