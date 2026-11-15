from datetime import datetime, timezone

import pytest

from repopilot.core.schemas import (
    BudgetState,
    Diagnosis,
    Evidence,
    PatchResult,
    PlannedStep,
    ReviewResult,
    TaskPlan,
    TaskRequest,
    TestReport as ReportModel,
)
from repopilot.llm import FakeLLM
from repopilot.planning.models import PlanningExecutionResult
from repopilot.planning.planner import PlanningEngine, StructuredPlannerAgent
from repopilot.planning.policy import AdaptivePlanningPolicy, StaticPlanningPolicy
from repopilot.reflection.reflector import ReflectionEngine

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _task() -> TaskRequest:
    return TaskRequest(
        task_id="task-plan-001",
        repo_path="./repo",
        issue="parse_config returns the wrong value for empty mappings",
        stack_trace='File "app.py", line 3, in parse_config',
    )


def _valid_plan_json() -> str:
    return TaskPlan(
        objective="repair parse_config",
        steps=[
            PlannedStep(step_id="search", action="search", description="search", expected_output="evidence"),
            PlannedStep(
                step_id="diagnose",
                action="diagnose",
                description="diagnose",
                depends_on=["search"],
                expected_output="diagnosis",
            ),
        ],
        next_action="search",
        rationale="the bug points to parse_config",
    ).model_dump_json()


def _evidence() -> Evidence:
    return Evidence(
        evidence_id="ev-001",
        source_type="source_code",
        file_path="app.py",
        line_start=1,
        line_end=4,
        symbol="parse_config",
        content="return None",
        retrieval_sources=["path", "bm25"],
    )


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        root_cause="empty mappings return None",
        affected_files=["app.py"],
        related_symbols=["parse_config"],
        evidence_ids=["ev-001"],
        confidence=0.9,
        suggested_fix="return {}",
    )


def _patch() -> PatchResult:
    return PatchResult(
        unified_diff="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
        modified_files=["app.py"],
        explanation="fix empty mapping",
    )


def _test_report(status: str = "passed") -> ReportModel:
    if status == "passed":
        return ReportModel(
            command=["pytest"],
            status="passed",
            return_code=0,
            duration_seconds=0.1,
            tests_total=1,
            tests_passed=1,
        )
    return ReportModel(
        command=["pytest"],
        status=status,
        return_code=1,
        duration_seconds=0.1,
        tests_total=1,
        tests_failed=1,
    )


def _state(**overrides):
    state = {
        "task": _task(),
        "plan": None,
        "current_action": "search",
        "evidence": [],
        "memory_hits": [],
        "diagnosis": None,
        "baseline_test_report": None,
        "patch_result": None,
        "test_report": None,
        "review_result": None,
        "budget": BudgetState(max_llm_calls=10, max_total_tokens=1000, max_tool_calls=10),
        "tool_results": [],
        "status": "running",
    }
    state.update(overrides)
    return state


def _engine(responses: dict[str, str], policy=None) -> PlanningEngine:
    llm = FakeLLM(responses)
    planner = StructuredPlannerAgent(name="planner", output_model=TaskPlan, llm=llm)
    return PlanningEngine(planner, policy or AdaptivePlanningPolicy())


def test_illegal_action_and_dag_cycle_are_rejected() -> None:
    illegal = _engine({"TaskPlan": '{"objective":"x","steps":[{"step_id":"a","action":"search","description":"x","expected_output":"x"}],"next_action":"destroy","rationale":"x"}'})
    cycle = _engine({"TaskPlan": '{"objective":"x","steps":[{"step_id":"a","action":"search","description":"x","depends_on":["b"],"expected_output":"x"},{"step_id":"b","action":"diagnose","description":"x","depends_on":["a"],"expected_output":"x"}],"next_action":"search","rationale":"x"}'})

    illegal_decision = illegal.decide(_state())
    cycle_decision = cycle.decide(_state())

    assert illegal_decision.plan_valid is False
    assert "validation" in (illegal_decision.validation_error or "").lower()
    assert cycle_decision.plan_valid is False
    assert "cycle" in (cycle_decision.validation_error or "").lower()
    assert illegal_decision.effective_action in {"search", "replan", "finish"}


