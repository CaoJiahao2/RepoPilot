"""Benchmark executor ports and honest default fallbacks."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from repopilot.evaluation.models import BenchmarkExecutionResult
from repopilot.evaluation.task import AgentTask


class BenchmarkExecutor(Protocol):
    def run(
        self,
        task: AgentTask,
        *,
        workspace_path: Path,
        run_index: int,
    ) -> BenchmarkExecutionResult:
        ...


class SkippedExecutor:
    def run(
        self,
        task: AgentTask,
        *,
        workspace_path: Path,
        run_index: int,
    ) -> BenchmarkExecutionResult:
        return BenchmarkExecutionResult(
            status="skipped",
            success=False,
            execution_mode="skipped",
            logs="real benchmark executor is not configured; result is not an agent benchmark",
        )


class MockExecutor:
    """Infrastructure smoke executor that never claims a real agent success."""

    def run(
        self,
        task: AgentTask,
        *,
        workspace_path: Path,
        run_index: int,
    ) -> BenchmarkExecutionResult:
        return BenchmarkExecutionResult(
            status="failed",
            success=False,
            execution_mode="mock",
            failure_type="not_evaluated",
            logs="mock executor completed without claiming benchmark success",
            duration_seconds=0,
        )
