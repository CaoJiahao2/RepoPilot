"""Tool contracts, path safety, registry, and unified execution gateway."""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generic, Literal, Mapping, TypeVar

from pydantic import ValidationError

from repopilot.core.errors import (
    RepoPilotError,
    SandboxViolationError,
    ToolExecutionError,
    ToolRegistrationError,
)
from repopilot.core.schemas import RepoPilotModel, ToolResult, TraceEvent
from repopilot.observability.logging import get_logger

RiskLevel = Literal["read", "execute", "write", "admin"]
ToolNamePattern = re.compile(r"^[a-z][a-z0-9_]*$")

InputT = TypeVar("InputT", bound="ToolInput")


class ToolInput(RepoPilotModel):
    """Base class for tool arguments validated before execution."""


@dataclass(frozen=True)
class ToolContext:
    allowed_root: Path
    approved: bool = False
    max_output_bytes: int = 1_000_000
    max_file_bytes: int = 1_000_000
    command_timeout_seconds: float = 30.0
    logger: logging.Logger = field(default_factory=lambda: get_logger("repopilot.tools"))
    clock: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        try:
            root = self.allowed_root.expanduser().resolve(strict=True)
        except OSError as exc:
            raise SandboxViolationError(
                "allowed repository root does not exist",
                details={"reason": type(exc).__name__},
            ) from exc
        if not root.is_dir():
            raise SandboxViolationError("allowed repository root must be a directory")
        if self.max_output_bytes <= 0 or self.max_file_bytes <= 0:
            raise ValueError("tool size limits must be positive")
        if self.command_timeout_seconds <= 0:
            raise ValueError("command timeout must be positive")
        object.__setattr__(self, "allowed_root", root)

    def resolve_path(
        self,
        relative_path: str,
        *,
        expected: str | None = None,
        must_exist: bool = False,
    ) -> Path:
        raw = Path(relative_path)
        if raw.is_absolute() or ".." in raw.parts:
            raise SandboxViolationError(
                "path traversal or absolute paths are not allowed",
                details={"path": relative_path},
            )

        candidate = self.allowed_root
        for part in raw.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise SandboxViolationError(
                    "symbolic links are not allowed in tool paths",
                    details={"path": relative_path},
                )

        resolved = candidate.resolve(strict=False)
        if resolved != self.allowed_root and self.allowed_root not in resolved.parents:
            raise SandboxViolationError(
                "path escapes the allowed repository root",
                details={"path": relative_path},
            )
        if must_exist and not resolved.exists():
            raise ToolExecutionError(
                "tool path does not exist",
                details={"error_code": "path_not_found", "path": relative_path},
            )
        if expected == "file" and resolved.exists() and not resolved.is_file():
            raise ToolExecutionError(
                "tool path is not a file",
                details={"error_code": "not_a_file", "path": relative_path},
            )
        if expected == "dir" and resolved.exists() and not resolved.is_dir():
            raise ToolExecutionError(
                "tool path is not a directory",
                details={"error_code": "not_a_directory", "path": relative_path},
            )
        return resolved


