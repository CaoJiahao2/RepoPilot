from datetime import datetime, timezone

import pytest

from repopilot.agents.base import FakeAgent
from repopilot.core.graph import RuntimeDependencies, build_graph
from repopilot.core.schemas import (
    Diagnosis,
    Evidence,
    MemoryHit,
    PatchResult,
    PlannedStep,
    ResearchResult,
    ReviewResult,
    TaskPlan,
    TaskRequest,
    TestReport as ReportModel,
    TraceEvent,
)
from repopilot.llm import FakeLLM
from repopilot.testing.fakes import FakeTestRunner

FIXED_CLOCK = lambda: datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _task(**overrides) -> TaskRequest:
    values = {
        "task_id": "task-001",
        "repo_path": "./fixture",
        "issue": "parse_config fails on empty mappings",
        "test_command": ["pytest", "tests/test_parser.py", "-q"],
        "max_patch_retries": 1,
        "max_total_tokens": 1000,
        "max_llm_calls": 20,
    }
    values.update(overrides)
    return TaskRequest.model_validate(values)


def _passed_report() -> ReportModel:
    return ReportModel(
        command=["pytest", "tests/test_parser.py", "-q"],
        status="passed",
        return_code=0,
        duration_seconds=0.2,
        tests_total=1,
        tests_passed=1,
    )


def _failed_report() -> ReportModel:
    return ReportModel(
        command=["pytest", "tests/test_parser.py", "-q"],
        status="assertion_failed",
        return_code=1,
        duration_seconds=0.2,
        tests_total=1,
        tests_failed=1,
        failure_type="regression",
    )


def _responses(
    *,
    planner: str | None = None,
    research: str | None = None,
    diagnosis_override: str | None = None,
    patch: str | None = None,
    review: str | None = None,
) -> dict[str, str]:
    plan = TaskPlan(
        objective="fix parser handling",
        steps=[
            PlannedStep(
                step_id="research",
                action="search",
                description="find parser code",
                expected_output="source evidence",
            ),
            PlannedStep(
                step_id="diagnose",
                action="diagnose",
                description="identify cause",
                depends_on=["research"],
                expected_output="root cause",
            ),
        ],
        next_action="search",
        rationale="the issue names parser behavior",
    )
    evidence = Evidence(
        evidence_id="ev-001",
        source_type="source_code",
        file_path="src/parser.py",
        line_start=10,
        line_end=14,
        symbol="parse_config",
        content="empty mapping is not normalized",
    )
    research_result = ResearchResult(evidence=[evidence])
    diagnosis = Diagnosis(
        root_cause="empty mappings are not normalized",
        affected_files=["src/parser.py"],
        related_symbols=["parse_config"],
        evidence_ids=["ev-001"],
        confidence=0.9,
        suggested_fix="normalize empty mappings",
    )
    patch_result = PatchResult(
        unified_diff="--- a/src/parser.py\n+++ b/src/parser.py\n@@ -1 +1 @@\n-old\n+new\n",
        modified_files=["src/parser.py"],
        explanation="normalize empty mappings",
    )
    review_result = ReviewResult(
        approved=True,
        evidence=["ev-001"],
        feedback="patch and tests support the diagnosis",
        next_action="finish",
    )
    return {
        "TaskPlan": planner if planner is not None else plan.model_dump_json(),
        "ResearchResult": research if research is not None else research_result.model_dump_json(),
        "Diagnosis": diagnosis_override if diagnosis_override is not None else diagnosis.model_dump_json(),
        "PatchResult": patch if patch is not None else patch_result.model_dump_json(),
        "ReviewResult": review if review is not None else review_result.model_dump_json(),
    }


def _dependencies(responses: dict[str, str], post_patch_report: ReportModel) -> RuntimeDependencies:
    llm = FakeLLM(responses)
    agents = {
        "planner": FakeAgent(name="planner", output_model=TaskPlan, llm=llm),
        "research": FakeAgent(name="research", output_model=ResearchResult, llm=llm),
        "diagnosis": FakeAgent(name="diagnosis", output_model=Diagnosis, llm=llm),
        "coding": FakeAgent(name="coding", output_model=PatchResult, llm=llm),
        "review": FakeAgent(name="review", output_model=ReviewResult, llm=llm),
    }
    return RuntimeDependencies(
        llm=llm,
        test_runner=FakeTestRunner(
            baseline_report=_passed_report(),
            post_patch_report=post_patch_report,
        ),
        agents=agents,
        clock=FIXED_CLOCK,
    )


