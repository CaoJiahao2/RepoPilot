"""Unified Diff validation and controlled application inside a Git Worktree."""

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path, PurePosixPath

from pydantic import Field

from repopilot.core.errors import PatchValidationError
from repopilot.core.schemas import PatchResult, RepoPilotModel
from repopilot.sandbox.worktree import GitWorktreeManager, WorktreeSession
from repopilot.tools.base import ToolExecutionError

HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")

DEFAULT_FORBIDDEN_PATHS = (
    ".git",
    ".git/**",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "credentials*",
    ".ssh/**",
    "docker.sock",
)


class PatchPolicy(RepoPilotModel):
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=lambda: list(DEFAULT_FORBIDDEN_PATHS))
    max_diff_bytes: int = Field(default=2_000_000, ge=1)
    max_modified_files: int = Field(default=20, ge=1)
    max_hunks: int = Field(default=500, ge=1)


class PatchValidationResult(RepoPilotModel):
    modified_files: list[str]
    diff_bytes: int = Field(ge=0)
    hunk_count: int = Field(ge=1)


class PatchApplicationRecord(RepoPilotModel):
    base_commit: str
    worktree_path: str
    initial_status: str
    validation: PatchValidationResult
    diff_before: str
    diff_after: str
    patch_applied: bool
    error_code: str | None = None
    error_message: str | None = None
    apply_stdout: str = ""
    apply_stderr: str = ""


def _parse_diff_path(line: str, marker: str, original_line: str) -> str | None:
    raw = original_line[len(marker) :].strip()
    if raw == "/dev/null":
        return None
    if raw.startswith('"'):
        try:
            raw = ast.literal_eval(raw)
        except (SyntaxError, ValueError) as exc:
            raise PatchValidationError(
                "diff path could not be parsed",
                details={"line": original_line},
            ) from exc
    raw = raw.split("\t", 1)[0]
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise PatchValidationError(
            "diff contains an unsafe path",
            details={"path": raw},
        )
    return path.as_posix()


def _matches_pattern(path: str, pattern: str) -> bool:
    normalized = pattern.rstrip("/")
    return (
        path == normalized
        or path.startswith(f"{normalized}/")
        or fnmatch.fnmatch(path, pattern)
    )


class PatchValidator:
    def validate(
        self,
        patch: PatchResult | str,
        policy: PatchPolicy | None = None,
    ) -> PatchValidationResult:
        policy = policy or PatchPolicy()
        diff = patch.unified_diff if isinstance(patch, PatchResult) else patch
        if not isinstance(diff, str) or not diff.strip():
            raise PatchValidationError("patch must be a non-empty Unified Diff")

        diff_bytes = len(diff.encode("utf-8"))
        if diff_bytes > policy.max_diff_bytes:
            raise PatchValidationError(
                "patch exceeds maximum diff size",
                details={"diff_bytes": diff_bytes, "limit": policy.max_diff_bytes},
            )
        if "GIT binary patch" in diff or "Binary files " in diff:
            raise PatchValidationError("binary patches are not supported")

        modified_files: list[str] = []
        hunk_count = 0
        old_path: str | None = None
        pair_started = False
        current_file = False

        for line in diff.splitlines():
            if line.startswith("--- "):
                if pair_started:
                    raise PatchValidationError("malformed diff: overlapping file headers")
                old_path = _parse_diff_path(line, "--- ", line)
                pair_started = True
                continue
            if line.startswith("+++ "):
                if not pair_started:
                    raise PatchValidationError("malformed diff: missing --- header")
                new_path = _parse_diff_path(line, "+++ ", line)
                if old_path is None and new_path is None:
                    raise PatchValidationError("diff does not modify a file")
                if old_path is not None and new_path is not None and old_path != new_path:
                    raise PatchValidationError("renames are not supported")
                modified_files.append(old_path or new_path or "")
                old_path = None
                pair_started = False
                current_file = True
                continue
            if line.startswith("@@ "):
                if pair_started or not current_file:
                    raise PatchValidationError("malformed diff: hunk before file headers")
                if not HUNK_PATTERN.match(line):
                    raise PatchValidationError("malformed unified diff hunk header")
                hunk_count += 1

        if pair_started or not modified_files or hunk_count == 0:
            raise PatchValidationError("diff must contain file headers and at least one hunk")
        if len(set(modified_files)) != len(modified_files):
            raise PatchValidationError("diff modifies the same file more than once")
        if len(modified_files) > policy.max_modified_files:
            raise PatchValidationError(
                "patch modifies too many files",
                details={"count": len(modified_files), "limit": policy.max_modified_files},
            )
        if hunk_count > policy.max_hunks:
            raise PatchValidationError(
                "patch contains too many hunks",
                details={"count": hunk_count, "limit": policy.max_hunks},
            )

        for path in modified_files:
            if any(_matches_pattern(path, pattern) for pattern in policy.forbidden_paths):
                raise PatchValidationError(
                    "patch targets a forbidden file",
                    details={"path": path},
                )
            if policy.allowed_paths and not any(
                _matches_pattern(path, pattern) for pattern in policy.allowed_paths
            ):
                raise PatchValidationError(
                    "patch targets a path outside the allowed list",
                    details={"path": path},
                )

        if isinstance(patch, PatchResult) and set(patch.modified_files) != set(modified_files):
            raise PatchValidationError(
                "PatchResult.modified_files does not match the Unified Diff",
                details={"declared": patch.modified_files, "parsed": modified_files},
            )

        return PatchValidationResult(
            modified_files=modified_files,
            diff_bytes=diff_bytes,
            hunk_count=hunk_count,
        )


