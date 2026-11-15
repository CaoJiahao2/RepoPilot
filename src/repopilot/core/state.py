"""LangGraph state with explicit overwrite and append channels."""

from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict

from repopilot.core.schemas import (
    Action,
    BudgetState,
    Diagnosis,
    Evidence,
    FailureType,
    FinalReport,
    MemoryHit,
    PatchResult,
    RetryCounters,
    TaskPlan,
    TaskRequest,
    TaskStatus,
    TestReport,
    ToolResult,
    TraceEvent,
    ReviewResult,
    EndToEndReport,
    RunCost,
    TaskValidationResult,
    WorkspaceRecord,
)
from repopilot.reflection.models import ReflectionResult
from repopilot.tools.patch import PatchApplicationRecord, PatchValidationResult


class RepoPilotState(TypedDict):
    task: TaskRequest
    plan: NotRequired[TaskPlan | None]
    current_action: NotRequired[Action | None]
    evidence: NotRequired[Annotated[list[Evidence], operator.add]]
    memory_hits: NotRequired[Annotated[list[MemoryHit], operator.add]]
    diagnosis: NotRequired[Diagnosis | None]
    baseline_test_report: NotRequired[TestReport | None]
    patch_result: NotRequired[PatchResult | None]
    test_report: NotRequired[TestReport | None]
    review_result: NotRequired[ReviewResult | None]
    retry_counts: NotRequired[RetryCounters]
    budget: NotRequired[BudgetState]
    status: NotRequired[TaskStatus]
    execution_trace: NotRequired[Annotated[list[TraceEvent], operator.add]]
    tool_results: NotRequired[Annotated[list[ToolResult], operator.add]]
    report: NotRequired[FinalReport | None]
    task_validation: NotRequired[TaskValidationResult | None]
    workspace: NotRequired[WorkspaceRecord | None]
    patch_validation: NotRequired[PatchValidationResult | None]
    patch_application: NotRequired[PatchApplicationRecord | None]
    repair_report: NotRequired[EndToEndReport | None]
    reflection_result: NotRequired[ReflectionResult | None]
    cost: NotRequired[RunCost | None]
    failure_type: NotRequired[FailureType | None]
    failure_node: NotRequired[str | None]
    failure_reason: NotRequired[str | None]
    last_error: NotRequired[str | None]

    # Explicit overwrite semantics:
    # plan, diagnosis, baseline_test_report, patch_result, test_report,
    # review_result, retry_counts, budget, status, report, current_action,
    # failure_type, and last_error are replaced by each new round.
    # Only evidence, memory_hits, execution_trace, and tool_results use operator.add.
