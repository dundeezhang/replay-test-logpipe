"""Mask personal data and secrets before records leave the host.

The stage scrubs the record message and string values in ``fields`` with a
set of regular-expression rules, and blanks out fields whose *name* marks
them as sensitive (``password``, ``authorization``, ...). Redacted records
drop their ``raw`` line, since it still contains the original text.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from logpipe.pipeline import Transform
from logpipe.record import LogRecord
from logpipe.stages import register_stage

log = logging.getLogger(__name__)

Replacement = str | Callable[[re.Match[str]], str]

REDACTED = "[REDACTED]"


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    replacement: Replacement


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _mask_card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    # Card numbers are 13-19 digits, start with 3-6 and pass the Luhn check;
    # anything else is more likely an order id or a timestamp.
    if not 13 <= len(digits) <= 19 or digits[0] not in "3456" or not _luhn_valid(digits):
        return match.group(0)
    return f"[CARD ...{digits[-4:]}]"


def _mask_assignment(match: re.Match[str]) -> str:
    return f"{match['key']}{match['sep']}{REDACTED}"


BUILTIN_RULES: dict[str, Rule] = {
    rule.name: rule
    for rule in (
        Rule(
            "email",
            re.compile(r"\b[A-Za-z0-9._%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
            "[EMAIL]",
        ),
        Rule(
            "ipv4",
            re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
            "[IP]",
        ),
        Rule("card", re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), _mask_card),
        Rule("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
        Rule(
            "bearer",
            re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
            f"Bearer {REDACTED}",
        ),
        Rule(
            "assignment",
            re.compile(
                r"(?i)\b(?P<key>password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)"
                r"(?P<sep>\s*[=:]\s*)[^\s,;&\"']+"
            ),
            _mask_assignment,
        ),
    )
}

DEFAULT_RULES = tuple(BUILTIN_RULES)

# Fields with these names are replaced wholesale, whatever their value.
SENSITIVE_KEYS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "set-cookie",
)


@register_stage("redact")
class RedactTransform(Transform):
    """Mask PII and secrets in messages and fields.

    ``rules`` selects built-in rules by name; ``patterns`` adds custom ones as
    ``{name, regex, replacement}`` tables; ``keys`` adds field names that are
    always masked in addition to the built-in sensitive names.
    """

    def __init__(
        self,
        rules: Sequence[str] = DEFAULT_RULES,
        patterns: Sequence[dict[str, str]] = (),
        keys: list[str] = [],
        fields: bool = True,
    ) -> None:
        unknown = sorted(set(rules) - set(BUILTIN_RULES))
        if unknown:
            raise ValueError(f"unknown redaction rule(s): {', '.join(unknown)}")
        self.rules = [BUILTIN_RULES[name] for name in rules]
        for spec in patterns:
            try:
                rule = Rule(
                    spec["name"],
                    re.compile(spec["regex"]),
                    spec.get("replacement", REDACTED),
                )
            except KeyError as exc:
                raise ValueError(f"custom redaction pattern is missing {exc}") from None
            except re.error as exc:
                raise ValueError(f"invalid regex for pattern {spec.get('name')!r}: {exc}") from exc
            self.rules.append(rule)

        self.sensitive_keys = keys
        self.sensitive_keys.extend(SENSITIVE_KEYS)
        self.redact_fields = fields
        self.counts: Counter[str] = Counter()

    def _replace(self, rule: Rule, match: re.Match[str]) -> str:
        if callable(rule.replacement):
            replacement = rule.replacement(match)
        else:
            replacement = match.expand(rule.replacement)
        if replacement != match.group(0):
            self.counts[rule.name] += 1
        return replacement

    def scrub(self, text: str) -> str:
        for rule in self.rules:
            text = rule.pattern.sub(lambda m, rule=rule: self._replace(rule, m), text)
        return text

    def _scrub_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in fields.items():
            if key.lower() in self.sensitive_keys:
                cleaned[key] = REDACTED
                self.counts["key"] += 1
            elif isinstance(value, str):
                cleaned[key] = self.scrub(value)
            else:
                cleaned[key] = value
        return cleaned

    def apply(self, record: LogRecord) -> LogRecord:
        message = self.scrub(record.message)
        fields = self._scrub_fields(record.fields) if self.redact_fields else record.fields
        if message == record.message and fields == record.fields:
            return record
        return dataclasses.replace(record, message=message, fields=fields, raw=None)

    def close(self) -> None:
        if self.counts:
            summary = ", ".join(f"{name}={n}" for name, n in sorted(self.counts.items()))
            log.info("redacted values: %s", summary)
