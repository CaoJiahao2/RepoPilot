"""Real RepairPipeline executor for benchmark and experiment runs."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from repopilot.agents.base import FakeAgent
from repopilot.core.config import load_config
from repopilot.core.repair import RepairDependencies, RepairPipeline
from repopilot.core.schemas import (
    Diagnosis,
    PatchResult,
    ReviewResult,
    TaskPlan,
    TaskRequest,
)
from repopilot.evaluation.models import BenchmarkExecutionResult
from repopilot.evaluation.task import AgentTask
from repopilot.llm import build_llm_client
from repopilot.retrieval.index import RepositoryIndexer
from repopilot.retrieval.research import CodeRAGResearchAgent
from repopilot.retrieval.retriever import CodeRAGRetriever
from repopilot.sandbox.worktree import GitWorktreeManager
from repopilot.tools.patch import PatchExecutor, PatchPolicy
from repopilot.tools.tests import CommandTestRunner, TestCommandPolicy, TestCommandSpec


class RealRepairExecutor:
    def __init__(self, *, max_runtime_seconds: int = 120) -> None:
        self.llm = build_llm_client(load_config())
        if self.llm is None:
            raise RuntimeError("real LLM is not configured")
        self.max_runtime_seconds = max_runtime_seconds

    def run(self, task: AgentTask, *, workspace_path: Path, run_index: int) -> BenchmarkExecutionResult:
        command = [sys.executable, "-m", "pytest", "-q"]
        request = TaskRequest(
            task_id=task.task_id,
            repo_path=str(workspace_path),
            issue=task.issue,
            stack_trace=task.stack_trace,
            test_command=command,
            allowed_paths=["app.py", "tests"],
            max_runtime_seconds=self.max_runtime_seconds,
        )
        index = RepositoryIndexer().index(workspace_path)
        retriever = CodeRAGRetriever(index)
        agents = {
            "planner": FakeAgent(name="planner", output_model=TaskPlan, llm=self.llm),
            "research": CodeRAGResearchAgent(retriever),
            "diagnosis": FakeAgent(name="diagnosis", output_model=Diagnosis, llm=self.llm),
            "coding": FakeAgent(name="coding", output_model=PatchResult, llm=self.llm),
            "review": FakeAgent(name="review", output_model=ReviewResult, llm=self.llm),
        }
        manager = GitWorktreeManager()
        deps = RepairDependencies(
            llm=self.llm,
            test_runner=CommandTestRunner(
                TestCommandPolicy(
                    commands={
                        "pytest": TestCommandSpec(
                            name="pytest",
                            argv=command,
                            timeout_seconds=30,
                        )
                    },
                    default_command="pytest",
                )
            ),
            worktree_manager=manager,
            patch_executor=PatchExecutor(
                manager,
                policy=PatchPolicy(allowed_paths=["app.py", "tests"]),
            ),
            agents=agents,
            execution_mode="real",
        )
        started = time.perf_counter()
        report = RepairPipeline(deps).run(request, cleanup=True)
        elapsed = time.perf_counter() - started
        baseline = report.baseline_test_report
        post = report.post_patch_test_report
        return BenchmarkExecutionResult(
            status="succeeded" if report.status == "succeeded" else "failed",
            success=report.status == "succeeded",
            patch_passed=bool(post and post.status == "passed"),
            regression_detected=bool(
                baseline
                and baseline.status == "passed"
                and post
                and post.status != "passed"
            ),
            root_cause_correct=None,
            root_cause=report.root_cause,
            patch_diff=report.unified_diff or "",
            logs=report.summary,
            failure_stage=report.failure_node,
            failure_type=None,
            tool_calls=0,
            tool_successes=0,
            replans=0,
            reflection_attempts=0,
            reflection_recoveries=0,
            memory_retrievals=0,
            memory_hits=0,
            duration_seconds=elapsed,
            input_tokens=report.cost.input_tokens if report.cost else None,
            output_tokens=report.cost.output_tokens if report.cost else None,
            llm_calls=report.cost.llm_calls if report.cost else 0,
            estimated_cost_usd=report.cost.estimated_cost_usd if report.cost else None,
            execution_mode="real",
        )
