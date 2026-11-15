"""Controlled deterministic test command execution."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Protocol

from pydantic import Field

from repopilot.core.schemas import PatchResult, RepoPilotModel, TaskRequest, TestReport


class TestRunner(Protocol):
    def run(
        self,
        task: TaskRequest,
        *,
        patch: PatchResult | None,
        worktree_path: Path | None = None,
    ) -> TestReport:
        ...


class TestCommandSpec(RepoPilotModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    argv: list[str] = Field(min_length=1)
    timeout_seconds: float = Field(default=30, gt=0, le=3_600)

    def model_post_init(self, __context: object) -> None:
        if any(not item for item in self.argv):
            raise ValueError("test command arguments must be non-empty")


class TestCommandPolicy(RepoPilotModel):
    commands: dict[str, TestCommandSpec] = Field(min_length=1)
    default_command: str | None = None
    max_output_bytes: int = Field(default=1_000_000, ge=1)

    def model_post_init(self, __context: object) -> None:
        for name, spec in self.commands.items():
            if name != spec.name:
                raise ValueError("test command key must match spec.name")
        if self.default_command is not None and self.default_command not in self.commands:
            raise ValueError("default_command must refer to a registered command")

    def resolve(self, command: list[str] | None) -> TestCommandSpec:
        if command is None:
            if self.default_command is None:
                raise ValueError("no default test command is configured")
            return self.commands[self.default_command]
        for spec in self.commands.values():
            if spec.argv == command:
                return spec
        raise ValueError("test command is not in the controlled allowlist")


def _truncate(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore") + "\n[output truncated]"


def _classify(returncode: int, stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}"
    if returncode == 0:
        return "passed"
    lowered = combined.lower()
    if "error collecting" in lowered or "collection error" in lowered or "collected 0 items" in lowered:
        return "collection_error"
    if any(
        marker in lowered
        for marker in (
            "modulenotfounderror",
            "importerror",
            "no module named",
            "command not found",
            "dependency error",
        )
    ):
        return "dependency_error"
    if any(marker in lowered for marker in ("assert", "failed", "failure", "error: test failed")):
        return "assertion_failed"
    return "execution_error"


def _parse_counts(stdout: str, stderr: str) -> dict[str, int]:
    combined = f"{stdout}\n{stderr}"
    patterns = {
        "tests_passed": r"(\d+)\s+passed",
        "tests_failed": r"(\d+)\s+failed",
        "tests_errors": r"(\d+)\s+errors?",
        "tests_skipped": r"(\d+)\s+skipped",
    }
    counts = {name: 0 for name in patterns}
    for name, pattern in patterns.items():
        matches = re.findall(pattern, combined)
        if matches:
            counts[name] = int(matches[-1])
    counts["tests_total"] = (
        counts["tests_passed"]
        + counts["tests_failed"]
        + counts["tests_errors"]
        + counts["tests_skipped"]
    )
    return counts


class CommandTestRunner:
    def __init__(
        self,
        policy: TestCommandPolicy,
        *,
        max_output_bytes: int | None = None,
    ) -> None:
        self.policy = policy
        self.max_output_bytes = max_output_bytes or policy.max_output_bytes

    def run(
        self,
        task: TaskRequest,
        *,
        patch: PatchResult | None,
        worktree_path: Path | None = None,
    ) -> TestReport:
        try:
            spec = self.policy.resolve(task.test_command)
        except ValueError as exc:
            return TestReport(
                command=task.test_command or ["<not-allowlisted>"],
                status="execution_error",
                return_code=125,
                duration_seconds=0,
                stderr=str(exc),
                failure_type="tool_failure",
            )

        if worktree_path is None:
            return TestReport(
                command=spec.argv,
                status="execution_error",
                return_code=125,
                duration_seconds=0,
                stderr="worktree_path is required for test execution",
                failure_type="tool_failure",
            )
        if not worktree_path.exists():
            return TestReport(
                command=spec.argv,
                status="execution_error",
                return_code=125,
                duration_seconds=0,
                stderr="worktree_path does not exist",
                failure_type="tool_failure",
            )

        started = time.perf_counter()
        process = subprocess.Popen(
            spec.argv,
            cwd=str(worktree_path),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        try:
            stdout, stderr = process.communicate(timeout=spec.timeout_seconds)
            duration = time.perf_counter() - started
            output_bytes = len((stdout + stderr).encode("utf-8"))
            if output_bytes > self.max_output_bytes:
                return TestReport(
                    command=spec.argv,
                    status="execution_error",
                    return_code=125,
                    duration_seconds=duration,
                    stdout=_truncate(stdout, self.max_output_bytes),
                    stderr=_truncate(stderr, self.max_output_bytes),
                    failure_type="tool_failure",
                )
            status = _classify(process.returncode, stdout, stderr)
            counts = _parse_counts(stdout, stderr)
            return TestReport(
                command=spec.argv,
                status=status,
                return_code=process.returncode,
                duration_seconds=duration,
                stdout=stdout,
                stderr=stderr,
                **counts,
            )
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
            duration = time.perf_counter() - started
            return TestReport(
                command=spec.argv,
                status="timeout",
                return_code=process.returncode if process.returncode is not None else -9,
                duration_seconds=duration,
                stdout=_truncate(stdout, self.max_output_bytes),
                stderr=_truncate(stderr, self.max_output_bytes),
                failure_type="tool_failure",
            )
        except OSError as exc:
            duration = time.perf_counter() - started
            return TestReport(
                command=spec.argv,
                status="execution_error",
                return_code=125,
                duration_seconds=duration,
                stderr=f"{type(exc).__name__}: {exc}",
                failure_type="tool_failure",
            )
