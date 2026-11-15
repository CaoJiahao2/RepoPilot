"""Deterministic rule-constrained adaptive and static planning policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from repopilot.core.schemas import Action, TaskPlan
from repopilot.planning.models import ComplexityFeatures, PlanningExecutionResult


@dataclass(frozen=True)
class PolicyDecision:
    action: Action
    rationale: str


class PlanningPolicy(Protocol):
    name: str

    def decide(
        self,
        state: Mapping[str, Any],
        *,
        features: ComplexityFeatures,
        plan: TaskPlan | None,
        execution_result: PlanningExecutionResult | None = None,
        reflection: Any = None,
    ) -> PolicyDecision:
        ...


class AdaptivePlanningPolicy:
    name = "adaptive_rules"
    failure_test_statuses = {"assertion_failed", "collection_error", "dependency_error", "timeout", "execution_error"}

    def __init__(self, *, max_invalid_plan_replans: int = 2) -> None:
        self.max_invalid_plan_replans = max_invalid_plan_replans

    def decide(
        self,
        state: Mapping[str, Any],
        *,
        features: ComplexityFeatures,
        plan: TaskPlan | None,
        execution_result: PlanningExecutionResult | None = None,
        reflection: Any = None,
    ) -> PolicyDecision:
        if state.get("current_action") == "finish" or state.get("report") is not None:
            return PolicyDecision("finish", "task is already finished")
        if features.budget_exhausted:
            return PolicyDecision("finish", "budget is exhausted")
        if features.invalid_plan_count > self.max_invalid_plan_replans:
            return PolicyDecision("finish", "invalid planning attempts exceeded the limit")
        if reflection is not None:
            action = getattr(reflection, "recommended_action", None)
            if action is not None:
                return PolicyDecision(action, getattr(reflection, "root_cause_hypothesis", "reflection feedback"))

        latest_test = state.get("test_report") or state.get("baseline_test_report")
        if latest_test is not None and latest_test.status in self.failure_test_statuses:
            if state.get("diagnosis") is not None:
                return PolicyDecision("replan", "latest test feedback requires replanning")
        if execution_result is not None and not execution_result.success:
            return PolicyDecision(
                "replan",
                f"execution feedback failed at {execution_result.action}",
            )
        if features.evidence_completeness < 0.5 or features.stack_localization_score < 0.5:
            return PolicyDecision("search", "evidence is insufficient for a reliable diagnosis")
        if state.get("diagnosis") is None:
            return PolicyDecision("diagnose", "evidence is sufficient and diagnosis is missing")
        if state.get("patch_result") is None:
            return PolicyDecision("patch", "diagnosis is sufficient and patch is missing")
        if state.get("test_report") is None:
            return PolicyDecision("test", "patch exists and post-patch test is missing")
        if state["test_report"].status != "passed":
            return PolicyDecision("replan", "post-patch test did not pass")
        if state.get("review_result") is None:
            return PolicyDecision("review", "tests passed and review is missing")
        return PolicyDecision("finish", "review is complete")


class StaticPlanningPolicy:
    name = "static_workflow"

    def decide(
        self,
        state: Mapping[str, Any],
        *,
        features: ComplexityFeatures,
        plan: TaskPlan | None,
        execution_result: PlanningExecutionResult | None = None,
        reflection: Any = None,
    ) -> PolicyDecision:
        if state.get("current_action") == "finish":
            return PolicyDecision("finish", "static workflow is complete")
        if not state.get("evidence"):
            return PolicyDecision("search", "static workflow always searches first")
        if state.get("diagnosis") is None:
            return PolicyDecision("diagnose", "static workflow diagnoses after research")
        if state.get("patch_result") is None:
            return PolicyDecision("patch", "static workflow patches after diagnosis")
        if state.get("test_report") is None:
            return PolicyDecision("test", "static workflow tests after patching")
        if state.get("review_result") is None:
            return PolicyDecision("review", "static workflow reviews after tests")
        return PolicyDecision("finish", "static workflow is complete")
