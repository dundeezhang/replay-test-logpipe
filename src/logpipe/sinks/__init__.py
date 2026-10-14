"""Output sinks and their registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from logpipe.pipeline import Sink

_REGISTRY: dict[str, type[Sink]] = {}


def register_sink(name: str) -> Callable[[type[Sink]], type[Sink]]:
    def decorator(cls: type[Sink]) -> type[Sink]:
        if name in _REGISTRY:
            raise ValueError(f"sink {name!r} is already registered")
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return decorator


def build_sink(kind: str, **options: Any) -> Sink:
    try:
        cls = _REGISTRY[kind]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"unknown sink type {kind!r} (known: {known})") from None
    try:
        return cls(**options)
    except TypeError as exc:
        raise ValueError(f"invalid options for sink {kind!r}: {exc}") from exc


def available_sinks() -> list[str]:
    return sorted(_REGISTRY)


__all__ = ["available_sinks", "build_sink", "register_sink"]

# Built-in sinks register themselves on import.
from logpipe.sinks import stream  # noqa: E402,F401
