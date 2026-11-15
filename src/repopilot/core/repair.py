"""End-to-end repair pipeline joining validated agents, worktrees, patches, and tests."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from langgraph.graph import END, START, StateGraph

from repopilot.agents.base import Agent
from repopilot.core.errors import RepoPilotError
from repopilot.core.schemas import (
    Diagnosis,
    EndToEndReport,
    Evidence,
    PatchResult,
    ResearchResult,
    RunCost,
    TaskPlan,
    TaskRequest,
    TaskValidationResult,
    TestReport,
    TraceEvent,
    ReviewResult,
    WorkspaceRecord,
)
from repopilot.core.state import RepoPilotState
from repopilot.llm import LLMClient, LLMUsage
from repopilot.sandbox.worktree import GitWorktreeManager, WorktreeSession
from repopilot.tools.patch import PatchExecutor
from repopilot.tools.tests import TestRunner

_REQUIRED_AGENTS = ("planner", "research", "diagnosis", "coding", "review")


@dataclass(frozen=True)
class RepairDependencies:
    llm: LLMClient
    test_runner: TestRunner
    worktree_manager: GitWorktreeManager
    patch_executor: PatchExecutor
    agents: Mapping[str, Agent]
    workspace_root: Path | None = None
    execution_mode: str = "real"
    clock: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        missing = sorted(set(_REQUIRED_AGENTS) - set(self.agents))
        if missing:
            raise ValueError(f"missing repair agents: {missing}")


@dataclass
class _RunContext:
    session: WorktreeSession | None = None


def _now(deps: RepairDependencies) -> datetime:
    value = deps.clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("repair clock must return timezone-aware datetimes")
    return value


def _trace(
    deps: RepairDependencies,
    state: Mapping[str, Any],
    *,
    event_type: str,
    actor: str,
    action: str,
    status: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> TraceEvent:
    task_id = state["task"].task_id
    existing = state.get("execution_trace", [])
    return TraceEvent(
        event_id=f"{task_id}:{event_type}:{action}:{len(existing)}",
        task_id=task_id,
        timestamp=_now(deps),
        event_type=event_type,  # type: ignore[arg-type]
        actor=actor,
        action=action,
        status=status,  # type: ignore[arg-type]
        message=message,
        details=dict(details or {}),
    )


def _failure(
    *,
    node: str,
    reason: str,
    failure_type: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_node": node,
        "failure_reason": reason,
        "failure_type": failure_type,
        "last_error": reason,
    }


def _cost(deps: RepairDependencies) -> RunCost:
    usage_method = getattr(deps.llm, "usage", None)
    if not callable(usage_method):
        return RunCost(cost_status="unavailable")
    usage: LLMUsage = usage_method()
    return RunCost(
        llm_calls=usage.calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        estimated_cost_usd=usage.estimated_cost_usd,
        cost_status=usage.source if usage.source in {"actual", "fake"} else "unavailable",
    )


def _route_or_report(next_node: str):
    def route(state: RepoPilotState) -> str:
        return "report" if state.get("status") == "failed" else next_node

    return route


def build_repair_graph(
    deps: RepairDependencies,
    *,
    run_context: _RunContext,
    workspace_root: Path,
):
    builder = StateGraph(RepoPilotState)

    def validate_task(state: RepoPilotState) -> dict[str, Any]:
        start = _trace(
            deps,
            state,
            event_type="task",
            actor="runtime",
            action="validate_task",
            status="started",
            message="validating task request",
        )
        task = state["task"]
        errors: list[str] = []
        if not task.test_command:
            errors.append("test_command is required")
        if not task.issue.strip():
            errors.append("issue is required")
        end = _trace(
            deps,
            state,
            event_type="task",
            actor="runtime",
            action="validate_task",
            status="failed" if errors else "succeeded",
            message="task validation failed" if errors else "task request validated",
            details={"error_count": len(errors)},
        )
        if errors:
            return {
                **_failure(node="validate_task", reason="; ".join(errors)),
                "task_validation": TaskValidationResult(
                    task_id=task.task_id,
                    valid=False,
                    errors=errors,
                ),
                "execution_trace": [start, end],
            }
        return {
            "status": "running",
            "current_action": "search",
            "task_validation": TaskValidationResult(
                task_id=task.task_id,
                valid=True,
            ),
            "execution_trace": [start, end],
        }

    def prepare_workspace(state: RepoPilotState) -> dict[str, Any]:
        start = _trace(
            deps,
            state,
            event_type="task",
            actor="workspace",
            action="prepare_workspace",
            status="started",
            message="creating isolated Git Worktree",
        )
        task = state["task"]
        try:
            source = Path(task.repo_path).expanduser().resolve(strict=True)
            session = deps.worktree_manager.create(source, workspace_root / "worktree")
        except RepoPilotError as exc:
            end = _trace(
                deps,
                state,
                event_type="task",
                actor="workspace",
                action="prepare_workspace",
                status="failed",
                message=str(exc),
                details={"error_code": exc.code.value},
            )
            return {
                **_failure(node="prepare_workspace", reason=str(exc)),
                "execution_trace": [start, end],
            }

        run_context.session = session
        workspace = WorkspaceRecord(
            source_repo=str(session.source_repo),
            worktree_path=str(session.path),
            base_commit=session.base_commit,
            initial_status=session.initial_status,
        )
        end = _trace(
            deps,
            state,
            event_type="task",
            actor="workspace",
            action="prepare_workspace",
            status="succeeded",
            message="isolated worktree prepared",
            details={"base_commit": session.base_commit},
        )
        return {
            "status": "running",
            "current_action": "search",
            "workspace": workspace,
            "execution_trace": [start, end],
        }

    def agent_node(
        *,
        agent_name: str,
        output_field: str,
        next_action: str,
        event_type: str = "agent",
        validate_result: Callable[[dict[str, Any], Any], None] | None = None,
    ):
        def node(state: RepoPilotState) -> dict[str, Any]:
            agent = deps.agents[agent_name]
            start = _trace(
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
                if validate_result is not None:
                    validate_result(dict(state), result)
            except RepoPilotError as exc:
                end = _trace(
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
                    **_failure(
                        node=agent_name,
                        reason=str(exc),
                        failure_type="tool_failure",
                    ),
                    "execution_trace": [start, end],
                }
            except Exception as exc:
                end = _trace(
                    deps,
                    state,
                    event_type=event_type,
                    actor=agent_name,
                    action=agent_name,
                    status="failed",
                    message=f"{type(exc).__name__}: {exc}",
                )
                return {
                    **_failure(
                        node=agent_name,
                        reason=f"{type(exc).__name__}: {exc}",
                        failure_type="tool_failure",
                    ),
                    "execution_trace": [start, end],
                }

            updates: dict[str, Any] = {
                output_field: result,
                "status": "running",
                "current_action": next_action,
                "execution_trace": [
                    start,
                    _trace(
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

    def validate_diagnosis(state: dict[str, Any], result: Diagnosis) -> None:
        known_ids = {item.evidence_id for item in state.get("evidence", [])}
        missing = sorted(set(result.evidence_ids) - known_ids)
        if missing:
            raise ValueError(f"diagnosis references unknown evidence IDs: {missing}")

    def baseline_test(state: RepoPilotState) -> dict[str, Any]:
        start = _trace(
            deps,
            state,
            event_type="test",
            actor="test_runner",
            action="baseline_test",
            status="started",
            message="running baseline tests",
        )
        session = run_context.session
        if session is None:
            reason = "workspace session is unavailable"
            return {
                **_failure(node="baseline_test", reason=reason),
                "execution_trace": [start],
            }
        try:
            report = deps.test_runner.run(
                state["task"],
                patch=None,
                worktree_path=session.path,
            )
        except Exception as exc:
            end = _trace(
                deps,
                state,
                event_type="test",
                actor="test_runner",
                action="baseline_test",
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
            return {
                **_failure(
                    node="baseline_test",
                    reason=f"{type(exc).__name__}: {exc}",
                    failure_type="tool_failure",
                ),
                "execution_trace": [start, end],
            }

        if report.status in {"collection_error", "dependency_error", "timeout", "execution_error"}:
            end = _trace(
                deps,
                state,
                event_type="test",
                actor="test_runner",
                action="baseline_test",
                status="failed",
                message=f"baseline test status: {report.status}",
                details={"return_code": report.return_code},
            )
            return {
                **_failure(
                    node="baseline_test",
                    reason=f"baseline test status: {report.status}",
                    failure_type="tool_failure",
                ),
                "baseline_test_report": report,
                "execution_trace": [start, end],
            }

        end = _trace(
            deps,
            state,
            event_type="test",
            actor="test_runner",
            action="baseline_test",
            status="succeeded",
            message="baseline test report recorded",
            details={"test_status": report.status},
        )
        return {
            "status": "running",
            "current_action": "patch",
            "baseline_test_report": report,
            "execution_trace": [start, end],
        }

    def validate_diff(state: RepoPilotState) -> dict[str, Any]:
        start = _trace(
            deps,
            state,
            event_type="tool",
            actor="patch_validator",
            action="validate_diff",
            status="started",
            message="validating Unified Diff",
        )
        patch = state.get("patch_result")
        if patch is None:
            reason = "coding did not produce a patch"
            return {
                **_failure(node="validate_diff", reason=reason),
                "execution_trace": [start],
            }
        try:
            validation = deps.patch_executor.validator.validate(
                patch,
                deps.patch_executor.policy,
            )
        except RepoPilotError as exc:
            end = _trace(
                deps,
                state,
                event_type="tool",
                actor="patch_validator",
                action="validate_diff",
                status="failed",
                message=str(exc),
                details={"error_code": exc.code.value},
            )
            return {
                **_failure(
                    node="validate_diff",
                    reason=str(exc),
                    failure_type="patch_error",
                ),
                "execution_trace": [start, end],
            }

        end = _trace(
            deps,
            state,
            event_type="tool",
            actor="patch_validator",
            action="validate_diff",
            status="succeeded",
            message="Unified Diff validated",
            details={"modified_files": len(validation.modified_files)},
        )
        return {
            "status": "running",
            "current_action": "test",
            "patch_validation": validation,
            "execution_trace": [start, end],
        }

    def apply_patch(state: RepoPilotState) -> dict[str, Any]:
        start = _trace(
            deps,
            state,
            event_type="tool",
            actor="patch_executor",
            action="apply_patch",
            status="started",
            message="applying patch to isolated worktree",
        )
        session = run_context.session
        patch = state.get("patch_result")
        if session is None or patch is None:
            reason = "patch or workspace session is unavailable"
            return {
                **_failure(node="apply_patch", reason=reason),
                "execution_trace": [start],
            }
        try:
            record = deps.patch_executor.apply(session, patch)
        except RepoPilotError as exc:
            end = _trace(
                deps,
                state,
                event_type="tool",
                actor="patch_executor",
                action="apply_patch",
                status="failed",
                message=str(exc),
                details={"error_code": exc.code.value},
            )
            return {
                **_failure(
                    node="apply_patch",
                    reason=str(exc),
                    failure_type="patch_error",
                ),
                "execution_trace": [start, end],
            }

        if not record.patch_applied:
            end = _trace(
                deps,
                state,
                event_type="tool",
                actor="patch_executor",
                action="apply_patch",
                status="failed",
                message=record.error_message or "patch failed",
                details={"error_code": record.error_code},
            )
            return {
                **_failure(
                    node="apply_patch",
                    reason=record.error_message or "patch failed",
                    failure_type="patch_error",
                ),
                "patch_application": record,
                "execution_trace": [start, end],
            }

        end = _trace(
            deps,
            state,
            event_type="tool",
            actor="patch_executor",
            action="apply_patch",
            status="succeeded",
            message="patch applied",
            details={"modified_files": len(record.validation.modified_files)},
        )
        return {
            "status": "running",
            "current_action": "test",
            "patch_application": record,
            "execution_trace": [start, end],
        }

    def post_patch_test(state: RepoPilotState) -> dict[str, Any]:
        start = _trace(
            deps,
            state,
            event_type="test",
            actor="test_runner",
            action="post_patch_test",
            status="started",
            message="running post-patch tests",
        )
        session = run_context.session
        if session is None:
            return {
                **_failure(node="post_patch_test", reason="workspace session is unavailable"),
                "execution_trace": [start],
            }
        try:
            report = deps.test_runner.run(
                state["task"],
                patch=state.get("patch_result"),
                worktree_path=session.path,
            )
        except Exception as exc:
            end = _trace(
                deps,
                state,
                event_type="test",
                actor="test_runner",
                action="post_patch_test",
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
            return {
                **_failure(
                    node="post_patch_test",
                    reason=f"{type(exc).__name__}: {exc}",
                    failure_type="tool_failure",
                ),
                "execution_trace": [start, end],
            }

        if report.status != "passed":
            end = _trace(
                deps,
                state,
                event_type="test",
                actor="test_runner",
                action="post_patch_test",
                status="failed",
                message=f"post-patch test status: {report.status}",
                details={"return_code": report.return_code},
            )
            return {
                **_failure(
                    node="post_patch_test",
                    reason=f"post-patch test status: {report.status}",
                    failure_type="regression" if report.status == "assertion_failed" else "tool_failure",
                ),
                "test_report": report,
                "execution_trace": [start, end],
            }

        end = _trace(
            deps,
            state,
            event_type="test",
            actor="test_runner",
            action="post_patch_test",
            status="succeeded",
            message="post-patch tests passed",
            details={"return_code": report.return_code},
        )
        return {
            "status": "running",
            "current_action": "review",
            "test_report": report,
            "execution_trace": [start, end],
        }

    def review(state: RepoPilotState) -> dict[str, Any]:
        start = _trace(
            deps,
            state,
            event_type="review",
            actor="review",
            action="review",
            status="started",
            message="reviewing diagnosis, diff, and tests",
        )
        try:
            result: ReviewResult = deps.agents["review"].run(dict(state))
            evidence_ids = {item.evidence_id for item in state.get("evidence", [])}
            if not result.approved:
                raise ValueError(result.feedback)
            if state.get("test_report") is None or state["test_report"].status != "passed":
                raise ValueError("review cannot approve without passed post-patch tests")
            if state.get("patch_application") is None or not state["patch_application"].patch_applied:
                raise ValueError("review cannot approve without an applied patch")
            if state.get("diagnosis") is None or not state["diagnosis"].evidence_ids:
                raise ValueError("review cannot approve without evidence-backed diagnosis")
            unknown = sorted(set(result.evidence) - evidence_ids)
            if unknown:
                raise ValueError(f"review references unknown evidence IDs: {unknown}")
        except Exception as exc:
            end = _trace(
                deps,
                state,
                event_type="review",
                actor="review",
                action="review",
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
            return {
                **_failure(
                    node="review",
                    reason=f"{type(exc).__name__}: {exc}",
                    failure_type="wrong_root_cause",
                ),
                "review_result": result if "result" in locals() else None,
                "execution_trace": [start, end],
            }

        end = _trace(
            deps,
            state,
            event_type="review",
            actor="review",
            action="review",
            status="succeeded",
            message="review approved the repair",
        )
        return {
            "status": "running",
            "current_action": "finish",
            "review_result": result,
            "execution_trace": [start, end],
        }

    def report(state: RepoPilotState) -> dict[str, Any]:
        start = _trace(
            deps,
            state,
            event_type="task",
            actor="report",
            action="report",
            status="started",
            message="building end-to-end repair report",
        )
        workspace = state.get("workspace")
        patch_application = state.get("patch_application")
        patch = state.get("patch_result")
        diagnosis = state.get("diagnosis")
        review_result = state.get("review_result")
        success = (
            state.get("status") != "failed"
            and review_result is not None
            and review_result.approved
            and state.get("test_report") is not None
            and state["test_report"].status == "passed"
        )
        end = _trace(
            deps,
            state,
            event_type="task",
            actor="report",
            action="report",
            status="succeeded",
            message="end-to-end report built",
            details={"status": "succeeded" if success else "failed"},
        )
        full_trace = [*state.get("execution_trace", []), start, end]
        summary = (
            "patch applied and post-patch tests passed"
            if success
            else f"repair failed at {state.get('failure_node') or 'unknown'}: "
            f"{state.get('failure_reason') or 'no approval'}"
        )
        final_report = EndToEndReport(
            task_id=state["task"].task_id,
            status="succeeded" if success else "failed",
            summary=summary,
            plan=state.get("plan"),
            root_cause=diagnosis.root_cause if diagnosis else None,
            evidence=state.get("evidence", []),
            modified_files=patch.modified_files if patch else [],
            unified_diff=patch.unified_diff if patch else None,
            baseline_test_report=state.get("baseline_test_report"),
            post_patch_test_report=state.get("test_report"),
            review_result=review_result,
            reflection_result=state.get("reflection_result"),
            failure_node=state.get("failure_node"),
            failure_reason=state.get("failure_reason"),
            base_commit=workspace.base_commit if workspace else None,
            initial_git_status=workspace.initial_status if workspace else "",
            git_diff_before=patch_application.diff_before if patch_application else "",
            git_diff_after=patch_application.diff_after if patch_application else "",
            cost=_cost(deps),
            execution_mode=deps.execution_mode,  # type: ignore[arg-type]
            execution_trace=full_trace,
        )
        return {
            "status": final_report.status,
            "current_action": "finish",
            "repair_report": final_report,
            "execution_trace": [start, end],
        }

    builder.add_node("validate_task", validate_task)
    builder.add_node("prepare_workspace", prepare_workspace)
    builder.add_node("planner", agent_node(agent_name="planner", output_field="plan", next_action="search"))
    builder.add_node("research", agent_node(agent_name="research", output_field="evidence", next_action="diagnose"))
    builder.add_node(
        "diagnosis",
        agent_node(
            agent_name="diagnosis",
            output_field="diagnosis",
            next_action="patch",
            validate_result=validate_diagnosis,
        ),
    )
    builder.add_node("baseline_test", baseline_test)
    builder.add_node("coding", agent_node(agent_name="coding", output_field="patch_result", next_action="test"))
    builder.add_node("validate_diff", validate_diff)
    builder.add_node("apply_patch", apply_patch)
    builder.add_node("post_patch_test", post_patch_test)
    builder.add_node("review", review)
    builder.add_node("report", report)

    builder.add_edge(START, "validate_task")
    builder.add_conditional_edges("validate_task", _route_or_report("prepare_workspace"), {"prepare_workspace": "prepare_workspace", "report": "report"})
    builder.add_conditional_edges("prepare_workspace", _route_or_report("planner"), {"planner": "planner", "report": "report"})
    builder.add_conditional_edges("planner", _route_or_report("research"), {"research": "research", "report": "report"})
    builder.add_conditional_edges("research", _route_or_report("diagnosis"), {"diagnosis": "diagnosis", "report": "report"})
    builder.add_conditional_edges("diagnosis", _route_or_report("baseline_test"), {"baseline_test": "baseline_test", "report": "report"})
    builder.add_conditional_edges("baseline_test", _route_or_report("coding"), {"coding": "coding", "report": "report"})
    builder.add_conditional_edges("coding", _route_or_report("validate_diff"), {"validate_diff": "validate_diff", "report": "report"})
    builder.add_conditional_edges("validate_diff", _route_or_report("apply_patch"), {"apply_patch": "apply_patch", "report": "report"})
    builder.add_conditional_edges("apply_patch", _route_or_report("post_patch_test"), {"post_patch_test": "post_patch_test", "report": "report"})
    builder.add_conditional_edges("post_patch_test", _route_or_report("review"), {"review": "review", "report": "report"})
    builder.add_conditional_edges("review", _route_or_report("report"), {"report": "report"})
    builder.add_edge("report", END)
    return builder.compile()


class RepairPipeline:
    def __init__(self, deps: RepairDependencies) -> None:
        self.deps = deps

    def _usage_snapshot(self) -> dict[str, Any]:
        usage_method = getattr(self.deps.llm, "usage", None)
        if not callable(usage_method):
            return {}
        usage = usage_method()
        return {
            "calls": usage.calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": usage.estimated_cost_usd,
            "source": usage.source,
        }

    @staticmethod
    def _usage_cost(before: Mapping[str, Any], after: Mapping[str, Any]) -> RunCost:
        source = after.get("source", "unavailable")
        after_input = after.get("input_tokens")
        before_input = before.get("input_tokens")
        after_output = after.get("output_tokens")
        before_output = before.get("output_tokens")
        input_tokens = (
            max(0, after_input - (before_input or 0))
            if isinstance(after_input, int)
            else None
        )
        output_tokens = (
            max(0, after_output - (before_output or 0))
            if isinstance(after_output, int)
            else None
        )
        return RunCost(
            llm_calls=max(0, after.get("calls", 0) - before.get("calls", 0)),
            input_tokens=max(0, input_tokens) if input_tokens is not None else None,
            output_tokens=max(0, output_tokens) if output_tokens is not None else None,
            estimated_cost_usd=after.get("cost_usd"),
            cost_status=source if source in {"actual", "fake"} else "unavailable",
        )

    def run(self, task: TaskRequest, *, cleanup: bool = True) -> EndToEndReport:
        temporary_root: tempfile.TemporaryDirectory[str] | None = None
        if self.deps.workspace_root is None:
            temporary_root = tempfile.TemporaryDirectory(prefix="repopilot-repair-")
            workspace_root = Path(temporary_root.name)
        else:
            workspace_root = self.deps.workspace_root
            workspace_root.mkdir(parents=True, exist_ok=True)

        run_context = _RunContext()
        graph = build_repair_graph(
            self.deps,
            run_context=run_context,
            workspace_root=workspace_root,
        )
        usage_before = self._usage_snapshot()
        try:
            state = graph.invoke({"task": task})
            report = state.get("repair_report")
            if report is None:
                raise RuntimeError("repair graph did not produce a report")
            usage_after = self._usage_snapshot()
            return report.model_copy(
                update={"cost": self._usage_cost(usage_before, usage_after)}
            )
        finally:
            if cleanup and run_context.session is not None:
                try:
                    self.deps.worktree_manager.cleanup(run_context.session)
                except RepoPilotError:
                    pass
            if temporary_root is not None:
                temporary_root.cleanup()
