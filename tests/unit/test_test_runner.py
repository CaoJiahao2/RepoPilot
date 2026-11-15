import sys
import time

from repopilot.core.schemas import TaskRequest
from repopilot.tools.tests import CommandTestRunner, TestCommandPolicy as CommandPolicy, TestCommandSpec as CommandSpec


def _task(command: list[str]) -> TaskRequest:
    return TaskRequest(
        task_id="task-test-runner",
        repo_path="./repo",
        issue="run controlled tests",
        test_command=command,
    )


def _policy(argv: list[str], *, timeout_seconds: float = 2, max_output_bytes: int = 1_000_000) -> CommandPolicy:
    return CommandPolicy(
        commands={
            "configured": CommandSpec(
                name="configured",
                argv=argv,
                timeout_seconds=timeout_seconds,
            )
        },
        default_command="configured",
        max_output_bytes=max_output_bytes,
    )


def test_test_runner_records_passed_assertion_collection_dependency_and_execution_results(tmp_path) -> None:
    cases = [
        (f"print('ok')", 0, "passed"),
        (f"print('assert 1 == 2'); raise SystemExit(1)", 1, "assertion_failed"),
        (f"print('ERROR collecting tests'); raise SystemExit(2)", 2, "collection_error"),
        (f"print('ModuleNotFoundError: missing'); raise SystemExit(1)", 1, "dependency_error"),
        (f"print('unexpected'); raise SystemExit(3)", 3, "execution_error"),
    ]

    for code, expected_returncode, expected_status in cases:
        argv = [sys.executable, "-c", code]
        runner = CommandTestRunner(_policy(argv))
        report = runner.run(_task(argv), patch=None, worktree_path=tmp_path)

        assert report.return_code == expected_returncode
        assert report.status == expected_status
        assert report.command == argv
        assert report.duration_seconds >= 0


def test_test_runner_timeout_terminates_process(tmp_path) -> None:
    argv = [sys.executable, "-c", "import time; time.sleep(2)"]
    runner = CommandTestRunner(_policy(argv, timeout_seconds=0.1))

    started = time.perf_counter()
    report = runner.run(_task(argv), patch=None, worktree_path=tmp_path)
    elapsed = time.perf_counter() - started

    assert report.status == "timeout"
    assert report.failure_type == "tool_failure"
    assert elapsed < 1.5


def test_test_runner_rejects_commands_outside_allowlist(tmp_path) -> None:
    runner = CommandTestRunner(_policy([sys.executable, "-c", "print('ok')"]))

    report = runner.run(
        _task(["rm", "-rf", "/"]),
        patch=None,
        worktree_path=tmp_path,
    )

    assert report.status == "execution_error"
    assert report.return_code == 125
    assert "allowlist" in report.stderr


def test_test_runner_enforces_output_limit(tmp_path) -> None:
    argv = [sys.executable, "-c", "print('x' * 100)"]
    runner = CommandTestRunner(_policy(argv, max_output_bytes=20))

    report = runner.run(_task(argv), patch=None, worktree_path=tmp_path)

    assert report.status == "execution_error"
    assert report.return_code == 125
    assert "truncated" in report.stdout