def test_insufficient_evidence_routes_to_search_and_sufficient_evidence_routes_to_coding() -> None:
    engine = _engine({"TaskPlan": _valid_plan_json()})

    search_decision = engine.decide(_state())
    coding_state = _state(
        evidence=[_evidence()],
        diagnosis=_diagnosis(),
    )
    coding_decision = engine.decide(coding_state)

    assert search_decision.effective_action == "search"
    assert coding_decision.effective_action == "patch"
    assert coding_decision.requested_action == "search"
    assert coding_decision.rationale


def test_test_failure_replans_and_budget_exhaustion_finishes() -> None:
    engine = _engine({"TaskPlan": _valid_plan_json()})
    failed_state = _state(
        evidence=[_evidence()],
        diagnosis=_diagnosis(),
        patch_result=_patch(),
        test_report=_test_report("assertion_failed"),
    )
    exhausted_state = _state(
        budget=BudgetState(
            max_llm_calls=1,
            max_total_tokens=10,
            max_tool_calls=1,
            llm_calls_used=1,
        )
    )

    failed_decision = engine.decide(failed_state)
    exhausted_decision = engine.decide(exhausted_state)

    assert failed_decision.effective_action == "replan"
    assert exhausted_decision.effective_action == "finish"
    assert engine.journal.records[-1].cost.llm_calls == 0
    assert exhausted_decision.budget_after.llm_calls_used == 1


def test_finish_is_terminal_and_invalid_replanning_is_bounded() -> None:
    engine = _engine(
        {"TaskPlan": '{"objective":"x","steps":[],"next_action":"search","rationale":"x"}'},
        AdaptivePlanningPolicy(max_invalid_plan_replans=2),
    )

    finish_decision = engine.decide(_state(current_action="finish"))
    invalid_decision = engine.decide(_state(), invalid_plan_count=3)

    assert finish_decision.effective_action == "finish"
    assert invalid_decision.effective_action == "finish"
    assert invalid_decision.invalid_plan_count == 4


def test_static_workflow_is_a_stable_baseline() -> None:
    policy = StaticPlanningPolicy()
    engine = _engine({"TaskPlan": _valid_plan_json()}, policy)
    state = _state()

    first = engine.decide(state)
    state["evidence"] = [_evidence()]
    second = engine.decide(state)
    state["diagnosis"] = _diagnosis()
    third = engine.decide(state)
    state["patch_result"] = _patch()
    fourth = engine.decide(state)
    state["test_report"] = _test_report()
    fifth = engine.decide(state)
    state["review_result"] = ReviewResult(approved=True, feedback="ok", next_action="finish")
    sixth = engine.decide(state)

    assert [first.effective_action, second.effective_action, third.effective_action, fourth.effective_action, fifth.effective_action, sixth.effective_action] == [
        "search",
        "diagnose",
        "patch",
        "test",
        "review",
        "finish",
    ]


def test_planning_record_contains_input_action_rationale_result_and_cost() -> None:
    engine = _engine({"TaskPlan": _valid_plan_json()})
    result = PlanningExecutionResult(
        action="search",
        success=True,
        result_summary="found parse_config",
        duration_seconds=0.25,
    )

    decision = engine.decide(_state(), execution_result=result)
    record = engine.journal.records[-1]

    assert decision.input_summary.task_id == "task-plan-001"
    assert decision.input_summary.complexity.evidence_count == 0
    assert record.decision.effective_action == decision.effective_action
    assert record.execution_result is result
    assert record.cost.llm_calls == 1
    assert record.cost.runtime_seconds == 0.25
    assert record.cost.cost_status == "fake"


def test_structured_reflection_feedback_reaches_planner_but_cannot_bypass_budget() -> None:
    engine = _engine({"TaskPlan": _valid_plan_json()})
    reflection = ReflectionEngine().reflect(
        _state(
            patch_application={
                "patch_applied": False,
                "error_code": "patch_error",
                "error_message": "patch failed",
            }
        )
    )

    accepted = engine.decide(_state(), reflection=reflection)
    exhausted = engine.decide(
        _state(
            budget=BudgetState(
                max_llm_calls=1,
                max_total_tokens=10,
                max_tool_calls=10,
                llm_calls_used=1,
            )
        ),
        reflection=reflection,
    )

    assert accepted.effective_action == "patch"
    assert accepted.reflection_feedback is not None
    assert accepted.reflection_feedback.failure_type == "patch_error"
    assert exhausted.effective_action == "finish"
