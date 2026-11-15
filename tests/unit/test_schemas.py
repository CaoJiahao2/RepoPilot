from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from repopilot.core.schemas import (
    BudgetState,
    Diagnosis,
    Evidence,
    PatchResult,
    PlannedStep,
    RetryCounters,
    TaskPlan,
    TaskRequest,
    TestReport as ReportModel,
    ToolResult,
    TraceEvent,
    ReviewResult,
)


def test_all_core_schemas_accept_valid_input() -> None:
    task = TaskRequest(
        task_id="task-001",
        repo_path="./sample-project",
        issue="parse_config fails for empty input",
        test_command=["pytest", "tests/test_parser.py", "-q"],
    )
    plan = TaskPlan(
        objective="identify and fix the parser regression",
        steps=[
            PlannedStep(
                step_id="research",
                action="search",
                description="find parser code",
                expected_output="relevant source files",
            ),
            PlannedStep(
                step_id="diagnosis",
                action="diagnose",
                description="explain the root cause",
                depends_on=["research"],
                expected_output="traceable diagnosis",
            ),
        ],
        next_action="diagnose",
        rationale="the issue points to parser behavior",
    )
    evidence = Evidence(
        evidence_id="ev-001",
        source_type="source_code",
        file_path="src/parser.py",
        line_start=10,
        line_end=14,
        symbol="parse_config",
        content="def parse_config(value): ...",
        retrieval_score=0.91,
    )
    diagnosis = Diagnosis(
        root_cause="empty mappings are not normalized before validation",
        affected_files=["src/parser.py"],
        related_symbols=["parse_config"],
        evidence_ids=["ev-001"],
        confidence=0.8,
        suggested_fix="normalize empty mappings before validation",
    )
    patch = PatchResult(
        unified_diff="--- a/src/parser.py\n+++ b/src/parser.py\n@@ -1 +1 @@\n-old\n+new\n",
        modified_files=["src/parser.py"],
        explanation="normalize empty mappings",
    )
    report = ReportModel(
        command=["pytest", "tests/test_parser.py", "-q"],
        status="passed",
        return_code=0,
        duration_seconds=0.4,
        tests_total=2,
        tests_passed=2,
    )
    review = ReviewResult(
        approved=True,
        feedback="the patch is supported by tests",
        next_action="finish",
    )
    tool = ToolResult(
        tool_name="read_file",
        success=True,
        output="content",
        duration_ms=12,
    )
    budget = BudgetState()
    retries = RetryCounters()
    trace = TraceEvent(
        event_id="evt-001",
        task_id="task-001",
        timestamp=datetime.now(timezone.utc),
        event_type="tool",
        actor="tool_gateway",
        action="read_file",
        status="succeeded",
        duration_ms=12,
    )

    assert task.test_command == ["pytest", "tests/test_parser.py", "-q"]
    assert plan.steps[1].depends_on == ["research"]
    assert evidence.line_end == 14
    assert diagnosis.confidence == 0.8
    assert patch.modified_files == ["src/parser.py"]
    assert report.tests_passed == 2
    assert review.approved is True
    assert tool.success is True
    assert budget.llm_calls_used == 0
    assert retries.replans == 0
    assert trace.status == "succeeded"


