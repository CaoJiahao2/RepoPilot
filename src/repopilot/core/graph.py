"""Minimal LangGraph runtime with bounded routing and deterministic doubles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from repopilot.agents.base import Agent
from repopilot.core.errors import RepoPilotError
from repopilot.core.schemas import (
    BudgetState,
    FailureType,
    FinalReport,
    PatchResult,
    ResearchResult,
    RetryCounters,
    TaskPlan,
    TaskRequest,
    TestReport,
    TraceEvent,
    ReviewResult,
)
from repopilot.core.state import RepoPilotState
from repopilot.llm import LLMClient
from repopilot.tools.tests import TestRunner

REQUIRED_AGENT_NAMES = ("planner", "research", "diagnosis", "coding", "review")


@dataclass(frozen=True)
class RuntimeDependencies:
    llm: LLMClient
    test_runner: TestRunner
    agents: Mapping[str, Agent]
    clock: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        missing = sorted(set(REQUIRED_AGENT_NAMES) - set(self.agents))
        if missing:
            raise ValueError(f"missing graph agents: {missing}")


def _now(deps: RuntimeDependencies) -> datetime:
    value = deps.clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("runtime clock must return a timezone-aware datetime")
    return value


def _trace_event(
    deps: RuntimeDependencies,
    state: RepoPilotState,
    *,
    event_type: str,
    actor: str,
    action: str,
    status: str,
    message: str,
    details: Mapping[str, str | int | float | bool | None] | None = None,
) -> TraceEvent:
    task_id = state["task"].task_id
    existing = state.get("execution_trace", [])
    event_id = f"{task_id}:{event_type}:{action}:{len(existing)}"
    return TraceEvent(
        event_id=event_id,
        task_id=task_id,
        timestamp=_now(deps),
        event_type=event_type,  # type: ignore[arg-type]
        actor=actor,
        action=action,
        status=status,  # type: ignore[arg-type]
        message=message,
        details=dict(details or {}),
    )


def _failure_state(message: str, *, failure_type: FailureType | None = None) -> dict:
    return {
        "status": "failed",
        "failure_type": failure_type,
        "last_error": message,
    }


def _initialize_node(deps: RuntimeDependencies):
    def node(state: RepoPilotState) -> dict:
        start = _trace_event(
            deps,
            state,
            event_type="task",
            actor="runtime",
            action="initialize",
            status="started",
            message="initializing task state",
        )
        task: TaskRequest = state["task"]
        budget_values = {
            "max_llm_calls": task.max_llm_calls,
            "max_total_tokens": task.max_total_tokens,
            "max_runtime_seconds": task.max_runtime_seconds,
            "max_patch_retries": task.max_patch_retries,
            "max_tool_calls": task.max_tool_calls,
        }
        try:
            baseline_report = deps.test_runner.run(task, patch=None)
        except RepoPilotError as exc:
            end = _trace_event(
                deps,
                state,
                event_type="test",
                actor="test_runner",
                action="run_baseline_tests",
                status="failed",
                message=str(exc),
                details={"error_code": exc.code.value},
            )
            return {
                **_failure_state(str(exc), failure_type="tool_failure"),
                "baseline_test_report": None,
                "retry_counts": RetryCounters(),
                "budget": budget_values,
                "execution_trace": [start, end],
            }

        end = _trace_event(
            deps,
            state,
            event_type="test",
            actor="test_runner",
            action="run_baseline_tests",
            status="succeeded",
            message="baseline test report recorded",
            details={"test_status": baseline_report.status},
        )
        return {
            "status": "running",
            "current_action": "search",
            "baseline_test_report": baseline_report,
            "retry_counts": RetryCounters(),
            "budget": BudgetState(**budget_values),
            "evidence": [],
            "memory_hits": [],
            "execution_trace": [start, end],
        }

    return node


def _agent_node(
    deps: RuntimeDependencies,
    *,
    agent_name: str,
    output_field: str,
    next_action: str,
    event_type: str = "agent",
):
    def node(state: RepoPilotState) -> dict:
        agent = deps.agents[agent_name]
        start = _trace_event(
            deps,
            state,
            event_type=event_type,
            actor=agent_name,
            action=agent_name,
            status="started",
            message=f"{agent_name} started",
        )
        try:
            result = agent.run(dict(state))
        except RepoPilotError as exc:
            end = _trace_event(
                deps,
                state,
                event_type=event_type,
                actor=agent_name,
                action=agent_name,
                status="failed",
                message=str(exc),
                details={"error_code": exc.code.value},
            )
            return {
                **_failure_state(str(exc), failure_type="tool_failure"),
                "execution_trace": [start, end],
            }

        updates: dict = {
            output_field: result,
            "status": "running",
            "current_action": next_action,
            "execution_trace": [
                start,
                _trace_event(
                    deps,
                    state,
                    event_type=event_type,
                    actor=agent_name,
                    action=agent_name,
                    status="succeeded",
                    message=f"{agent_name} output validated",
                    details={"output_type": type(result).__name__},
                ),
            ],
        }
        if output_field == "evidence":
            updates["evidence"] = result.evidence
        return updates

    return node


def _review_node(deps: RuntimeDependencies):
    def node(state: RepoPilotState) -> dict:
        agent = deps.agents["review"]
        start = _trace_event(
            deps,
            state,
            event_type="review",
            actor="review",
            action="review",
            status="started",
            message="review started",
        )
        try:
            review: ReviewResult = agent.run(dict(state))
        except RepoPilotError as exc:
            end = _trace_event(
                deps,
                state,
                event_type="review",
                actor="review",
                action="review",
                status="failed",
                message=str(exc),
                details={"error_code": exc.code.value},
            )
            return {
                **_failure_state(str(exc), failure_type="tool_failure"),
                "execution_trace": [start, end],
            }

        retry_counts = state.get("retry_counts") or RetryCounters()
        budget = state.get("budget")
        values = retry_counts.model_dump()
        status = "running"
        failure_type = review.failure_type
        last_error = None
        if budget is not None:
            if review.next_action == "re_patch":
                if retry_counts.patch_retries < budget.max_patch_retries:
                    values["patch_retries"] += 1
                else:
                    status = "budget_exceeded"
                    failure_type = "budget_exceeded"
                    last_error = "patch retry budget exhausted"
            elif review.next_action in {"re_search", "re_diagnose"}:
                if retry_counts.replans < budget.max_replans:
                    values["replans"] += 1
                else:
                    status = "budget_exceeded"
                    failure_type = "budget_exceeded"
                    last_error = "replan budget exhausted"

        current_action = {
            "finish": "finish",
            "re_search": "search",
            "re_diagnose": "diagnose",
            "re_patch": "patch",
            "fix_environment": "test",
            "human_review": "review",
        }[review.next_action]

        end = _trace_event(
            deps,
            state,
            event_type="review",
            actor="review",
            action="review",
            status="succeeded",
            message="review output validated",
            details={
                "approved": review.approved,
                "next_action": review.next_action,
                "failure_type": review.failure_type,
            },
        )
        return {
            "review_result": review,
            "retry_counts": RetryCounters.model_validate(values),
            "failure_type": failure_type,
            "last_error": last_error,
            "status": status,
            "current_action": current_action,
            "execution_trace": [start, end],
        }

    return node


def _report_node(deps: RuntimeDependencies):
    def node(state: RepoPilotState) -> dict:
        start = _trace_event(
            deps,
            state,
            event_type="task",
            actor="report",
            action="report",
            status="started",
            message="building final report",
        )
        review = state.get("review_result")
        test_report = state.get("test_report")
        patch = state.get("patch_result")
        evidence = state.get("evidence", [])
        final_status = "succeeded" if review is not None and review.approved else "failed"
        summary = (
            "patch approved by review"
            if final_status == "succeeded"
            else "task finished without approval"
        )
        report = FinalReport(
            task_id=state["task"].task_id,
            status=final_status,
            summary=summary,
            review_approved=bool(review and review.approved),
            test_status=test_report.status if test_report else None,
            modified_files=patch.modified_files if patch else [],
            evidence_ids=[item.evidence_id for item in evidence],
            failure_type=review.failure_type if review else state.get("failure_type"),
            trace_count=len(state.get("execution_trace", [])) + 2,
        )
        end = _trace_event(
            deps,
            state,
            event_type="task",
            actor="report",
            action="report",
            status="succeeded",
            message="final report built",
            details={"final_status": final_status},
        )
        return {
            "report": report,
            "status": final_status,
            "current_action": "finish",
            "execution_trace": [start, end],
        }

    return node


def _route_or_report(next_node: str):
    def route(state: RepoPilotState) -> str:
        return "report" if state.get("status") in {"failed", "budget_exceeded"} else next_node

    return route


def route_after_review(state: RepoPilotState) -> str:
    if state.get("status") in {"failed", "budget_exceeded"}:
        return "report"
    review = state.get("review_result")
    if review is None:
        return "report"
    if review.approved:
        return "report"

    retry_counts = state.get("retry_counts") or RetryCounters()
    budget = state.get("budget")
    if budget is None:
        return "report"

    patch_failures: set[FailureType] = {"patch_error", "regression"}
    replan_failures: set[FailureType] = {"missing_context", "wrong_root_cause"}
    if (
        review.next_action == "re_patch"
        and review.failure_type in patch_failures
        and retry_counts.patch_retries <= budget.max_patch_retries
    ):
        return "coding"
    if (
        review.next_action in {"re_search", "re_diagnose"}
        and review.failure_type in replan_failures
        and retry_counts.replans <= budget.max_replans
    ):
        return "planner"
    return "report"


def build_graph(
    deps: RuntimeDependencies,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
):
    builder = StateGraph(RepoPilotState)
    builder.add_node("initialize", _initialize_node(deps))
    builder.add_node("planner", _agent_node(deps, agent_name="planner", output_field="plan", next_action="search"))
    builder.add_node("research", _agent_node(deps, agent_name="research", output_field="evidence", next_action="diagnose"))
    builder.add_node("diagnosis", _agent_node(deps, agent_name="diagnosis", output_field="diagnosis", next_action="patch"))
    builder.add_node("coding", _agent_node(deps, agent_name="coding", output_field="patch_result", next_action="test"))
    builder.add_node("test", _test_node(deps))
    builder.add_node("review", _review_node(deps))
    builder.add_node("report", _report_node(deps))

    builder.add_edge(START, "initialize")
    builder.add_conditional_edges("initialize", _route_or_report("planner"), {"planner": "planner", "report": "report"})
    builder.add_conditional_edges("planner", _route_or_report("research"), {"research": "research", "report": "report"})
    builder.add_conditional_edges("research", _route_or_report("diagnosis"), {"diagnosis": "diagnosis", "report": "report"})
    builder.add_conditional_edges("diagnosis", _route_or_report("coding"), {"coding": "coding", "report": "report"})
    builder.add_conditional_edges("coding", _route_or_report("test"), {"test": "test", "report": "report"})
    builder.add_conditional_edges("test", _route_or_report("review"), {"review": "review", "report": "report"})
    builder.add_conditional_edges("review", route_after_review, {"planner": "planner", "coding": "coding", "report": "report"})
    builder.add_edge("report", END)
    return builder.compile(checkpointer=checkpointer)


def _test_node(deps: RuntimeDependencies):
    def node(state: RepoPilotState) -> dict:
        start = _trace_event(
            deps,
            state,
            event_type="test",
            actor="test_runner",
            action="run_tests",
            status="started",
            message="post-patch tests started",
        )
        try:
            report: TestReport = deps.test_runner.run(
                state["task"],
                patch=state.get("patch_result"),
            )
        except RepoPilotError as exc:
            end = _trace_event(
                deps,
                state,
                event_type="test",
                actor="test_runner",
                action="run_tests",
                status="failed",
                message=str(exc),
                details={"error_code": exc.code.value},
            )
            return {
                **_failure_state(str(exc), failure_type="tool_failure"),
                "execution_trace": [start, end],
            }

        end = _trace_event(
            deps,
            state,
            event_type="test",
            actor="test_runner",
            action="run_tests",
            status="succeeded",
            message="post-patch test report recorded",
            details={"test_status": report.status, "return_code": report.return_code},
        )
        return {
            "test_report": report,
            "status": "running",
            "current_action": "review",
            "execution_trace": [start, end],
        }

    return node
