"""Structured logging with conservative secret redaction."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd|authorization|cookie|credential|database[_-]?url)",
    re.IGNORECASE,
)

_SECRET_VALUE_PATTERNS = (
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        REDACTED,
    ),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), REDACTED),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd)"
            r"(\s*[:=]\s*)[^\s,;]+"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(r"(?i)\b(postgresql?://[^:\s/]+):([^@\s]+)@"),
        r"\1:[REDACTED]@",
    ),
)

_STANDARD_LOG_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


def redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEY_PATTERN.search(key):
        return REDACTED if value not in (None, "") else value
    if isinstance(value, Mapping):
        return {str(item_key): redact_value(str(item_key), item_value) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_value(key, item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): redact_value(str(key), value) for key, value in values.items()}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_KEYS or key.startswith("_"):
                continue
            payload[key] = redact_value(key, value)
        return redact_text(json.dumps(payload, ensure_ascii=False, default=str))


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        message = redact_text(record.getMessage())
        extras = {
            key: redact_value(key, value)
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOG_RECORD_KEYS and not key.startswith("_")
        }
        suffix = f" extras={json.dumps(extras, ensure_ascii=False, default=str)}" if extras else ""
        return redact_text(f"{timestamp} {record.levelname} {record.name} {message}{suffix}")


def configure_logging(
    *,
    level: str = "INFO",
    format: str = "json",
    logger_name: str = "repopilot",
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.setLevel(getattr(logging, level.upper()))
    logger.propagate = False

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if format == "json" else TextFormatter())
    logger.addHandler(handler)
    return logger


def get_logger(name: str = "repopilot") -> logging.Logger:
    return logging.getLogger(name)
