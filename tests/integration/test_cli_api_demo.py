import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from repopilot.api import create_app
from repopilot.core.schemas import EndToEndReport, TaskRequest, TraceEvent
from repopilot.service import InMemoryTaskStore, TaskService

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "benchmarks" / "tasks" / "task-001"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeExecutor:
    def __init__(self, *, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = []

    def run(self, task):
        self.calls.append(task)
        time.sleep(self.delay)
        return EndToEndReport(
            task_id=task.task_id,
            status="succeeded",
            summary="fake executor completed",
            unified_diff="--- a/app.py\n+++ b/app.py\n",
            baseline_test_report=None,
            post_patch_test_report=None,
            execution_trace=[
                TraceEvent(
                    event_id="evt-1",
                    task_id=task.task_id,
                    timestamp=NOW,
                    event_type="task",
                    actor="fake",
                    action="run",
                    status="succeeded",
                )
            ],
        )


def _task(task_id: str = "task-api-001") -> TaskRequest:
    return TaskRequest(
        task_id=task_id,
        repo_path=str(FIXTURE / "repo"),
        issue="parse_config returns the wrong value",
        test_command=["python", "-m", "pytest", "-q"],
    )


def test_task_service_runs_async_and_exposes_status_trace_artifacts_and_approval() -> None:
    service = TaskService(executor=FakeExecutor(delay=0.02), store=InMemoryTaskStore())
    record = service.submit(_task())

    assert record.status == "queued"
    done = service.wait("task-api-001", timeout=2)
    assert done.status == "succeeded"
    assert service.trace("task-api-001")[0].action == "run"
    assert service.artifacts("task-api-001").patch_diff.startswith("---")
    approved = service.approve(
        "task-api-001",
        approved=True,
        actor="alice",
        reason="verified",
    )
    assert approved.approval_status == "approved"
    cancelled = service.cancel("task-api-001")
    assert cancelled.status == "succeeded"


def test_fastapi_endpoints_validate_and_do_not_expose_arbitrary_commands() -> None:
    executor = FakeExecutor(delay=0.01)
    app = create_app(TaskService(executor=executor, store=InMemoryTaskStore()))
    client = TestClient(app)

    submitted = client.post("/api/v1/tasks", json=_task("task-api-002").model_dump(mode="json"))
    assert submitted.status_code == 200
    assert submitted.json()["task_id"] == "task-api-002"

    for _ in range(100):
        status = client.get("/api/v1/tasks/task-api-002").json()
        if status["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.01)
    assert status["status"] == "succeeded"
    trace = client.get("/api/v1/tasks/task-api-002/trace").json()
    artifacts = client.get("/api/v1/tasks/task-api-002/artifacts").json()
    assert trace["trace"][0]["action"] == "run"
    assert artifacts["patch_diff"].startswith("---")

    approved = client.post(
        "/api/v1/tasks/task-api-002/approve",
        json={"approved": True, "actor": "alice", "reason": "verified"},
    )
    assert approved.status_code == 200
    assert approved.json()["approval_status"] == "approved"

    cancelled = client.post(
        "/api/v1/tasks/task-api-002/cancel",
        json={"reason": "stop"},
    )
    assert cancelled.status_code == 200

    invalid = client.post("/api/v1/tasks", json={"task_id": "bad id", "repo_path": "", "issue": "x", "test_command": []})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    missing = client.get("/api/v1/tasks/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "task_not_found"

    paths = {route.path for route in app.routes}
    assert "/api/v1/tasks" in paths
    assert not any("exec" in path or "shell" in path for path in paths)


def test_cli_run_status_trace_and_artifacts_use_task_request_validation(tmp_path: Path) -> None:
    store = tmp_path / "tasks.db"
    repo = FIXTURE / "repo"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repopilot.cli",
            "run",
            "--repo",
            str(repo),
            "--issue",
            "parse_config returns the wrong value",
            "--test-command",
            "python -m pytest -q",
            "--task-id",
            "task-cli-001",
            "--store",
            str(store),
            "--wait",
        ],
        cwd=str(ROOT),
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "task-cli-001" in completed.stdout
    status = subprocess.run(
        [sys.executable, "-m", "repopilot.cli", "status", "task-cli-001", "--store", str(store)],
        cwd=str(ROOT),
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )
    trace = subprocess.run(
        [sys.executable, "-m", "repopilot.cli", "trace", "task-cli-001", "--store", str(store)],
        cwd=str(ROOT),
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )
    artifacts = subprocess.run(
        [sys.executable, "-m", "repopilot.cli", "artifacts", "task-cli-001", "--store", str(store)],
        cwd=str(ROOT),
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(status.stdout)["task_id"] == "task-cli-001"
    assert isinstance(json.loads(trace.stdout), list)
    assert json.loads(artifacts.stdout)["task_id"] == "task-cli-001"


def test_cli_demo_uses_real_pipeline_and_reports_fake_llm_provenance() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "repopilot.cli", "demo"],
        cwd=str(ROOT),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "succeeded"
    assert report["baseline_test_report"]["status"] == "assertion_failed"
    assert report["post_patch_test_report"]["status"] == "passed"
    assert report["review_result"]["approved"] is True
    assert report["execution_mode"] == "fake_llm"
    assert report["unified_diff"]
    assert report["execution_trace"]


def test_frontend_dashboard_and_live_task_list_are_served() -> None:
    app = create_app(TaskService(executor=FakeExecutor(), store=InMemoryTaskStore()))
    client = TestClient(app)

    dashboard = client.get("/")
    assets = client.get("/assets/app.js")
    tasks = client.get("/api/v1/tasks")

    assert dashboard.status_code == 200
    assert "RepoPilot Control Room" in dashboard.text
    assert "Submit a repository bug" in dashboard.text
    assert assets.status_code == 200
    assert "loadTasks" in assets.text
    assert tasks.status_code == 200
    assert tasks.json() == []
