from datetime import datetime, timezone

from repopilot.core.schemas import (
    BudgetState,
    Diagnosis,
    Evidence,
    PatchResult,
    RetryCounters,
    TaskRequest,
    TestReport as ReportModel,
    ToolResult,
)
from repopilot.reflection.classifier import FailureClassifier
from repopilot.reflection.metrics import calculate_recovery_rate
from repopilot.reflection.reflector import ReflectionEngine
from repopilot.sandbox.worktree import WorktreeSession
from repopilot.tools.patch import PatchApplicationRecord, PatchValidationResult

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _task() -> TaskRequest:
    return TaskRequest(task_id="task-reflection", repo_path="./repo", issue="valid issue")


def _report(status: str, *, baseline: bool = False) -> ReportModel:
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
        tests_failed=1 if status == "assertion_failed" else 0,
        tests_errors=0 if status == "assertion_failed" else 1,
    )


def _state(**overrides):
    state = {
        "task": _task(),
        "status": "failed",
        "current_action": "test",
        "evidence": [],
        "diagnosis": None,
        "baseline_test_report": None,
        "test_report": None,
        "patch_application": None,
        "tool_results": [],
        "execution_trace": [],
        "retry_counts": RetryCounters(),
        "budget": BudgetState(max_patch_retries=1, max_replans=1, max_tool_retries=1),
    }
    state.update(overrides)
    return state


def _patch_record(applied: bool = False) -> PatchApplicationRecord:
    return PatchApplicationRecord(
        base_commit="abc123",
        worktree_path="/tmp/worktree",
        initial_status="",
        validation=PatchValidationResult(modified_files=["app.py"], diff_bytes=10, hunk_count=1),
        diff_before="",
        diff_after="",
        patch_applied=applied,
        error_code=None if applied else "patch_error",
        error_message=None if applied else "git apply failed",
    )


def test_failure_classifier_handles_every_failure_type() -> None:
    classifier = FailureClassifier()
    states = {
        "patch_error": _state(patch_application=_patch_record(False)),
        "regression": _state(
            baseline_test_report=_report("passed"),
            test_report=_report("assertion_failed"),
        ),
        "wrong_root_cause": _state(
            baseline_test_report=_report("assertion_failed"),
            test_report=_report("assertion_failed"),
        ),
        "missing_context": _state(
            diagnosis=Diagnosis(
                root_cause="unknown",
                evidence_ids=["missing"],
                confidence=0.5,
                suggested_fix="investigate",
            )
        ),
        "test_env_error": _state(test_report=_report("dependency_error")),
        "tool_failure": _state(
            tool_results=[
                ToolResult(
                    tool_name="run_tests",
                    success=False,
                    error_code="tool_error",
                    error_message="tool failed",
                    duration_ms=1,
                )
            ]
        ),
        "budget_exceeded": _state(status="budget_exceeded"),
    }

    for expected, state in states.items():
        classification = classifier.classify(
            test_report=state.get("test_report"),
            baseline_test_report=state.get("baseline_test_report"),
            tool_results=state.get("tool_results", []),
            patch_application=state.get("patch_application"),
            diagnosis=state.get("diagnosis"),
            evidence=state.get("evidence", []),
            trace=state.get("execution_trace", []),
            status=state.get("status"),
        )
        assert classification.failure_type == expected
        assert classification.evidence


def test_reflection_strategy_maps_failures_and_preserves_code_for_environment_failures() -> None:
    engine = ReflectionEngine()
    cases = {
        "patch_error": ("patch", False, True),
        "regression": ("replan", True, True),
        "wrong_root_cause": ("replan", True, True),
        "missing_context": ("search", False, False),
        "test_env_error": ("test", False, False),
        "tool_failure": ("replan", False, False),
        "budget_exceeded": ("finish", False, False),
    }

    states = {
        "patch_error": _state(patch_application=_patch_record(False)),
        "regression": _state(baseline_test_report=_report("passed"), test_report=_report("assertion_failed")),
        "wrong_root_cause": _state(baseline_test_report=_report("assertion_failed"), test_report=_report("assertion_failed")),
        "missing_context": _state(diagnosis=Diagnosis(root_cause="x", evidence_ids=["missing"], confidence=0.5, suggested_fix="x")),
        "test_env_error": _state(test_report=_report("dependency_error")),
        "tool_failure": _state(tool_results=[ToolResult(tool_name="x", success=False, error_code="tool_error", error_message="x", duration_ms=1)]),
        "budget_exceeded": _state(status="budget_exceeded"),
    }

    for name, (action, rollback, modify_code) in cases.items():
        record = engine.reflect(states[name])
        assert record.result.recommended_action == action
        assert record.result.strategy.should_rollback_patch is rollback
        assert record.result.strategy.should_modify_code is modify_code
        assert record.planner_feedback.failure_type == name


def test_reflection_retry_budget_and_invalid_output_safe_degradation() -> None:
    engine = ReflectionEngine()
    exhausted = _state(
        patch_application=_patch_record(False),
        retry_counts=RetryCounters(patch_retries=1),
        budget=BudgetState(max_patch_retries=1, max_replans=0, max_tool_retries=0),
    )
    record = engine.reflect(exhausted, raw_reflection="not-json")

    assert record.result.recommended_action == "finish"
    assert record.result.strategy.requires_human is True
    assert record.result.retry_budget_remaining.patch_retries == 0
    assert record.cost.duration_seconds >= 0
    assert record.state_before.status == "failed"
    assert record.state_after.current_action == "finish"


def test_recovery_rate_is_calculated_only_from_actionable_records() -> None:
    engine = ReflectionEngine()
    base = _state(baseline_test_report=_report("passed"), test_report=_report("assertion_failed"))
    recovered = engine.reflect(base).model_copy(update={"recovery_outcome": "recovered"})
    failed = engine.reflect(base).model_copy(update={"recovery_outcome": "failed"})
    terminal = engine.reflect(_state(status="budget_exceeded")).model_copy(update={"recovery_outcome": "terminal"})

    metrics = calculate_recovery_rate([recovered, failed, terminal])

    assert metrics.total_records == 3
    assert metrics.actionable_records == 2
    assert metrics.recovered_records == 1
    assert metrics.recovery_rate == 0.5
