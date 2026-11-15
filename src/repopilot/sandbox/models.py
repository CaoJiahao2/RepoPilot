"""Sandbox execution contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from repopilot.core.schemas import RepoPilotModel

SandboxStatus = Literal["passed", "failed", "timeout", "error", "cancelled"]


class SandboxPolicy(RepoPilotModel):
    backend: Literal["docker", "local_worktree"] = "docker"
    image: str = Field(default="python:3.12-slim", min_length=1)
    network_disabled: bool = True
    cpus: float = Field(default=2.0, gt=0, le=64)
    memory_mb: int = Field(default=512, ge=64, le=65_536)
    pids_limit: int = Field(default=64, ge=1, le=1024)
    timeout_seconds: float = Field(default=300, gt=0, le=3_600)
    max_output_bytes: int = Field(default=1_000_000, ge=1)
    user: str | None = Field(default=None, pattern=r"^\d+:\d+$")


class SandboxCommand(RepoPilotModel):
    argv: list[str] = Field(min_length=1)
    cwd: str = "."
    timeout_seconds: float | None = Field(default=None, gt=0)


class SandboxResult(RepoPilotModel):
    status: SandboxStatus
    return_code: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = Field(ge=0)
    output_bytes: int = Field(ge=0)
    command: list[str] = Field(min_length=1)
    error_code: str | None = None
