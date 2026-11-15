"""Unified RepoPilot exceptions with sanitized structured details."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from repopilot.observability.logging import redact_mapping, redact_text


class ErrorCode(StrEnum):
    CONFIGURATION_ERROR = "configuration_error"
    SCHEMA_VALIDATION_ERROR = "schema_validation_error"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    TOOL_REGISTRATION_ERROR = "tool_registration_error"
    WORKTREE_ERROR = "worktree_error"
    PATCH_VALIDATION_ERROR = "patch_validation_error"
    CHECKPOINT_ERROR = "checkpoint_error"
    MEMORY_WRITE_ERROR = "memory_write_error"
    APPROVAL_ERROR = "approval_error"
    BUDGET_EXCEEDED = "budget_exceeded"
    SANDBOX_VIOLATION = "sandbox_violation"
    EXTERNAL_SERVICE_UNAVAILABLE = "external_service_unavailable"
    PATCH_APPLICATION_ERROR = "patch_application_error"
    TEST_EXECUTION_ERROR = "test_execution_error"


class RepoPilotError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.message = redact_text(message)
        self.code = code
        self.details = redact_mapping(details or {})
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.code.value,
            "message": self.message,
            "details": self.details,
        }


class ConfigurationError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.CONFIGURATION_ERROR, details=details)


class SchemaValidationError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.SCHEMA_VALIDATION_ERROR, details=details)


class ToolRegistrationError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code=ErrorCode.TOOL_REGISTRATION_ERROR,
            details=details,
        )


class WorktreeError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.WORKTREE_ERROR, details=details)


class PatchValidationError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code=ErrorCode.PATCH_VALIDATION_ERROR,
            details=details,
        )


class CheckpointError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.CHECKPOINT_ERROR, details=details)


class MemoryWriteError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.MEMORY_WRITE_ERROR, details=details)


class ApprovalError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.APPROVAL_ERROR, details=details)


class ToolExecutionError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.TOOL_EXECUTION_ERROR, details=details)


class BudgetExceededError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.BUDGET_EXCEEDED, details=details)


class SandboxViolationError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.SANDBOX_VIOLATION, details=details)


class ExternalServiceUnavailableError(RepoPilotError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code=ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE,
            details=details,
        )
