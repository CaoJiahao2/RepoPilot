import subprocess
import sys
from pathlib import Path

from repopilot.core.schemas import PatchResult, TaskRequest
from repopilot.sandbox.worktree import GitWorktreeManager
from repopilot.tools.patch import PatchExecutor
from repopilot.tools.tests import CommandTestRunner, TestCommandPolicy as CommandPolicy, TestCommandSpec as CommandSpec


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )


def _fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init")
    (repo / "message.py").write_text('VALUE = "BASE"\n', encoding="utf-8")
    _git(repo, "add", "message.py")
    _git(
        repo,
        "-c",
        "user.name=RepoPilot Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "initial fixture",
    )
    return repo


def _task() -> TaskRequest:
    argv = [sys.executable, "-c", "import message; print(message.VALUE)"]
    return TaskRequest(
        task_id="task-worktree",
        repo_path="./source",
        issue="change the message value",
        test_command=argv,
    )


def _runner() -> CommandTestRunner:
    argv = [sys.executable, "-c", "import message; print(message.VALUE)"]
    return CommandTestRunner(
        CommandPolicy(
            commands={
                "message": CommandSpec(
                    name="message",
                    argv=argv,
                    timeout_seconds=5,
                )
            },
            default_command="message",
        )
    )


def _patch() -> PatchResult:
    return PatchResult(
        unified_diff=(
            "--- a/message.py\n"
            "+++ b/message.py\n"
            "@@ -1 +1 @@\n"
            '-VALUE = "BASE"\n'
            '+VALUE = "PATCHED"\n'
        ),
        modified_files=["message.py"],
        explanation="change the value",
    )


def test_worktree_patch_baseline_post_patch_and_cleanup_preserve_source(tmp_path: Path) -> None:
    source = _fixture_repo(tmp_path)
    manager = GitWorktreeManager()
    session = manager.create(source, tmp_path / "worktree")
    runner = _runner()
    task = _task()

    baseline = runner.run(task, patch=None, worktree_path=session.path)
    record = PatchExecutor(manager).apply(session, _patch())
    post_patch = runner.run(task, patch=_patch(), worktree_path=session.path)

    assert baseline.status == "passed"
    assert "BASE" in baseline.stdout
    assert post_patch.status == "passed"
    assert "PATCHED" in post_patch.stdout
    assert record.patch_applied is True
    assert record.diff_before == ""
    assert '+VALUE = "PATCHED"' in record.diff_after
    assert record.validation.modified_files == ["message.py"]
    assert (source / "message.py").read_text(encoding="utf-8") == 'VALUE = "BASE"\n'

    manager.cleanup(session)
    assert not session.path.exists()


def test_patch_failure_restores_worktree_and_does_not_touch_source(tmp_path: Path) -> None:
    source = _fixture_repo(tmp_path)
    manager = GitWorktreeManager()
    session = manager.create(source, tmp_path / "worktree")
    bad_patch = PatchResult(
        unified_diff=(
            "--- a/message.py\n"
            "+++ b/message.py\n"
            "@@ -1 +1 @@\n"
            '-VALUE = "NOT_THE_BASE"\n'
            '+VALUE = "PATCHED"\n'
        ),
        modified_files=["message.py"],
        explanation="wrong context",
    )

    record = PatchExecutor(manager).apply(session, bad_patch)

    assert record.patch_applied is False
    assert record.error_code == "patch_error"
    assert record.diff_after == ""
    assert (session.path / "message.py").read_text(encoding="utf-8") == 'VALUE = "BASE"\n'
    assert (source / "message.py").read_text(encoding="utf-8") == 'VALUE = "BASE"\n'

    manager.cleanup(session)
    assert not session.path.exists()
