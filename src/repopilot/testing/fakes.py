"""Deterministic test doubles for graph integration tests."""

from __future__ import annotations

from dataclasses import dataclass

from repopilot.core.schemas import PatchResult, TaskRequest, TestReport
from repopilot.tools.tests import TestRunner


@dataclass(frozen=True)
class FakeTestRunner(TestRunner):
    baseline_report: TestReport
    post_patch_report: TestReport

    def run(self, task: TaskRequest, *, patch: PatchResult | None, worktree_path=None) -> TestReport:
        return self.baseline_report if patch is None else self.post_patch_report


class FakeToolHandler:
    """Deterministic tool handler for registry and gateway tests."""

    def __init__(
        self,
        output: object = None,
        *,
        error: Exception | None = None,
        delay_seconds: float = 0,
    ) -> None:
        self.output = output
        self.error = error
        self.delay_seconds = delay_seconds
        self.calls: list[tuple[object, object]] = []

    def __call__(self, arguments: object, context: object) -> object:
        self.calls.append((arguments, context))
        if self.delay_seconds:
            import time

            time.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return self.output


class RecordingToolHandler:
    """Mock tool handler that records calls and returns a configured value."""

    def __init__(self, output: object = None) -> None:
        self.output = output
        self.calls: list[tuple[object, object]] = []

    def __call__(self, arguments: object, context: object) -> object:
        self.calls.append((arguments, context))
        return self.output
