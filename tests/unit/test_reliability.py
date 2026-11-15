import time

from repopilot.core.errors import BudgetExceededError
from repopilot.core.schemas import BudgetState
from repopilot.reliability import (
    CancellationToken,
    ExecutionLedger,
    ReliabilityController,
    classify_error,
)


def test_execution_ledger_deduplicates_non_idempotent_success() -> None:
    controller = ReliabilityController(ledger=ExecutionLedger())
    calls = []

    def non_idempotent():
        calls.append(1)
        return "created"

    first = controller.execute("write-1", non_idempotent, budget=BudgetState())
    second = controller.execute("write-1", non_idempotent, budget=first.budget_after)

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert second.deduplicated is True
    assert calls == [1]


def test_error_classification_distinguishes_retryable_terminal_and_human() -> None:
    assert classify_error(TimeoutError()) == "retryable"
    assert classify_error(ConnectionError()) == "retryable"
    assert classify_error(BudgetExceededError("budget")) == "requires_human"
    assert classify_error(ValueError("bad")) == "terminal"


def test_reliability_timeout_cancellation_and_budget_exhaustion() -> None:
    controller = ReliabilityController()

    def slow():
        time.sleep(0.2)
        return "late"

    timed_out = controller.execute(
        "slow",
        slow,
        budget=BudgetState(max_runtime_seconds=10),
        timeout_seconds=0.01,
    )

    token = CancellationToken()
    token.cancel("task cancelled")
    called = []
    cancelled = controller.execute(
        "cancelled",
        lambda: called.append(1),
        budget=BudgetState(),
        token=token,
    )

    exhausted = controller.execute(
        "budget",
        lambda: "never",
        budget=BudgetState(max_tool_calls=1, tool_calls_used=1),
    )

    assert timed_out.status == "timeout"
    assert timed_out.retryability == "retryable"
    assert cancelled.status == "cancelled"
    assert called == []
    assert exhausted.status == "budget_exceeded"
    assert exhausted.retryability == "requires_human"


def test_terminal_failure_is_not_retried() -> None:
    controller = ReliabilityController()
    calls = []

    def fail():
        calls.append(1)
        raise ValueError("terminal")

    first = controller.execute("terminal", fail, budget=BudgetState())
    second = controller.execute("terminal", fail, budget=BudgetState())

    assert first.status == "failed"
    assert first.retryability == "terminal"
    assert second.status == "failed"
    assert second.attempts == 1
    assert calls == [1]
