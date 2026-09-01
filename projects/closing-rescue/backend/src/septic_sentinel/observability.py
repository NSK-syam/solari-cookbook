"""Structured logs and recursive privacy redaction."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "address",
        "authorization",
        "api_key",
        "approval_token",
        "context_blob",
        "owner",
        "ownername",
        "secret",
        "token",
        "token_hash",
    }
)
LOG_FIELDS = (
    "request_id",
    "case_id",
    "method",
    "path",
    "status_code",
    "latency_ms",
    "source",
    "outcome",
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else redact(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for field in LOG_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), separators=(",", ":"), default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
