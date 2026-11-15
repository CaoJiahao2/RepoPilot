"""Structured Planner output with deterministic adaptive policy decisions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel

from repopilot.agents.base import BaseAgent
from repopilot.core.errors import RepoPilotError
from repopilot.core.schemas import BudgetState, TaskPlan
from repopilot.llm import LLMClient
from repopilot.planning.features import extract_complexity_features, summarize_input
from repopilot.planning.models import (
    PlanningCost,
    PlanningDecision,
    PlanningExecutionResult,
    PlanningRecord,
)
from repopilot.planning.policy import PlanningPolicy


class StructuredPlannerAgent(BaseAgent[TaskPlan]):
    output_model = TaskPlan

    def build_prompt(self, state: Mapping[str, Any]) -> str:
        task = state["task"]
        evidence = list(state.get("evidence", []))
        memory_hits = list(state.get("memory_hits", []))
        return (
            "Create a bounded repair plan with one next action. "
            f"Task: {task.issue}. "
            f"Stack trace present: {bool(task.stack_trace)}. "
            f"Evidence count: {len(evidence)}. "
            f"Memory hits: {len(memory_hits)}. "
            "Use only search, inspect, diagnose, patch, test, review, replan, or finish."
        )


class PlanningJournal:
    def __init__(self) -> None:
        self.records: list[PlanningRecord] = []

    def record(
        self,
        *,
        task_id: str,
        decision: PlanningDecision,
        execution_result: PlanningExecutionResult | None,
        cost: PlanningCost,
    ) -> PlanningRecord:
        record = PlanningRecord(
            record_id=f"{task_id}:plan:{len(self.records)}",
            task_id=task_id,
            timestamp=datetime.now(timezone.utc),
            decision=decision,
            execution_result=execution_result,
            cost=cost,
        )
        self.records.append(record)
        return record


class PlanningEngine:
    def __init__(
        self,
        planner_agent: StructuredPlannerAgent,
        policy: PlanningPolicy,
        *,
        journal: PlanningJournal | None = None,
    ) -> None:
        self.planner_agent = planner_agent
        self.policy = policy
        self.journal = journal or PlanningJournal()

    def decide(
        self,
        state: Mapping[str, Any],
        *,
        invalid_plan_count: int = 0,
        execution_result: PlanningExecutionResult | None = None,
        reflection=None,
    ) -> PlanningDecision:
        features = extract_complexity_features(
            state,
            invalid_plan_count=invalid_plan_count,
        )
        summary = summarize_input(state, features)
        budget_before = state.get("budget") or BudgetState()
        usage_before = self._usage_snapshot()
        plan: TaskPlan | None = None
        plan_valid = False
        validation_error: str | None = None
        llm_call_made = False

        if not features.budget_exhausted:
            llm_call_made = True
            try:
                candidate = self.planner_agent.run(dict(state))
                if not isinstance(candidate, TaskPlan):
                    raise TypeError("planner output was not a TaskPlan")
                plan = candidate
                plan_valid = True
            except RepoPilotError as exc:
                messages = exc.details.get("errors", [])
                detail_messages = [
                    item.get("message", "")
                    for item in messages
                    if isinstance(item, dict) and item.get("message")
                ]
                validation_error = str(exc)
                if detail_messages:
                    validation_error = f"{validation_error}: {'; '.join(detail_messages)}"
            except Exception as exc:
                validation_error = f"{type(exc).__name__}: {exc}"

        reflection_result = getattr(reflection, "result", reflection) if reflection is not None else None
        effective = self.policy.decide(
            state,
            features=features,
            plan=plan,
            execution_result=execution_result,
            reflection=reflection_result,
        )
        budget_after = self._budget_after(
            budget_before,
            llm_call_made=llm_call_made,
        )
        usage_after = self._usage_snapshot()
        decision = PlanningDecision(
            policy_name=self.policy.name,
            plan=plan,
            plan_valid=plan_valid,
            validation_error=validation_error,
            requested_action=plan.next_action if plan else None,
            effective_action=effective.action,
            rationale=effective.rationale,
            input_summary=summary,
            complexity=features,
            budget_before=budget_before,
            budget_after=budget_after,
            invalid_plan_count=invalid_plan_count + (0 if plan_valid or not llm_call_made else 1),
            reflection_feedback=reflection_result.to_planner_feedback()
            if reflection_result is not None and hasattr(reflection_result, "to_planner_feedback")
            else None,
        )
        cost = self._cost(
            usage_before,
            usage_after,
            state=state,
            execution_result=execution_result,
        )
        self.journal.record(
            task_id=state["task"].task_id,
            decision=decision,
            execution_result=execution_result,
            cost=cost,
        )
        return decision

    @staticmethod
    def _budget_after(
        budget: BudgetState,
        *,
        llm_call_made: bool,
    ) -> BudgetState:
        values = budget.model_dump()
        if llm_call_made:
            values["llm_calls_used"] += 1
        return BudgetState.model_validate(values)

    def _usage_snapshot(self) -> dict[str, Any]:
        usage_method = getattr(self.planner_agent.llm, "usage", None)
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

    def _cost(
        self,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        *,
        state: Mapping[str, Any],
        execution_result: PlanningExecutionResult | None,
    ) -> PlanningCost:
        source = after.get("source", "unavailable")
        return PlanningCost(
            llm_calls=max(0, after.get("calls", 0) - before.get("calls", 0)),
            input_tokens=self._delta_tokens(before.get("input_tokens"), after.get("input_tokens")),
            output_tokens=self._delta_tokens(before.get("output_tokens"), after.get("output_tokens")),
            tool_calls=len(state.get("tool_results", [])),
            runtime_seconds=execution_result.duration_seconds if execution_result else 0,
            estimated_cost_usd=after.get("cost_usd"),
            cost_status=source if source in {"actual", "fake"} else "unavailable",
        )

    @staticmethod
    def _delta_tokens(before: Any, after: Any) -> int | None:
        if isinstance(before, int) and isinstance(after, int):
            return max(0, after - before)
        return None
