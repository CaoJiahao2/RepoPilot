"""Execution-aware Reflection with bounded recovery strategies."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import ValidationError

from repopilot.core.schemas import BudgetState, FailureType, RetryCounters
from repopilot.reflection.classifier import FailureClassifier, FailureClassification
from repopilot.reflection.models import (
    PlannerFeedback,
    RecoveryStrategy,
    ReflectionCost,
    ReflectionRecord,
    ReflectionResult,
    ReflectionStateSnapshot,
    RetryBudgetRemaining,
)


class ReflectionOutputParser:
    """Validate structured Reflection output and safely degrade invalid output."""

    @staticmethod
    def parse(raw_output: str, *, fallback: ReflectionResult) -> tuple[ReflectionResult, bool]:
        try:
            return ReflectionResult.model_validate_json(raw_output), False
        except ValidationError:
            return fallback, True


class ReflectionEngine:
    def __init__(
        self,
        *,
        classifier: FailureClassifier | None = None,
        clock=None,
    ) -> None:
        self.classifier = classifier or FailureClassifier()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def reflect(
        self,
        state: Mapping[str, Any],
        *,
        raw_reflection: str | None = None,
        recovery_outcome: str = "unknown",
    ) -> ReflectionRecord:
        started = time.perf_counter()
        state_before = self._snapshot(state)
        classification = self.classifier.classify(
            test_report=state.get("test_report"),
            baseline_test_report=state.get("baseline_test_report"),
            tool_results=state.get("tool_results", []),
            patch_application=state.get("patch_application"),
            diagnosis=state.get("diagnosis"),
            evidence=state.get("evidence", []),
            trace=state.get("execution_trace", []),
            status=state.get("status"),
        )
        retry_counts = state.get("retry_counts") or RetryCounters()
        budget = state.get("budget") or BudgetState()
        remaining = self._remaining(retry_counts, budget)
        strategy = self._strategy(classification.failure_type, remaining)
        fallback = ReflectionResult(
            failure_type=classification.failure_type,
            evidence=classification.evidence,
            root_cause_hypothesis=classification.reason,
            recommended_action=strategy.recommended_action,
            confidence=0.5,
            retry_budget_remaining=remaining,
            strategy=strategy,
        )
        result = fallback
        if raw_reflection is not None:
            result, _ = ReflectionOutputParser.parse(raw_reflection, fallback=fallback)

        if not self._can_retry(result.failure_type, remaining):
            strategy = self._terminal_strategy(result.failure_type)
            result = result.model_copy(
                update={
                    "recommended_action": strategy.recommended_action,
                    "strategy": strategy,
                    "retry_budget_remaining": remaining,
                }
            )

        state_after = self._snapshot(state, current_action=result.recommended_action)
        feedback: PlannerFeedback = result.to_planner_feedback()
        duration = max(0.0, time.perf_counter() - started)
        record = ReflectionRecord(
            reflection_id=f"{state['task'].task_id}:reflection:{int(started * 1000)}",
            task_id=state["task"].task_id,
            timestamp=self.clock(),
            state_before=state_before,
            state_after=state_after,
            result=result,
            planner_feedback=feedback,
            cost=ReflectionCost(duration_seconds=duration, cost_status="unavailable"),
            recovery_outcome=recovery_outcome,  # type: ignore[arg-type]
        )
        return record

    @staticmethod
    def _remaining(
        retry_counts: RetryCounters,
        budget: BudgetState,
    ) -> RetryBudgetRemaining:
        return RetryBudgetRemaining(
            patch_retries=max(0, budget.max_patch_retries - retry_counts.patch_retries),
            replans=max(0, budget.max_replans - retry_counts.replans),
            tool_retries=max(0, budget.max_tool_retries - retry_counts.tool_retries),
        )

    def _strategy(
        self,
        failure_type: FailureType,
        remaining: RetryBudgetRemaining,
    ) -> RecoveryStrategy:
        strategies = {
            "patch_error": RecoveryStrategy(
                failure_type="patch_error",
                recommended_action="patch",
                should_rollback_patch=False,
                should_modify_code=True,
                retry_kind="patch",
            ),
            "regression": RecoveryStrategy(
                failure_type="regression",
                recommended_action="replan",
                should_rollback_patch=True,
                should_modify_code=True,
                retry_kind="replan",
            ),
            "wrong_root_cause": RecoveryStrategy(
                failure_type="wrong_root_cause",
                recommended_action="replan",
                should_rollback_patch=True,
                should_modify_code=True,
                retry_kind="replan",
            ),
            "missing_context": RecoveryStrategy(
                failure_type="missing_context",
                recommended_action="search",
                should_rollback_patch=False,
                should_modify_code=False,
                retry_kind="replan",
            ),
            "test_env_error": RecoveryStrategy(
                failure_type="test_env_error",
                recommended_action="test",
                should_rollback_patch=False,
                should_modify_code=False,
                retry_kind="environment",
            ),
            "tool_failure": RecoveryStrategy(
                failure_type="tool_failure",
                recommended_action="replan",
                should_rollback_patch=False,
                should_modify_code=False,
                retry_kind="tool",
            ),
            "budget_exceeded": self._terminal_strategy("budget_exceeded"),
        }
        return strategies[failure_type]

    @staticmethod
    def _terminal_strategy(failure_type: FailureType) -> RecoveryStrategy:
        return RecoveryStrategy(
            failure_type=failure_type,
            recommended_action="finish",
            should_rollback_patch=False,
            should_modify_code=False,
            retry_kind="none",
            requires_human=True,
        )

    @staticmethod
    def _can_retry(failure_type: FailureType, remaining: RetryBudgetRemaining) -> bool:
        if failure_type == "budget_exceeded":
            return False
        if failure_type == "patch_error":
            return remaining.patch_retries > 0
        if failure_type in {"regression", "wrong_root_cause", "missing_context"}:
            return remaining.replans > 0
        if failure_type in {"test_env_error", "tool_failure"}:
            return remaining.tool_retries > 0
        return False

    @staticmethod
    def _snapshot(
        state: Mapping[str, Any],
        *,
        current_action: str | None = None,
    ) -> ReflectionStateSnapshot:
        test_report = state.get("test_report") or state.get("baseline_test_report")
        patch_application = state.get("patch_application")
        tool_results = state.get("tool_results", [])
        return ReflectionStateSnapshot(
            status=state.get("status", "running"),
            current_action=current_action or state.get("current_action"),
            evidence_count=len(state.get("evidence", [])),
            patch_applied=bool(
                patch_application
                and (
                    patch_application.get("patch_applied")
                    if isinstance(patch_application, Mapping)
                    else getattr(patch_application, "patch_applied", False)
                )
            ),
            latest_test_status=test_report.status if test_report else None,
            tool_failure_count=sum(1 for result in tool_results if not result.success),
            retry_counts=state.get("retry_counts") or RetryCounters(),
            trace_count=len(state.get("execution_trace", [])),
        )
