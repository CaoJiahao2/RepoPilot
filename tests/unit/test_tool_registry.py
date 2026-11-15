from pathlib import Path

from pydantic import Field

import pytest

from repopilot.core.errors import ToolRegistrationError
from repopilot.tools.base import (
    ToolContext,
    ToolGateway,
    ToolInput,
    ToolRegistry,
    ToolSpec,
)
from repopilot.testing.fakes import FakeToolHandler, RecordingToolHandler


class EchoInput(ToolInput):
    value: str = Field(min_length=1)


class SleepInput(ToolInput):
    pass


def _spec(
    handler,
    *,
    name: str = "echo",
    requires_approval: bool = False,
    timeout_seconds: float = 1.0,
    max_output_bytes: int = 1_000,
    input_model: type[ToolInput] = EchoInput,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="test tool",
        input_model=input_model,
        handler=handler,
        risk_level="read",
        timeout_seconds=timeout_seconds,
        idempotent=True,
        requires_approval=requires_approval,
        max_output_bytes=max_output_bytes,
    )


def _context(tmp_path: Path, **overrides) -> ToolContext:
    return ToolContext(allowed_root=tmp_path, **overrides)


def test_registry_registers_queries_and_validates_schema(tmp_path: Path) -> None:
    handler = RecordingToolHandler({"ok": True})
    registry = ToolRegistry()
    spec = _spec(handler)
    registry.register(spec)

    assert registry.names() == ("echo",)
    assert registry.get("echo") is spec
    validated = registry.validate_input("echo", {"value": "hello"})
    assert validated.model_dump() == {"value": "hello"}
    assert spec.risk_level == "read"
    assert spec.timeout_seconds == 1.0
    assert spec.idempotent is True
    assert spec.requires_approval is False


def test_duplicate_registration_is_rejected(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_spec(RecordingToolHandler()))

    with pytest.raises(ToolRegistrationError, match="already registered"):
        registry.register(_spec(RecordingToolHandler()))


def test_gateway_rejects_unknown_invalid_and_unauthorized_tools(tmp_path: Path) -> None:
    handler = RecordingToolHandler({"ok": True})
    registry = ToolRegistry()
    registry.register(_spec(handler, name="echo"))
    registry.register(_spec(handler, name="protected", requires_approval=True))
    gateway = ToolGateway(registry, _context(tmp_path))

    unknown = gateway.execute("missing", {})
    invalid = gateway.execute("echo", {"value": ""})
    unauthorized = gateway.execute("protected", {"value": "x"})

    assert unknown.success is False
    assert unknown.error_code == "tool_not_found"
    assert invalid.success is False
    assert invalid.error_code == "invalid_input"
    assert unauthorized.success is False
    assert unauthorized.error_code == "permission_denied"
    assert handler.calls == []


def test_gateway_captures_timeout_exception_and_output_limit(tmp_path: Path) -> None:
    def raise_error(arguments: EchoInput, context: ToolContext) -> str:
        raise RuntimeError("boom")

    def sleep_handler(arguments: SleepInput, context: ToolContext) -> str:
        import time

        time.sleep(0.05)
        return "late"

    registry = ToolRegistry()
    registry.register(_spec(raise_error, name="explode"))
    registry.register(
        _spec(sleep_handler, name="slow", input_model=SleepInput, timeout_seconds=0.01)
    )
    registry.register(
        _spec(
            RecordingToolHandler("x" * 100),
            name="large",
            max_output_bytes=10,
        )
    )
    gateway = ToolGateway(registry, _context(tmp_path))

    exploded = gateway.execute("explode", {"value": "x"})
    timed_out = gateway.execute("slow", {})
    too_large = gateway.execute("large", {"value": "x"})

    assert exploded.success is False
    assert exploded.error_code == "tool_error"
    assert timed_out.success is False
    assert timed_out.error_code == "timeout"
    assert too_large.success is False
    assert too_large.error_code == "output_limit_exceeded"


def test_fake_and_recording_tool_handlers_receive_validated_input(tmp_path: Path) -> None:
    fake = FakeToolHandler({"fake": True})
    recording = RecordingToolHandler({"mock": True})
    registry = ToolRegistry()
    registry.register(_spec(fake, name="fake_tool"))
    registry.register(_spec(recording, name="mock_tool"))
    gateway = ToolGateway(registry, _context(tmp_path))

    assert gateway.execute("fake_tool", {"value": "a"}).success is True
    assert gateway.execute("mock_tool", {"value": "b"}).success is True
    assert len(fake.calls) == 1
    assert len(recording.calls) == 1
    assert fake.calls[0][0].value == "a"
    assert recording.calls[0][0].value == "b"