class PatchExecutor:
    def __init__(
        self,
        worktree_manager: GitWorktreeManager,
        *,
        policy: PatchPolicy | None = None,
        command_timeout_seconds: float = 30.0,
        max_output_bytes: int = 2_000_000,
    ) -> None:
        self.worktree_manager = worktree_manager
        self.policy = policy or PatchPolicy()
        self.validator = PatchValidator()
        self.command_timeout_seconds = command_timeout_seconds
        self.max_output_bytes = max_output_bytes

    def apply(
        self,
        session: WorktreeSession,
        patch: PatchResult | str,
    ) -> PatchApplicationRecord:
        validation = self.validator.validate(patch, self.policy)
        diff = patch.unified_diff if isinstance(patch, PatchResult) else patch
        before = self.worktree_manager.diff(session, max_output_bytes=self.max_output_bytes)

        check = self._run_patch_command(session, ["apply", "--check", "--recount", "-"], diff)
        if check.returncode != 0:
            self.worktree_manager.restore(session)
            after = self.worktree_manager.diff(session, max_output_bytes=self.max_output_bytes)
            return PatchApplicationRecord(
                base_commit=session.base_commit,
                worktree_path=str(session.path),
                initial_status=session.initial_status,
                validation=validation,
                diff_before=before,
                diff_after=after,
                patch_applied=False,
                error_code="patch_error",
                error_message="git apply --check rejected the patch",
                apply_stdout=check.stdout,
                apply_stderr=check.stderr,
            )

        applied = self._run_patch_command(session, ["apply", "--recount", "--whitespace=nowarn", "-"], diff)
        if applied.returncode != 0:
            self.worktree_manager.restore(session)
            after = self.worktree_manager.diff(session, max_output_bytes=self.max_output_bytes)
            return PatchApplicationRecord(
                base_commit=session.base_commit,
                worktree_path=str(session.path),
                initial_status=session.initial_status,
                validation=validation,
                diff_before=before,
                diff_after=after,
                patch_applied=False,
                error_code="patch_error",
                error_message="git apply failed",
                apply_stdout=applied.stdout,
                apply_stderr=applied.stderr,
            )

        after = self.worktree_manager.diff(session, max_output_bytes=self.max_output_bytes)
        return PatchApplicationRecord(
            base_commit=session.base_commit,
            worktree_path=str(session.path),
            initial_status=session.initial_status,
            validation=validation,
            diff_before=before,
            diff_after=after,
            patch_applied=True,
            apply_stdout=applied.stdout,
            apply_stderr=applied.stderr,
        )

    def _run_patch_command(
        self,
        session: WorktreeSession,
        arguments: list[str],
        diff: str,
    ):
        command = ["git", *arguments]
        try:
            import subprocess

            completed = subprocess.run(
                command,
                cwd=str(session.path),
                input=diff,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolExecutionError(
                "patch command timed out",
                details={"error_code": "timeout"},
            ) from exc
        except OSError as exc:
            raise ToolExecutionError(
                "patch command could not be executed",
                details={"error_code": "tool_error", "exception": type(exc).__name__},
            ) from exc

        output_bytes = len((completed.stdout + completed.stderr).encode("utf-8"))
        if output_bytes > self.max_output_bytes:
            raise ToolExecutionError(
                "patch command output exceeded limit",
                details={"error_code": "output_limit_exceeded"},
            )
        return completed
