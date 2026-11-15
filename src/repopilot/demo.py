"""Fake-LLM demo executor backed by real repair infrastructure."""

from __future__ import annotations

from pathlib import Path

from repopilot.agents.base import FakeAgent
from repopilot.core.repair import RepairDependencies, RepairPipeline
from repopilot.core.schemas import (
    Diagnosis,
    EndToEndReport,
    PatchResult,
    PlannedStep,
    ReviewResult,
    TaskPlan,
    TaskRequest,
)
from repopilot.llm import FakeLLM
from repopilot.retrieval.index import RepositoryIndexer
from repopilot.retrieval.research import CodeRAGResearchAgent
from repopilot.retrieval.retriever import CodeRAGRetriever
from repopilot.sandbox.worktree import GitWorktreeManager
from repopilot.tools.patch import PatchExecutor, PatchPolicy
from repopilot.tools.tests import CommandTestRunner, TestCommandPolicy, TestCommandSpec


class DemoRepairExecutor:
    """Runs task-001 with Fake LLM decisions and real execution tools."""

    def run(self, task: TaskRequest) -> EndToEndReport:
        if task.task_id != "task-001":
            return EndToEndReport(
                task_id=task.task_id,
                status="failed",
                summary="demo executor only supports task-001",
                failure_node="demo",
                failure_reason="use the real repair executor for other tasks",
            )

        index = RepositoryIndexer().index(Path(task.repo_path))
        retriever = CodeRAGRetriever(index)
        research = CodeRAGResearchAgent(retriever)
        hits = retriever.search(task.issue, stack_trace=task.stack_trace, limit=3)
        evidence_id = f"ev-{hits[0].chunk_id}" if hits else "ev-app.py:1:function:parse_config"

        plan = TaskPlan(
            objective="repair parse_config empty mapping behavior",
            steps=[
                PlannedStep(
                    step_id="research",
                    action="search",
                    description="find parse_config evidence",
                    expected_output="file and line evidence",
                ),
                PlannedStep(
                    step_id="diagnose",
                    action="diagnose",
                    description="explain empty mapping behavior",
                    depends_on=["research"],
                    expected_output="root cause",
                ),
                PlannedStep(
                    step_id="patch",
                    action="patch",
                    description="return an empty mapping",
                    depends_on=["diagnose"],
                    expected_output="Unified Diff",
                ),
            ],
            next_action="search",
            rationale="the bug description and target test point to empty mapping handling",
        )
        diagnosis = Diagnosis(
            root_cause="empty mappings return None instead of an empty mapping",
            affected_files=["app.py"],
            related_symbols=["parse_config"],
            evidence_ids=[evidence_id],
            confidence=0.99,
            suggested_fix="return an empty mapping for empty input",
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
        review = ReviewResult(
            approved=True,
            evidence=[evidence_id],
            feedback="real post-patch tests passed and the diff matches the evidence",
            next_action="finish",
        )
        responses = {
            "TaskPlan": plan.model_dump_json(),
            "Diagnosis": diagnosis.model_dump_json(),
            "PatchResult": patch.model_dump_json(),
            "ReviewResult": review.model_dump_json(),
        }
        llm = FakeLLM(responses)
        agents = {
            "planner": FakeAgent(name="planner", output_model=TaskPlan, llm=llm),
            "research": research,
            "diagnosis": FakeAgent(name="diagnosis", output_model=Diagnosis, llm=llm),
            "coding": FakeAgent(name="coding", output_model=PatchResult, llm=llm),
            "review": FakeAgent(name="review", output_model=ReviewResult, llm=llm),
        }
        manager = GitWorktreeManager()
        test_runner = CommandTestRunner(
            TestCommandPolicy(
                commands={
                    "configured": TestCommandSpec(
                        name="configured",
                        argv=task.test_command,
                        timeout_seconds=15,
                    )
                },
                default_command="configured",
            )
        )
        pipeline = RepairPipeline(
            RepairDependencies(
                llm=llm,
                test_runner=test_runner,
                worktree_manager=manager,
                patch_executor=PatchExecutor(
                    manager,
                    policy=PatchPolicy(allowed_paths=["app.py", "tests/test_parser.py"]),
                ),
                agents=agents,
                execution_mode="fake_llm",
            )
        )
        return pipeline.run(task, cleanup=True)
