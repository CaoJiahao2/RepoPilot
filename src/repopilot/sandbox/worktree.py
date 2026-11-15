"""Git Worktree lifecycle with recorded base state and safe cleanup."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from repopilot.core.errors import WorktreeError

_REF_PATTERN = re.compile(r"^[A-Za-z0-9._/+-]+$")


@dataclass(frozen=True)
class GitCommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class WorktreeSession:
    source_repo: Path
    path: Path
    base_commit: str
    initial_status: str


class GitWorktreeManager:
    def __init__(self, *, command_timeout_seconds: float = 30.0) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("command timeout must be positive")
        self.command_timeout_seconds = command_timeout_seconds

    def create(
        self,
        source_repo: str | Path,
        destination: str | Path,
        *,
        base_ref: str = "HEAD",
    ) -> WorktreeSession:
        if not _REF_PATTERN.fullmatch(base_ref):
            raise WorktreeError("base_ref contains unsupported characters")

        source = Path(source_repo).expanduser().resolve(strict=True)
        destination = Path(destination).expanduser()
        destination_parent = destination.parent.resolve(strict=True)
        destination = destination_parent / destination.name

        if not source.is_dir():
            raise WorktreeError("source repository must be a directory")
        if source == destination or source in destination.parents or destination in source.parents:
            raise WorktreeError("worktree destination must be outside the source repository")
        if destination.exists():
            raise WorktreeError("worktree destination already exists")

        source_top = self._run_git(source, ["rev-parse", "--show-toplevel"]).stdout.strip()
        if Path(source_top).resolve() != source:
            raise WorktreeError("source path is not the Git repository root")

        base_commit = self._run_git(
            source, ["rev-parse", "--verify", f"{base_ref}^{{commit}}"]
        ).stdout.strip()
        initial_status = self._run_git(source, ["status", "--porcelain=v1"]).stdout

        try:
            self._run_git(
                source,
                ["worktree", "add", "--detach", str(destination), base_commit],
            )
        except WorktreeError:
            if destination.exists():
                self._run_git(source, ["worktree", "remove", "--force", str(destination)])
            raise

        return WorktreeSession(
            source_repo=source,
            path=destination,
            base_commit=base_commit,
            initial_status=initial_status,
        )

    def cleanup(self, session: WorktreeSession) -> None:
        self._run_git(session.source_repo, ["worktree", "remove", "--force", str(session.path)])
        self._run_git(session.source_repo, ["worktree", "prune"])

    def restore(self, session: WorktreeSession) -> None:
        self._run_git(session.path, ["reset", "--hard", session.base_commit])
        self._run_git(session.path, ["clean", "-fd"])

    def diff(self, session: WorktreeSession, *, max_output_bytes: int = 2_000_000) -> str:
        tracked = self._run_git(session.path, ["diff", "--no-ext-diff"]).stdout
        staged = self._run_git(session.path, ["diff", "--cached", "--no-ext-diff"]).stdout
        pieces = [tracked, staged]

        untracked = self._run_git(
            session.path, ["ls-files", "--others", "--exclude-standard"]
        ).stdout.splitlines()
        for relative_path in untracked:
            result = self._run_git(
                session.path,
                ["diff", "--no-index", "--", "/dev/null", relative_path],
                allowed_returncodes={0, 1},
            )
            pieces.append(result.stdout)

        output = "\n".join(piece for piece in pieces if piece)
        if len(output.encode("utf-8")) > max_output_bytes:
            raise WorktreeError(
                "git diff exceeded output limit",
                details={"error_code": "output_limit_exceeded"},
            )
        return output

    def _run_git(
        self,
        cwd: Path,
        arguments: list[str],
        *,
        input_text: str | None = None,
        allowed_returncodes: set[int] | None = None,
    ) -> GitCommandResult:
        command = ["git", *arguments]
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                input=input_text,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorktreeError(
                "git command timed out",
                details={"error_code": "timeout", "command": arguments[0]},
            ) from exc
        except OSError as exc:
            raise WorktreeError(
                "git command could not be executed",
                details={"error_code": "tool_error", "exception": type(exc).__name__},
            ) from exc

        allowed = allowed_returncodes or {0}
        if completed.returncode not in allowed:
            raise WorktreeError(
                "git command failed",
                details={
                    "error_code": "git_error",
                    "returncode": completed.returncode,
                    "stderr_tail": completed.stderr[-500:],
                },
            )
        return GitCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
