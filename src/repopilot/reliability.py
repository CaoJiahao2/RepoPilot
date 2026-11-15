"""Bounded execution, cancellation, deduplication, and retry classification."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable, Literal

from repopilot.core.errors import BudgetExceededError, RepoPilotError
from repopilot.core.schemas import BudgetState

Retryability = Literal["retryable", "terminal", "requires_human"]
ExecutionStatus = Literal["succeeded", "failed", "timeout", "cancelled", "budget_exceeded"]


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self, reason: str = "cancelled") -> None:
        self.reason = reason
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return getattr(self, "_reason", "cancelled")

    @reason.setter
    def reason(self, value: str) -> None:
        self._reason = value


@dataclass
class ExecutionRecord:
    key: str
    status: ExecutionStatus
    retryability: Retryability
    attempts: int
    result: Any = None
    error: str | None = None


@dataclass
class ReliabilityResult:
    status: ExecutionStatus
    retryability: Retryability
    value: Any = None
    error: str | None = None
    attempts: int = 1
    deduplicated: bool = False
    duration_seconds: float = 0.0
    budget_after: BudgetState | None = None


class ExecutionLedger:
    def __init__(self) -> None:
        self._records: dict[str, ExecutionRecord] = {}

    def get(self, key: str) -> ExecutionRecord | None:
        return self._records.get(key)

    def record_success(self, key: str, value: Any, *, attempts: int = 1) -> ExecutionRecord:
        record = ExecutionRecord(
            key=key,
            status="succeeded",
            retryability="terminal",
            attempts=attempts,
            result=value,
        )
        self._records[key] = record
        return record

    def record_failure(
        self,
        key: str,
        *,
        error: BaseException,
        retryability: Retryability,
        attempts: int,
    ) -> ExecutionRecord:
        record = ExecutionRecord(
            key=key,
            status="failed",
            retryability=retryability,
            attempts=attempts,
            error=f"{type(error).__name__}: {error}",
        )
        self._records[key] = record
        return record


def classify_error(error: BaseException) -> Retryability:
    if isinstance(error, BudgetExceededError):
        return "requires_human"
    if isinstance(error, RepoPilotError):
        code = error.code.value
        if code in {"budget_exceeded", "sandbox_violation", "patch_validation_error", "memory_write_error"}:
            return "terminal"
        return "retryable"
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return "retryable"
    return "terminal"


class ReliabilityController:
    def __init__(self, *, ledger: ExecutionLedger | None = None) -> None:
        self.ledger = ledger or ExecutionLedger()

    def execute(
        self,
        key: str,
        fn: Callable[[], Any],
        *,
        budget: BudgetState,
        token: CancellationToken | None = None,
        timeout_seconds: float = 30.0,
    ) -> ReliabilityResult:
        existing = self.ledger.get(key)
        if existing is not None and existing.status == "succeeded":
            return ReliabilityResult(
                status="succeeded",
                retryability="terminal",
                value=existing.result,
                attempts=existing.attempts,
                deduplicated=True,
                budget_after=budget,
            )
        if existing is not None and existing.retryability == "terminal":
            return ReliabilityResult(
                status="failed",
                retryability="terminal",
                error=existing.error,
                attempts=existing.attempts,
                budget_after=budget,
            )
        if token is not None and token.cancelled:
            return ReliabilityResult(
                status="cancelled",
                retryability="terminal",
                error=token.reason,
                attempts=existing.attempts if existing else 0,
                budget_after=budget,
            )
        if budget.tool_calls_used >= budget.max_tool_calls or budget.runtime_seconds_used >= budget.max_runtime_seconds:
            return ReliabilityResult(
                status="budget_exceeded",
                retryability="requires_human",
                error="execution budget exhausted",
                attempts=existing.attempts if existing else 0,
                budget_after=budget,
            )

        attempts = (existing.attempts if existing else 0) + 1
        started = time.perf_counter()
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(fn)
            try:
                value = future.result(timeout=timeout_seconds)
            except FutureTimeoutError as exc:
                future.cancel()
                self.ledger.record_failure(
                    key,
                    error=exc,
                    retryability="retryable",
                    attempts=attempts,
                )
                return ReliabilityResult(
                    status="timeout",
                    retryability="retryable",
                    error="execution timed out",
                    attempts=attempts,
                    duration_seconds=time.perf_counter() - started,
                    budget_after=self._budget_after(budget, started),
                )
        except BaseException as exc:
            retryability = classify_error(exc)
            self.ledger.record_failure(
                key,
                error=exc,
                retryability=retryability,
                attempts=attempts,
            )
            return ReliabilityResult(
                status="failed",
                retryability=retryability,
                error=f"{type(exc).__name__}: {exc}",
                attempts=attempts,
                duration_seconds=time.perf_counter() - started,
                budget_after=self._budget_after(budget, started),
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        self.ledger.record_success(key, value, attempts=attempts)
        return ReliabilityResult(
            status="succeeded",
            retryability="terminal",
            value=value,
            attempts=attempts,
            duration_seconds=time.perf_counter() - started,
            budget_after=self._budget_after(budget, started),
        )

    @staticmethod
    def _budget_after(budget: BudgetState, started: float) -> BudgetState:
        values = budget.model_dump()
        values["tool_calls_used"] += 1
        values["runtime_seconds_used"] += max(0.0, time.perf_counter() - started)
        return BudgetState.model_validate(values)
