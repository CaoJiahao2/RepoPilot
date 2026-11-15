import subprocess

import pytest

from repopilot.core.errors import SandboxViolationError
from repopilot.sandbox.docker import DockerSandbox
from repopilot.sandbox.models import SandboxCommand, SandboxPolicy


def _sandbox(tmp_path, **policy_overrides):
    (tmp_path / "src").mkdir()
    return DockerSandbox(tmp_path, SandboxPolicy(user="1000:1000", **policy_overrides))


def test_docker_command_is_network_disabled_non_root_resource_limited_and_mount_scoped(tmp_path) -> None:
    sandbox = _sandbox(tmp_path)
    command = sandbox.build_command(SandboxCommand(argv=["python", "-m", "pytest", "-q"]))

    assert command[0:3] == ["docker", "run", "--rm"]
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--user" in command and command[command.index("--user") + 1] == "1000:1000"
    assert "--cpus" in command
    assert "--memory" in command
    assert "--pids-limit" in command
    assert "--read-only" in command
    assert "--cap-drop" in command
    assert "--security-opt" in command
    assert command.count("--mount") == 1
    assert str(tmp_path) in command[command.index("--mount") + 1]
    assert command[-5:] == ["python:3.12-slim", "python", "-m", "pytest", "-q"]
    assert not any("docker.sock" in item or ".ssh" in item or ".aws" in item or "HOME" in item for item in command)
    assert "--network host" not in " ".join(command)


def test_docker_command_rejects_unsafe_cwd_and_nested_docker(tmp_path) -> None:
    sandbox = _sandbox(tmp_path)

    with pytest.raises(SandboxViolationError, match="cwd"):
        sandbox.build_command(SandboxCommand(argv=["pytest"], cwd="../outside"))
    with pytest.raises(SandboxViolationError, match="docker"):
        sandbox.build_command(SandboxCommand(argv=["docker", "run"]))


def test_docker_execute_classifies_timeout_nonzero_exit_and_oserror(tmp_path, monkeypatch) -> None:
    sandbox = _sandbox(tmp_path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)

    def failure(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 2, "", "boom")

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("repopilot.sandbox.docker.subprocess.run", timeout)
    assert sandbox.execute(SandboxCommand(argv=["pytest"], timeout_seconds=1)).status == "timeout"

    monkeypatch.setattr("repopilot.sandbox.docker.subprocess.run", failure)
    failed = sandbox.execute(SandboxCommand(argv=["pytest"]))
    assert failed.status == "failed"
    assert failed.return_code == 2

    monkeypatch.setattr("repopilot.sandbox.docker.subprocess.run", unavailable)
    error = sandbox.execute(SandboxCommand(argv=["pytest"]))
    assert error.status == "error"
    assert error.error_code == "sandbox_unavailable"


def test_docker_enforces_output_limit(tmp_path, monkeypatch) -> None:
    sandbox = _sandbox(tmp_path, max_output_bytes=10)

    monkeypatch.setattr(
        "repopilot.sandbox.docker.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "x" * 100, ""),
    )
    result = sandbox.execute(SandboxCommand(argv=["pytest"]))

    assert result.status == "error"
    assert result.error_code == "output_limit_exceeded"
