import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from repopilot.agents.base import FakeAgent
from repopilot.core.config import load_config
from repopilot.core.repair import RepairDependencies, RepairPipeline
from repopilot.core.schemas import (
    Diagnosis,
    Evidence,
    PatchResult,
    PlannedStep,
    ResearchResult,
    ReviewResult,
    TaskPlan,
    TaskRequest,
)
from repopilot.llm import FakeLLM, build_llm_client
from repopilot.retrieval.index import RepositoryIndexer
from repopilot.retrieval.research import CodeRAGResearchAgent
from repopilot.retrieval.retriever import CodeRAGRetriever
from repopilot.sandbox.worktree import GitWorktreeManager
from repopilot.tools.patch import PatchExecutor, PatchPolicy
from repopilot.tools.tests import CommandTestRunner, TestCommandPolicy as CommandPolicy, TestCommandSpec as CommandSpec

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "benchmarks" / "tasks" / "task-001"
FIXED_CLOCK = lambda: datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _task() -> TaskRequest:
    metadata = json.loads((FIXTURE / "task.json").read_text(encoding="utf-8"))
    return TaskRequest(
        task_id=metadata["task_id"],
        repo_path=str(FIXTURE / metadata["repository_fixture"]),
        issue=metadata["issue"],
        test_command=[sys.executable, "-m", "pytest", "-q"],
        allowed_paths=["app.py", "tests/test_parser.py"],
        forbidden_paths=[".git/**", ".env", "*.key", "*.pem"],
    )


def _responses(*, planner: str | None = None, review: str | None = None) -> dict[str, str]:
    evidence_id = "ev-app.py:1:function:parse_config"

    plan = TaskPlan(
        objective="fix parse_config empty mapping behavior",
        steps=[
            PlannedStep(
                step_id="research",
                action="search",
                description="locate parse_config and its failing test",
                expected_output="path and line evidence",
            ),
            PlannedStep(
                step_id="diagnose",
                action="diagnose",
                description="explain why empty mappings return None",
                depends_on=["research"],
                expected_output="root cause",
            ),
            PlannedStep(
                step_id="patch",
                action="patch",
                description="return an empty mapping for empty input",
                depends_on=["diagnose"],
                expected_output="Unified Diff",
            ),
        ],
        next_action="search",
        rationale="the issue and failing test point to empty input handling",
    )
    evidence = Evidence(
        evidence_id="ev-001",
        source_type="source_code",
        file_path="app.py",
        line_start=1,
        line_end=4,
        symbol="parse_config",
        content="if not value: return None",
        retrieval_score=1.0,
    )
    diagnosis = Diagnosis(
        root_cause="parse_config returns None instead of an empty mapping for empty input",
        affected_files=["app.py"],
        related_symbols=["parse_config"],
        evidence_ids=[evidence_id],
        confidence=0.99,
        suggested_fix="return {} for empty input",
    )
    patch = PatchResult(
        unified_diff=(
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1,4 +1,4 @@\n"
            " def parse_config(value):\n"
            "     if not value:\n"
            "-        return None\n"
            "+        return {}\n"
            "     return dict(value)\n"
        ),
        modified_files=["app.py"],
        explanation="return an empty mapping for empty input",
    )
    review_result = ReviewResult(
        approved=True,
        evidence=[evidence_id],
        feedback="the evidence, diff, and real post-patch test support the repair",
        next_action="finish",
    )
    return {
        "TaskPlan": planner or plan.model_dump_json(),
        "ResearchResult": ResearchResult(evidence=[evidence]).model_dump_json(),
        "Diagnosis": diagnosis.model_dump_json(),
        "PatchResult": patch.model_dump_json(),
        "ReviewResult": review or review_result.model_dump_json(),
    }


def _dependencies(responses: dict[str, str]) -> RepairDependencies:
    llm = FakeLLM(responses)
    index = RepositoryIndexer().index(FIXTURE / "repo")
    agents = {
        "planner": FakeAgent(name="planner", output_model=TaskPlan, llm=llm),
        "research": CodeRAGResearchAgent(CodeRAGRetriever(index)),
        "diagnosis": FakeAgent(name="diagnosis", output_model=Diagnosis, llm=llm),
        "coding": FakeAgent(name="coding", output_model=PatchResult, llm=llm),
        "review": FakeAgent(name="review", output_model=ReviewResult, llm=llm),
    }
    command = [sys.executable, "-m", "pytest", "-q"]
    runner = CommandTestRunner(
        CommandPolicy(
            commands={
                "pytest": CommandSpec(
                    name="pytest",
                    argv=command,
                    timeout_seconds=15,
                )
            },
            default_command="pytest",
        )
    )
    manager = GitWorktreeManager()
    return RepairDependencies(
        llm=llm,
        test_runner=runner,
        worktree_manager=manager,
        patch_executor=PatchExecutor(
            manager,
            policy=PatchPolicy(allowed_paths=["app.py", "tests/test_parser.py"]),
        ),
        agents=agents,
        clock=FIXED_CLOCK,
    )


