"""Structured reflection, recovery, and planner feedback contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from repopilot.core.schemas import (
    Action,
    FailureType,
    RepoPilotModel,
    RetryCounters,
    TaskStatus,
    TestReport,
)

ReflectionSource = Literal["test_report", "tool_result", "diff", "trace", "diagnosis", "budget"]


class ReflectionEvidence(RepoPilotModel):
    source_type: ReflectionSource
    reference: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    failure_type: FailureType | None = None


class RetryBudgetRemaining(RepoPilotModel):
    patch_retries: int = Field(ge=0)
    replans: int = Field(ge=0)
    tool_retries: int = Field(ge=0)


class RecoveryStrategy(RepoPilotModel):
    failure_type: FailureType
    recommended_action: Action
    should_rollback_patch: bool = False
    should_modify_code: bool = True
    retry_kind: Literal["none", "patch", "replan", "tool", "environment"] = "none"
    requires_human: bool = False


class ReflectionResult(RepoPilotModel):
    failure_type: FailureType
    evidence: list[ReflectionEvidence] = Field(min_length=1)
    root_cause_hypothesis: str = Field(min_length=1)
    recommended_action: Action
    confidence: float = Field(ge=0, le=1)
    retry_budget_remaining: RetryBudgetRemaining
    strategy: RecoveryStrategy

    def to_planner_feedback(self) -> "PlannerFeedback":
        return PlannerFeedback(
            failure_type=self.failure_type,
            recommended_action=self.recommended_action,
            root_cause_hypothesis=self.root_cause_hypothesis,
            evidence_references=[item.reference for item in self.evidence],
            retry_budget_remaining=self.retry_budget_remaining,
            should_rollback_patch=self.strategy.should_rollback_patch,
            should_modify_code=self.strategy.should_modify_code,
        )


class PlannerFeedback(RepoPilotModel):
    failure_type: FailureType
    recommended_action: Action
    root_cause_hypothesis: str = Field(min_length=1)
    evidence_references: list[str] = Field(min_length=1)
    retry_budget_remaining: RetryBudgetRemaining
    should_rollback_patch: bool
    should_modify_code: bool


class ReflectionStateSnapshot(RepoPilotModel):
    status: TaskStatus
    current_action: Action | None
    evidence_count: int = Field(ge=0)
    patch_applied: bool
    latest_test_status: str | None
    tool_failure_count: int = Field(ge=0)
    retry_counts: RetryCounters
    trace_count: int = Field(ge=0)


class ReflectionCost(RepoPilotModel):
    llm_calls: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    duration_seconds: float = Field(default=0, ge=0)
    cost_status: Literal["actual", "fake", "unavailable"] = "unavailable"


class ReflectionRecord(RepoPilotModel):
    reflection_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    timestamp: datetime
    state_before: ReflectionStateSnapshot
    state_after: ReflectionStateSnapshot
    result: ReflectionResult
    planner_feedback: PlannerFeedback
    cost: ReflectionCost
    recovery_outcome: Literal["recovered", "failed", "terminal", "unknown"] = "unknown"
