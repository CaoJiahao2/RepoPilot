"""Structured adaptive planning records and complexity features."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from repopilot.reflection.models import PlannerFeedback
from repopilot.core.schemas import (
    Action,
    BudgetState,
    FailureType,
    RepoPilotModel,
    TaskPlan,
    TaskStatus,
)


class ComplexityFeatures(RepoPilotModel):
    stack_trace_present: bool
    stack_file_count: int = Field(ge=0)
    stack_line_count: int = Field(ge=0)
    stack_localization_score: float = Field(ge=0, le=1)
    evidence_count: int = Field(ge=0)
    evidence_file_count: int = Field(ge=0)
    evidence_symbol_count: int = Field(ge=0)
    evidence_completeness: float = Field(ge=0, le=1)
    memory_hit_count: int = Field(ge=0)
    verified_memory_hit_count: int = Field(ge=0)
    latest_test_status: str | None = None
    tool_success_count: int = Field(ge=0)
    tool_failure_count: int = Field(ge=0)
    invalid_plan_count: int = Field(ge=0)
    budget_exhausted: bool


class PlanningInputSummary(RepoPilotModel):
    task_id: str = Field(min_length=1)
    issue_chars: int = Field(ge=0)
    stack_trace_chars: int = Field(ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    memory_ids: list[str] = Field(default_factory=list)
    latest_test_status: str | None = None
    tool_result_count: int = Field(ge=0)
    complexity: ComplexityFeatures
    budget: BudgetState


class PlanningCost(RepoPilotModel):
    llm_calls: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    runtime_seconds: float = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    cost_status: Literal["actual", "fake", "unavailable"] = "unavailable"


class PlanningDecision(RepoPilotModel):
    policy_name: str = Field(min_length=1)
    plan: TaskPlan | None = None
    plan_valid: bool
    validation_error: str | None = None
    requested_action: Action | None = None
    effective_action: Action
    rationale: str = Field(min_length=1)
    input_summary: PlanningInputSummary
    complexity: ComplexityFeatures
    budget_before: BudgetState
    budget_after: BudgetState
    invalid_plan_count: int = Field(ge=0)
    reflection_feedback: PlannerFeedback | None = None


class PlanningExecutionResult(RepoPilotModel):
    action: Action
    success: bool
    result_summary: str = Field(min_length=1)
    failure_type: FailureType | None = None
    duration_seconds: float = Field(default=0, ge=0)


class PlanningRecord(RepoPilotModel):
    record_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    timestamp: datetime
    decision: PlanningDecision
    execution_result: PlanningExecutionResult | None = None
    cost: PlanningCost
