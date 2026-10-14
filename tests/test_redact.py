import pytest

from logpipe.stages import build_stage
from logpipe.stages.redact import RedactTransform


@pytest.fixture
def redact():
    return build_stage({"type": "redact"})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("login ok for jane.doe@example.com", "login ok for [EMAIL]"),
        ("connection from 203.0.113.42:51234", "connection from [IP]:51234"),
        ("charged card 4111 1111 1111 1111 ok", "charged card [CARD ...1111] ok"),
        ("charged card 5555-5555-5555-4444", "charged card [CARD ...4444]"),
        ("ssn=123-45-6789 on file", "ssn=[SSN] on file"),
        ("Authorization: Bearer abc.def-ghi", "Authorization: Bearer [REDACTED]"),
        (
            "retrying with password=not-a-real-pw&user=bob",
            "retrying with password=[REDACTED]&user=bob",
        ),
        ("api_key: placeholder-value, region=eu", "api_key: [REDACTED], region=eu"),
    ],
)
def test_builtin_rules(redact, text, expected):
    assert redact.scrub(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "order 4111111111111112 shipped",  # fails Luhn
        "ts=1714564800123",  # epoch millis, not a card
        "version 1.2.3 released",
        "999.1.1.1 is not an address",
    ],
)
def test_leaves_non_matching_text_alone(redact, text):
    assert redact.scrub(text) == text


def test_record_message_and_fields_are_scrubbed(redact, make_record):
    record = make_record(
        "user bob@example.com logged in",
        fields={"client_ip": "198.51.100.7", "status": 200, "password": "s3cret"},
        raw="original line with bob@example.com",
    )
    out = redact.apply(record)
    assert out.message == "user [EMAIL] logged in"
    assert out.fields == {"client_ip": "[IP]", "status": 200, "password": "[REDACTED]"}
    assert out.raw is None
    assert record.message == "user bob@example.com logged in"


def test_clean_records_are_passed_through_unchanged(redact, make_record):
    record = make_record("cache warm", fields={"keys": 1200}, raw="cache warm")
    assert redact.apply(record) is record


def test_sensitive_field_names_are_case_insensitive(redact, make_record):
    out = redact.apply(make_record(fields={"Authorization": "Basic Zm9vOmJhcg=="}))
    assert out.fields["Authorization"] == "[REDACTED]"


def test_extra_sensitive_keys(make_record):
    stage = build_stage({"type": "redact", "keys": ["customer_name"]})
    out = stage.apply(make_record(fields={"customer_name": "Jane Doe", "plan": "pro"}))
    assert out.fields == {"customer_name": "[REDACTED]", "plan": "pro"}


def test_selected_rules_only(make_record):
    stage = build_stage({"type": "redact", "rules": ["email"]})
    assert stage.scrub("a@b.io from 10.0.0.1") == "[EMAIL] from 10.0.0.1"


def test_fields_can_be_left_alone(make_record):
    stage = build_stage({"type": "redact", "fields": False})
    out = stage.apply(make_record("to a@b.io", fields={"to": "a@b.io"}))
    assert out.message == "to [EMAIL]"
    assert out.fields == {"to": "a@b.io"}


def test_custom_patterns():
    stage = build_stage(
        {
            "type": "redact",
            "rules": [],
            "patterns": [
                {"name": "order", "regex": r"ORD-(\d{4})\d{4}", "replacement": r"ORD-\1****"},
                {"name": "member", "regex": r"M\d{6}"},
            ],
        }
    )
    assert stage.scrub("ORD-20240001 for M123456") == "ORD-2024**** for [REDACTED]"
    assert stage.counts == {"order": 1, "member": 1}


@pytest.mark.parametrize(
    "spec",
    [
        {"rules": ["phone"]},
        {"patterns": [{"regex": "x"}]},
        {"patterns": [{"name": "bad", "regex": "("}]},
    ],
)
def test_invalid_configuration(spec):
    with pytest.raises(ValueError):
        build_stage({"type": "redact", **spec})


def test_counts_only_real_redactions(redact):
    redact.scrub("order 1234567890123 for jane@example.com")
    assert redact.counts == {"email": 1}
    assert isinstance(redact, RedactTransform)
