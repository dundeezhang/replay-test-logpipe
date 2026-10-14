"""Input format parsers and their registry."""

from __future__ import annotations

from typing import Any

from logpipe.parsers.base import ParseError, Parser

_REGISTRY: dict[str, type[Parser]] = {}


def register(cls: type[Parser]) -> type[Parser]:
    """Class decorator that makes a parser available by its ``name``."""
    if cls.name in _REGISTRY:
        raise ValueError(f"parser {cls.name!r} is already registered")
    _REGISTRY[cls.name] = cls
    return cls


def get_parser(name: str, **options: Any) -> Parser:
    try:
        cls = _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"unknown input format {name!r} (known: {known})") from None
    return cls(**options)


def available_parsers() -> dict[str, str]:
    return {name: cls.description for name, cls in sorted(_REGISTRY.items())}


__all__ = ["ParseError", "Parser", "available_parsers", "get_parser", "register"]

# Built-in parsers register themselves on import.
from logpipe.parsers import jsonlines  # noqa: E402,F401
from logpipe.parsers import syslog  # noqa: E402,F401