def test_fake_llm_runs_complete_graph_without_api_key() -> None:
    graph = build_graph(_dependencies(_responses(), _passed_report()))
    result = graph.invoke({"task": _task()})

    assert result["status"] == "succeeded"
    assert result["report"].review_approved is True
    assert result["report"].test_status == "passed"
    assert result["plan"].objective == "fix parser handling"
    assert result["diagnosis"].root_cause.startswith("empty mappings")
    assert result["patch_result"].modified_files == ["src/parser.py"]
    assert result["test_report"].status == "passed"

    actions = [event.action for event in result["execution_trace"]]
    assert actions == [
        "initialize",
        "run_baseline_tests",
        "planner",
        "planner",
        "research",
        "research",
        "diagnosis",
        "diagnosis",
        "coding",
        "coding",
        "run_tests",
        "run_tests",
        "review",
        "review",
        "report",
        "report",
    ]
    assert all(isinstance(event, TraceEvent) for event in result["execution_trace"])


@pytest.mark.parametrize(
    ("output_name", "invalid_output"),
    [
        ("TaskPlan", '{"objective":"x","steps":[],"next_action":"search","rationale":"r"}'),
        ("ResearchResult", '{"evidence":[]}'),
        ("Diagnosis", '{"root_cause":"x","evidence_ids":[],"confidence":2,"suggested_fix":"x"}'),
        ("PatchResult", '{"unified_diff":"","modified_files":[],"explanation":"x"}'),
        ("ReviewResult", '{"approved":false,"feedback":"x","next_action":"finish"}'),
    ],
)
def test_invalid_structured_llm_output_is_terminal(output_name: str, invalid_output: str) -> None:
    responses = _responses()
    responses[output_name] = invalid_output
    graph = build_graph(_dependencies(responses, _passed_report()))
    result = graph.invoke({"task": _task()})

    assert result["status"] == "failed"
    assert result["report"] is not None
    assert result["report"].status == "failed"
    absent_fields = {
        "TaskPlan": ("plan", "diagnosis", "patch_result", "test_report", "review_result"),
        "ResearchResult": ("diagnosis", "patch_result", "test_report", "review_result"),
        "Diagnosis": ("diagnosis", "patch_result", "test_report", "review_result"),
        "PatchResult": ("patch_result", "test_report", "review_result"),
        "ReviewResult": ("review_result",),
    }[output_name]
    for field in absent_fields:
        assert result.get(field) is None

    failed_actions = [
        event.action
        for event in result["execution_trace"]
        if event.status == "failed"
    ]
    assert failed_actions
    assert "report" in [event.action for event in result["execution_trace"]]


def test_invalid_planner_output_does_not_reach_research() -> None:
    responses = _responses(
        planner='{"objective":"x","steps":[],"next_action":"search","rationale":"r"}'
    )
    graph = build_graph(_dependencies(responses, _passed_report()))
    result = graph.invoke({"task": _task()})

    assert result["status"] == "failed"
    assert result.get("plan") is None
    assert result.get("diagnosis") is None
    assert result.get("patch_result") is None
    assert result.get("test_report") is None
    assert all(event.action != "research" for event in result["execution_trace"])


def test_repeated_fake_inputs_produce_identical_results() -> None:
    first = build_graph(_dependencies(_responses(), _passed_report())).invoke({"task": _task()})
    second = build_graph(_dependencies(_responses(), _passed_report())).invoke({"task": _task()})

    assert first["report"] == second["report"]
    assert first["plan"] == second["plan"]
    assert first["diagnosis"] == second["diagnosis"]
    assert first["patch_result"] == second["patch_result"]
    assert first["test_report"] == second["test_report"]
    assert [event.model_dump(mode="json") for event in first["execution_trace"]] == [
        event.model_dump(mode="json") for event in second["execution_trace"]
    ]


def test_patch_retry_is_bounded_and_terminates() -> None:
    review = ReviewResult(
        approved=False,
        failure_type="patch_error",
        feedback="patch still fails",
        next_action="re_patch",
    )
    responses = _responses(review=review.model_dump_json())
    graph = build_graph(_dependencies(responses, _failed_report()))
    result = graph.invoke({"task": _task(max_patch_retries=1)})

    assert result["status"] == "failed"
    assert result["retry_counts"].patch_retries == 1
    assert result["failure_type"] == "budget_exceeded"
    assert result["report"].status == "failed"

    coding_count = sum(event.action == "coding" for event in result["execution_trace"])
    review_count = sum(event.action == "review" for event in result["execution_trace"])
    assert coding_count == 4
    assert review_count == 4


def test_invalid_structured_output_retries_once_then_remains_terminal() -> None:
    from repopilot.agents.base import FakeAgent
    from repopilot.core.errors import SchemaValidationError
    from repopilot.llm import FakeLLM

    llm = FakeLLM({"TaskPlan": '{"objective":"x","steps":[],"next_action":"search","rationale":"x"}'})
    agent = FakeAgent(name="planner", output_model=TaskPlan, llm=llm, max_validation_retries=1)

    with pytest.raises(SchemaValidationError):
        agent.run({"task": _task()})

    assert len(llm.calls) == 2
    assert "failed schema validation" in llm.calls[1][0]