@pytest.mark.parametrize(
    "field,value",
    [
        ("issue", "bug"),
        ("max_runtime_seconds", 0),
        ("max_llm_calls", 0),
        ("max_total_tokens", 0),
        ("max_patch_retries", -1),
    ],
)
def test_task_request_rejects_invalid_boundaries(field: str, value: object) -> None:
    payload = {
        "task_id": "task-001",
        "repo_path": "./repo",
        "issue": "valid issue",
        "max_runtime_seconds": 10,
        "max_llm_calls": 1,
        "max_total_tokens": 1,
        "max_patch_retries": 0,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        TaskRequest.model_validate(payload)


def test_task_request_rejects_conflicting_paths() -> None:
    with pytest.raises(ValidationError, match="allowed and forbidden"):
        TaskRequest(
            task_id="task-001",
            repo_path="./repo",
            issue="valid issue",
            allowed_paths=["src"],
            forbidden_paths=["src"],
        )


def test_task_plan_rejects_unknown_dependency_and_cycle() -> None:
    with pytest.raises(ValidationError, match="unknown steps"):
        TaskPlan(
            objective="objective",
            steps=[
                PlannedStep(
                    step_id="one",
                    action="search",
                    description="search",
                    depends_on=["missing"],
                    expected_output="evidence",
                )
            ],
            next_action="search",
            rationale="rationale",
        )

    with pytest.raises(ValidationError, match="cycle"):
        TaskPlan(
            objective="objective",
            steps=[
                PlannedStep(
                    step_id="one",
                    action="search",
                    description="search",
                    depends_on=["two"],
                    expected_output="evidence",
                ),
                PlannedStep(
                    step_id="two",
                    action="inspect",
                    description="inspect",
                    depends_on=["one"],
                    expected_output="code",
                ),
            ],
            next_action="search",
            rationale="rationale",
        )


def test_evidence_rejects_invalid_line_ranges() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        Evidence(
            evidence_id="ev-001",
            source_type="source_code",
            file_path="src/parser.py",
            line_start=1,
            content="content",
        )

    with pytest.raises(ValidationError, match="greater than or equal"):
        Evidence(
            evidence_id="ev-001",
            source_type="source_code",
            file_path="src/parser.py",
            line_start=10,
            line_end=9,
            content="content",
        )

    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="ev-001",
            source_type="memory",
            content="content",
            retrieval_score=1.01,
        )


def test_diagnosis_accepts_confidence_boundaries_but_rejects_out_of_range() -> None:
    for confidence in (0, 1):
        Diagnosis(
            root_cause="root cause",
            evidence_ids=["ev-001"],
            confidence=confidence,
            suggested_fix="fix",
        )

    with pytest.raises(ValidationError):
        Diagnosis(
            root_cause="root cause",
            evidence_ids=["ev-001"],
            confidence=1.01,
            suggested_fix="fix",
        )


def test_patch_result_rejects_duplicate_modified_files() -> None:
    with pytest.raises(ValidationError, match="unique"):
        PatchResult(
            unified_diff="diff --git a/a.py b/a.py\n",
            modified_files=["a.py", "a.py"],
            explanation="change",
        )


def test_test_report_rejects_inconsistent_counts_and_status() -> None:
    with pytest.raises(ValidationError, match="sum to tests_total"):
        ReportModel(
            command=["pytest"],
            status="assertion_failed",
            return_code=1,
            duration_seconds=1,
            tests_total=2,
            tests_passed=1,
        )

    with pytest.raises(ValidationError, match="return_code=0"):
        ReportModel(
            command=["pytest"],
            status="passed",
            return_code=1,
            duration_seconds=1,
            tests_total=1,
            tests_failed=1,
        )


def test_review_result_requires_failure_type_when_rejected() -> None:
    with pytest.raises(ValidationError, match="must set failure_type"):
        ReviewResult(
            approved=False,
            feedback="not enough evidence",
            next_action="re_search",
        )

    with pytest.raises(ValidationError, match="must not set failure_type"):
        ReviewResult(
            approved=True,
            failure_type="wrong_root_cause",
            feedback="looks correct",
            next_action="finish",
        )


def test_tool_result_requires_errors_only_for_failure() -> None:
    with pytest.raises(ValidationError, match="error_code and error_message"):
        ToolResult(tool_name="run_tests", success=False, duration_ms=1)

    with pytest.raises(ValidationError, match="must not include errors"):
        ToolResult(
            tool_name="run_tests",
            success=True,
            error_code="unexpected",
            error_message="unexpected",
            duration_ms=1,
        )


def test_budget_state_rejects_usage_over_limit() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        BudgetState(
            max_llm_calls=1,
            max_total_tokens=10,
            max_runtime_seconds=10,
            llm_calls_used=2,
        )


def test_retry_counters_accept_zero_and_reject_negative_values() -> None:
    RetryCounters()
    with pytest.raises(ValidationError):
        RetryCounters(replans=-1)


def test_trace_event_requires_timezone_and_non_negative_duration() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        TraceEvent(
            event_id="evt-001",
            task_id="task-001",
            timestamp=datetime.now(),
            event_type="task",
            actor="runtime",
            action="start",
            status="started",
        )

    with pytest.raises(ValidationError):
        TraceEvent(
            event_id="evt-001",
            task_id="task-001",
            timestamp=datetime.now(timezone.utc),
            event_type="task",
            actor="runtime",
            action="start",
            status="started",
            duration_ms=-1,
        )
