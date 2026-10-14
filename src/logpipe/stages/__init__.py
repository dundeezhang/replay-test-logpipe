"""Pipeline stages (filters and transforms) and their registry.

Stages are configured from ``[[stages]]`` tables in the config file, each with
a ``type`` key naming a registered stage and the remaining keys passed to the
stage constructor as keyword arguments.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from logpipe.pipeline import Stage

_REGISTRY: dict[str, type[Stage]] = {}


def register_stage(name: str) -> Callable[[type[Stage]], type[Stage]]:
    def decorator(cls: type[Stage]) -> type[Stage]:
        if name in _REGISTRY:
            raise ValueError(f"stage {name!r} is already registered")
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return decorator


def build_stage(spec: Mapping[str, Any]) -> Stage:
    options = dict(spec)
    try:
        kind = options.pop("type")
    except KeyError:
        raise ValueError(f"stage spec is missing 'type': {dict(spec)!r}") from None
    try:
        cls = _REGISTRY[kind]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"unknown stage type {kind!r} (known: {known})") from None
    try:
        return cls(**options)
    except TypeError as exc:
        raise ValueError(f"invalid options for stage {kind!r}: {exc}") from exc


def available_stages() -> list[str]:
    return sorted(_REGISTRY)


__all__ = ["available_stages", "build_stage", "register_stage"]

# Built-in stages register themselves on import.
from logpipe.stages import level  # noqa: E402,F401
from logpipe.stages import match  # noqa: E402,F401
from logpipe.stages import redact  # noqa: E402,F401
