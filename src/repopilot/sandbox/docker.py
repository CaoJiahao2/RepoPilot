"""Docker sandbox command construction and bounded execution."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from repopilot.core.errors import SandboxViolationError
from repopilot.sandbox.models import SandboxCommand, SandboxPolicy, SandboxResult


class DockerSandbox:
    def __init__(self, worktree_path: str | Path, policy: SandboxPolicy | None = None) -> None:
        self.worktree_path = Path(worktree_path).expanduser().resolve(strict=True)
        if not self.worktree_path.is_dir():
            raise SandboxViolationError("sandbox worktree must be a directory")
        self.policy = policy or SandboxPolicy()

    def build_command(self, command: SandboxCommand) -> list[str]:
        if not command.argv or any(not isinstance(item, str) or not item for item in command.argv):
            raise SandboxViolationError("sandbox command argv must contain non-empty strings")
        if any(item == "docker" for item in command.argv):
            raise SandboxViolationError("nested docker commands are not allowed")
        cwd = Path(command.cwd)
        if cwd.is_absolute() or ".." in cwd.parts:
            raise SandboxViolationError("sandbox cwd must be a relative path inside the worktree")
        resolved_cwd = (self.worktree_path / cwd).resolve(strict=False)
        if resolved_cwd != self.worktree_path and self.worktree_path not in resolved_cwd.parents:
            raise SandboxViolationError("sandbox cwd escapes the worktree")

        user = self.policy.user or (
            "65534:65534" if os.getuid() == 0 else f"{os.getuid()}:{os.getgid()}"
        )
        if user == "0:0" or user.startswith("0:"):
            raise SandboxViolationError("sandbox must run as a non-root user")
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none" if self.policy.network_disabled else "bridge",
            "--user",
            user,
            "--cpus",
            str(self.policy.cpus),
            "--memory",
            f"{self.policy.memory_mb}m",
            "--pids-limit",
            str(self.policy.pids_limit),
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--mount",
            f"type=bind,src={self.worktree_path},dst=/workspace",
            "--workdir",
            f"/workspace/{cwd.as_posix()}",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            self.policy.image,
            *command.argv,
        ]
        return docker_command

    def execute(self, command: SandboxCommand) -> SandboxResult:
        argv = self.build_command(command)
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                timeout=command.timeout_seconds or self.policy.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            duration = time.perf_counter() - started
            return SandboxResult(
                status="timeout",
                return_code=-9,
                stderr="sandbox execution timed out",
                duration_seconds=duration,
                output_bytes=0,
                command=argv,
                error_code="timeout",
            )
        except OSError as exc:
            duration = time.perf_counter() - started
            return SandboxResult(
                status="error",
                return_code=127,
                stderr=f"{type(exc).__name__}: {exc}",
                duration_seconds=duration,
                output_bytes=0,
                command=argv,
                error_code="sandbox_unavailable",
            )

        stdout = completed.stdout
        stderr = completed.stderr
        output_bytes = len((stdout + stderr).encode("utf-8"))
        duration = time.perf_counter() - started
        if output_bytes > self.policy.max_output_bytes:
            return SandboxResult(
                status="error",
                return_code=completed.returncode,
                stdout=stdout[: self.policy.max_output_bytes],
                stderr=stderr[: self.policy.max_output_bytes],
                duration_seconds=duration,
                output_bytes=output_bytes,
                command=argv,
                error_code="output_limit_exceeded",
            )
        return SandboxResult(
            status="passed" if completed.returncode == 0 else "failed",
            return_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            output_bytes=output_bytes,
            command=argv,
        )
