import io
import json
import logging

from repopilot.core.errors import ToolExecutionError
from repopilot.observability.logging import (
    JsonFormatter,
    configure_logging,
    redact_mapping,
    redact_text,
)


def _capture_logger(name: str = "repopilot.tests.logging") -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger, stream


def test_structured_logging_redacts_secrets() -> None:
    logger, stream = _capture_logger()
    secret = "sk-super-secret-value"
    password = "database-password"

    logger.info(
        "config loaded",
        extra={
            "api_key": secret,
            "database_url": f"postgresql://user:{password}@localhost/repopilot",
            "nested": {"authorization": f"Bearer {secret}"},
        },
    )

    output = stream.getvalue()
    payload = json.loads(output)

    assert secret not in output
    assert password not in output
    assert payload["message"] == "config loaded"
    assert payload["api_key"] == "[REDACTED]"
    assert payload["database_url"] == "[REDACTED]"
    assert payload["nested"]["authorization"] == "[REDACTED]"


def test_secret_patterns_are_redacted_from_messages() -> None:
    message = "failed with api_key=sk-secret-123456 and Bearer abc.def.ghi"
    redacted = redact_text(message)

    assert "sk-secret-123456" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "[REDACTED]" in redacted


def test_error_details_are_redacted() -> None:
    error = ToolExecutionError(
        "tool failed",
        details={
            "api_key": "sk-secret-123456",
            "database_url": "postgresql://user:password@localhost/db",
        },
    )

    serialized = json.dumps(error.to_dict())
    assert "sk-secret-123456" not in serialized
    assert "password" not in serialized
    assert error.to_dict()["details"]["api_key"] == "[REDACTED]"


def test_redact_mapping_preserves_non_sensitive_values() -> None:
    values = redact_mapping({"task_id": "task-001", "duration_ms": 12})

    assert values == {"task_id": "task-001", "duration_ms": 12}
