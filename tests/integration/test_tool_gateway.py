import subprocess
from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph

from repopilot.core.schemas import TaskRequest
from repopilot.core.state import RepoPilotState
from repopilot.tools.base import ToolContext, ToolGateway, execute_tool_with_trace
from repopilot.tools.builtins import build_default_registry


FIXED_CLOCK = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)


def _task() -> TaskRequest:
    return TaskRequest(
        task_id="task-tools",
        repo_path="./fixture",
        issue="inspect repository files",
    )


def test_read_only_file_search_and_trace_integration(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("parser fixture\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "parser.py").write_text("def parse_config():\n    return {}\n", encoding="utf-8")

    gateway = ToolGateway(
        build_default_registry(),
        ToolContext(allowed_root=repo, clock=FIXED_CLOCK),
    )
    builder = StateGraph(RepoPilotState)
    builder.add_node(
        "list",
        lambda state: execute_tool_with_trace(
            gateway, state, "list_files", {"path": "."}
        ),
    )
    builder.add_node(
        "read",
        lambda state: execute_tool_with_trace(
            gateway, state, "read_file", {"path": "src/parser.py"}
        ),
    )
    builder.add_node(
        "search",
        lambda state: execute_tool_with_trace(
            gateway, state, "search_code", {"query": "parse_config"}
        ),
    )
    builder.add_edge(START, "list")
    builder.add_edge("list", "read")
    builder.add_edge("read", "search")
    builder.add_edge("search", END)

    result = builder.compile().invoke({"task": _task()})

    assert result["status"] == "running"
    assert [item.tool_name for item in result["tool_results"]] == [
        "list_files",
        "read_file",
        "search_code",
    ]
    assert all(item.success for item in result["tool_results"])
    assert [event.action for event in result["execution_trace"]] == [
        "list_files",
        "read_file",
        "search_code",
    ]
    assert result["tool_results"][1].output.startswith("def parse_config")
    assert "parse_config" in result["tool_results"][2].output


def test_git_tools_use_argument_arrays_and_shell_false(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        stdout = " M src/parser.py\n" if command[1] == "status" else "--- a/src/parser.py\n+++ b/src/parser.py\n"
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr("repopilot.tools.git.subprocess.run", fake_run)
    gateway = ToolGateway(build_default_registry(), ToolContext(allowed_root=repo, clock=FIXED_CLOCK))

    status = gateway.execute("git_status", {})
    diff = gateway.execute("git_diff", {"path": "src/parser.py", "staged": False})

    assert status.success is True
    assert diff.success is True
    assert calls[0][0] == ["git", "status", "--short", "--branch"]
    assert calls[1][0] == ["git", "diff", "--unified=3", "--", "src/parser.py"]
    assert all(kwargs["shell"] is False for _, kwargs in calls)
    assert all(isinstance(command, list) for command, _ in calls)


def test_tool_failure_is_recorded_in_state_and_trace(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    gateway = ToolGateway(
        build_default_registry(),
        ToolContext(allowed_root=repo, clock=FIXED_CLOCK),
    )
    builder = StateGraph(RepoPilotState)
    builder.add_node(
        "failed_tool",
        lambda state: execute_tool_with_trace(
            gateway,
            state,
            "read_file",
            {"path": "missing.txt"},
        ),
    )
    builder.add_edge(START, "failed_tool")
    builder.add_edge("failed_tool", END)

    result = builder.compile().invoke({"task": _task()})

    assert result["status"] == "failed"
    assert result["failure_type"] == "tool_failure"
    assert result["tool_results"][0].success is False
    assert result["tool_results"][0].error_code == "path_not_found"
    assert result["execution_trace"][0].status == "failed"
    assert result["execution_trace"][0].action == "read_file"