def test_fake_llm_runs_first_end_to_end_bug_repair_without_api_key() -> None:
    source_file = FIXTURE / "repo" / "app.py"
    source_before = source_file.read_text(encoding="utf-8")

    report = RepairPipeline(_dependencies(_responses())).run(_task())

    assert report.status == "succeeded"
    assert report.summary == "patch applied and post-patch tests passed"
    assert report.root_cause is not None and "empty mapping" in report.root_cause
    assert report.evidence
    assert report.evidence[0].evidence_id.startswith("ev-app.py:")
    assert report.evidence[0].file_path == "app.py"
    assert report.evidence[0].line_start == 1
    assert report.evidence[0].retrieval_sources
    assert report.evidence[0].repository_commit == report.base_commit
    assert report.modified_files == ["app.py"]
    assert "return {}" in (report.unified_diff or "")
    assert report.baseline_test_report is not None
    assert report.baseline_test_report.status == "assertion_failed"
    assert report.post_patch_test_report is not None
    assert report.post_patch_test_report.status == "passed"
    assert report.review_result is not None and report.review_result.approved is True
    assert report.base_commit == json.loads((FIXTURE / "task.json").read_text(encoding="utf-8"))["base_commit"]
    assert report.git_diff_before == ""
    assert '+        return {}' in report.git_diff_after
    assert report.cost is not None
    assert report.cost.cost_status == "fake"
    assert report.cost.llm_calls == 4
    assert source_file.read_text(encoding="utf-8") == source_before

    actions = [event.action for event in report.execution_trace]
    unique_actions = [action for index, action in enumerate(actions) if index == 0 or action != actions[index - 1]]
    assert unique_actions == [
        "validate_task",
        "prepare_workspace",
        "planner",
        "research",
        "diagnosis",
        "baseline_test",
        "coding",
        "validate_diff",
        "apply_patch",
        "post_patch_test",
        "review",
        "report",
    ]


def test_invalid_planner_output_reports_failure_node_without_touching_source() -> None:
    source_file = FIXTURE / "repo" / "app.py"
    source_before = source_file.read_text(encoding="utf-8")

    report = RepairPipeline(
        _dependencies(
            _responses(
                planner='{"objective":"x","steps":[],"next_action":"search","rationale":"r"}'
            )
        )
    ).run(_task())

    assert report.status == "failed"
    assert report.failure_node == "planner"
    assert "schema validation" in (report.failure_reason or "")
    assert report.baseline_test_report is None
    assert report.unified_diff is None
    assert source_file.read_text(encoding="utf-8") == source_before


@pytest.mark.skipif(
    not (os.environ.get("LLM_ENABLED", "").lower() == "true" and os.environ.get("LLM_API_KEY")),
    reason="real LLM API is not configured; Fake LLM E2E is verified instead",
)
def test_real_llm_end_to_end_when_configured() -> None:
    config = load_config()
    llm = build_llm_client(config)
    assert llm is not None

    index = RepositoryIndexer().index(FIXTURE / "repo")
    agents = {
        "planner": FakeAgent(name="planner", output_model=TaskPlan, llm=llm),
        "research": CodeRAGResearchAgent(CodeRAGRetriever(index)),
        "diagnosis": FakeAgent(name="diagnosis", output_model=Diagnosis, llm=llm),
        "coding": FakeAgent(name="coding", output_model=PatchResult, llm=llm),
        "review": FakeAgent(name="review", output_model=ReviewResult, llm=llm),
    }
    manager = GitWorktreeManager()
    command = [sys.executable, "-m", "pytest", "-q"]
    deps = RepairDependencies(
        llm=llm,
        test_runner=CommandTestRunner(
            CommandPolicy(
                commands={
                    "pytest": CommandSpec(
                        name="pytest",
                        argv=command,
                        timeout_seconds=15,
                    )
                },
                default_command="pytest",
            )
        ),
        worktree_manager=manager,
        patch_executor=PatchExecutor(
            manager,
            policy=PatchPolicy(allowed_paths=["app.py", "tests/test_parser.py"]),
        ),
        agents=agents,
        clock=FIXED_CLOCK,
    )

    report = RepairPipeline(deps).run(_task())
    assert report.status == "succeeded"
    assert report.cost is not None and report.cost.cost_status == "actual"


def test_repair_cost_usage_is_per_run_incremental() -> None:
    from repopilot.core.repair import RepairPipeline

    cost = RepairPipeline._usage_cost(
        {
            "calls": 0,
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
            "source": "actual",
        },
        {
            "calls": 4,
            "input_tokens": 3158,
            "output_tokens": 4336,
            "cost_usd": None,
            "source": "actual",
        },
    )

    assert cost.llm_calls == 4
    assert cost.input_tokens == 3158
    assert cost.output_tokens == 4336

    next_cost = RepairPipeline._usage_cost(
        {
            "calls": 4,
            "input_tokens": 3158,
            "output_tokens": 4336,
            "cost_usd": None,
            "source": "actual",
        },
        {
            "calls": 8,
            "input_tokens": 6000,
            "output_tokens": 7000,
            "cost_usd": None,
            "source": "actual",
        },
    )

    assert next_cost.llm_calls == 4
    assert next_cost.input_tokens == 2842
    assert next_cost.output_tokens == 2664
