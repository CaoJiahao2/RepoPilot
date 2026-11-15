"""Read-only Git tools using argument arrays and no shell interpolation."""

from __future__ import annotations

import subprocess
from typing import Literal

from pydantic import Field

from repopilot.core.errors import ToolExecutionError
from repopilot.tools.base import ToolContext, ToolInput


class GitStatusInput(ToolInput):
    pass


class GitDiffInput(ToolInput):
    path: str | None = Field(default=None, min_length=1)
    staged: bool = False
    context_lines: int = Field(default=3, ge=0, le=20)


def _run_git(arguments: list[str], context: ToolContext) -> dict[str, object]:
    command = ["git", *arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=str(context.allowed_root),
            shell=False,
            capture_output=True,
            text=True,
            timeout=context.command_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError(
            "git command timed out",
            details={"error_code": "timeout", "command": command[1]},
        ) from exc
    except OSError as exc:
        raise ToolExecutionError(
            "git command could not be executed",
            details={"error_code": "tool_error", "exception": type(exc).__name__},
        ) from exc

    if completed.returncode != 0:
        raise ToolExecutionError(
            "git command failed",
            details={
                "error_code": "git_error",
                "returncode": completed.returncode,
                "stderr_tail": completed.stderr[-500:],
            },
        )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def git_status_handler(arguments: GitStatusInput, context: ToolContext) -> dict[str, object]:
    return _run_git(["status", "--short", "--branch"], context)


def git_diff_handler(arguments: GitDiffInput, context: ToolContext) -> dict[str, object]:
    diff_arguments = ["diff", f"--unified={arguments.context_lines}"]
    if arguments.staged:
        diff_arguments.append("--cached")
    if arguments.path is not None:
        resolved = context.resolve_path(arguments.path, must_exist=False)
        relative = resolved.relative_to(context.allowed_root).as_posix()
        diff_arguments.extend(["--", relative])
    return _run_git(diff_arguments, context)
