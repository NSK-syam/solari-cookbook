import json
import logging

from septic_sentinel.observability import JsonFormatter, redact


def test_redact_removes_nested_credentials_and_addresses() -> None:
    value = {
        "token": "secret",
        "nested": {"address": "123 Main", "safe": "visible"},
        "items": [{"approval_token": "once"}],
    }
    redacted = redact(value)
    assert redacted["token"] == "[REDACTED]"
    assert redacted["nested"] == {"address": "[REDACTED]", "safe": "visible"}
    assert redacted["items"][0]["approval_token"] == "[REDACTED]"


def test_json_formatter_emits_structured_request_fields() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request.completed",
        args=(),
        exc_info=None,
    )
    record.request_id = "req_1"
    record.status_code = 200
    record.latency_ms = 12.4
    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "request.completed"
    assert payload["request_id"] == "req_1"
    assert payload["status_code"] == 200