@dataclass(frozen=True)
class ToolSpec(Generic[InputT]):
    name: str
    description: str
    input_model: type[InputT]
    handler: Callable[[InputT, ToolContext], Any]
    risk_level: RiskLevel
    timeout_seconds: float
    idempotent: bool
    requires_approval: bool
    max_output_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if not ToolNamePattern.fullmatch(self.name):
            raise ValueError("tool names must use lowercase snake_case")
        if not self.description.strip():
            raise ValueError("tool description must not be empty")
        if not issubclass(self.input_model, ToolInput):
            raise TypeError("tool input_model must extend ToolInput")
        if not callable(self.handler):
            raise TypeError("tool handler must be callable")
        if self.timeout_seconds <= 0 or self.max_output_bytes <= 0:
            raise ValueError("tool timeout and output limit must be positive")
        self.input_model.model_json_schema()


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec[Any]] = {}

    def register(self, spec: ToolSpec[Any]) -> None:
        if spec.name in self._tools:
            raise ToolRegistrationError(
                "tool name is already registered",
                details={"tool_name": spec.name},
            )
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec[Any]:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolRegistrationError(
                "tool is not registered",
                details={"tool_name": name},
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def specs(self) -> tuple[ToolSpec[Any], ...]:
        return tuple(self._tools[name] for name in self.names())

    def validate_input(self, name: str, arguments: Mapping[str, Any]) -> ToolInput:
        spec = self.get(name)
        return spec.input_model.model_validate(arguments)


class ToolGateway:
    def __init__(self, registry: ToolRegistry, context: ToolContext) -> None:
        self.registry = registry
        self.context = context

    def execute(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        started = time.perf_counter()
        try:
            spec = self.registry.get(name)
        except RepoPilotError as exc:
            return self._failure(name, started, "tool_not_found", str(exc))

        if spec.requires_approval and not self.context.approved:
            return self._failure(
                name,
                started,
                "permission_denied",
                "tool requires approval",
            )

        try:
            validated_input = spec.input_model.model_validate(arguments)
        except ValidationError as exc:
            return self._failure(
                name,
                started,
                "invalid_input",
                "tool input failed schema validation",
                details={"error_count": len(exc.errors())},
            )

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(spec.handler, validated_input, self.context)
            try:
                raw_output = future.result(timeout=spec.timeout_seconds)
            except FutureTimeoutError as exc:
                future.cancel()
                raise ToolExecutionError(
                    "tool execution timed out",
                    details={"error_code": "timeout"},
                ) from exc
        except RepoPilotError as exc:
            error_code = str(exc.details.get("error_code", exc.code.value))
            return self._failure(name, started, error_code, str(exc))
        except Exception as exc:
            return self._failure(
                name,
                started,
                "tool_error",
                "tool handler raised an unexpected exception",
                details={"exception": type(exc).__name__},
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        output = self._serialize_output(raw_output)
        limit = min(spec.max_output_bytes, self.context.max_output_bytes)
        output_bytes = len(output.encode("utf-8"))
        if output_bytes > limit:
            return self._failure(
                name,
                started,
                "output_limit_exceeded",
                "tool output exceeded configured limit",
                details={"output_bytes": output_bytes, "limit_bytes": limit},
            )

        result = ToolResult(
            tool_name=name,
            success=True,
            output=output,
            duration_ms=self._duration_ms(started),
        )
        self._log(result, output_bytes=output_bytes)
        return result

    def _serialize_output(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def _failure(
        self,
        name: str,
        started: float,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        result = ToolResult(
            tool_name=name or "unknown_tool",
            success=False,
            error_code=error_code,
            error_message=message,
            duration_ms=self._duration_ms(started),
        )
        self._log(result, output_bytes=0, details=details)
        return result

    def _duration_ms(self, started: float) -> int:
        return max(0, round((time.perf_counter() - started) * 1000))

    def _log(
        self,
        result: ToolResult,
        *,
        output_bytes: int,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        payload = {
            "tool_name": result.tool_name,
            "success": result.success,
            "error_code": result.error_code,
            "duration_ms": result.duration_ms,
            "output_bytes": output_bytes,
        }
        if details:
            payload.update({key: value for key, value in details.items()})
        if result.success:
            self.context.logger.info("tool_execution", extra=payload)
        else:
            self.context.logger.error("tool_execution", extra=payload)


def execute_tool_with_trace(
    gateway: ToolGateway,
    state: Mapping[str, Any],
    name: str,
    arguments: Mapping[str, Any],
    *,
    actor: str = "agent",
) -> dict[str, Any]:
    """Execute one tool and return LangGraph state updates with trace records."""

    result = gateway.execute(name, arguments)
    task = state["task"]
    existing_results = state.get("tool_results", [])
    event = TraceEvent(
        event_id=f"{task.task_id}:tool:{name}:{len(existing_results)}",
        task_id=task.task_id,
        timestamp=gateway.context.clock(),
        event_type="tool",
        actor=actor,
        action=name,
        status="succeeded" if result.success else "failed",
        duration_ms=result.duration_ms,
        message="tool execution succeeded" if result.success else result.error_message or "tool failed",
        details={
            "tool_name": result.tool_name,
            "success": result.success,
            "error_code": result.error_code,
            "output_bytes": len(result.output.encode("utf-8")),
        },
    )
    updates: dict[str, Any] = {
        "tool_results": [result],
        "execution_trace": [event],
    }
    if result.success:
        updates["status"] = state.get("status", "running")
    else:
        updates.update(
            {
                "status": "failed",
                "failure_type": "tool_failure",
                "last_error": result.error_message,
            }
        )
    return updates
